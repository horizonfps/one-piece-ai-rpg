"""Post-turn event executor.

Applies the parsed Director decisions to world state in the canonical order from
docs/phases/decisions.md (append_world_event before the deltas; chaos negative gate;
referential card_id for append_alias). Channels owned by other systems are only recorded
in the report and persisted, not executed here.
"""
from __future__ import annotations

import copy
import random
import re
import unicodedata
import uuid

import aiosqlite

from ..db import repositories as repo
from . import agent_state as ast
from . import alliances
from . import crew
from . import economy
from . import faction
from . import legend
from . import mushi
from . import ship
from . import techniques as tech
from . import world_map
from . import world_state as ws

# edit_primitives the executor actually applies (the rest is recorded, not executed).
_EXECUTED_PRIMITIVES = {
    "append_world_event", "update_world_event", "append_agent_log_entry",
    "pair_mushi", "unpair_mushi", "receive_vivre_card", "remove_vivre_card",
    "plant_black_mushi", "remove_black_mushi", "set_white_mushi",
    "plant_tap_on_player", "remove_tap_on_player",
}

# Cap on the new summary in card_corrections; the channel rejects anything longer.
CARD_CORRECTION_MAX_CHARS = 300


def _player_alignment_value(player_snapshot: dict) -> float:
    a = player_snapshot.get("alignment")
    if isinstance(a, dict):
        try:
            return float(a.get("value", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _crew_member_alignments(npcs: dict) -> list[float]:
    return [
        float(d.get("alignment_baseline", 0.0) or 0.0)
        for d in npcs.values()
        if d.get("affiliation") == "player_crew"
    ]


def _apply_mushi_vivre_primitive(
    p: dict, psnap: dict, npcs: dict, *, turn_index: int, report: dict
) -> None:
    """Apply a mushi/vivre edit_primitive to player_snapshot (in-place). The received card's
    initial visual_state derives from the owner's status + vital_at_risk. Records in the report."""
    kind = p.get("kind")
    log = report.setdefault("mushi_vivre", [])
    if kind == "pair_mushi":
        if mushi.apply_pair_mushi(
            psnap, npc_id=p.get("npc_id"), mushi_kind=p.get("mushi_kind"),
            location=p.get("location", ""), turn_index=turn_index,
        ):
            log.append({"kind": "pair_mushi", "npc_id": p.get("npc_id"), "mushi_kind": p.get("mushi_kind")})
    elif kind == "unpair_mushi":
        if mushi.apply_unpair_mushi(psnap, npc_id=p.get("npc_id")):
            log.append({"kind": "unpair_mushi", "npc_id": p.get("npc_id")})
    elif kind == "receive_vivre_card":
        owner = npcs.get(p.get("from_npc_id")) or {}
        visual = mushi.derive_vital_state(owner.get("status"), bool(owner.get("vital_at_risk")))
        if mushi.apply_receive_vivre_card(
            psnap, npc_id=p.get("from_npc_id"), origin_note=p.get("origin_note", ""),
            location=p.get("received_at_location", ""), turn_index=turn_index, visual_state=visual,
        ):
            log.append({"kind": "receive_vivre_card", "npc_id": p.get("from_npc_id"), "visual_state": visual})
        else:
            report["rejected"].append({"primitive": p, "why": "receive_vivre_card: já tem card desse NPC ou id vazio"})
    elif kind == "remove_vivre_card":
        if mushi.apply_remove_vivre_card(psnap, npc_id=p.get("npc_id")):
            log.append({"kind": "remove_vivre_card", "npc_id": p.get("npc_id")})
    elif kind == "plant_black_mushi":
        if mushi.apply_plant_black_mushi(
            psnap, target_npc_id=p.get("target_npc_id"), location=p.get("location", ""), turn_index=turn_index
        ):
            log.append({"kind": "plant_black_mushi", "target_npc_id": p.get("target_npc_id")})
    elif kind == "remove_black_mushi":
        if mushi.apply_remove_black_mushi(psnap, target_npc_id=p.get("target_npc_id")):
            log.append({"kind": "remove_black_mushi", "target_npc_id": p.get("target_npc_id")})
    elif kind == "set_white_mushi":
        if mushi.apply_set_white_mushi(psnap, active=bool(p.get("white_active"))):
            log.append({"kind": "set_white_mushi", "white_active": bool(p.get("white_active"))})


async def execute_ship_swap(
    conn: aiosqlite.Connection,
    campaign_id: str,
    *,
    crew: dict,
    swap_event: dict,
    ship_cards: dict,
    turn_index: int,
    scene_location: str = "",
) -> tuple[dict, dict | None]:
    """Apply ONE ship_swap_event (new ship already carded) to the crew fleet.

    Shared by the post-turn executor and the runner. Returns a new crew dict, annotates the
    previous ship's disposition, and emits the audit crystal. Existence gate: new_ship_card_id
    must be in ship_cards; gate failure returns (crew, None) untouched."""
    new_id = (swap_event.get("new_ship_card_id") or "").strip()
    if not new_id or new_id not in ship_cards:
        return crew, None
    prev_id = swap_event.get("previous_ship_card_id") or None
    disp = swap_event.get("previous_ship_disposition")
    new_crew, report = ship.apply_swap(
        crew,
        new_ship_card_id=new_id,
        previous_ship_card_id=prev_id,
        previous_ship_disposition=disp,
        swap_kind=swap_event.get("swap_kind", "acquired"),
        turn_index=turn_index,
    )
    # Annotate the disposition on the previous ship's card; reload to get the story_card_id.
    prev_name = ""
    if prev_id:
        prev_card = await repo.get_card_by_entity_id(conn, campaign_id, prev_id)
        if prev_card:
            prev_name = (prev_card["data"] or {}).get("name", "")
            if disp in ship.DISPOSITIONS:
                await repo.update_story_card(
                    conn, prev_card["id"], ship.apply_disposition(prev_card["data"], disp)
                )
    new_name = (ship_cards.get(new_id) or {}).get("name", "")
    # No engine-templated crystal: the crystallizer extracts the swap fact from the scene prose.
    return new_crew, {**report, "new_name": new_name, "previous_name": prev_name}


async def apply_post_turn(
    conn: aiosqlite.Connection,
    campaign_id: str,
    *,
    decisions: dict,
    player_card: dict,
    npcs: dict,
    metadata: dict,
    clock: dict | None,
    turn_index: int,
    ran_agent_ids: set | None = None,
    rng: random.Random | None = None,
    turn_meta: dict | None = None,
    item_cards: dict | None = None,
    ship_cards: dict | None = None,
    faction_cards: dict | None = None,
) -> dict:
    """Apply the deltas/events to state and persist. Returns a report of what changed.

    Mutates copies of player_card/metadata and persists via repositories. Never raises:
    malformed channels are recorded in report["rejected"] and the turn continues.

    ran_agent_ids = NPCs that ran an agent this turn (log already persisted by the runner);
    append_agent_log_entry for those is skipped to avoid duplicates. turn_meta feeds the
    player's fruit_usage_log.
    """
    rng = rng or random
    ran = ran_agent_ids or set()
    item_cards = item_cards or {}
    ship_cards = ship_cards or {}
    faction_card_ids = set(faction_cards or {})
    day = int((clock or {}).get("campaign_day", 0))
    psnap = dict(player_card.get("player_snapshot") or {})
    # Turn-start snapshot, for the 3-way merge at persistence: a sheet edit (tier/belly/alignment)
    # may land after this turn loaded its state, so we only write back the keys the engine changed.
    snapshot_base = copy.deepcopy(player_card.get("player_snapshot") or {})
    meta = dict(metadata or {})

    report: dict = {
        "alignment": None, "crew_alignment": None, "chaos": None,
        "bounty_scheduled": [], "tier_change": None, "breakthrough": None,
        "condition_change": None, "world_events_added": [], "rejected": [],
        "recorded_edit_primitives": [], "recorded_dispatched_jobs": [],
        "belly": None, "inventory_changes": [],
        "hull_changes": [], "ship_swaps": [],
        "faction_reputation": [],
        "crew_alliances": [],
        "card_corrections": [],
        "inspector_warnings": decisions.get("inspector_warnings", []),
    }

    deltas = decisions.get("deltas") or []
    edit_primitives = decisions.get("edit_primitives") or []
    npc_faction_deltas: dict[str, list[tuple[str, float, str]]] = {}  # npc_id -> [(faction_id, value, reason)]
    crew_dissat_deltas: dict[str, float] = {}  # member npc_id -> dissatisfaction delta
    active_card_ids = {d.get("id") for d in npcs.values() if d.get("id")}
    active_card_ids.add(player_card.get("id", "player"))

    # 1. append_world_event (before the deltas).
    events_bg = list(meta.get("events_background") or [])
    agent_log_appends: dict[str, list] = {}
    alias_appends: dict[str, list] = {}  # entity_id -> [alias, ...] (applied after the loop)
    for p in edit_primitives:
        kind = p.get("kind")
        if kind == "append_world_event":
            we = dict(p.get("world_event") or {})
            we.setdefault("id", uuid.uuid4().hex[:12])
            we["triggered_at_turn_index"] = turn_index
            we.setdefault("player_engagement", "unreached")
            events_bg.append(we)
            report["world_events_added"].append(we["id"])
        elif kind == "update_world_event":
            # Off-screen event lifecycle: find the event by id and apply the patch
            # (status, summary_addition, new_discovery_channel).
            eid = p.get("event_id")
            patch = p.get("patch") or {}
            target = next((e for e in events_bg if isinstance(e, dict) and e.get("id") == eid), None)
            if target is None or not isinstance(patch, dict):
                report["rejected"].append({"primitive": p, "why": "update_world_event.event_id inexistente"})
            else:
                if isinstance(patch.get("status"), str) and patch["status"].strip():
                    target["status"] = patch["status"].strip()
                    if patch["status"].strip() in ("resolved", "ignored_by_player"):
                        target["resolved_at_turn_index"] = turn_index
                add = (patch.get("summary_addition") or "").strip()
                if add:
                    target["summary"] = (target.get("summary", "") + " " + add).strip()
                ndc = patch.get("new_discovery_channel")
                if isinstance(ndc, dict) and ndc.get("channel"):
                    target["discovery_channel"] = ndc["channel"]
                    if ndc.get("trigger_now"):
                        target.setdefault("discovered_at_turn_index", turn_index)
                report.setdefault("world_events_updated", []).append(eid)
        elif kind == "append_alias":
            # Referential gate: card_id must exist in active_cards.
            cid = p.get("card_id")
            alias = (p.get("alias") or "").strip()
            if cid not in active_card_ids:
                report["rejected"].append({"primitive": p, "why": "append_alias.card_id inexistente"})
            elif not alias:
                report["rejected"].append({"primitive": p, "why": "append_alias.alias vazio"})
            else:
                alias_appends.setdefault(cid, []).append(alias)
        elif kind == "legend_update":
            # Public myth of the player or a crewmate. A new epithet also lands as card alias.
            cid = p.get("card_id")
            player_id = player_card.get("id", "player")
            if cid not in active_card_ids:
                report["rejected"].append({"primitive": p, "why": "legend_update.card_id inexistente"})
            elif cid != player_id and (npcs.get(cid) or {}).get("affiliation") != "player_crew":
                report["rejected"].append({"primitive": p, "why": "legend_update: alvo precisa ser o player ou um tripulante"})
            else:
                if cid == player_id:
                    tname = (player_card.get("player_character") or {}).get("name", "")
                else:
                    tname = (npcs.get(cid) or {}).get("name", "")
                applied = legend.apply_legend_update(meta, p, turn_index=turn_index, target_name=tname)
                if applied is None:
                    report["rejected"].append({"primitive": p, "why": "legend_update sem conteúdo"})
                else:
                    report.setdefault("legend_updates", []).append(applied)
                    # Crewmate epithet doubles as card alias (dedup). The player's epithet
                    # lives in legend_state only (the player card has no entity id).
                    if cid != player_id and (p.get("epithet") or "").strip():
                        alias_appends.setdefault(cid, []).append(p["epithet"].strip())
        elif kind == "append_agent_log_entry":
            # Log of an NPC narrated on-scene. Gate: agent_id must exist; agents that ran are
            # already logged by the runner.
            aid = p.get("agent_id")
            if not aid or aid not in npcs:
                report["rejected"].append({"primitive": p, "why": "append_agent_log_entry.agent_id inexistente"})
            elif aid in ran:
                report["recorded_edit_primitives"].append(p)  # already logged by the runner
            else:
                agent_log_appends.setdefault(aid, []).append(p.get("entry") or {})
        elif kind in (
            "pair_mushi", "unpair_mushi", "receive_vivre_card", "remove_vivre_card",
            "plant_black_mushi", "remove_black_mushi", "set_white_mushi",
        ):
            # mushi/vivre (+ exotic black/white); the engine persists into player_snapshot.
            _apply_mushi_vivre_primitive(p, psnap, npcs, turn_index=turn_index, report=report)
        elif kind == "plant_tap_on_player":
            # An NPC starts tapping the player (lives in metadata, not the snapshot).
            if mushi.apply_plant_tap_on_player(
                meta, watcher_npc_id=p.get("watcher_npc_id"), turn_index=turn_index, note=p.get("note", "")
            ):
                report.setdefault("mushi_vivre", []).append(
                    {"kind": "plant_tap_on_player", "watcher_npc_id": p.get("watcher_npc_id")}
                )
        elif kind == "remove_tap_on_player":
            if mushi.apply_remove_tap_on_player(meta, watcher_npc_id=p.get("watcher_npc_id")):
                report.setdefault("mushi_vivre", []).append(
                    {"kind": "remove_tap_on_player", "watcher_npc_id": p.get("watcher_npc_id")}
                )
        else:
            report["recorded_edit_primitives"].append(p)
    meta["events_background"] = events_bg

    # 1b. Buster Call (golden/silver mushi). Engine records the flag; chaos comes through the
    # normal chaos_delta channel (not duplicated here).
    buster = decisions.get("buster_call_triggered")
    if isinstance(buster, dict) and (buster.get("target_island") or "").strip():
        rep = mushi.apply_buster_call(
            meta,
            target_island=buster.get("target_island", ""),
            ordered_by_npc_id=buster.get("ordered_by_npc_id"),
            reason=buster.get("reason", ""),
            turn_index=turn_index,
        )
        report["buster_call"] = rep["active"]

    # 1c. Campaign phase: the Director promotes it qualitatively (early/mid/late); calibrates
    # invented-island complexity. Only when it names a step.
    _phase = decisions.get("campaign_phase_update")
    if _phase in ("early", "mid", "late") and meta.get("campaign_phase") != _phase:
        meta["campaign_phase"] = _phase
        report["campaign_phase"] = _phase

    # 2-4. deltas (alignment / chaos / bounty / crew_alignment).
    align_value = _player_alignment_value(psnap)
    chaos = meta.get("chaos_meter")
    crew_delta_value: float | None = None
    for d in deltas:
        kind = d.get("kind")
        if kind == "alignment_delta":
            v = d.get("value")
            if ws.is_valid_alignment_delta(v):
                new = ws.apply_alignment_delta({"value": align_value}, v)
                align_value = new["value"]
                report.setdefault("alignment_deltas_applied", []).append(v)
            else:
                report["rejected"].append({"delta": d, "why": "alignment value fora da faixa"})
        elif kind == "chaos_delta":
            v = d.get("value")
            if not ws.is_valid_chaos_delta(v):
                report["rejected"].append({"delta": d, "why": "chaos value fora da faixa"})
                continue
            chaos = ws.apply_chaos_delta(chaos, v)
        elif kind == "bounty_delta":
            tier = d.get("tier")
            target = d.get("target") or "player"
            if tier in ws.BOUNTY_TIERS:
                amount = ws.coerce_bounty_amount(d.get("exact_amount"), tier, rng)
                sched = ws.scheduled_day_from_delay(day, d.get("news_delay_days"), rng)
                reason = d.get("reason", "")
                open_pending = await repo.get_open_bounty_pending(conn, campaign_id, target)
                if open_pending is not None:
                    prev_total = int(open_pending["delta"])
                    total = prev_total + amount
                    new_tier = ws.tier_for_amount(total)
                    # Headline reason is the Director's call: consolidated_reason if it wrote one
                    # for the fold, else the newest act's reason. No magnitude comparison in code.
                    headline_reason = (d.get("consolidated_reason") or reason or open_pending["reason"])
                    new_sched = min(int(open_pending["scheduled_day"]), sched)
                    await repo.bump_bounty_pending(
                        conn, open_pending["id"], delta=total, tier=new_tier,
                        reason=headline_reason, scheduled_day=new_sched,
                    )
                    report["bounty_scheduled"].append(
                        {"id": open_pending["id"], "target": target, "tier": new_tier,
                         "delta": total, "scheduled_day": new_sched, "consolidated": True}
                    )
                else:
                    bid = await repo.add_bounty_pending_update(
                        conn, campaign_id, target=target, tier=tier, delta=amount,
                        reason=reason, source=d.get("source", "action"),
                        source_turn_index=turn_index, scheduled_day=sched,
                    )
                    report["bounty_scheduled"].append(
                        {"id": bid, "target": target, "tier": tier, "delta": amount, "scheduled_day": sched}
                    )
            else:
                report["rejected"].append({"delta": d, "why": "bounty tier inválido"})
        elif kind == "crew_alignment_delta":
            v = d.get("value")
            if ws.is_valid_alignment_delta(v):
                crew_delta_value = float(v)
            else:
                report["rejected"].append({"delta": d, "why": "crew_alignment value fora da faixa"})
        elif kind == "belly_delta":
            # Captain's single pot. The Director emits the exact berry figure (exact_amount);
            # tier is a magnitude guideline and the sampling fallback for saves/omissions. No target.
            direction = d.get("direction")
            tier = d.get("tier")
            cur = economy.belly_amount(psnap)
            new_belly, amount = economy.apply_exact_belly_delta(
                cur, direction, d.get("exact_amount"), tier, rng
            )
            if amount == 0:
                report["rejected"].append({"delta": d, "why": "belly_delta direction/exact_amount/tier inválido"})
            else:
                psnap["belly"] = new_belly
                report["belly"] = {
                    "old": cur, "new": new_belly, "amount": amount,
                    "direction": direction, "tier": tier,
                    "reason": d.get("reason", ""),
                }
        elif kind == "faction_reputation_delta":
            # Institutional reputation (cumulative float). Existence gate: faction_id must have a
            # FACTION card. target=player -> player_snapshot; target=<npc_id> -> NPC card (after
            # the loop). Crew gets no delta (engine-derived). No snap-to-enum.
            fid = (d.get("faction_id") or "").strip()
            target = (d.get("target") or "player").strip() or "player"
            v = d.get("value")
            if not fid or fid not in faction_card_ids:
                report["rejected"].append({"delta": d, "why": "faction_reputation_delta faction_id sem card FACTION"})
            elif not isinstance(v, (int, float)):
                report["rejected"].append({"delta": d, "why": "faction_reputation_delta value não-numérico"})
            elif target == "crew":
                report["rejected"].append({"delta": d, "why": "faction_reputation_delta target=crew (engine deriva)"})
            elif target == "player":
                reps = faction.reputations_of(psnap)
                old = reps.get(fid, 0.0)
                reps = faction.apply_reputation_delta(reps, fid, v)
                psnap["faction_reputations"] = reps
                report["faction_reputation"].append({
                    "target": "player", "faction_id": fid, "value": float(v),
                    "old": old, "new": reps[fid], "bucket": faction.reputation_bucket(reps[fid]),
                    "reason": d.get("reason", ""),
                })
            elif target in npcs:
                npc_faction_deltas.setdefault(target, []).append((fid, float(v), d.get("reason", "")))
            else:
                report["rejected"].append({"delta": d, "why": "faction_reputation_delta target inexistente"})
        elif kind == "crew_dissatisfaction_delta":
            # Crew dissatisfaction. Only for player_crew members; no snap. Applied after the loop
            # (untouched members decay).
            target = (d.get("target") or d.get("target_npc_id") or "").strip()
            v = d.get("value")
            if not isinstance(v, (int, float)):
                report["rejected"].append({"delta": d, "why": "crew_dissatisfaction value não-numérico"})
            elif target not in npcs or npcs[target].get("affiliation") != crew.CREW_AFFILIATION:
                report["rejected"].append({"delta": d, "why": "crew_dissatisfaction target não é membro do bando"})
            else:
                crew_dissat_deltas[target] = float(v)

    psnap["alignment"] = ws.make_alignment(align_value)
    report["alignment"] = psnap["alignment"]
    if chaos is not None:
        meta["chaos_meter"] = chaos
        report["chaos"] = chaos

    # 5. tier_change_event (+ fighting_style hook).
    tier_change = decisions.get("tier_change_event")
    if isinstance(tier_change, dict) and tier_change.get("new_tier"):
        psnap["tier"] = tier_change["new_tier"]
        # fighting_style regen runs elsewhere; just set the hook here.
        psnap["fighting_style_regen_pending"] = True
        report["tier_change"] = {"new_tier": tier_change["new_tier"], "reason": tier_change.get("reason", "")}

    # 5b. condition_change_event; tier untouched. condition is ephemeral, tier is accumulated competence.
    cce = decisions.get("condition_change_event")
    if isinstance(cce, dict) and isinstance(cce.get("new_condition"), str) and cce["new_condition"].strip():
        psnap["condition"] = cce["new_condition"].strip()
        report["condition_change"] = {
            "new_condition": psnap["condition"],
            "reason": cce.get("reason", ""),
            "source_item_id": cce.get("source_item_id"),
        }

    # 5c. crew dissatisfaction + departure. Applies the Director's delta to touched members. An
    # untouched member keeps its value; cooling is an explicit negative crew_dissatisfaction_delta,
    # no passive decay. Departure removes the member + audit crystal. Runs before the crew_alignment
    # recompute so the mean reflects the departure. Mutates npcs.
    crew_departure = decisions.get("crew_departure_event")
    departed_id = crew_departure.get("npc_id") if isinstance(crew_departure, dict) else None
    member_ids = [aid for aid, d in npcs.items() if d.get("affiliation") == crew.CREW_AFFILIATION]
    if member_ids:
        crew_agents = await repo.get_npc_agents(conn, campaign_id)
        for aid in member_ids:
            info = crew_agents.get(aid)
            if not info or aid == departed_id:
                continue  # departed handled below
            if aid not in crew_dissat_deltas:
                continue  # untouched: no passive decay; the Director emits a negative delta to cool
            data = crew.apply_dissatisfaction_delta(info["data"], crew_dissat_deltas[aid])
            report.setdefault("crew_dissatisfaction", []).append(
                {"npc_id": aid, "value": crew_dissat_deltas[aid], "new": data.get("dissatisfaction")})
            await repo.update_story_card(conn, info["story_card_id"], data)
            npcs[aid] = data
        if departed_id and departed_id in member_ids:
            info = crew_agents.get(departed_id)
            if info:
                reason = crew_departure.get("reason", "") if isinstance(crew_departure, dict) else ""
                data = crew.remove_member(info["data"], turn_index=turn_index, reason=reason)
                await repo.update_story_card(conn, info["story_card_id"], data)
                npcs[departed_id] = data
                await repo.append_new_crystals(
                    conn, campaign_id,
                    [crew.departure_audit_crystal(data.get("name", ""), reason=reason)],
                    source_turn_index=turn_index,
                )
                report["crew_departure"] = {"npc_id": departed_id, "name": data.get("name", "")}
            else:
                report["rejected"].append({"crew_departure": departed_id, "why": "membro inexistente"})

    # 6. crew_alignment (recompute + explicit delta).
    crew_align = ws.compute_crew_alignment(align_value, _crew_member_alignments(npcs))
    if crew_delta_value is not None:
        crew_align = ws.apply_alignment_delta(crew_align, crew_delta_value)
    meta["crew_alignment"] = crew_align
    report["crew_alignment"] = crew_align

    # 6c. NPC faction_reputation_delta; persists on the NPC card. Cumulative in the card data_json.
    # Existence gate already passed in the loop.
    if npc_faction_deltas:
        agents_map = await repo.get_npc_agents(conn, campaign_id)
        for npc_id, pairs in npc_faction_deltas.items():
            info = agents_map.get(npc_id)
            if not info:
                report["rejected"].append({"faction_npc": npc_id, "why": "card de NPC sumiu entre o gate e a aplicação"})
                continue
            data = dict(info["data"])
            reps = faction.reputations_of(data)
            for fid, value, reason in pairs:
                old = reps.get(fid, 0.0)
                reps = faction.apply_reputation_delta(reps, fid, value)
                report["faction_reputation"].append({
                    "target": npc_id, "faction_id": fid, "value": value,
                    "old": old, "new": reps[fid], "bucket": faction.reputation_bucket(reps[fid]),
                    "reason": reason,
                })
            data["faction_reputations"] = reps
            await repo.update_story_card(conn, info["story_card_id"], data)

    # 6d. card_corrections. Director-requested correction of a card's summary the campaign already
    # contradicted. Scope: ONLY current_state.summary_text (other fields have their own channels).
    # Gates: id in turn context, non-empty justification, size cap, card exists. An NPC that left the
    # crew this turn is skipped (remove_member just rewrote the summary; the correction would be stale).
    for c in decisions.get("card_corrections") or []:
        cid = (c.get("card_id") or "").strip()
        new_summary = (c.get("corrected_summary_text") or "").strip()
        fact = (c.get("contradicted_fact") or "").strip()
        contradicted_by = (c.get("contradicted_by") or "").strip()
        if cid not in set(decisions.get("_cards_in_context") or []):
            report["rejected"].append({"card_correction": c, "why": "card_id fora do contexto do turn"})
            continue
        if not fact or not contradicted_by:
            report["rejected"].append({"card_correction": c, "why": "justificativa ausente (contradicted_fact/contradicted_by)"})
            continue
        if not new_summary:
            report["rejected"].append({"card_correction": c, "why": "corrected_summary_text vazio"})
            continue
        if len(new_summary) > CARD_CORRECTION_MAX_CHARS:
            report["rejected"].append(
                {"card_correction": c, "why": f"corrected_summary_text acima de {CARD_CORRECTION_MAX_CHARS} chars"})
            continue
        if cid == departed_id and report.get("crew_departure"):
            report["rejected"].append({"card_correction": c, "why": "summary reescrito pelo crew_departure neste turn"})
            continue
        card = await repo.get_card_by_entity_id(conn, campaign_id, cid)
        if card is None:
            report["rejected"].append({"card_correction": c, "why": "card inexistente"})
            continue
        data = dict(card["data"])
        cs = dict(data.get("current_state") or {})
        old_summary = cs.get("summary_text", "")
        cs["summary_text"] = new_summary
        data["current_state"] = cs
        await repo.update_story_card(conn, card["id"], data)
        if cid in npcs:
            npcs[cid] = data
        report["card_corrections"].append({
            "card_id": cid, "old_summary": old_summary, "new_summary": new_summary,
            "contradicted_fact": fact, "contradicted_by": contradicted_by,
        })

    # 6b. inventory_events. Existence gate: item_card_id must have a card or already be in the
    # inventory; lost/consumed/given_away require being in the inventory. New items go via
    # dispatched_jobs[item_generator], not here. Forged ids are rejected.
    inv_events = decisions.get("inventory_events") or []
    if inv_events:
        inventory = list(psnap.get("inventory") or [])
        known_card_ids = set(item_cards.keys()) | {d.get("id") for d in npcs.values() if d.get("id")}
        for ev in inv_events:
            if not isinstance(ev, dict):
                continue
            kind = ev.get("kind")
            iid = (ev.get("item_card_id") or "").strip()
            if kind not in economy.INVENTORY_KINDS or not iid:
                report["rejected"].append({"inventory_event": ev, "why": "inventory_event kind/item_card_id ausente"})
                continue
            in_inventory = iid in economy.inventory_ids(inventory)
            if iid not in known_card_ids and not in_inventory:
                report["rejected"].append({"inventory_event": ev, "why": "item_card_id inexistente (sem card e fora do inventário)"})
                continue
            if kind != "acquired" and not in_inventory:
                report["rejected"].append({"inventory_event": ev, "why": f"{kind} de item fora do inventário"})
                continue
            inventory, applied = economy.apply_inventory_event(inventory, ev, turn_index=turn_index)
            if applied:
                report["inventory_changes"].append(applied)
        psnap["inventory"] = inventory

    # 7. breakthrough_event (unique per kind).
    brk = decisions.get("breakthrough_event")
    if isinstance(brk, dict) and brk.get("kind"):
        existing = psnap.get("breakthroughs") or []
        if not any(b.get("kind") == brk["kind"] for b in existing if isinstance(b, dict)):
            entry = {
                "kind": brk["kind"],
                "unlocked_at_turn_index": turn_index,
                "trigger_context": brk.get("trigger_context", ""),
            }
            if brk.get("target_card_id"):
                entry["target_card_id"] = brk["target_card_id"]
            existing = existing + [entry]
            psnap["breakthroughs"] = existing
            report["breakthrough"] = entry
        else:
            report["rejected"].append({"breakthrough": brk, "why": "kind já desbloqueado (unicidade)"})

    # 8. ship events: hull_condition_change + ship_swap. Existence gate: ship_card_id /
    # new_ship_card_id reference an existing SHIP card; a new ship without a card goes via
    # dispatched_jobs[ship_generator]. The fleet lives in meta["crew"].
    scene_loc = (decisions.get("_scene_location") or "")
    # Local copy so the speed derive sees the new hull (the DB card is updated; the in-memory dict
    # would be stale). ship_speed_factor derives from subtype x hull.
    ship_cards = dict(ship_cards)
    for ev in decisions.get("hull_condition_change_events") or []:
        cid = (ev.get("ship_card_id") or "").strip()
        nc = ev.get("new_condition")
        if cid not in ship_cards or nc not in ship.HULL_CONDITIONS:
            report["rejected"].append({"hull_event": ev, "why": "ship_card_id inexistente ou new_condition inválido"})
            continue
        sc_card = await repo.get_card_by_entity_id(conn, campaign_id, cid)
        if not sc_card:
            report["rejected"].append({"hull_event": ev, "why": "SHIP card sumiu entre o gate e a aplicação"})
            continue
        new_data = ship.apply_hull_change(sc_card["data"], nc)
        await repo.update_story_card(conn, sc_card["id"], new_data)
        ship_cards[cid] = new_data  # fresh hull for the speed derive below
        report["hull_changes"].append({"ship_card_id": cid, "new_condition": nc, "reason": ev.get("reason", "")})

    swap_events = decisions.get("ship_swap_events") or []
    if swap_events:
        crew_obj = ship.get_crew(meta)
        for ev in swap_events:
            new_crew, swap_report = await execute_ship_swap(
                conn, campaign_id,
                crew=crew_obj, swap_event=ev, ship_cards=ship_cards,
                turn_index=turn_index, scene_location=scene_loc,
            )
            if swap_report is None:
                report["rejected"].append({"ship_swap_event": ev, "why": "new_ship_card_id inexistente (id forjado — navio novo vai por ship_generator)"})
                continue
            crew_obj = new_crew
            report["ship_swaps"].append(swap_report)
        meta["crew"] = crew_obj

    # Hull change or ship swap changed the active ship: re-derive ship_speed_factor for the next
    # crossing. No-op without a world or active ship.
    if report["hull_changes"] or report["ship_swaps"]:
        world_map.refresh_player_ship_speed(meta, ship_cards)

    # 8b. crew_alliance_events. Mutates metadata.crew_alliances + audit crystal. Existence gate on
    # crew_b inside apply_alliance_events. alliance_broken with no active alliance is rejected.
    alliance_events = decisions.get("crew_alliance_events") or []
    if alliance_events:
        valid_cb = alliances.valid_crew_b_ids(faction_card_ids, npcs)
        new_alliances, applied_alliances, rejected_alliances = alliances.apply_alliance_events(
            alliances.crew_alliances_of(meta), alliance_events,
            turn_index=turn_index, valid_crew_b_ids=valid_cb,
        )
        for rj in rejected_alliances:
            report["rejected"].append(rj)
        if applied_alliances:
            meta["crew_alliances"] = new_alliances
            report["crew_alliances"] = applied_alliances
            audit_crystals = [
                alliances.alliance_audit_crystal(
                    ap["kind"],
                    alliances.crew_b_display_name(ap["crew_b_id"], faction_cards, npcs),
                    formality=ap.get("formality", ""), hierarchy=ap.get("hierarchy", ""),
                    reason=ap.get("reason", ""), location=scene_loc,
                )
                for ap in applied_alliances
            ]
            await repo.append_new_crystals(conn, campaign_id, audit_crystals, source_turn_index=turn_index)

    # append_alias: dedup in card.data["aliases"] + persist. Referential gate already passed in the
    # loop. Case-insensitive dedup; skips an alias equal to the card's own name.
    if alias_appends:
        applied_aliases = []
        for entity_id, aliases in alias_appends.items():
            card = await repo.get_card_by_entity_id(conn, campaign_id, entity_id)
            if not card:
                report["rejected"].append({"primitive": {"kind": "append_alias", "card_id": entity_id}, "why": "card sumiu entre o gate e a aplicação"})
                continue
            data = dict(card["data"])
            current = list(data.get("aliases") or [])
            seen = {a.strip().lower() for a in current if isinstance(a, str)}
            seen.add(str(data.get("name", "")).strip().lower())
            added = []
            for alias in aliases:
                key = alias.lower()
                if key in seen:
                    continue
                seen.add(key)
                current.append(alias)
                added.append(alias)
            if added:
                data["aliases"] = current
                await repo.update_story_card(conn, card["id"], data)
                applied_aliases.append({"card_id": entity_id, "added": added})
        if applied_aliases:
            report["aliases_appended"] = applied_aliases

    # dispatched_jobs: recorded, not executed here.
    report["recorded_dispatched_jobs"] = decisions.get("dispatched_jobs") or []

    # Agent log of an NPC narrated on-scene.
    if agent_log_appends:
        agents_map = await repo.get_npc_agents(conn, campaign_id)
        applied = []
        for aid, entries in agent_log_appends.items():
            info = agents_map.get(aid)
            if not info:
                continue
            data = info["data"]
            loc = data.get("current_location", "")
            for e in entries:
                data = ast.append_log_entry(data, ast.make_log_entry(
                    turn_index=turn_index,
                    action_summary=e.get("action_summary", ""),
                    location=loc,
                    scene_mode="on_scene",
                    important=bool(e.get("important")),
                    source=e.get("source", "self"),
                    subject_npc_id=e.get("subject_npc_id"),
                ))
            await repo.update_story_card(conn, info["story_card_id"], data)
            applied.append({"agent_id": aid, "entries": len(entries)})
        report["agent_log_appended"] = applied

    # fruit_usage_log: turn_meta.fruit_usage[] -> player log. Player-only; source of truth is the
    # Narrator inline. The Director only flags via inspector when prose uses a fruit without an entry.
    fruit_usage = (turn_meta or {}).get("fruit_usage") or []
    if fruit_usage:
        usage_log = list(psnap.get("fruit_usage_log") or [])
        player_root = _canon_fruit_id(psnap.get("fruit")).split("-", 1)[0]
        npc_fruit_roots = {_canon_fruit_id(n.get("devil_fruit")).split("-", 1)[0] for n in npcs.values()}
        npc_fruit_roots.discard("")
        npc_fruit_roots.discard(player_root)
        added = 0
        for fu in fruit_usage:
            if not isinstance(fu, dict):
                continue
            summary = (fu.get("usage_summary") or "").strip()
            if not summary:
                continue
            # Player-only channel: drop a use whose fruit is a present NPC's (Narrator mislogged it).
            if _canon_fruit_id(fu.get("fruit_id")).split("-", 1)[0] in npc_fruit_roots:
                report["rejected"].append(
                    {"channel": "fruit_usage", "why": "fruta pertence a um NPC, não ao player", "fruit_id": fu.get("fruit_id")}
                )
                continue
            usage_log.append({
                "turn_index": turn_index,
                "fruit_id": fu.get("fruit_id", ""),
                "usage_summary": summary,
            })
            added += 1
        if added:
            psnap["fruit_usage_log"] = usage_log
            report["fruit_usage_logged"] = added

    # News Coo: the Narrator staged the paper inline and reported the edition here. Register the
    # record in news_editions[], drain the consumed pool, mark unpublished events published.
    edition_in = (turn_meta or {}).get("news_coo_edition")
    if isinstance(edition_in, dict) and (edition_in.get("headline") or "").strip():
        from . import news_coo  # late import (mirror settle_day_advance)
        record = news_coo.build_edition_record(edition_in, campaign_day=day, turn_index=turn_index)
        editions = list(meta.get("news_editions") or [])
        editions.append(record)
        meta["news_editions"] = editions
        news_pool = dict(meta.get("news_pool") or {})
        news_pool["bounty_updates"] = []
        news_pool["last_news_turn"] = turn_index
        meta["news_pool"] = news_pool
        for ev in meta.get("events_background") or []:
            if isinstance(ev, dict) and not ev.get("published_in_news"):
                ev["published_in_news"] = True
        report["news_coo"] = record

    # custom techniques: turn_meta.techniques_used[] -> registry. Source of truth is the Narrator
    # inline. Upsert by (owner_id, name): player in the snapshot, crew/nemesis on the card.
    techniques_used = (turn_meta or {}).get("techniques_used") or []
    if techniques_used:
        # The Narrator emits owner_id by NAME; register_from_turn_meta resolves name to id.
        pc_block = player_card.get("player_character") or {}
        player_names = {"[jogador]"}
        pname = (pc_block.get("name") or "").strip().lower()
        if pname:
            player_names.add(pname)
        tech_result = tech.register_from_turn_meta(
            techniques_used,
            player_id=player_card.get("id", "player"),
            player_names=player_names,
            player_techniques=psnap.get("techniques") or [],
            npcs=npcs,
            turn_index=turn_index,
        )
        psnap["techniques"] = tech_result["player_techniques"]
        if tech_result["npc_updates"]:
            agents_map = await repo.get_npc_agents(conn, campaign_id)
            for owner_id, new_list in tech_result["npc_updates"].items():
                info = agents_map.get(owner_id)
                if not info:
                    continue
                data = dict(info["data"])
                data["techniques"] = new_list
                await repo.update_story_card(conn, info["story_card_id"], data)
        if tech_result["registered"]:
            report["techniques_registered"] = tech_result["registered"]

    # Persistence. Re-read the player card fresh: a sheet edit (tier/belly/alignment) may have
    # landed after this turn loaded its state. Overlay only the snapshot keys the engine changed
    # this turn, so a concurrent edit to an untouched field is not clobbered. A confirmed tier-up
    # mirrors into the character faces the sheet shows, keeping the three tier fields consistent.
    player_sc = await repo.get_player_story_card(conn, campaign_id)
    if player_sc is not None:
        new_data = dict(player_sc["data"])
        fresh_snapshot = new_data.get("player_snapshot") or {}
        new_data["player_snapshot"] = _merge_player_snapshot(fresh_snapshot, snapshot_base, psnap)
        if report.get("tier_change") and report["tier_change"].get("new_tier"):
            new_tier = report["tier_change"]["new_tier"]
            char = dict(new_data.get("player_character") or {})
            char["tier"] = new_tier
            new_data["player_character"] = char
            cc = dict(new_data.get("character_creation") or {})
            cc["tier_alvo"] = new_tier
            new_data["character_creation"] = cc
        await repo.update_story_card(conn, player_sc["id"], new_data)
    await repo.update_campaign_metadata(conn, campaign_id, meta)

    return report


def _merge_player_snapshot(fresh: dict, base: dict, working: dict) -> dict:
    """3-way merge of the player_snapshot at persistence time. `base` is the snapshot the turn
    loaded, `working` is the engine's copy after this turn's mutations, `fresh` is what the DB
    holds now (may carry a sheet edit that landed during the turn). Overlay the keys the engine
    changed (working != base) onto fresh and keep fresh for everything else, so a concurrent edit
    to an untouched field survives. Drop keys the engine removed."""
    out = dict(fresh or {})
    base = base or {}
    working = working or {}
    for k, v in working.items():
        if v != base.get(k):
            out[k] = v
    for k in base:
        if k not in working:
            out.pop(k, None)
    return out


def _canon_fruit_id(raw) -> str:
    """Canonical devil-fruit slug: strip diacritics, lowercase, spaces/underscores -> hyphens."""
    if isinstance(raw, dict):
        raw = raw.get("id") or raw.get("name") or ""
    s = unicodedata.normalize("NFKD", str(raw or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[\s_]+", "-", s.strip().lower())


def _bounty_amount(bounty) -> int:
    if isinstance(bounty, dict):
        return int(bounty.get("current_amount", 0) or 0)
    return int(bounty or 0)


async def settle_day_advance(
    conn: aiosqlite.Connection,
    campaign_id: str,
    *,
    old_day: int,
    new_day: int,
) -> dict:
    """Settle what depends on the clock advancing (call when day_counter rises): apply due
    bounty_pending_updates (player and crewmate), feed the News Coo pool (bounty updates +
    cutaway marcos the player crossed) and the passive chaos decay. Reloads metadata from the DB."""
    from . import news_coo  # late import avoids a cycle

    report: dict = {"bounty_applied": []}
    if new_day <= old_day:
        return report
    campaign = await repo.get_campaign(conn, campaign_id)
    metadata = (campaign or {}).get("metadata") or {}
    meta = dict(metadata or {})
    news_pool = dict(meta.get("news_pool") or {})
    pool_bounty_updates = list(news_pool.get("bounty_updates") or [])
    meta_changed = False

    due = await repo.get_due_bounty_updates(conn, campaign_id, new_day)
    if due:
        # NPCs (crewmates) by id, to apply the bounty on their own card (target != player).
        agents_map = await repo.get_npc_agents(conn, campaign_id)
        player_sc = await repo.get_player_story_card(conn, campaign_id)
        player_data = dict(player_sc["data"]) if player_sc else {}
        player_name = (player_data.get("player_character") or {}).get("name", "")
        psnap = dict(player_data.get("player_snapshot") or {})
        player_bounty = psnap.get("bounty")
        if not isinstance(player_bounty, dict):
            player_bounty = {"current_amount": int(player_bounty or 0), "history": []}
        player_touched = False
        crew_touched: dict[str, dict] = {}

        for u in due:
            target = u["target"]
            delta = int(u["delta"])
            if target == "player":
                old_amt = int(player_bounty.get("current_amount", 0))
                new_amt = ws.round_bounty(old_amt + delta)
                player_bounty["current_amount"] = new_amt
                player_bounty.setdefault("history", []).append(
                    {"delta": delta, "tier": u["tier"], "day": new_day, "reason": u["reason"]}
                )
                player_touched = True
                pool_bounty_updates.append({
                    "id": f"bu_{u['id']}", "char_id": player_data.get("id") or "player",
                    "char_name": player_name, "char_kind": "player",
                    "old_amount": old_amt, "new_amount": new_amt,
                    "delta_tier": u["tier"], "reason": u["reason"],
                })
            else:
                info = agents_map.get(target)
                if info is not None:
                    cdata = crew_touched.get(target) or dict(info["data"])
                    cb = cdata.get("bounty")
                    if not isinstance(cb, dict):
                        cb = {"current_amount": int(cb or 0), "history": []}
                    old_amt = int(cb.get("current_amount", 0))
                    new_amt = ws.round_bounty(old_amt + delta)
                    cb["current_amount"] = new_amt
                    cb.setdefault("history", []).append(
                        {"delta": delta, "tier": u["tier"], "day": new_day, "reason": u["reason"]}
                    )
                    cdata["bounty"] = cb
                    crew_touched[target] = cdata
                    is_crew = cdata.get("affiliation") == "player_crew"
                    pool_bounty_updates.append({
                        "id": f"bu_{u['id']}", "char_id": target,
                        "char_name": cdata.get("name", ""),
                        "char_kind": "crewmate" if is_crew else "external_npc",
                        "old_amount": old_amt, "new_amount": new_amt,
                        "delta_tier": u["tier"], "reason": u["reason"],
                    })
            await repo.mark_bounty_update_applied(conn, u["id"], new_day)
            report["bounty_applied"].append({"id": u["id"], "target": target, "delta": delta})

        if player_touched and player_sc is not None:
            psnap["bounty"] = player_bounty
            player_data["player_snapshot"] = psnap
            await repo.update_story_card(conn, player_sc["id"], player_data)
            # No threshold-computed marcos: the Director judges the bounty jump from the raw
            # old_amount/new_amount already carried in the bounty_updates payload.
        for cid, cdata in crew_touched.items():
            info = agents_map.get(cid)
            if info:
                await repo.update_story_card(conn, info["story_card_id"], cdata)

        if pool_bounty_updates != (news_pool.get("bounty_updates") or []):
            news_pool["bounty_updates"] = pool_bounty_updates
            meta["news_pool"] = news_pool
            meta_changed = True
        report["bounty_news_queued"] = len(pool_bounty_updates)

    # Chaos drift over an ellipsis is the Director's call: a chaos_delta source="elapsed" in the
    # POST deltas, applied by apply_post_turn. No passive engine decay.

    if meta_changed:
        await repo.update_campaign_metadata(conn, campaign_id, meta)

    return report
