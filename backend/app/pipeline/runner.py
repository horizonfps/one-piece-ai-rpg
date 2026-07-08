"""Async turn orchestrator: Director pre-turn, agents, narrator, persist, post-turn, crystallizer.

run_turn_events is an async generator emitting status/prose_delta/turn_complete events for the
WebSocket; run_turn consumes the same generator and returns the final payload only.
"""
from __future__ import annotations

import asyncio
import json
import random
import re
from typing import AsyncIterator

import aiosqlite

from .. import config
from ..db import repositories as repo
from ..db import world_snapshot
from . import (
    agent_state,
    agents,
    alliances,
    auditor,
    breakthroughs,
    creature_generator,
    crew,
    crystallizer,
    departure,
    director,
    economy,
    endgame,
    faction,
    fighting_style,
    fruit_alt_canon,
    game_clock,
    item_generator,
    language,
    legend,
    meta_router,
    mushi,
    narrator,
    nemesis,
    news_coo,
    npc_generator,
    npc_mind_post,
    plots,
    poneglyph,
    post_turn,
    reconcile,
    ship,
    ship_generator,
    tactical_actions,
    timeskip,
    trace,
    world_map,
    world_state,
)
from ..proxy.errors import ModelRefusalError, QuotaExceededError

# Prose history fetched per turn. Broad window feeds the ENGINE consumers (cast-transition diff,
# director pre-turn) which read it factually by id/scene. The NARRATOR gets a far shorter slice
# (see below): raw self-prose fed back as context is a style bank the model imitates, and a wide
# window amplifies its tics turn over turn (in-context self-conditioning). Factual long-term
# continuity lives in prior_crystals, not in raw prose.
RECENT_TURNS_FETCH = 20
# Narrator raw-prose window: the open scene's turns. Sized to cover the full crystallization
# cycle: prior_crystals only exist for CLOSED scenes and a scene force-closes at SCENE_TURN_CAP
# (8), so an in-progress scene would lose factual continuity with a tighter cap. prior_crystals
# carry everything from closed scenes; the window never crosses a scene cut (no cross-scene bank).
NARRATOR_SCENE_PROSE_CAP = 10
# Anti-repetition ledger: scan a wider prose window but feed back only the DISTILLED list of
# overused imagery, so the history teaches divergence instead of imitation. Pure bookkeeping
# (counts cross-turn repeats); the Narrator decides how to vary.
OVERUSED_IMAGERY_WINDOW = 8
OVERUSED_IMAGERY_MAX = 10
CONTEXT_TURNS_FOR_CRYSTALLIZER = 4
# Soft cap: at this length the Narrator is nudged (scene_length_notice) to close or justify.
SCENE_TURN_CAP = 8
# Hard ceiling: force-close so long-term memory never stays pending forever (bookkeeping guard).
SCENE_HARD_CAP = 16
# Defensive cap on hunters spawned per appearance event (large squad is texture, not N cards).
BOUNTY_HUNTER_SPAWN_CAP = 5
DEFAULT_NARRATIVE_TIME = 120
RECENT_SUMMARY_MAX_CHARS = 600  # recent_turn_summary truncation for the META router

_DIRECTOR_NEMESIS_ADDENDUM = "director_nemesis_addendum.pt-br.md"
_DIRECTOR_NEMESIS_PARALELO_ADDENDUM = "director_nemesis_paralelo_addendum.pt-br.md"

_NARRATOR_ISLAND_ADDENDUM = "narrator_island_addendum.pt-br.md"
_NARRATOR_THREADS_ADDENDUM = "narrator_threads_addendum.pt-br.md"
_NARRATOR_FRUIT_REMOVAL_HOOK_ADDENDUM = "narrator_fruit_removal_hook_addendum.pt-br.md"

_NARRATOR_COMBAT_ADDENDUM = "narrator_combat_addendum.pt-br.md"

_NARRATOR_OPENING_ADDENDUM = "narrator_opening_addendum.pt-br.md"

# Loaded WITH the combat addendum (references its sections); validated stack is system+combat+tactical.
_NARRATOR_TACTICAL_ADDENDUM = "narrator_tactical_actions_addendum.pt-br.md"

_NARRATOR_CHAOS_ADDENDUM = "narrator_chaos_meter_addendum.pt-br.md"
_NARRATOR_MARINE_MORAL_CODE_ADDENDUM = "narrator_marine_moral_code_addendum.pt-br.md"
_NARRATOR_FIGHTING_STYLE_ADDENDUM = "narrator_fighting_style_addendum.pt-br.md"
_NARRATOR_FACTION_ADDENDUM = "narrator_faction_reputation_addendum.pt-br.md"

_NARRATOR_MUSHI_ADDENDUM = "narrator_mushi_addendum.pt-br.md"

_NARRATOR_CAST_TRANSITION_ADDENDUM = "narrator_cast_transition_addendum.pt-br.md"

_NARRATOR_RETURNING_NPC_ADDENDUM = "narrator_returning_npc_addendum.pt-br.md"

_NARRATOR_SCENE_TRANSITION_ADDENDUM = "narrator_scene_transition_addendum.pt-br.md"

_NARRATOR_ECONOMY_ADDENDUM = "narrator_economy_inventory_addendum.pt-br.md"
_NARRATOR_SHIP_ADDENDUM = "narrator_ship_addendum.pt-br.md"
_NARRATOR_NEWS_COO_ADDENDUM = "narrator_news_coo_addendum.pt-br.md"


async def _load_state(conn: aiosqlite.Connection, campaign_id: str) -> dict:
    campaign = await repo.get_campaign(conn, campaign_id)
    if campaign is None:
        raise LookupError(f"campanha '{campaign_id}' não existe")
    # Every LLM entry point (turn/opening/meta) funnels through here; the language
    # contextvar feeds the writers' volatile directive and engine strings.
    language.set_from_campaign(campaign)
    cards = await repo.get_story_cards(conn, campaign_id)
    player_card = next((c["data"] for c in cards if c["kind"] == "player"), None)
    if player_card is None:
        raise LookupError(f"campanha '{campaign_id}' sem story_card 'player'")
    npcs = {c["data"]["id"]: c["data"] for c in cards if c["kind"] == "npc_agent"}
    item_cards = {
        c["data"]["id"]: c["data"]
        for c in cards
        if c["kind"] == "story_card" and (c["data"] or {}).get("type") == "ITEM" and c["data"].get("id")
    }
    ship_cards = {
        c["data"]["id"]: c["data"]
        for c in cards
        if c["kind"] == "story_card" and (c["data"] or {}).get("type") == "SHIP" and c["data"].get("id")
    }
    faction_cards = {
        c["data"]["id"]: c["data"]
        for c in cards
        if c["kind"] == "story_card" and (c["data"] or {}).get("type") == "FACTION" and c["data"].get("id")
    }
    meta = campaign.get("metadata") or {}
    return {
        "campaign": campaign,
        "player_card": player_card,
        "npcs": npcs,
        "item_cards": item_cards,
        "ship_cards": ship_cards,
        "faction_cards": faction_cards,
        "scene": meta.get("scene", {}),
        "present_npc_ids": meta.get("present_npc_ids", []),
        "clock": await repo.get_clock(conn, campaign_id),
        # Promise crystals feed world_state.open_promises in the Director PRE briefing.
        "promise_crystals": await repo.get_promise_crystals(conn, campaign_id),
    }


def _scene_context(
    scene: dict,
    player_snapshot: dict,
    player_action: dict,
    others: list[dict],
    briefing_note: str = "",
    player_condition: str = "normal",
) -> dict:
    return {
        "location": scene.get("location", ""),
        "ambient": scene.get("ambient", ""),
        "tension_level": scene.get("tension_level", "calm"),
        "trigger": player_action.get("raw", ""),
        "player_visible_state": player_snapshot.get("player_visible_state", ""),
        "player_public_facts": player_snapshot.get("player_public_facts", []),
        # Player body/context condition so the agent calibrates tactics; "normal" = no limitation.
        "player_condition": player_condition,
        "other_npcs_in_scene": others,
        "director_briefing": briefing_note or "",
    }


def _onscene_perception(self_id: str, scene_location: str, npcs: dict, present_ids: set) -> dict:
    """On-scene agent_perception: same-area NPCs not in frame, via last_act (T-1)."""
    acts = []
    for aid, data in npcs.items():
        if aid == self_id or aid in present_ids:
            continue
        last = data.get("last_act")
        if not isinstance(last, dict) or not last.get("action_type"):
            continue
        acts.append({
            "npc_id": aid,
            "npc_name": data.get("name", ""),
            "action_type": last.get("action_type", ""),
            "action_details": last.get("action_details") or {},
            "location": last.get("location") or data.get("current_location", ""),
        })
    return agent_state.build_perception(scene_location, acts)


def _onscene_agent_input(
    agent_self: dict, scene_context: dict, mode: str, clock_light: dict | None,
    *, npcs: dict, present_ids: set, scene_location: str, paired_mushi_ids: set | None = None,
    institutional_standing: dict | None = None, alliance_with_player_crew: dict | None = None,
    recruitment_decision: dict | None = None,
) -> dict:
    """On-scene agent input: perception + own log slice, plus mushi/standing/alliance/recruit signals.
    recruitment_decision is the engine roll outcome for the invite target to voice, not decide."""
    return agents.build_agent_input(
        agent_self,
        scene_mode="on_scene",
        scene_context=scene_context,
        orchestration_mode=mode,
        perception=_onscene_perception(agent_self.get("id", ""), scene_location, npcs, present_ids),
        log_slice=agent_state.log_slice(agent_self.get("personal_event_log")),
        has_paired_mushi=agent_self.get("id", "") in (paired_mushi_ids or set()),
        game_clock=clock_light,
        institutional_standing=institutional_standing,
        alliance_with_player_crew=alliance_with_player_crew,
        recruitment_decision=recruitment_decision,
    )


def _cast_transition_signal(
    meta: dict, *, scene: dict, present_set: set, npcs_known: dict, next_index: int,
) -> dict | None:
    """Cast diff between the previous turn end and this turn's scene, continuous scene only
    (scene did not close last turn + same location). present_npc_ids_turn_index gates freshness:
    no prior turn recorded means no signal. The Director's reconciled present_set arbitrates the
    diff (who entered/left the frame); the engine only relays the set delta. Non-alive exits
    skipped (already staged when the condition landed)."""
    if int(meta.get("present_npc_ids_turn_index") or 0) != next_index - 1:
        return None
    scene_buf = meta.get("scene_buffer") or {}
    open_since = int(scene_buf.get("open_since_turn_index") or 1)
    if open_since >= next_index:
        return None  # scene closed last turn -> new scene, no bridge
    prev_scene = meta.get("scene") or {}
    if (prev_scene.get("location") or "") != (scene.get("location") or ""):
        return None  # location changed -> scene cut, no bridge

    prev_present = set(meta.get("present_npc_ids") or [])
    entrances = [
        npcs_known[a].get("name") for a in sorted(present_set - prev_present)
        if a in npcs_known and npcs_known[a].get("name")
    ]
    exits = [
        npcs_known[a].get("name") for a in sorted(prev_present - present_set)
        if a in npcs_known and npcs_known[a].get("name")
        and (npcs_known[a].get("status") or "alive") == "alive"
    ]
    if not exits and not entrances:
        return None
    out: dict = {}
    if exits:
        out["exits_this_turn"] = exits
    if entrances:
        out["entrances_this_turn"] = entrances
    return out


def _narrator_scene_prose(
    recent_prose: list[dict], *, open_since: int, next_index: int, cap: int = NARRATOR_SCENE_PROSE_CAP
) -> list[dict]:
    """Raw prose handed to the Narrator: only the open scene's last `cap` turns (immediate physical
    continuity). Never the full history, which the model imitates; prior_crystals carry the rest."""
    floor = max(int(open_since or 1), int(next_index) - cap)
    return [e for e in (recent_prose or []) if int(e.get("turn_index") or 0) >= floor]


_NARRATOR_NEARBY_ISLANDS_CAP = 8


def _narrator_nav_block(metadata: dict, decisions: dict) -> dict | None:
    """Real island names for the Narrator so prose names a real place instead of inventing one:
    the Director's chosen_destination (when it picked a real island for a criterion trip) plus the
    nearest navigable islands by name. None off-sea with no destination choice — no risk of the
    prose naming a sea destination there."""
    world = (metadata or {}).get("world") or {}
    pos = (world.get("player") or {}).get("position") or {}
    choice = decisions.get("sea_destination_choice") if isinstance(decisions, dict) else None
    if pos.get("kind") != "sea" and not choice:
        return None
    by_id = {i.get("id"): i for i in (world.get("islands") or []) if i.get("id")}
    names = {iid: i.get("name") for iid, i in by_id.items()}
    cur = world_map.current_island_id(world)
    # Same-sea filter: euclidean nav hints on the wrapped map surface a Grand Line island near the
    # Red Line as "close" to an East Blue one, so restrict names to the player's current cluster(s).
    clusters = {(by_id.get(a) or {}).get("cluster")
                for a in (pos.get("origin_id"), pos.get("dest_id"), cur) if a}
    clusters.discard(None)
    clusters.discard("")
    nav = world_map.nav_summary(metadata).get("navigable_hints") or {}
    ranked = sorted(
        ((iid, d) for iid, d in nav.items()
         if iid != cur and (not clusters or (by_id.get(iid) or {}).get("cluster") in clusters)),
        key=lambda kv: kv[1],
    )
    block: dict = {
        "nearby_islands": [
            {"id": iid, "name": names.get(iid) or iid, "days": days}
            for iid, days in ranked[:_NARRATOR_NEARBY_ISLANDS_CAP]
        ]
    }
    if isinstance(choice, dict) and choice.get("island_id"):
        iid = choice["island_id"]
        block["chosen_destination"] = {"id": iid, "name": choice.get("display_name") or names.get(iid) or iid}
    return block


# Anti-repetition ledger: the Narrator declares (turn_meta.imagery_leaned_on) which images it leaned
# on each open-scene turn; the engine rolls a recent window and feeds it back as the "vary this" bank
# next turn (model-authored, no engine n-gram scan).
def _roll_imagery_ledger(ledger, *, turn_index: int, terms: list[str], window: int) -> list[dict]:
    """Append this turn's declared imagery to the rolling ledger, dropping entries older than the
    window. Each entry is {turn_index, terms}."""
    floor = int(turn_index) - int(window)
    kept = [
        e for e in (ledger or [])
        if isinstance(e, dict)
        and floor < int(e.get("turn_index") or 0) != int(turn_index)
    ]
    clean = [s.strip() for s in (terms or []) if isinstance(s, str) and s.strip()]
    if clean:
        kept.append({"turn_index": int(turn_index), "terms": clean})
    return kept


def _declared_imagery_bank(ledger, *, current_index: int, window: int, cap: int) -> list[str]:
    """Flatten the imagery the Narrator declared over the recent window into a deduped 'vary this'
    bank (most recent first), capped. Empty when nothing was declared."""
    floor = int(current_index) - int(window)
    out: list[str] = []
    seen: set[str] = set()
    entries = sorted(
        (e for e in (ledger or []) if isinstance(e, dict) and int(e.get("turn_index") or 0) >= floor),
        key=lambda e: int(e.get("turn_index") or 0), reverse=True,
    )
    for e in entries:
        for s in (e.get("terms") or []):
            k = (s or "").strip().lower()
            if k and k not in seen:
                seen.add(k)
                out.append(s.strip())
                if len(out) >= cap:
                    return out
    return out


def _recent_offscene_excerpt(data: dict) -> str:
    """Last off_scene log entry of the NPC."""
    for e in reversed(data.get("personal_event_log") or []):
        if isinstance(e, dict) and e.get("scene_mode") == "off_scene":
            return e.get("action_summary", "")
    return ""


def _distance_signal(relation: str) -> str:
    return {"same_subarea": "adjacente", "same_island": "proximo"}.get(relation, "longe_mas_audivel")


def _build_off_screen_periphery(npcs: dict, *, present_ids: set, player_location: str) -> list[dict]:
    # Near-dead since the off-scene tick was removed: the only live off_scene log producer left is
    # the timeskip recap, so it fires rarely. Passive projection (factual, no content-determinism).
    """off_screen_combat_periphery[]: off-scene crew on the player's island with a recent off_scene log."""
    out: list[dict] = []
    for aid, data in npcs.items():
        if aid in present_ids or data.get("affiliation") != "player_crew":
            continue
        if not agent_state.is_active_for_tick(data.get("status", "alive")):
            continue
        rel = agent_state.location_relation(player_location, data.get("current_location", ""))
        if rel == "elsewhere":
            continue
        excerpt = _recent_offscene_excerpt(data)
        if not excerpt:
            continue
        out.append({
            "npc_id": aid,
            "npc_name": data.get("name", ""),
            "location": data.get("current_location", ""),
            "personal_event_log_excerpt": excerpt,
            "distance_signal": _distance_signal(rel),
        })
    return out


async def _persist_onscene_agent(
    conn: aiosqlite.Connection, agents_map: dict, aid: str, output: dict,
    *, scene_location: str, turn_index: int,
) -> None:
    """Persists an on-scene NPC result: log entry + relationship_delta + last_act/last_tick/last_seen."""
    info = agents_map.get(aid)
    if not info:
        return
    details = output.get("action_details") or {}
    involved = [details[k] for k in ("target_npc_id", "hostage_npc_id") if details.get(k)]
    data = agent_state.append_log_entry(info["data"], agent_state.make_log_entry(
        turn_index=turn_index,
        action_summary=output.get("action_summary", ""),
        location=scene_location,
        scene_mode="on_scene",
        npcs_involved=involved,
        important=bool(output.get("important")),
        source="self",
    ))
    data = agent_state.apply_relationship_deltas(
        data, output.get("relationship_delta"), turn_index=turn_index,
        bond_tier_changes=output.get("bond_tier_change"),
    )
    data["last_act"] = {
        "action_type": output.get("action_type", "idle"),
        "action_details": details,
        "location": scene_location,
        "turn_index": turn_index,
    }
    # Position is the Director's call alone (scene_cast_audit + npc_location_updates). The agent
    # only states intent via last_act; the Narrator stages it and the next Director pass moves the
    # NPC if it stands. Writing current_location here was a parallel channel that stranded an
    # off-scene NPC in the scene when its agent was called by mistake (#C1).
    data["last_tick_index"] = turn_index
    data["last_seen_by_player_index"] = turn_index
    data.pop("dormant", None)  # ran on-scene -> catalog wakes and joins the off-scene tick
    await repo.update_story_card(conn, info["story_card_id"], data)


def _creature_briefing(data: dict, briefing_note: str) -> dict:
    """Card-only briefing for a present creature (entity_kind=creature): no agent call. The
    Narrator renders it from species/disposition/behavior_notes, never as dialogue."""
    return {
        "name": data.get("name", ""),
        "is_creature": True,
        "species": data.get("species", ""),
        "tier": data.get("tier", ""),
        "decision": "encene esta criatura pela aparência e pelo comportamento; ela não fala",
        "speech_intent": "",
        "key_information": [],
        "physical_action": briefing_note or data.get("behavior_notes", ""),
        "behavior_notes": data.get("behavior_notes", ""),
        "disposition": data.get("disposition", ""),
        "emotion": data.get("disposition", ""),
        "owner_id": data.get("owner_id"),
        "voice_notes": "",
        "secret_intent": None,
    }


async def _persist_hostage_captures(
    conn: aiosqlite.Connection, campaign_id: str, captures: list[dict],
    *, scene_mode: str, turn_index: int, fallback_location: str = "",
) -> list[dict]:
    """Applies status: captured to taken hostages and persists. Reloads fresh from DB.
    Best-effort. The hostage moves to the captor's current_location (fallback = scene location)."""
    if not captures:
        return []
    fresh = await repo.get_npc_agents(conn, campaign_id)
    applied: list[dict] = []
    for cap in captures:
        info = fresh.get(cap["hostage_id"])
        if not info:
            continue
        captor = (fresh.get(cap["captor_id"]) or {}).get("data") or {}
        new_data = tactical_actions.apply_capture(
            info["data"],
            captor_id=cap.get("captor_id"),
            captor_location=captor.get("current_location") or fallback_location or None,
            scene_mode=scene_mode,
            turn_index=turn_index,
        )
        await repo.update_story_card(conn, info["story_card_id"], new_data)
        applied.append({
            "hostage_id": cap["hostage_id"],
            "hostage_name": info["data"].get("name", ""),
            "captor_id": cap.get("captor_id"),
            "source": cap.get("source"),
        })
    return applied


async def _persist_surrenders(
    conn: aiosqlite.Connection, campaign_id: str, surrenders: list[dict],
    *, scene_mode: str, turn_index: int,
) -> list[dict]:
    """Applies status: surrendered to NPCs that laid down arms (action_type surrender) and persists.
    Reloads fresh from DB. Best-effort. No location change; the next fate is the player's call."""
    if not surrenders:
        return []
    fresh = await repo.get_npc_agents(conn, campaign_id)
    applied: list[dict] = []
    for s in surrenders:
        info = fresh.get(s["npc_id"])
        if not info:
            continue
        new_data = tactical_actions.apply_surrender(
            info["data"], scene_mode=scene_mode, turn_index=turn_index,
        )
        await repo.update_story_card(conn, info["story_card_id"], new_data)
        applied.append({
            "npc_id": s["npc_id"],
            "npc_name": info["data"].get("name", ""),
            "source": s.get("source"),
        })
    return applied


def _narrator_player_combat_view(player_character: dict, real_player_card: dict) -> dict:
    """Enriches the Narrator's player_character with persistent combat state
    (breakthroughs/fighting_style/condition + post-breakthrough fruit/weapon). Adult-only."""
    out = dict(player_character)
    psnap = real_player_card.get("player_snapshot") or {}
    if psnap.get("breakthroughs"):
        out["breakthroughs"] = psnap["breakthroughs"]
    if psnap.get("fighting_style"):
        out["fighting_style"] = psnap["fighting_style"]
    cond = psnap.get("condition")
    if cond and cond != "normal":
        out["condition"] = cond
    cc = real_player_card.get("character_creation") or {}
    df = cc.get("devil_fruit") or {}
    if df.get("awakened") or psnap.get("fruit_awakened"):
        out["fruit_awakened"] = True
        out["fruit_awakening_description"] = (
            df.get("awakening_description") or psnap.get("fruit_awakening_description", "")
        )
    weapon_state = psnap.get("weapon_state") or {}
    if weapon_state.get("is_black_blade"):
        out["weapon_black_blade"] = True
        out["weapon_black_blade_description"] = weapon_state.get("black_blade_description", "")
    return out


# Full character view of another in-scene NPC for the deciding agent: identity, combat kit
# (fruit/haki/techniques/class/armor), read (appearance/alignment/personality/traits) and live
# state/intent. Omits secret backstory and engine bookkeeping; knowledge_clearance flags a
# classified NPC without leaking its content.
_OTHER_NPC_FIELDS = (
    "race", "sex", "age_at_creation", "affiliation", "subtype", "canonical", "aliases",
    "crew_role", "class", "devil_fruit", "haki_profile", "techniques", "narrative_armor",
    "alignment_baseline", "description", "appearance", "personality", "traits",
    "expressiveness", "voice_notes", "status", "mood", "current_state",
    "current_location", "current_goal", "long_term_dream", "knowledge_clearance",
    "relationships",
)


def _other_npcs(resolved: list[tuple], self_id: str, prior_actions: dict[str, str]) -> list[dict]:
    """other_npcs_in_scene for the agent contract: full character card of each other in-scene NPC
    (combat kit + read + live state) so the decider sees real power asymmetry, not just tier. In
    sequential mode, attaches last_action_in_scene of NPCs that already decided this turn."""
    out: list[dict] = []
    for oid, odata, _skip, _bn in resolved:
        if oid == self_id:
            continue
        entry = {"id": oid, "name": odata.get("name", ""), "tier": odata.get("tier", "")}
        entry.update({k: odata.get(k) for k in _OTHER_NPC_FIELDS})
        if oid in prior_actions:
            entry["last_action_in_scene"] = prior_actions[oid]
        out.append(entry)
    return out


def _skipped_crew_briefing(data: dict, briefing_note: str) -> dict:
    """Minimal briefing for an on-scene combat crewmate (skip_agent_call): physical presence
    for inline narration, no agent call."""
    return {
        "name": data.get("name", ""),
        "tier": data.get("tier", ""),
        "knowledge_tier": data.get("knowledge_clearance", ""),
        "decision": "em combate — Opus narra a ação inline",
        "speech_intent": "",
        "key_information": [],
        "physical_action": briefing_note or "",
        "emotion": data.get("mood", ""),
        "voice_notes": data.get("voice_notes", ""),
        "secret_intent": None,
    }


async def _run_outgoing_mushi_target(
    outgoing: dict | None, npcs_known: dict, present_set: set, *,
    scene: dict, player_snapshot: dict, player_action: dict, mode: str,
    clock_light: dict | None, player_condition: str, paired_mushi_ids: set,
    crew_faction_reps: dict | None = None, faction_card_ids: set | None = None,
    crew_alliances: list[dict] | None = None,
) -> tuple[dict, dict] | None:
    """Player called NPC X (outgoing_mushi_call). When the Director validated the channel and X is
    not already in frame, runs X's agent with incoming_player_mushi_call. Returns (data, turn_out)
    for the Narrator briefing (present via mushi, no body) and persistence; None when not applicable."""
    if not isinstance(outgoing, dict) or outgoing.get("target_unavailable"):
        return None
    target_id = outgoing.get("target_npc_id")
    data = npcs_known.get(target_id)
    if not data or target_id in present_set:
        return None
    sc = _scene_context(scene, player_snapshot, player_action, [], "", player_condition)
    inp = agents.build_agent_input(
        data, scene_mode="on_scene", scene_context=sc, orchestration_mode=mode,
        perception={"same_location_events": []},
        log_slice=agent_state.log_slice(data.get("personal_event_log")),
        incoming_player_mushi_call={"mushi_kind": outgoing.get("mushi_kind", "baby")},
        has_paired_mushi=target_id in paired_mushi_ids,
        game_clock=clock_light,
        institutional_standing=faction.build_institutional_standing(data, crew_faction_reps, faction_card_ids),
        alliance_with_player_crew=alliances.alliance_signal_for_npc(
            data, crew_alliances, faction_card_ids=faction_card_ids
        ),
    )
    return data, await agents.call_npc_agent(inp)


# ======================================================================================
# dispatched_jobs: NPC Generator + Conflict Resolver post-turn
# ======================================================================================
def _bounty_int(snapshot: dict) -> int:
    b = snapshot.get("bounty", 0)
    return int(b.get("current_amount", 0) or 0) if isinstance(b, dict) else int(b or 0)


def _news_edition_of(post_report: dict) -> dict | None:
    """News Coo edition registered this turn (built by apply_post_turn from
    turn_meta.news_coo_edition), or None when no paper arrived."""
    if not isinstance(post_report, dict):
        return None
    edition = post_report.get("news_coo")
    return edition if isinstance(edition, dict) and edition.get("markdown") else None


def _endgame_signals(post_report: dict) -> dict:
    """Endgame signals for turn_complete: ending reached this turn (+ epilogue),
    Poneglyphs revealed, and Laugh Tale revealed."""
    eg = post_report.get("endgame") if isinstance(post_report, dict) else None
    if not isinstance(eg, dict):
        return {"ending_reached": None, "epilogue": "",
                "poneglyph_revealed": [], "laugh_tale_revealed": False}
    ending = eg.get("ending") if isinstance(eg.get("ending"), dict) else {}
    pg = eg.get("poneglyph") if isinstance(eg.get("poneglyph"), dict) else {}
    return {
        "ending_reached": ending.get("ending_reached"),
        "epilogue": ending.get("epilogue") or "",
        "poneglyph_revealed": pg.get("revealed") or [],
        "laugh_tale_revealed": bool(ending.get("laugh_tale_revealed")),
    }


def _arc_context(state: dict, scene: dict, clock: dict | None) -> dict:
    """current_arc_context for npc_generator: arc/island/day/tier/bounty.
    island_region stays empty until the island designer structures a region."""
    campaign = state.get("campaign") or {}
    player_card = state.get("player_card") or {}
    pc = player_card.get("player_character") or {}
    ps = player_card.get("player_snapshot") or {}
    location = scene.get("location", "")
    try:
        player_age = int(pc.get("age"))
    except (TypeError, ValueError):
        player_age = None
    return {
        "current_arc": campaign.get("current_arc") or (clock or {}).get("current_arc") or "",
        "island_slug": agent_state.island_of(location),
        "island_region": "",
        "campaign_day": int((clock or {}).get("campaign_day", 0)),
        "player_tier": ps.get("tier") or pc.get("tier", ""),
        "player_bounty": _bounty_int(ps),
        "player_age": player_age,
    }


def _existing_name_keys(npcs_known: dict, player_card: dict) -> set:
    """Lowercase names + aliases that already have a card; base for the npc_generator dedup."""
    keys: set = set()
    for d in npcs_known.values():
        n = (d.get("name") or "").strip().lower()
        if n:
            keys.add(n)
        for a in d.get("aliases") or []:
            if isinstance(a, str) and a.strip():
                keys.add(a.strip().lower())
    pname = ((player_card.get("player_character") or {}).get("name") or "").strip().lower()
    if pname:
        keys.add(pname)
    return keys


async def _run_dispatched_jobs(
    conn: aiosqlite.Connection,
    campaign_id: str,
    *,
    dispatched_jobs: list[dict],
    npcs_to_generate: list[dict],
    items_to_generate: list[dict],
    ships_to_generate: list[dict],
    inspector_warnings: list[dict] | None = None,
    arc_context: dict,
    npcs_known: dict,
    item_cards: dict,
    ship_cards: dict,
    player_card: dict,
    turn_index: int,
    scene_location: str = "",
    anchor_location: str = "",
    scene_prose: str = "",
) -> dict:
    """Runs the dispatched jobs: npc_generator, item_generator, ship_generator.
    All gated by the Director (dispatched_jobs): no dispatch, no run. Generated NPC becomes an
    npc_agent row; item a story_card type=ITEM (+ inventory_entry if acquired); ship a story_card
    type=SHIP (+ swap to active if acquired). Best-effort."""
    report: dict = {
        "generated_npcs": [], "generated_items": [], "generated_ships": [],
        "ship_swaps": [], "skipped": [], "deduped_present_ids": [],
    }
    gen_jobs = [j for j in dispatched_jobs if j.get("kind") == "npc_generator"]
    item_jobs = [j for j in dispatched_jobs if j.get("kind") == "item_generator"]
    ship_jobs = [j for j in dispatched_jobs if j.get("kind") == "ship_generator"]

    # Remediation: a ship the player took possession of in prose that the Narrator never flagged
    # surfaces as an inspector_warnings[unsignaled_ship] with possession fields. Synthesize the
    # generator job + entry so the existing generate+swap path materializes the card and swap.
    syn_ship_jobs, syn_ship_entries = ship.synthesize_unsignaled_ship_acquisitions(
        inspector_warnings, turn_index=turn_index
    )
    if syn_ship_jobs:
        ship_jobs = ship_jobs + syn_ship_jobs
        ships_to_generate = list(ships_to_generate or []) + syn_ship_entries

    # --- NPC Generator --------------------------------------------------------------
    if gen_jobs and npcs_to_generate:
        def _hint_for(name: str) -> str | None:
            nl = (name or "").lower()
            for j in gen_jobs:
                if nl and nl in (j.get("input_ref") or "").lower():
                    return j.get("moral_code_hint")
            return None

        # No name-key pre-filter: the generator judges duplication model-side
        # (agent.duplicate_of_existing_id, FASE 31). Only guard against firing the same-named
        # entry twice in ONE turn (bookkeeping, not a content decision), so the parallel gens
        # do not collide.
        to_gen: list[dict] = []
        creatures_to_gen: list[dict] = []
        _seen_this_turn: set[str] = set()
        for entry in npcs_to_generate:
            name = (entry.get("name") or "").strip()
            if not name:
                continue
            if name.lower() in _seen_this_turn:
                continue
            _seen_this_turn.add(name.lower())
            if (entry.get("entity_kind") or "person") == "creature":
                creatures_to_gen.append(entry)
            else:
                to_gen.append(entry)

        # Existing cast + world memory in one cached block (shared breakpoint), built once and used
        # by the turn's parallel NPCs. Feeds cast awareness so the generator can dedup.
        npc_cached_sections: list | None = None
        # Ids the dedup must never mint as an NPC: the protagonist (any form).
        _player_ids = {
            str(x) for x in (
                player_card.get("id"),
                (player_card.get("player_character") or {}).get("id"),
                "player",
            ) if x
        }

        async def _gen_one(entry: dict) -> dict | None:
            # Siblings minted/named THIS turn (name/role/on_scene): lets each parallel gen see the
            # off-scene captain a mook names and the peers whose name it must not borrow.
            peers = [
                {"name": (p.get("name") or "").strip(), "role": p.get("role") or "",
                 "on_scene": bool(p.get("on_scene", True))}
                for p in npcs_to_generate
                if p is not entry and (p.get("name") or "").strip()
            ]
            try:
                # If this NPC is the canonical owner of the player's chosen fruit, generate it
                # without the fruit (pick-conditional alt-canon). None most of the time.
                active_hook = fruit_alt_canon.active_hook_for(player_card, entry.get("name"))
                npc_input = npc_generator.build_npc_input(
                    entry, arc_context=arc_context, affiliation_hint=entry.get("role"),
                    active_fruit_removal_hook=active_hook,
                    scene_prose_anchor=scene_prose or None,
                    anchor_location=anchor_location or None,
                    peers_this_turn=peers,
                )
                parsed = await npc_generator.call_generate_npc(
                    npc_input, cached_sections=npc_cached_sections
                )
            except Exception as exc:  # noqa: BLE001 best-effort
                return {"name": entry.get("name", ""), "error": f"{type(exc).__name__}: {exc}"}
            if not parsed:
                return {"name": entry.get("name", ""), "error": "sem output utilizável"}
            # Model-side dedup (FASE 31): the generator judged this person already has a card.
            # Reuse it instead of minting a second (the "two Kysa" bug). Matching the protagonist
            # skips materialization (no NPC-clone of the player); a hallucinated id (not the player,
            # not a known NPC) falls through to normal generation.
            _agent = parsed.get("agent") or {}
            dup_id = _agent.get("duplicate_of_existing_id")
            if dup_id:
                if dup_id in _player_ids:
                    return {"duplicate_of": dup_id, "name": entry.get("name", ""), "is_player": True}
                if dup_id in npcs_known:
                    return {
                        "duplicate_of": dup_id, "name": entry.get("name", ""),
                        "duplicate_present_in_scene": bool(_agent.get("duplicate_present_in_scene")),
                    }
            merged = npc_generator.merge_card_agent(parsed["card"], parsed["agent"], turn_index=turn_index)
            # Presence attest (the generator judged, informed by intended_presence + peers): an in-scene
            # mint sits at the scene anchor slug (a prose location or another sub-area's slug both fail
            # the presence gate and expel it the turn it appeared; mirrors the opening normalization).
            # An off-scene mention (a captain named elsewhere) gets a card but no anchor, so it stays
            # out of this turn's cast and the next.
            _present = bool((parsed.get("agent") or {}).get("present_in_scene", True))
            if anchor_location and _present:
                merged["current_location"] = anchor_location
            elif not _present:
                merged["current_location"] = ""
            hint = _hint_for(entry.get("name", ""))
            if hint:
                merged["moral_code"] = hint  # Director annotation
            return {"merged": merged, "present_in_scene": _present}

        if to_gen:
            crystals = await repo.get_all_crystals_for_narrator(conn, campaign_id)
            npc_cached_sections = npc_generator.build_npc_cached_block(npcs_known, crystals)
            results = await asyncio.gather(*[_gen_one(e) for e in to_gen])
            for r in results:
                if r is None or "merged" not in r:
                    if r and r.get("is_player"):
                        report["skipped"].append({
                            "npc_generator": r.get("name", "?"), "why": "dedup → jogador (não materializa)",
                        })
                    elif r and r.get("duplicate_of"):
                        dup_id = r["duplicate_of"]
                        existing = npcs_known.get(dup_id) or {}
                        report["skipped"].append({
                            "npc_generator": r.get("name", "?"),
                            "why": f"dedup pelo modelo → {existing.get('name', dup_id)} ({dup_id})",
                        })
                        # Reconcile presence: the generator attests (duplicate_present_in_scene)
                        # whether the reused person is physically in THIS scene. Honor it; never
                        # resurrect on-scene (an archived card stays archived even if flagged).
                        _dup_present = bool(r.get("duplicate_present_in_scene"))
                        if _dup_present and existing.get("status", "alive") not in ("dead", "missing", "captured"):
                            report["deduped_present_ids"].append(dup_id)
                            if anchor_location and existing.get("current_location") != anchor_location:
                                row = await repo.get_card_by_entity_id(conn, campaign_id, dup_id)
                                if row:
                                    fresh = dict(row["data"])
                                    fresh["current_location"] = anchor_location
                                    await repo.update_story_card(conn, row["id"], fresh)
                                    existing["current_location"] = anchor_location
                    else:
                        report["skipped"].append({"npc_generator": (r or {}).get("name", "?"), "why": (r or {}).get("error", "?")})
                    continue
                merged = r["merged"]
                scid = await repo.add_story_card(conn, campaign_id, "npc_agent", merged)
                report["generated_npcs"].append({
                    "story_card_id": scid, "id": merged.get("id"), "name": merged.get("name"),
                    "tier": (merged.get("current_state") or {}).get("tier"),
                    "affiliation": merged.get("affiliation"),
                    "present_in_scene": r.get("present_in_scene", True),
                })

        # Creatures (entity_kind=creature): lightweight beast cards, no agent mind. Persisted as
        # npc_agent rows so scene presence + Narrator render reach them by id; rendered card-only,
        # never run through an agent call.
        async def _gen_creature(entry: dict) -> dict | None:
            try:
                creature_input = creature_generator.build_creature_input(
                    entry, arc_context=arc_context, owner_hint=entry.get("role"),
                    scene_prose_anchor=scene_prose or None,
                )
                parsed = await creature_generator.call_generate_creature(creature_input, turn_index=turn_index)
            except Exception as exc:  # noqa: BLE001 best-effort
                return {"name": entry.get("name", ""), "error": f"{type(exc).__name__}: {exc}"}
            if not parsed:
                return {"name": entry.get("name", ""), "error": "sem output utilizável"}
            return {"creature": parsed}

        if creatures_to_gen:
            results = await asyncio.gather(*[_gen_creature(e) for e in creatures_to_gen])
            for r in results:
                if r is None or "creature" not in r:
                    report["skipped"].append({"creature_generator": (r or {}).get("name", "?"), "why": (r or {}).get("error", "?")})
                    continue
                cdata = r["creature"]
                if anchor_location:
                    cdata["current_location"] = anchor_location
                scid = await repo.add_story_card(conn, campaign_id, "npc_agent", cdata)
                report["generated_npcs"].append({
                    "story_card_id": scid, "id": cdata.get("id"), "name": cdata.get("name"),
                    "tier": (cdata.get("current_state") or {}).get("tier"),
                    "affiliation": cdata.get("affiliation"), "entity_kind": "creature",
                })

    # --- Item Generator -------------------------------------------------------------
    # Generates an ITEM story_card (card-only) and, if acquired_by_player, an inventory_entry
    # pointing at the returned id (the Director cannot emit an acquired event for a new id). Dedup by name.
    if item_jobs and items_to_generate:
        # No name-key pre-filter against existing cards: the item generator judges duplication
        # model-side (item.duplicate_of_existing_id, FASE 31 pattern). Only guard the same name
        # firing twice in ONE turn (bookkeeping, not a content decision).
        _seen_items_this_turn: set[str] = set()
        to_gen_items: list[dict] = []
        for entry in items_to_generate:
            name = (entry.get("name") or "").strip()
            if not name:
                continue
            if name.lower() in _seen_items_this_turn:
                continue
            _seen_items_this_turn.add(name.lower())
            to_gen_items.append(entry)

        async def _gen_item(entry: dict) -> dict | None:
            try:
                item_input = item_generator.build_item_input(entry, arc_context=arc_context)
                card = await item_generator.call_generate_item(item_input, turn_index=turn_index)
            except Exception as exc:  # noqa: BLE001 best-effort
                return {"name": entry.get("name", ""), "error": f"{type(exc).__name__}: {exc}"}
            if not card:
                return {"name": entry.get("name", ""), "error": "sem output utilizável"}
            _dup = card.get("duplicate_of_existing_id")
            if _dup and _dup in item_cards:
                return {"duplicate_of": _dup, "name": entry.get("name", "")}
            return {
                "card": card,
                "acquired": bool(entry.get("acquired_by_player")),
                "stackable": bool(entry.get("stackable")),
                "origin": entry.get("context", ""),
            }

        if to_gen_items:
            results_items = await asyncio.gather(*[_gen_item(e) for e in to_gen_items])
            acquired_entries: list[dict] = []
            for r in results_items:
                if r is None or "card" not in r:
                    if r and r.get("duplicate_of"):
                        report["skipped"].append({
                            "item_generator": r.get("name", "?"),
                            "why": f"dedup pelo modelo → item {r['duplicate_of']}",
                        })
                    else:
                        report["skipped"].append({"item_generator": (r or {}).get("name", "?"), "why": (r or {}).get("error", "?")})
                    continue
                card = r["card"]
                scid = await repo.add_story_card(conn, campaign_id, "story_card", card)
                report["generated_items"].append({
                    "story_card_id": scid, "id": card.get("id"), "name": card.get("name"),
                    "subtype": card.get("subtype"), "acquired_by_player": r["acquired"],
                })
                if r["acquired"]:
                    acquired_entries.append(economy.make_inventory_entry(
                        card["id"], turn_index=turn_index, origin_note=r["origin"],
                        quantity=(1 if r["stackable"] else None),
                    ))
            # Persist acquired item inventory_entries (reload the player fresh; apply_post_turn
            # already wrote belly/inventory before this stage).
            if acquired_entries:
                player_sc = await repo.get_player_story_card(conn, campaign_id)
                if player_sc is not None:
                    pdata = dict(player_sc["data"])
                    psnap = dict(pdata.get("player_snapshot") or {})
                    psnap["inventory"] = list(psnap.get("inventory") or []) + acquired_entries
                    pdata["player_snapshot"] = psnap
                    await repo.update_story_card(conn, player_sc["id"], pdata)
                    report["inventory_added"] = [e["item_card_id"] for e in acquired_entries]

    # --- Ship Generator -------------------------------------------------------------
    # Generates a SHIP story_card (card-only) and, if acquired_by_player, executes the full swap
    # (active fleet_entry, flip the previous, migrate the Jolly Roger, crystal). The Director
    # cannot emit a swap event for a new id.
    if ship_jobs and ships_to_generate:
        existing_ship_names = {
            (d.get("name") or "").strip().lower() for d in ship_cards.values() if d.get("name")
        }
        # Pair each job to a ships_to_generate entry (by name in input_ref; ordinal fallback).
        consumed: set[int] = set()
        pending_ships: list[tuple[dict, dict]] = []
        for job in ship_jobs:
            ref = (job.get("input_ref") or "").lower()
            picked = None
            for i, e in enumerate(ships_to_generate):
                if i in consumed:
                    continue
                nm = (e.get("tentative_name") or e.get("name") or "").strip().lower()
                if nm and nm in ref:
                    picked = (i, e)
                    break
            if picked is None:
                for i, e in enumerate(ships_to_generate):
                    if i not in consumed:
                        picked = (i, e)
                        break
            if picked is None:
                continue
            idx, entry = picked
            consumed.add(idx)
            nm = (entry.get("tentative_name") or entry.get("name") or "").strip().lower()
            if nm and nm in existing_ship_names:
                report["skipped"].append({"ship_generator": nm, "why": "dedup (navio já tem card)"})
                continue
            if nm:
                existing_ship_names.add(nm)
            pending_ships.append((job, entry))

        async def _gen_ship(pair: tuple[dict, dict]) -> dict | None:
            job, entry = pair
            label = entry.get("tentative_name") or entry.get("name") or ""
            try:
                ship_input = ship_generator.build_ship_input(entry, arc_context=arc_context)
                card = await ship_generator.call_generate_ship(ship_input, turn_index=turn_index)
            except Exception as exc:  # noqa: BLE001 best-effort
                return {"name": label, "error": f"{type(exc).__name__}: {exc}"}
            if not card:
                return {"name": label, "error": "sem output utilizável"}
            return {"card": card, "job": job, "acquired": bool(entry.get("acquired_by_player"))}

        if pending_ships:
            results_ships = await asyncio.gather(*[_gen_ship(p) for p in pending_ships])
            fresh_meta: dict | None = None
            crew_obj: dict | None = None
            gen_cards: dict = {}  # generated cards for the ship_speed_factor derive
            for r in results_ships:
                if r is None or "card" not in r:
                    report["skipped"].append({"ship_generator": (r or {}).get("name", "?"), "why": (r or {}).get("error", "?")})
                    continue
                card = r["card"]
                gen_cards[card["id"]] = card
                await repo.add_story_card(conn, campaign_id, "story_card", card)
                report["generated_ships"].append({
                    "id": card.get("id"), "name": card.get("name"), "subtype": card.get("subtype"),
                    "acquired_by_player": r["acquired"],
                    "hull_condition": (card.get("current_state") or {}).get("hull_condition"),
                })
                if not r["acquired"]:
                    continue
                # Swap: new ship joins the fleet as active (reads fresh metadata). Accumulates
                # crew across jobs and writes once at the end.
                if fresh_meta is None:
                    campaign = await repo.get_campaign(conn, campaign_id)
                    fresh_meta = dict((campaign or {}).get("metadata") or {})
                    crew_obj = ship.get_crew(fresh_meta)
                job = r["job"]
                new_crew, swap_report = await post_turn.execute_ship_swap(
                    conn, campaign_id,
                    crew=crew_obj,
                    swap_event={
                        "new_ship_card_id": card["id"],
                        "previous_ship_card_id": job.get("previous_ship_card_id"),
                        "previous_ship_disposition": job.get("previous_ship_disposition"),
                        "swap_kind": job.get("swap_kind", "acquired"),
                    },
                    ship_cards={card["id"]: card},
                    turn_index=turn_index, scene_location=scene_location,
                )
                if swap_report is not None:
                    crew_obj = new_crew
                    report["ship_swaps"].append(swap_report)
            if fresh_meta is not None and crew_obj is not None:
                fresh_meta["crew"] = crew_obj
                # New ship became active -> re-derive ship_speed_factor (subtype x hull).
                world_map.refresh_player_ship_speed(fresh_meta, {**ship_cards, **gen_cards})
                await repo.update_campaign_metadata(conn, campaign_id, fresh_meta)

    return report


# ======================================================================================
# Adult-world navigation: day advance + position/fog/sea/News Coo
# ======================================================================================
async def _apply_world_navigation(
    conn: aiosqlite.Connection,
    campaign_id: str,
    post_decisions: dict,
    *,
    base_clock: dict,
    turn_index: int,
    arrival_slug: str = "",
) -> tuple[dict, int]:
    """Consumes time_advancement/world_movement from the post-turn (adult world). Advances the
    world clock and updates position/fog/sea-events/News-Coo. Best-effort. Returns (report, final_day).

    Multi-turn voyage: crossing duration is firm (engine). The Director advances time aboard via
    normal narrative trigger and the engine consumes voyage days at the player's pace; arrival
    completes the firm days still owed, so the player never lands with fewer."""
    report: dict = {}
    final_day = int(base_clock["campaign_day"])

    # Position BEFORE touching the clock: during an in-progress voyage it decides the effective advance.
    campaign = await repo.get_campaign(conn, campaign_id)
    meta = dict((campaign or {}).get("metadata") or {})
    world = meta.get("world")
    has_world = isinstance(world, dict)

    movement = post_decisions.get("world_movement")
    movement = movement if (
        isinstance(movement, dict)
        and (movement.get("destination_id") or movement.get("kind") == "set_adrift")
    ) else None
    mv_kind = movement.get("kind") if movement else None
    # The island the arrival pipeline designed/researched this turn IS the one the player lands on
    # (its plot/scene are keyed to that slug). When the Director points arrive_island at a different
    # destination (e.g. a catalogued neighbour or a placeholder id), the map pin would diverge from
    # the story place. Reconcile the pin to the arrived slug so an invented island gets its own
    # blank-slot marker instead of borrowing a catalogued neighbour.
    if mv_kind == "arrive_island" and arrival_slug and movement.get("destination_id") != arrival_slug:
        report["destination_reconciled"] = {"from": movement.get("destination_id"), "to": arrival_slug}
        movement = {**movement, "destination_id": arrival_slug}

    pos = ((world.get("player") or {}).get("position") if has_world else None) or {}
    at_sea = pos.get("kind") == "sea"
    at_sea_directed = at_sea and bool(pos.get("dest_id"))  # adrift (no dest) owes no crossing days
    remaining = world_map.sea_days_remaining(world) if has_world else 0

    # (1) day advance. The Director emits advance_days via narrative trigger. On an arrival from
    # the sea, the engine completes the firm days still owed (player picks the pace, not the duration).
    ta = post_decisions.get("time_advancement")
    advance_days = (
        int(ta["advance_days"])
        if isinstance(ta, dict) and isinstance(ta.get("advance_days"), int) and ta["advance_days"] > 0
        else 0
    )
    days_for_arrival = None  # sea days to sample on arrival (None = not an arrival)
    if mv_kind == "arrive_island":
        if at_sea_directed:
            days_for_arrival = remaining  # completes what the in-progress voyage owed
        else:
            # Compressed into one turn (skipped without boarding): engine imposes the duration
            # (firm hint); an explicit number from prose (advance_days) wins only if larger.
            origin = movement.get("origin_id") or world_map.current_island_id(world)
            hint = world_map.crossing_days_hint(world, origin, movement.get("destination_id"))
            days_for_arrival = max(advance_days, hint) if hint >= 1 else advance_days
        effective_advance = max(advance_days, days_for_arrival)
    else:
        effective_advance = advance_days

    if effective_advance > 0:
        advanced, _w = game_clock.compute_next_clock(
            base_clock,
            time_advancement={"advance_days": effective_advance},
            set_arc=None,
            scene_npc_ages={},
            turn_index=turn_index,
        )
        await repo.save_clock(conn, campaign_id, advanced)
        await repo.append_clock_snapshot(
            conn, campaign_id, turn_index, game_clock.snapshot_of(advanced, turn_index)
        )
        final_day = int(advanced["campaign_day"])
        report["advance_days"] = effective_advance

    # (2) position/fog/progress. No world_movement on land -> position intact. At sea, time
    # advance without movement progresses the voyage.
    if not has_world:
        return report, final_day

    old_island = world_map.current_island_id(world)
    new_world = None
    mv_report = None

    # Off-catalog invented destination: anchor it onto a real blank map slot (Blues only) so it
    # gets coords + a marker instead of a phantom position. Name comes from the island designer
    # (cached at arrival); placeholder until then, upgraded when the designer name lands.
    if movement and mv_kind in ("set_sea", "arrive_island") and movement.get("destination_id"):
        dest_id = movement["destination_id"]
        existing = next((i for i in (world.get("islands") or []) if i.get("id") == dest_id), None)
        if existing is None or existing.get("canonical") == "generated":
            ctx = await repo.get_invented_context(conn, campaign_id, dest_id)
            gen = world_map.ensure_generated_island(
                world, dest_id, name=(ctx or {}).get("island_name"),
                near_island_id=movement.get("origin_id") or old_island,
            )
            if gen is not None:
                report["generated_island"] = {
                    "id": gen["id"], "name": gen.get("name"), "coords": gen.get("coords")
                }

    if mv_kind == "set_adrift":
        # Left port with no chosen destination: adrift at open sea. Time still passes aboard.
        new_world, mv_report = world_map.apply_movement(
            world, movement, days=advance_days, arrival_day=final_day, rng=random,
        )
    elif mv_kind == "arrive_island":
        # Arrival: from the sea samples only the remaining sea days (the rest came leg by leg);
        # a voyage compressed into one turn samples the whole crossing (hint duration).
        new_world, mv_report = world_map.apply_movement(
            world, movement, days=days_for_arrival, arrival_day=final_day, rng=random,
        )
    elif mv_kind == "set_sea":
        same_voyage = at_sea and pos.get("dest_id") == movement.get("destination_id")
        if same_voyage:
            # Re-emit of the same in-progress route: progress at pace, do not restart the voyage.
            if advance_days > 0:
                new_world, mv_report = world_map.advance_sea_travel(world, advance_days, rng=random)
        else:
            new_world, mv_report = world_map.apply_movement(
                world, movement, days=advance_days, arrival_day=final_day, rng=random,
            )
    elif at_sea and advance_days > 0:
        # Aboard, no world_movement: consume voyage time at the player's pace.
        new_world, mv_report = world_map.advance_sea_travel(world, advance_days, rng=random)

    if new_world is not None:
        meta["world"] = new_world
        await repo.update_campaign_metadata(conn, campaign_id, meta)
        report["movement"] = mv_report
    return report, final_day


# ======================================================================================
# Evolving Nemesis Marine + News Coo (adult world, post-navigation)
# ======================================================================================
async def _apply_nemesis_and_news(
    conn: aiosqlite.Connection,
    campaign_id: str,
    *,
    director_state: dict,
    scene: dict,
    clock: dict | None,
    final_day: int,
    turn_index: int,
    nemesis_update: dict | None,
    nemesis_spawn: dict | None,
    recent_act_summary: str,
) -> dict:
    """Nemesis Marine watcher (spawn + Director milestone + permadeath). Rereads fresh metadata and
    rewrites it once at the end. Best-effort. nemesis_update is the parsed Director POST channel
    (usually None). News Coo is no longer composed here; the Narrator stages it inline and
    apply_post_turn registers the edition from turn_meta."""
    report: dict = {}
    fresh_campaign = await repo.get_campaign(conn, campaign_id)
    metadata = dict((fresh_campaign or {}).get("metadata") or {})

    player_sc = await repo.get_player_story_card(conn, campaign_id)
    player_card = (player_sc or {}).get("data") or director_state["player_card"]
    psnap = player_card.get("player_snapshot") or {}
    player_bounty = _bounty_int(psnap)
    arc_context = _arc_context(director_state, scene, clock)
    arc_context["campaign_day"] = final_day      # day already advanced post-settle
    arc_context["player_bounty"] = player_bounty  # bounty already settled

    # --- Nemesis Marine (spawn/evolve/permadeath) ---
    try:
        nem_state, nem_report = await nemesis.run_nemesis(
            conn, campaign_id,
            metadata=metadata, player_bounty=player_bounty, scene=scene,
            day=final_day, turn_index=turn_index,
            recent_act_summary=recent_act_summary, player_snapshot=psnap,
            arc_context=arc_context, director_update=nemesis_update, spawn_decision=nemesis_spawn,
        )
        metadata["nemesis"] = nem_state
        if nem_report:
            report["nemesis"] = nem_report
    except Exception as exc:  # noqa: BLE001 nemesis best-effort
        report["nemesis"] = {"error": f"{type(exc).__name__}: {exc}"}

    await repo.update_campaign_metadata(conn, campaign_id, metadata)
    return report


# ======================================================================================
# Endgame: Poneglyphs (reveal + triangulate Laugh Tale) + Ending Candidate Detector
# ======================================================================================
async def _run_endgame(
    conn: aiosqlite.Connection,
    campaign_id: str,
    *,
    director_state: dict,
    scene: dict,
    dispatched_jobs: list[dict],
    recent_act_summary: str,
    turn_index: int,
) -> dict:
    """Post-turn endgame (adult world). (1) Poneglyphs: reveal content of translated ones +
    triangulate Laugh Tale -> patch metadata.endgame. (2) Ending Candidate Detector, gated by
    dispatched_jobs[ending_candidate_detector]. Rereads fresh state. Best-effort."""
    report: dict = {}
    cards = await repo.get_story_cards(conn, campaign_id)
    player_card = next((c["data"] for c in cards if c["kind"] == "player"), None) or director_state["player_card"]
    npcs = {
        c["data"]["id"]: c["data"]
        for c in cards if c["kind"] == "npc_agent" and (c["data"] or {}).get("id")
    }
    item_cards = {
        c["data"]["id"]: c["data"]
        for c in cards
        if c["kind"] == "story_card" and (c["data"] or {}).get("type") == "ITEM" and (c["data"] or {}).get("id")
    }
    campaign = await repo.get_campaign(conn, campaign_id)
    metadata = dict((campaign or {}).get("metadata") or {})
    clock = await repo.get_clock(conn, campaign_id)
    campaign_day = int((clock or {}).get("campaign_day", 0))
    current_arc = (campaign or {}).get("current_arc") or (clock or {}).get("current_arc") or ""

    # (1) Poneglyphs: reveal translated ones + triangulate Laugh Tale.
    pg = await poneglyph.process(
        conn, campaign_id,
        item_cards=item_cards, player_card=player_card, npcs=npcs,
        metadata=metadata, current_arc=current_arc, turn_index=turn_index,
    )
    if pg.get("endgame_patch"):
        # process wrote the cards but not the metadata: fresh RMW and merge the patch so the
        # detector reads the updated state.
        fresh = await repo.get_campaign(conn, campaign_id)
        metadata = endgame.merge_endgame_patch(dict((fresh or {}).get("metadata") or {}), pg["endgame_patch"])
        await repo.update_campaign_metadata(conn, campaign_id, metadata)
    if pg.get("revealed") or pg.get("errors"):
        report["poneglyph"] = pg

    # (2) Ending Candidate Detector, gated by the Director (dispatched_jobs). Qualitatively judges
    # world-flag mutations + Laugh Tale reveal + ending reached; fires the automatic epilogue on detection.
    if any(isinstance(j, dict) and j.get("kind") == "ending_candidate_detector" for j in dispatched_jobs):
        present_names = [
            npcs[i].get("name", "") for i in (metadata.get("present_npc_ids") or []) if i in npcs
        ]
        report["ending"] = await endgame.detect_and_persist(
            conn, campaign_id,
            player_card=player_card, npcs=npcs, metadata=metadata, item_cards=item_cards,
            campaign_day=campaign_day, recent_turn_summary=recent_act_summary, turn_index=turn_index,
            scene=scene, present_names=present_names,
            current_age=int((clock or {}).get("current_player_age", 0)),
        )
    return report


# ======================================================================================
# Crew recruitment + bounty hunters (adult world, post-jobs)
# ======================================================================================
async def _apply_crew_recruitment(
    conn: aiosqlite.Connection,
    campaign_id: str,
    *,
    join_ids: list[str],
    resolved_offer_ids: list[str],
    new_invite_ids: list[str],
    pending_offers: list[dict],
    player_alignment_value: float,
    scene_location: str,
    turn_index: int,
    reconcile_ids: list[str] | None = None,
) -> dict:
    """Materializes engine-decided recruitment. join_ids become members (affiliation: player_crew);
    resolved_offer_ids leave the pending queue; new_invite_ids enter it; reconcile_ids only clear
    the reconciliation gate. Recomputes crew_alignment (captain weight 3) and persists. Best-effort."""
    agents_map = await repo.get_npc_agents(conn, campaign_id)
    report: dict = {"joined": [], "offers_added": [], "offers_resolved": list(resolved_offer_ids),
                    "reconciled": [], "skipped": [], "warnings": []}
    crystals: list[dict] = []

    for nid in join_ids:
        info = agents_map.get(nid)
        if not info:
            report["skipped"].append({"join": nid, "why": "inexistente"})
            continue
        if crew.is_member(info["data"]):
            continue
        # Aptitude gate. allow_reconcile: re-inviting a present ex-member is the reconciliation
        # scene; add_member clears the flag.
        _ok, _why = crew.can_recruit(info["data"], allow_reconcile=True)
        if not _ok:
            report["skipped"].append({"join": nid, "why": _why})
            # The Narrator staged this join as accepted but the target is not eligible: flag it for
            # the Auditor instead of vetoing in silence (prose/state drift becomes a case).
            report["warnings"].append({"join": nid, "name": info["data"].get("name", ""), "why": _why})
            continue
        data = crew.add_member(info["data"], turn_index=turn_index)
        await repo.update_story_card(conn, info["story_card_id"], data)
        agents_map[nid] = {**info, "data": data}
        report["joined"].append({"id": nid, "name": data.get("name", "")})
        crystals.append(crew.recruit_audit_crystal(data.get("name", ""), location=scene_location, accepted=True))

    # Reconciliation without rejoining: player made peace but the ex-member declined to return now.
    # Clear awaiting_reconciliation so a future invite is not stuck (does not become a member).
    for nid in (reconcile_ids or []):
        info = agents_map.get(nid)
        if not info or not crew.is_awaiting_reconciliation(info["data"]):
            continue
        data = crew.mark_reconciled(info["data"])
        await repo.update_story_card(conn, info["story_card_id"], data)
        agents_map[nid] = {**info, "data": data}
        report["reconciled"].append({"id": nid, "name": data.get("name", "")})

    offers = list(pending_offers or [])
    for nid in resolved_offer_ids:
        offers = crew.remove_pending_offer(offers, nid)
    for nid in new_invite_ids:
        info = agents_map.get(nid)
        if not info or crew.is_member(info["data"]):
            continue
        offers = crew.add_pending_offer(offers, nid, info["data"].get("name", ""), turn_index=turn_index)
        report["offers_added"].append({"id": nid, "name": info["data"].get("name", "")})

    fresh = {aid: i["data"] for aid, i in agents_map.items()}
    # Prune orphan offers (dead/gone/missing/already-member target) from the persisted queue.
    offers = crew.prune_pending_offers(offers, fresh)
    crew_align = world_state.compute_crew_alignment(player_alignment_value, crew.member_alignment_values(fresh))
    campaign = await repo.get_campaign(conn, campaign_id)
    meta = dict((campaign or {}).get("metadata") or {})
    meta["crew_offers"] = offers
    meta["crew_alignment"] = crew_align
    await repo.update_campaign_metadata(conn, campaign_id, meta)
    if crystals:
        await repo.append_new_crystals(conn, campaign_id, crystals, source_turn_index=turn_index)
    report["crew_alignment"] = crew_align
    report["crew_size"] = crew.crew_size(fresh)
    return report


async def _apply_bounty_hunters(
    conn: aiosqlite.Connection,
    campaign_id: str,
    *,
    events: list[dict],
    arc_context: dict,
    scene: dict,
    turn_index: int,
    crew_alliances: list[dict],
) -> dict:
    """Runs the Director's bounty_hunter_events. appearance generates hunters via NPC Generator
    (npc_agent, affiliation bounty_hunter_*) + anti-saturation log + crystal; the spawn is the gate.
    nemesis_paralelo_promoted marks the hunter card (is_nemesis_paralelo). Best-effort."""
    report: dict = {"spawned": [], "promoted": [], "skipped": [], "warnings": []}
    appearances = [e for e in events if isinstance(e, dict) and e.get("kind") == "appearance"]
    promotions = [e for e in events if isinstance(e, dict) and e.get("kind") == "nemesis_paralelo_promoted"]
    allied_ids = {a.get("crew_b_id") for a in (crew_alliances or [])}
    scene_loc = scene.get("location", "")

    for ev in appearances:
        archetype = (ev.get("hunter_archetype") or "").strip()
        scene_hint = (ev.get("scene_hint") or "").strip()
        affiliation = alliances.affiliation_for_archetype(archetype)
        # The Director already consults active alliances (world_state.crew_alliances +
        # alliances_hunters_pre_audit spawn-blocking). Trust the emitted event and honor the spawn;
        # log a soft warning instead of vetoing, so a canon-justified hunter from an allied faction
        # is not silently dropped (a betrayal may be intentional).
        if affiliation in allied_ids:
            report["warnings"].append(
                {"archetype": archetype, "note": "afiliação aliada — spawn honrado (era veto)"}
            )
        _emitted_ids = [i for i in (ev.get("hunter_npc_ids") or []) if i]
        if not _emitted_ids:
            report["skipped"].append({"archetype": archetype, "why": "appearance sem hunter_npc_ids (Diretor nomeia cada caçador)"})
            continue
        ids = _emitted_ids[:BOUNTY_HUNTER_SPAWN_CAP]
        if len(_emitted_ids) > BOUNTY_HUNTER_SPAWN_CAP:
            report["warnings"].append({"archetype": archetype, "note": f"cap {BOUNTY_HUNTER_SPAWN_CAP} — {len(_emitted_ids)} pedidos, {BOUNTY_HUNTER_SPAWN_CAP} gerados"})

        async def _gen(_placeholder, _arch=archetype, _hint=scene_hint, _aff=affiliation) -> dict:
            entry = {
                "name": None, "role": "bounty_hunter",
                "context": f"Caçador de recompensa não-Marine: {_arch}. {_hint}".strip(),
            }
            try:
                npc_input = npc_generator.build_npc_input(
                    entry, arc_context=arc_context, affiliation_hint=_aff, expected_recurrence="low",
                )
                # No cast-dedup block here on purpose: a bounty hunter is always a fresh spawn.
                parsed = await npc_generator.call_generate_npc(npc_input)
            except Exception as exc:  # noqa: BLE001 best-effort
                return {"error": f"{type(exc).__name__}: {exc}"}
            if not parsed:
                return {"error": "sem output utilizável"}
            merged = npc_generator.merge_card_agent(parsed["card"], parsed["agent"], turn_index=turn_index)
            merged["affiliation"] = _aff
            merged["role"] = "bounty_hunter"
            merged["current_location"] = merged.get("current_location") or scene_loc
            return {"merged": merged}

        results = await asyncio.gather(*[_gen(i) for i in ids])
        spawned_names: list[str] = []
        spawned_ids: list[str] = []
        for r in results:
            if "merged" not in r:
                report["skipped"].append({"archetype": archetype, "why": r.get("error", "?")})
                continue
            m = r["merged"]
            await repo.add_story_card(conn, campaign_id, "npc_agent", m)
            spawned_names.append(m.get("name", ""))
            spawned_ids.append(m.get("id"))
            report["spawned"].append({
                "id": m.get("id"), "name": m.get("name"), "affiliation": affiliation,
                "tier": (m.get("current_state") or {}).get("tier") or m.get("tier", ""),
            })
        if spawned_ids:
            await repo.append_new_crystals(
                conn, campaign_id,
                [alliances.bounty_hunter_audit_crystal(
                    archetype, affiliation=affiliation, location=scene_loc, hunter_names=spawned_names,
                )],
                source_turn_index=turn_index,
            )
            campaign = await repo.get_campaign(conn, campaign_id)
            meta = dict((campaign or {}).get("metadata") or {})
            meta["bounty_hunter_log"] = alliances.append_bounty_hunter_log(
                alliances.bounty_hunter_log_of(meta),
                turn_index=turn_index, archetype=archetype, affiliation=affiliation,
                hunter_ids=spawned_ids, location=scene_loc, summary=scene_hint,
            )
            await repo.update_campaign_metadata(conn, campaign_id, meta)

    for ev in promotions:
        hid = (ev.get("hunter_npc_id") or "").strip()
        card = await repo.get_card_by_entity_id(conn, campaign_id, hid) if hid else None
        if not card:
            report["skipped"].append({"promote": hid, "why": "caçador inexistente"})
            continue
        data = dict(card["data"])
        data["is_nemesis_paralelo"] = True
        data["nemesis_paralelo_promoted_at_turn_index"] = turn_index
        data["nemesis_paralelo_reasoning"] = (ev.get("reasoning") or "").strip()
        await repo.update_story_card(conn, card["id"], data)
        _promo_fact = (ev.get("reasoning") or "").strip() or f"{data.get('name', 'O caçador')} virou perseguidor recorrente do bando."
        await repo.append_new_crystals(
            conn, campaign_id,
            [{"category": "world_fact",
              "fact": _promo_fact,
              "characters": [data.get("name", "")], "location": scene_loc, "participants": []}],
            source_turn_index=turn_index,
        )
        report["promoted"].append({"id": hid, "name": data.get("name")})
    return report


async def _apply_parallel_nemesis_updates(
    conn: aiosqlite.Connection,
    campaign_id: str,
    *,
    events: list[dict],
    scene: dict,
    turn_index: int,
) -> dict:
    """Applies the Director's parallel_nemesis_updates: evolution of hunters already promoted to
    parallel nemesis, decoupled from confrontation. defeated_on_scene dead/missing archives by card
    status. Only acts on cards with is_nemesis_paralelo (gate). Best-effort."""
    report: dict = {"updated": [], "archived": [], "skipped": []}
    scene_loc = scene.get("location", "")
    for ev in events:
        hid = (ev.get("hunter_npc_id") or "").strip()
        card = await repo.get_card_by_entity_id(conn, campaign_id, hid) if hid else None
        if not card or not (card["data"] or {}).get("is_nemesis_paralelo"):
            report["skipped"].append({"hunter_npc_id": hid, "why": "caçador inexistente ou não promovido"})
            continue
        new_data, evo = nemesis.apply_parallel_nemesis_update(card["data"], ev, turn_index=turn_index)
        await repo.update_story_card(conn, card["id"], new_data)
        hunter_name = (new_data.get("name") or "").strip()
        name = hunter_name or language.engine_str("fallback_the_hunter")
        kind = evo.get("change_kind")
        if kind == "defeated_on_scene" and evo.get("outcome") in ("dead", "missing"):
            report["archived"].append({"id": hid, "name": name, "outcome": evo["outcome"]})
            fact, cat = language.engine_str("hunter_out_of_play", name=name, outcome=evo["outcome"]), "combat_outcome"
        elif kind == "evolved":
            report["updated"].append({"id": hid, "name": name, "change_kind": kind, "facet": evo.get("facet")})
            facet = evo.get("facet") or language.engine_str("hunter_facet_fallback")
            fact, cat = language.engine_str("hunter_evolved", name=name, facet=facet), "world_fact"
        elif kind == "posture_shift":
            report["updated"].append({"id": hid, "name": name, "change_kind": kind})
            fact, cat = language.engine_str("hunter_posture_shift", name=name, posture=evo.get("new_posture")), "world_fact"
        else:  # clash / defeated captured
            report["updated"].append({"id": hid, "name": name, "change_kind": kind})
            fact, cat = language.engine_str("hunter_clash", name=name), "combat_outcome"
        await repo.append_new_crystals(
            conn, campaign_id,
            [{"category": cat, "fact": fact, "characters": [hunter_name] if hunter_name else [],
              "location": scene_loc, "participants": []}],
            source_turn_index=turn_index,
        )
    return report


async def _persist_pending_offer(
    conn: aiosqlite.Connection, campaign_id: str, *, new_offer: dict | None,
    withdraw: bool, turn_index: int,
) -> None:
    """Maintains metadata.pending_offer_training. A valid training offer the player did not accept
    this turn becomes pending for the next; the Director withdraws a stale one via withdraw. Fresh RMW."""
    campaign = await repo.get_campaign(conn, campaign_id)
    meta = dict((campaign or {}).get("metadata") or {})
    changed = False
    if isinstance(new_offer, dict) and new_offer.get("mentor_npc_id"):
        meta["pending_offer_training"] = {**new_offer, "offered_at_turn_index": turn_index}
        changed = True
    elif withdraw and isinstance(meta.get("pending_offer_training"), dict):
        meta.pop("pending_offer_training", None)
        changed = True
    if changed:
        await repo.update_campaign_metadata(conn, campaign_id, meta)


# ======================================================================================
# Communication: persist PRE-turn effects (mushi/vivre)
# ======================================================================================
async def _persist_mushi_vivre_pre(
    conn: aiosqlite.Connection, campaign_id: str, *, decisions: dict, turn_index: int
) -> dict:
    """Persists PRE-turn communication effects the Narrator just rendered:
    (1) vivre_card_state_change updates visual_state in player_snapshot + syncs agent.vital_at_risk;
    (2) mushi_call_active carries into metadata across turns.
    Rereads fresh. Best-effort."""
    report: dict = {}
    change = decisions.get("vivre_card_state_change")
    if isinstance(change, dict) and change.get("npc_id"):
        player_sc = await repo.get_player_story_card(conn, campaign_id)
        if player_sc is not None:
            data = dict(player_sc["data"])
            psnap = dict(data.get("player_snapshot") or {})
            res = mushi.apply_vivre_card_state_change(psnap, change)
            if res["applied"]:
                data["player_snapshot"] = psnap
                await repo.update_story_card(conn, player_sc["id"], data)
                report["vivre_card_change"] = res
                var = mushi.vital_at_risk_for_visual(res["new_visual_state"])
                if var is not None:
                    info = (await repo.get_npc_agents(conn, campaign_id)).get(res["npc_id"])
                    if info and bool(info["data"].get("vital_at_risk")) != var:
                        adata = dict(info["data"])
                        adata["vital_at_risk"] = var
                        await repo.update_story_card(conn, info["story_card_id"], adata)

    campaign = await repo.get_campaign(conn, campaign_id)
    meta = dict((campaign or {}).get("metadata") or {})
    new_active = decisions.get("mushi_call_active")
    if meta.get("mushi_call_active") != new_active:
        if new_active:
            meta["mushi_call_active"] = new_active
        else:
            meta.pop("mushi_call_active", None)
        await repo.update_campaign_metadata(conn, campaign_id, meta)
        report["mushi_call_active"] = new_active
    return report


# ======================================================================================
# Timeskip: batch executor + recap (counts as 1 turn)
# ======================================================================================
async def _run_timeskip(
    conn: aiosqlite.Connection,
    campaign_id: str,
    *,
    offer: dict,
    player_action: dict,
    scene: dict,
    clock: dict | None,
    npcs: dict,
    turn_index: int,
    trace_buf,
) -> AsyncIterator[dict]:
    """Short-circuits the turn as a timeskip: batch executor + tier-up + recap, persists as one
    turn, advances the clock by the duration and closes the scene (no crystallizer; recap is the
    summary). Best-effort inside the apply."""
    skip = timeskip.skip_params_from_offer(offer)
    yield {"type": "status", "phase": "timeskip"}
    result = await timeskip.apply_timeskip(
        conn, campaign_id,
        skip=skip, scene=scene, clock=clock, turn_index=turn_index, npcs=npcs,
    )
    await conn.commit()
    prose = result["prose"]

    # Auditor gate over the recap montage before the reveal: form vices (§3.3) + player agency. The
    # recap is a summary BY DESIGN (prose_kind scopes the recap vice off the time compression) and the
    # scene closes on the jump, so no cast to mint/re-presence. Best-effort.
    try:
        _ts_crystals = await repo.get_all_crystals_for_narrator(conn, campaign_id)
        _ts_psc = await repo.get_player_story_card(conn, campaign_id)
        prose, _ts_audit = await auditor.audit_prose(
            conn, campaign_id,
            prose=prose, player_action=player_action, scene=scene, prose_kind="timeskip_recap",
            crystals=_ts_crystals,
            player_card=(_ts_psc or {}).get("data"),
            game_clock=game_clock.light_clock(clock) if clock else None,
        )
    except Exception:  # noqa: BLE001 timeskip auditor best-effort
        pass
    yield {"type": "prose_delta", "text": prose}

    real_index = await repo.append_turn(
        conn, campaign_id,
        player_input=player_action,
        narrator_prose=prose,
        agent_decisions={"timeskip": result["report"]},
        scene_snapshot=scene,
        trace=trace_buf,
    )
    # Close the current scene: the recap is a long ellipsis, the next scene starts fresh.
    campaign_now = await repo.get_campaign(conn, campaign_id)
    meta_now = dict((campaign_now or {}).get("metadata") or {})
    meta_now["scene_buffer"] = {"open_since_turn_index": real_index + 1}
    await repo.update_campaign_metadata(conn, campaign_id, meta_now)
    await conn.commit()

    final_clock = result.get("final_clock") or await repo.get_clock(conn, campaign_id)
    yield {
        "type": "turn_complete",
        "turn_index": real_index,
        "prose": prose,
        "turn_meta": {"scene_status": "fecha"},
        "scene_closed": True,
        "new_crystals": [],
        "clock": game_clock.light_clock(final_clock) if final_clock else None,
        "scene": meta_now.get("scene", {}),
        "timeskip": result["report"],
        "post_turn": {"timeskip": True, "tier_change": result["report"].get("tier_after")},
        "trace": trace_buf,
    }


# ======================================================================================
# Error runtime: quota exceeded + model refusal
# ======================================================================================
# Terminal turn events the UI handles without breaking immersion (not generic errors).
TURN_ERROR_TYPES = ("quota_exceeded", "model_refusal")


def turn_error_event(exc: BaseException) -> dict | None:
    """Maps a structured runtime error to its turn event, or None if generic (caller surfaces as
    error). A pre-append quota/refusal (the Narrator call) aborts the whole turn; a post-append one
    keeps the durable narration and is flagged via turn_complete.quota_interrupted instead."""
    if isinstance(exc, QuotaExceededError):
        return {
            "type": "quota_exceeded",
            "message": str(exc) or "assinatura Claude Max no limite — volte mais tarde",
            "retry_after_seconds": exc.retry_after_seconds,
            "reset_hint": exc.reset_hint,
        }
    if isinstance(exc, ModelRefusalError):
        return {
            "type": "model_refusal",
            "message": str(exc) or "o modelo recusou renderizar este input",
            "stage": exc.stage,
        }
    return None


async def run_turn_events(
    conn: aiosqlite.Connection, campaign_id: str, player_action: dict
) -> AsyncIterator[dict]:
    """Surfacing wrapper: runs the turn and converts quota/refusal into terminal structured events;
    other exceptions bubble. Scene transitions live inside a single turn (place-hook at the close,
    time-ellipsis mid-prose); the engine never chains a player-less follow turn."""
    try:
        async for ev in _run_turn_events_inner(conn, campaign_id, player_action):
            yield ev
    except (QuotaExceededError, ModelRefusalError) as exc:
        yield turn_error_event(exc)


async def _run_turn_events_inner(
    conn: aiosqlite.Connection, campaign_id: str, player_action: dict
) -> AsyncIterator[dict]:
    # META does not advance the turn: route pergunta/lembre/esqueça and return.
    if (player_action.get("type") or "DO").upper() == "META":
        async for ev in run_meta_events(conn, campaign_id, player_action):
            yield ev
        return

    # Devtools turn trace buffer (each LLM call input/output). Goes in turn_complete; not persisted.
    trace_buf = trace.start()

    state = await _load_state(conn, campaign_id)
    player_card = state["player_card"]
    player_character = player_card["player_character"]
    player_snapshot = player_card["player_snapshot"]
    clock = state["clock"]
    clock_light = game_clock.light_clock(clock) if clock else None

    # --- Director state + addenda (adult world) ------------------------------------
    director_state = state
    # Post-turn decides day advance + map movement.
    director_pre_addenda: list[str] = []
    director_post_addenda: list[str] = []
    # Nemesis trajectory is decided only when there is an active nemesis; load the addendum then
    # (stable prefix otherwise).
    if ((state["campaign"].get("metadata") or {}).get("nemesis") or {}).get("current_nemesis_id"):
        director_post_addenda = director_post_addenda + [_DIRECTOR_NEMESIS_ADDENDUM]
    # Parallel-nemesis trajectory only when at least one is active; load the addendum then.
    if alliances.active_parallel_nemeses(state["npcs"]):
        director_post_addenda = director_post_addenda + [_DIRECTOR_NEMESIS_PARALELO_ADDENDUM]
    npcs_known = state["npcs"]
    # Tier/condition from the player card. tier_before feeds fighting_style consolidation on
    # tier-up; player_condition goes to agent/Narrator.
    real_player_snapshot = state["player_card"].get("player_snapshot") or {}
    tier_before = real_player_snapshot.get("tier")
    player_condition = real_player_snapshot.get("condition") or "normal"
    # NPC ids with a paired mushi -> agent_mushi_addendum gate (has_paired_mushi).
    paired_mushi_ids = mushi.paired_mushi_ids(real_player_snapshot)
    active_directives = await repo.get_active_directives(conn, campaign_id)
    active_directives_text = [d["text"] for d in active_directives]

    # Trackable faction catalog (FACTION cards) + player reputations. Crew reputation (captain
    # weight 3) is derived per use from npcs_known, since the off-scene tick may change the roster.
    faction_card_ids = set(state.get("faction_cards") or {})
    player_faction_reps = faction.reputations_of(real_player_snapshot)
    # Player crew alliances (metadata.crew_alliances). Derive each allied agent's
    # alliance_with_player_crew and the Narrator's active_crew_alliances. Read once.
    crew_alliances_list = alliances.crew_alliances_of(state["campaign"].get("metadata") or {})

    # Crew: pending NPC->player offers + persisted crew_alignment (recomputed each turn, fallback to
    # captain alignment). Recruitment is deterministic (engine rolls the sigmoid; Narrator stages).
    _meta0 = state["campaign"].get("metadata") or {}
    crew_offers_pending = list(_meta0.get("crew_offers") or [])
    player_alignment_value = crew.alignment_scalar(real_player_snapshot.get("alignment"))
    crew_alignment_value = crew.current_crew_alignment_value(_meta0, real_player_snapshot.get("alignment"))

    def _crew_faction_reps(npcs_map: dict) -> dict:
        return faction.compute_crew_reputations(
            player_faction_reps,
            [faction.reputations_of(d) for d in npcs_map.values() if d.get("affiliation") == "player_crew"],
        )

    recent_prose = await repo.get_recent_turns_prose(conn, campaign_id, RECENT_TURNS_FETCH)

    # --- Off-scene tick: every N actions the world moves outside the frame ----------
    next_index = await repo.next_turn_index(conn, campaign_id)
    # Rewind snapshot: capture the world before any mutation this turn (including the tick below).
    # Commit immediately: otherwise this INSERT holds a write transaction across the turn's LLM
    # calls and the SQLite write lock blocks concurrent writes (caused "database is locked" when
    # creating a campaign during an opening). An aborted turn leaves at most a harmless orphan
    # snapshot (INSERT OR IGNORE; a retry of the same index reuses it).
    await world_snapshot.save_snapshot(
        conn, campaign_id, next_index, await world_snapshot.capture_world(conn, campaign_id)
    )
    await conn.commit()
    scene_location = state["scene"].get("location", "")
    world_now = (state["campaign"].get("metadata") or {}).get("world")
    player_island = world_map.current_island_id(world_now) if isinstance(world_now, dict) else None
    # Off-scene channel the retired tick used to feed. Empty carrier so the Director PRE feed
    # no-ops; the off-frame world is the evolutive freeze-on-exit + reconcile-on-return path below.
    agent_tick_outputs: list[dict] = []

    # --- 0. Director PRE-turn: scene, present NPCs, mode, pre-flags ---------
    yield {"type": "status", "phase": "director"}
    pre_turn_state = director.build_pre_turn_state(
        player_action, director_state, recent_prose,
        agent_tick_outputs=agent_tick_outputs,
        active_directives=active_directives_text,
        current_turn_index=next_index,
    )
    decisions = await director.call_pre_turn(
        pre_turn_state,
        extra_addenda=director_pre_addenda,
        cached_sections=director.pre_turn_cached_sections(director_state),
    )
    scene = decisions["scene"]
    mode = scene.get("mode", "A")
    crew_present_ids = set(decisions.get("crew_present_in_scene") or [])

    # Cast movement decided by the Director (npc_location_updates): the single channel for who
    # ENTERS the scene's sub-area and who LEAVES it. Applied here, BEFORE the presence gate below,
    # so the slug the gate matches on is already current (the gate's old bug was reading a position
    # one turn stale). Post-snapshot: rewind reverts the move.
    _npc_move_warnings: list[dict] = []
    _loc_updates = director.validate_npc_location_updates(
        decisions.get("npc_location_updates"), npcs_known, warnings=_npc_move_warnings
    )
    if _loc_updates:
        _agents_now = await repo.get_npc_agents(conn, campaign_id)
        for _u in _loc_updates:
            _info = _agents_now.get(_u["agent_id"])
            if not _info:
                continue
            _info["data"]["current_location"] = _u["new_location"]
            await repo.update_story_card(conn, _info["story_card_id"], _info["data"])
        await conn.commit()
        npcs_known = {aid: info["data"] for aid, info in _agents_now.items()}
        state["npcs"] = npcs_known

    # --- Timeskip (adult world) --------------------------------------------------
    # Fires on a valid training offer (this turn's offer_training or a pending one) AND player
    # engagement (the Director's timeskip_intent). Short-circuits the turn (executor + tier-up +
    # recap, counts as 1 turn). No valid offer -> normal flow (the offer becomes pending / narrated).
    ts_meta = state["campaign"].get("metadata") or {}
    pending = ts_meta.get("pending_offer_training")
    pending_valid = bool(isinstance(pending, dict) and pending.get("mentor_npc_id"))
    offer = decisions.get("offer_training") or (pending if pending_valid else None)
    if offer and offer.get("mentor_npc_id") and decisions.get("timeskip_intent") in ("accepted", "requested"):
        async for ev in _run_timeskip(
            conn, campaign_id,
            offer=offer, player_action=player_action, scene=scene,
            clock=clock, npcs=npcs_known, turn_index=next_index, trace_buf=trace_buf,
        ):
            yield ev
        return

    # --- Arrival pipeline: RESEARCH ONLY (FASE 29) -------------------------
    # On first arrival (Director arrival_triggers) run research (canonical) or the island designer
    # (invented) and cache it. The island is born NEUTRAL: no plot is created. The canonical
    # briefing is injected into the Narrator every turn via island_briefing (below).
    world_for_plot = (state["campaign"].get("metadata") or {}).get("world") or {}
    _arrival = decisions.get("arrival_triggers") or {}
    _arrival_slug = (_arrival.get("research_pipeline") or _arrival.get("island_designer") or "").strip()
    # Arrival slug = the island reached this turn (drift/voyage); world position only catches up
    # in the post-turn, so current_island_id still points at the origin during this DO turn.
    current_island_slug = (
        _arrival_slug or world_map.current_island_id(world_for_plot) or plots.island_slug_of_scene(scene)
    )
    research_report: dict | None = None
    try:
        if any(_arrival.get(k) for k in ("research_pipeline", "island_designer")) and current_island_slug:
            yield {"type": "status", "phase": "island_research"}
            research_report = await plots.run_island_research(
                conn, campaign_id, island_slug=current_island_slug,
            )
            await conn.commit()
            # Rehydrate in-memory metadata: research wrote visited_islands / invented context; else
            # apply_post_turn would overwrite the blob with the pre-research state.
            fresh_campaign = await repo.get_campaign(conn, campaign_id)
            if fresh_campaign is not None:
                state["campaign"]["metadata"] = fresh_campaign.get("metadata") or {}
    except Exception as exc:  # noqa: BLE001 research best-effort: never drops the turn
        research_report = {"error": f"{type(exc).__name__}: {exc}"}

    # --- Opt-in continuity thread (FASE 30) --------------------------------
    # The Director plants a thread only when a scene genuinely asks for a later payoff (null on
    # most turns; the island is neutral). Parked in the foreshadow pool for future turns to weigh;
    # the Narrator weaves it when the player touches the theme/place. Mutates the live metadata in
    # place (the island_threads projection below picks it up). Best-effort: this runs PRE, so a
    # plant hiccup must never drop the turn.
    _thread = decisions.get("plant_thread")
    if isinstance(_thread, dict) and str(_thread.get("hook_summary") or "").strip():
        try:
            _meta_thread = state["campaign"].get("metadata") or {}
            plots.plant_thread(
                _meta_thread,
                hook_summary=_thread.get("hook_summary", ""), theme_tag=_thread.get("theme_tag", ""),
                where_hint=_thread.get("where_hint", ""),
                source_name=current_island_slug, turn_index=next_index,
            )
            state["campaign"]["metadata"] = _meta_thread  # keep in-memory ref in step (covers empty-meta edge)
            await repo.update_campaign_metadata(conn, campaign_id, _meta_thread)
            await conn.commit()
        except Exception:  # noqa: BLE001 thread plant best-effort
            pass

    # Resolve decided NPCs against known cards (anonymous extras with no card are handled by Opus
    # via active_cards).
    resolved: list[tuple] = []
    # Malformed npcs_in_scene diagnostics for turn_state (never a silent skip). Covers entries the
    # parser dropped for a missing agent_id plus ids matching no known card (stale or forged).
    _malformed_nis: list[dict] = list(decisions.get("malformed_npcs_in_scene") or [])
    for entry in decisions.get("npcs_in_scene") or []:
        aid = entry.get("agent_id") if isinstance(entry, dict) else None
        data = npcs_known.get(aid)
        if data is None:
            if aid:
                _malformed_nis.append({"agent_id": aid, "reason": "no_matching_card"})
            continue
        resolved.append((aid, data, bool(entry.get("skip_agent_call")), entry.get("briefing_note", "")))

    scene_location = scene.get("location", "")
    # On-foot island relocation: the Director's scene.island_slug moved the scene to another
    # catalogued island on the same landmass (no sea crossing). Sync world.position + fog so the
    # map, HUD and location_relation follow the scene instead of trailing the seed island. Re-read
    # the world after any plot-gen rehydration; mutates in place so apply_post_turn persists it.
    world_now = (state["campaign"].get("metadata") or {}).get("world")
    if isinstance(world_now, dict):
        world_map.apply_scene_island_relocation(world_now, scene.get("island_slug", ""))
    # Mechanical location anchor: world "island/sub-area" slug + the Director's area_slug, not the
    # scene.location prose. NPC current_location and proximity player_location match on this slug;
    # anchoring on prose diverged from off-scene slugs and threw everything to "elsewhere". The
    # sub-area separates who is IN the scene (same_subarea) from another sector (same_island).
    anchor_location = world_map.scene_anchor_location(
        world_now, scene.get("area_slug", ""), fallback=scene_location
    )
    # Presence is the Director's call: npcs_in_scene is authoritative (position moves ride
    # npc_location_updates, applied above). The engine no longer expels a listed NPC whose
    # registered slug diverges from the scene anchor; it honors the presence and flags the
    # divergence for the Auditor to reconcile. Crewmates and ambiguous (prose/bare-island) slugs
    # never diverge.
    presence_divergences = [
        {
            "agent_id": t[0], "name": t[1].get("name", ""),
            "registered_location": t[1].get("current_location", ""), "scene_anchor": anchor_location,
        }
        for t in resolved
        if t[0] not in crew_present_ids
        and not agent_state.shares_scene_sector(anchor_location, t[1].get("current_location", ""))
    ]

    present_agents = [data for _aid, data, _skip, _bn in resolved]
    present_names = [d.get("name", "") for d in present_agents]
    present_set = {aid for aid, _data, _skip, _bn in resolved}
    # Creature (entity_kind=creature): present in the scene but no agent mind. Rendered card-only by
    # the Narrator, never run through a Sonnet call, on-scene or off.
    creatures = [(aid, data, bn) for aid, data, _skip, bn in resolved if data.get("entity_kind") == "creature"]
    # Present NPCs with an agent mind (every non-creature): each enters as a mind snapshot the
    # Narrator authors from.
    enabled = [t for t in resolved if t[1].get("entity_kind") != "creature"]

    # FASE 33: reconcile-on-return. A frozen NPC (departure_snapshot on its card) is back in scene.
    # One call redraws its volatile state against current canon (crystals + world) + elapsed time,
    # before the Narrator authors, so it enters stale-truth-free. Mutating the card dict in place
    # propagates to resolved/enabled/present_agents (same object refs) so the mind snapshot below reads
    # the fresh card.
    # Prior present cast (before this turn overwrites present_npc_ids). Source of who was LEFT BEHIND
    # on a time-ellipsis freeze below.
    _prior_present_ids = set((state["campaign"].get("metadata") or {}).get("present_npc_ids") or [])
    returning_npcs: list[dict] = []
    _returning = [
        (aid, data) for aid, data, _skip, _bn in resolved
        if data.get("departure_snapshot") and data.get("entity_kind") != "creature"
        and data.get("affiliation") != crew.CREW_AFFILIATION
    ]
    if _returning:
        _agents_map_r = await repo.get_npc_agents(conn, campaign_id)
        _recon_crystals = await repo.get_all_crystals_for_narrator(conn, campaign_id)
        _cards_cat = director.build_card_catalog(director_state)
        _agents_cat = director.build_agents_catalog(director_state)
        _world_now = {
            "current_arc": (clock_light or {}).get("current_arc", ""),
            "campaign_day": (clock_light or {}).get("campaign_day"),
            "player_location": anchor_location,
            "player_island": player_island,
        }
        _recon_changed = False
        for aid, data in _returning:
            info = _agents_map_r.get(aid)
            if not info:
                continue
            snapshot = data.get("departure_snapshot") or {}
            elapsed = reconcile.elapsed_since(
                snapshot, current_turn=next_index,
                current_day=int((clock_light or {}).get("campaign_day") or 0),
            )
            # The reconciler always runs with the elapsed gap as input; it emits a no-change
            # (empty) output cheaply on a trivial gap instead of the engine vetoing by threshold.
            out = await reconcile.run_reconcile(
                npc_view=reconcile.card_view(data),
                departure_snapshot=snapshot,
                elapsed=elapsed,
                crystals=_recon_crystals,
                cards_catalog=_cards_cat,
                agents_catalog=_agents_cat,
                world_now=_world_now,
            )
            if out:
                new_data = reconcile.apply_reconciliation(data, out, turn_index=next_index)
                # Stage the reunion note only when the reconciler actually redrew something; an
                # all-empty output is a no-change thaw (a scene boundary, not a real absence).
                if reconcile.reconciliation_changed(out):
                    returning_npcs.append(
                        reconcile.returning_context(data.get("name", ""), snapshot, out, elapsed=elapsed)
                    )
            else:  # thaw with the existing card (reconcile failure/no-op)
                new_data = dict(data)
                new_data.pop("dormant", None)
                new_data.pop("departure_snapshot", None)
            data.clear()
            data.update(new_data)  # propagate to the shared refs the Narrator reads below
            await repo.update_story_card(conn, info["story_card_id"], data)
            _recon_changed = True
        if _recon_changed:
            await conn.commit()

    # Director-decided scene transition this turn: place-hook (scene continues, closes on a hook) or
    # time-ellipsis (jump mid-prose into the post-jump scene the Director already built). Drives the
    # Narrator addendum + close. On a time-ellipsis the new presence arrives by ellipsis, not on
    # screen, so the cast-transition bridge is silenced.
    _scene_transition = decisions.get("scene_transition")
    _scene_transition = _scene_transition if isinstance(_scene_transition, dict) else None
    _time_ellipsis = bool(_scene_transition and _scene_transition.get("kind") == "elipse_de_tempo")
    if _time_ellipsis:
        cast_transition = None
    else:
        # Cast transition in a continuous scene (engine-side diff of prior vs current presence):
        # becomes a fact in the Narrator turn_state + conditional addendum. None most turns.
        cast_transition = _cast_transition_signal(
            state["campaign"].get("metadata") or {},
            scene=scene, present_set=present_set, npcs_known=npcs_known, next_index=next_index,
        )

    # FASE 27. Narrator-author path covers every on-scene cast (social AND combat): the Narrator
    # decides each NPC's tactic/speech/gesture/emotion from mind snapshots AND writes it, no on-scene
    # agent pre-scripts the turn, and the subjective update runs as a post-tick after the prose.
    # Combat folds in here too; its pre-flags (surprise/imminent/plot_armor/player_condition) still
    # reach the Narrator via turn_state below.

    # --- 1. On-scene cast: mind snapshots for the Narrator to author (no agent pre-script) ---
    yield {"type": "status", "phase": "agents", "npcs": present_names}

    # Institutional standing of each NPC's faction toward the crew. Derived crew reputation
    # recomputed after the tick; None for an NPC with no trackable faction -> silent addendum.
    crew_faction_reps_now = _crew_faction_reps(npcs_known)

    # Recruitment (FASE 27 D6): the Narrator decides the acceptance in prose. The Director PRE only
    # flags the trigger (invite to a present NPC, or a response to a pending offer); it is forwarded
    # as recruitment_request below and resolved via turn_meta.recruitment_resolutions. No sigmoid.

    # No on-scene agent runs: the Narrator authors the cast from mind snapshots. results stays empty;
    # mushi adds its own remote-voice entry later, and agent_outputs feeds the Director post-turn.
    results: list[tuple[dict, dict]] = []
    npcs_in_scene: list[dict] = []
    crew_present: list[dict] = []
    agent_outputs: list[dict] = []
    returning_logs = False
    # FASE 27 narrator-author path: present NPCs enter as mind snapshots (no agent pre-script). The
    # Narrator decides each one's tactic/speech/gesture/emotion from this. No `decision` field marks
    # the snapshot as author-it-yourself for the Narrator. Covers social AND combat.
    _public_legend = legend.player_public_view(
        state["campaign"].get("metadata") or {}, player_card.get("id", "player")
    )
    for _aid, data, _skip, bn in enabled:
        snap = agents.to_narrator_mind_snapshot(data)
        if bn:
            snap["director_note"] = bn
        if any(e.get("scene_mode") == "off_scene"
               for e in agent_state.log_slice(data.get("personal_event_log"))):
            returning_logs = True
        if data.get("id") in crew_present_ids or data.get("affiliation") == "player_crew":
            crew_present.append(snap)
        else:
            # A stranger (no bond, no shared knowledge) reacts to the poster/myth, not the person.
            rel = snap.get("relationship_to_player") or {}
            if _public_legend and not (
                rel.get("bond_tier") or rel.get("affinity") or rel.get("what_they_know")
            ):
                snap["player_public_legend"] = _public_legend
            npcs_in_scene.append(snap)
    # Present creatures: card-only creature briefing, no agent call.
    for _aid, data, bn in creatures:
        briefing = _creature_briefing(data, bn)
        if data.get("id") in crew_present_ids or data.get("affiliation") == "player_crew":
            crew_present.append(briefing)
        else:
            npcs_in_scene.append(briefing)

    # NPCs that asked to join (invite_to_crew) on-scene + in the off-scene tick become pending
    # offers (player accepts/rejects via DO/META or the UI).
    crew_invite_ids: list[str] = []
    seen_inv: set = set()
    # On-scene invites come from the Narrator (turn_meta.crew_offers, resolved post-narration);
    # this path only fires for a decision-making on-scene agent (results is empty in the author path).
    for nid in crew.invites_from_agent_turns([(d.get("id"), o) for d, o in results]):
        if nid and nid not in seen_inv:
            seen_inv.add(nid)
            crew_invite_ids.append(nid)

    # Player called an off-frame NPC (validated outgoing_mushi_call). Runs the target's agent
    # (present via mushi) and injects the briefing. Persisted separately at its own location.
    mushi_target_result: tuple[dict, dict] | None = await _run_outgoing_mushi_target(
        decisions.get("outgoing_mushi_call"), npcs_known, present_set,
        scene=scene, player_snapshot=player_snapshot, player_action=player_action,
        mode=mode, clock_light=clock_light, player_condition=player_condition,
        paired_mushi_ids=paired_mushi_ids,
        crew_faction_reps=crew_faction_reps_now, faction_card_ids=faction_card_ids,
        crew_alliances=crew_alliances_list,
    )
    if mushi_target_result is not None:
        m_data, m_out = mushi_target_result
        agent_outputs.append(m_out)
        npcs_in_scene.append(agents.to_narrator_briefing(m_data, m_out))

    # Off-scene crew periphery on the same island -> narrator periphery addendum.
    off_screen_periphery = _build_off_screen_periphery(
        npcs_known, present_ids=present_set, player_location=anchor_location
    )

    yield {"type": "agents_done", "npcs": present_names}

    # --- 2. Narrator (emit_turn: prose + turn_meta) ------------------------
    prior_crystals = await repo.get_all_crystals_for_narrator(conn, campaign_id)
    # Enrich the sheet with persistent combat state.
    narrator_player_character = _narrator_player_combat_view(player_character, state["player_card"])
    # Narrator memory: factual continuity from prior_crystals (closed scenes); raw prose fed back
    # only for the open scene's last few turns. A wider window is scanned for the overused-imagery
    # ledger (vary-this), never injected as prose (self-imitation loop).
    open_since = int(
        ((state["campaign"].get("metadata") or {}).get("scene_buffer") or {}).get("open_since_turn_index") or 1
    )
    narrator_recent_prose = _narrator_scene_prose(recent_prose, open_since=open_since, next_index=next_index)
    overused_imagery = _declared_imagery_bank(
        (state["campaign"].get("metadata") or {}).get("imagery_ledger"),
        current_index=next_index, window=OVERUSED_IMAGERY_WINDOW, cap=OVERUSED_IMAGERY_MAX,
    )
    turn_state = {
        "player_input": player_action,
        "scene": scene,
        "player_character": narrator_player_character,
        "npcs_in_scene": npcs_in_scene,
        "crew_present": crew_present,
        "off_screen_combat_periphery": off_screen_periphery,
        "world_memory_relevant": decisions.get("world_memory_relevant", ""),
        "prior_crystals": prior_crystals,
        "recent_turns_prose": narrator_recent_prose,
        "narrative_time_seconds": int(player_action.get("narrative_time_seconds", DEFAULT_NARRATIVE_TIME)),
        "plot_armor_engaged": bool(decisions.get("plot_armor_engaged", False)),
        "game_clock": clock_light,
        "active_directives": active_directives_text,
    }
    if overused_imagery:
        turn_state["overused_imagery"] = overused_imagery
    # Scene at/over the soft cap: nudge the Narrator to close or justify continuing, then honor its
    # scene_status (no hard force-close). N = turns this scene has been open including this one.
    _scene_open_len = next_index - open_since + 1
    if _scene_open_len >= SCENE_TURN_CAP:
        turn_state["scene_length_notice"] = {"open_turns": _scene_open_len, "soft_cap": SCENE_TURN_CAP}
    if returning_npcs:
        turn_state["returning_npcs"] = returning_npcs
    if cast_transition:
        turn_state["cast_transition"] = cast_transition
    # Presence divergences (Director listed an NPC whose registered slug is off the anchor): soft
    # diagnostic for the Auditor, not an expulsion.
    if presence_divergences:
        turn_state["presence_divergences"] = presence_divergences
    if _npc_move_warnings:
        turn_state["npc_move_warnings"] = _npc_move_warnings
    if _malformed_nis:
        turn_state["malformed_npcs_in_scene"] = _malformed_nis
    # Scene transition this turn (place-hook closes on a hook; time-ellipsis jumps mid-prose into
    # the new scene). Contract in the conditional addendum.
    if _scene_transition:
        turn_state["scene_transition"] = _scene_transition
    # World context for tone (chaos_meter top-level) + consolidated fighting_style
    # (world.player.fighting_style; null before the first tier-up).
    meta_world = state["campaign"].get("metadata") or {}
    turn_state["chaos_meter"] = meta_world.get("chaos_meter") or {"value": 0.0, "bucket": "calm"}
    # Institutional standing of factions toward the crew for tone of anonymous extras.
    # Only factions with bucket != neutral (informative signal); absence = common posture.
    faction_standings = faction.reputation_summary(
        crew_faction_reps_now, state.get("faction_cards") or {}, include_neutral=False
    )
    if faction_standings:
        turn_state["faction_standings"] = faction_standings
    # Current alliances for the Narrator to reference. All, unprioritized; Opus calibrates relevance.
    if crew_alliances_list:
        turn_state["active_crew_alliances"] = alliances.narrator_alliance_summary(
            crew_alliances_list, state.get("faction_cards") or {}, npcs_known
        )
    player_fighting_style = real_player_snapshot.get("fighting_style")
    # Economy in world.player: raw belly modulates NPC treatment, inventory_summary
    # says what is at hand. Inventory resolved by name via item cards + NPCs.
    player_belly = economy.belly_amount(real_player_snapshot)
    player_inventory_summary = economy.inventory_summary(
        real_player_snapshot.get("inventory") or [],
        {**(state.get("npcs") or {}), **(state.get("item_cards") or {})},
    )
    world_player = {"belly": player_belly}
    if player_inventory_summary:
        world_player["inventory_summary"] = player_inventory_summary
    if player_fighting_style:
        world_player["fighting_style"] = player_fighting_style
    turn_state["world"] = {"player": world_player}
    # Real island names for prose (anti-invention): the Director's chosen sea destination + the
    # nearest navigable islands. Only at sea / when a destination was chosen (see helper).
    _nav_block = _narrator_nav_block(meta_world, decisions)
    if _nav_block:
        turn_state["navigation"] = _nav_block
    # Active ship (hull modulates tone) + declared Jolly Roger (flag raised). jolly_roger
    # description colors flag scenes; active_ship hull_condition locks navigation if broken.
    crew_obj = ship.get_crew(meta_world)
    jr_text = ship.jolly_roger_text(crew_obj)
    ship_active_view = ship.active_ship_brief(crew_obj, state.get("ship_cards") or {})
    jolly_declared = bool(jr_text)
    crew_ship_state: dict = {}
    if jr_text:
        crew_ship_state["jolly_roger"] = {"description": jr_text}
    if ship_active_view:
        crew_ship_state["active_ship"] = ship_active_view
        crew_ship_state["reserve_count"] = len(ship.reserve_entries(crew_obj))
    if crew_ship_state:
        turn_state["crew"] = crew_ship_state
    # Crew for the Narrator. Roster + crew_alignment bucket as context; the recruitment result
    # enters as a diegetic fact, the Opus stages it.
    crew_roster_now = crew.roster_summary(npcs_known)
    if crew_roster_now:
        crew_block = turn_state.setdefault("crew", {})
        crew_block["roster"] = crew_roster_now
        crew_block["crew_alignment_value"] = round(float(crew_alignment_value), 4)
    # FASE 27 (D6): the Narrator decides the acceptance. When the Director flagged a recruitment
    # invite/response this turn, pass the request so the Narrator resolves it in prose and reports
    # via turn_meta.recruitment_resolutions. No engine roll.
    _recruit_requests: list[dict] = []
    _ri_id = crew.select_recruitment_target(
        decisions.get("player_recruitment_intent"), present_set
    )
    if _ri_id:
        _ri_data = npcs_known.get(_ri_id) or {}
        _ri_nm = _ri_data.get("name", "")
        if _ri_nm:
            _ok, _why = crew.can_recruit(_ri_data, allow_reconcile=True)
            _recruit_requests.append({
                "npc_name": _ri_nm, "kind": "player_invites",
                "eligible": _ok, "ineligibility_reason": ("" if _ok else _why),
            })
    _or_kind, _or_id = crew.select_offer_response(
        decisions.get("player_offer_response"), crew_offers_pending
    )
    if _or_id:
        _or_nm = (npcs_known.get(_or_id) or {}).get("name", "")
        if _or_nm:
            _recruit_requests.append({"npc_name": _or_nm, "kind": "responding_to_offer"})
    if _recruit_requests:
        turn_state["recruitment_request"] = {
            "requests": _recruit_requests,
            "guidance": (
                "O jogador está mexendo com recrutamento neste turn. Encene a cena e decida, "
                "encarnando o NPC (afinidade, sonho, código, momento), se ele aceita ou recusa. "
                "Reporte o desfecho em turn_meta.recruitment_resolutions."
            ),
        }
    if crew_invite_ids:
        _names = [(npcs_known.get(i) or {}).get("name", "") for i in crew_invite_ids]
        _names = [n for n in _names if n]
        if _names:
            turn_state["pending_crew_offer"] = {
                "npc_names": _names,
                "fact": language.engine_str("crew_join_request", names=", ".join(_names)),
            }
    # Combat pre-flags for the Narrator to pause/narrate the climax: surprise_actions,
    # breakthrough_imminent, plot_armor_engaged (already in turn_state), player_condition.
    surprise = decisions.get("surprise_actions") or []
    imminent = decisions.get("breakthrough_imminent")
    plot_armor = bool(decisions.get("plot_armor_engaged", False))
    if surprise:
        turn_state["surprise_actions"] = surprise
    if imminent:
        turn_state["breakthrough_imminent"] = imminent
    if player_condition != "normal":
        turn_state["player_condition"] = player_condition
    combat_context = (
        scene.get("tension_level") == "combat"
        or bool(surprise) or bool(imminent) or plot_armor
        or player_condition != "normal"
    )
    # Communication (mushi/vivre). The Director PRE validated pairing + status + range; here it just
    # forwards the decided channels for the Narrator to render. Null-driven: no event, nothing enters.
    incoming_mushi = decisions.get("incoming_mushi_call")
    outgoing_mushi = decisions.get("outgoing_mushi_call")
    active_mushi = decisions.get("mushi_call_active")
    vivre_change = decisions.get("vivre_card_state_change")
    # Exotic: interception (black) + counter-surveillance alert (white) are PRE channels; a buster
    # call in progress comes from metadata (set in a prior POST and escalating over turns).
    intercepted = decisions.get("intercepted_transmission")
    surveillance = decisions.get("surveillance_alert")
    buster_active = (meta_world or {}).get("buster_call_active")
    if incoming_mushi:
        turn_state["incoming_mushi_call"] = incoming_mushi
    if outgoing_mushi:
        turn_state["outgoing_mushi_call"] = outgoing_mushi
    if active_mushi:
        turn_state["mushi_call_active"] = active_mushi
    if vivre_change:
        turn_state["vivre_card_state_change"] = vivre_change
    if intercepted:
        turn_state["intercepted_transmission"] = intercepted
    if surveillance:
        turn_state["surveillance_alert"] = surveillance
    if buster_active:
        turn_state["buster_call_active"] = buster_active
    mushi_signal = bool(
        incoming_mushi or outgoing_mushi or active_mushi or vivre_change
        or intercepted or surveillance or buster_active
    )

    # Organic News Coo: the Director decided a paper arrives this turn (context-driven, never
    # scheduled). Build the staging material (cover pool + suggested reaction roster) for the
    # Narrator; the addendum is gated below. None on the vast majority of turns.
    news_arrival = decisions.get("news_coo_arrival")
    news_coo_incoming = None
    if news_arrival:
        news_coo_incoming = news_coo.build_news_incoming(
            news_arrival,
            metadata=meta_world,
            npcs=npcs_known,
            player_card=state["player_card"],
            current_turn=next_index,
        )
        turn_state["news_coo_incoming"] = news_coo_incoming

    # Canonical/invented island briefing for the Narrator (FASE 29): cached background read every
    # turn on a known island (not just arrival). Neutral island, context only, no imposed plot.
    # Arrival slug first (world position only catches up post-turn), then the world position.
    island_briefing = None
    _briefing_slug = _arrival_slug or world_map.current_island_id(
        (state["campaign"].get("metadata") or {}).get("world") or {}
    ) or ""
    if _briefing_slug:
        island_briefing = await plots.get_island_briefing(conn, campaign_id, _briefing_slug)
        if island_briefing:
            turn_state["island_briefing"] = island_briefing

    # Open continuity threads (FASE 30): raw projection of the foreshadow pool (no buckets/TTL; the
    # Narrator decides relevance). The Narrator weaves a thread only when the player touches it, and
    # leaves the rest as background texture. Injected only when the pool is non-empty.
    _island_threads = [
        {"hook_id": h["hook_id"], "theme_tag": h["theme_tag"], "description": h["description"],
         "where_hint": h["where_hint"], "age_in_turns": h["age_in_turns"]}
        for h in plots.build_foreshadow_pool((state["campaign"].get("metadata") or {}), next_index)
    ]
    if _island_threads:
        turn_state["island_threads"] = _island_threads

    # Pick-conditional alt-canon: background of the canonical owner displaced from the fruit. Only
    # when the fruit is visible to the Narrator.
    narrator_fruit_hook = fruit_alt_canon.narrator_hook(
        state["player_card"],
        fruit_visible_to_narrator=bool((narrator_player_character or {}).get("fruit")),
    )
    if narrator_fruit_hook:
        turn_state["fruit_removal_hook"] = narrator_fruit_hook

    # Tactical addendum when the scene has surrender/hostage/regroup (explicit signal) or engaged
    # combat with an on-scene antagonist. Always loaded WITH the combat addendum (validated stack).
    tactical_in_scene = (
        any(isinstance(s, dict) and s.get("type") == "hostage_grab"
            for s in (decisions.get("surprise_actions") or []))
        or any(o.get("action_type") in tactical_actions.TACTICAL_ACTION_TYPES for o in agent_outputs)
        or (scene.get("tension_level") == "combat" and bool(npcs_in_scene))
    )

    # Conditional addenda: combat + tactical + off-screen periphery + log discretion +
    # plot + chaos/moral_code/fighting_style.
    extra_addenda: list[str] = []
    if _scene_transition:
        extra_addenda.append(_NARRATOR_SCENE_TRANSITION_ADDENDUM)
    if cast_transition:
        extra_addenda.append(_NARRATOR_CAST_TRANSITION_ADDENDUM)
    if combat_context or tactical_in_scene:
        extra_addenda.append(_NARRATOR_COMBAT_ADDENDUM)
    if tactical_in_scene:
        extra_addenda.append(_NARRATOR_TACTICAL_ADDENDUM)
    if off_screen_periphery:
        extra_addenda.append("narrator_off_screen_periphery_addendum.pt-br.md")
    if returning_logs:
        extra_addenda.append("narrator_event_log_discretion_addendum.pt-br.md")
    if returning_npcs:
        extra_addenda.append(_NARRATOR_RETURNING_NPC_ADDENDUM)
    if island_briefing:
        extra_addenda.append(_NARRATOR_ISLAND_ADDENDUM)
    if _island_threads:
        extra_addenda.append(_NARRATOR_THREADS_ADDENDUM)
    if mushi_signal:
        extra_addenda.append(_NARRATOR_MUSHI_ADDENDUM)
    if news_coo_incoming:
        extra_addenda.append(_NARRATOR_NEWS_COO_ADDENDUM)
    if narrator_fruit_hook:  # gate is fruit visibility
        extra_addenda.append(_NARRATOR_FRUIT_REMOVAL_HOOK_ADDENDUM)
    # chaos always; moral_code = NPC with moral_code in scene; fighting_style = consolidated
    # identity (after the first tier-up).
    extra_addenda.append(_NARRATOR_CHAOS_ADDENDUM)
    if any(b.get("moral_code") for b in npcs_in_scene + crew_present):
        extra_addenda.append(_NARRATOR_MARINE_MORAL_CODE_ADDENDUM)
    if player_fighting_style:
        extra_addenda.append(_NARRATOR_FIGHTING_STYLE_ADDENDUM)
    # Trackable faction with non-neutral standing -> the Narrator calibrates anonymous extras'
    # tone (inert if none of that faction is in scene).
    if faction_standings:
        extra_addenda.append(_NARRATOR_FACTION_ADDENDUM)
    # Economy & inventory: economic substance (wealth OR item) or the Director flagged relevance.
    # Broke + empty + not relevant -> the master covers it.
    if (
        player_belly > 0
        or bool(real_player_snapshot.get("inventory"))
        or bool(decisions.get("economy_relevant"))
    ):
        extra_addenda.append(_NARRATOR_ECONOMY_ADDENDUM)
    # Ship & Jolly Roger: active ship (hull/flag) OR the Director flagged ship relevance this turn.
    if (
        ship_active_view or jolly_declared
        or bool(decisions.get("ship_relevant"))
    ):
        extra_addenda.append(_NARRATOR_SHIP_ADDENDUM)

    yield {"type": "status", "phase": "narrator"}
    narr = await narrator.call_narrator(turn_state, extra_addenda=extra_addenda)
    prose = narr["prose"]
    turn_meta = narr["turn_meta"]
    # FASE 32: prose is NOT revealed here. The post-turn Auditor runs after the generators (the
    # cards exist to cross-check) and may rewrite it; the single prose_delta is yielded after the
    # audit gate, below.

    # FASE 27. Narrator-author path: the tactical outcome, crew offers and recruitment acceptance
    # are facts the Narrator's prose consumed, reported via turn_meta. Resolve names/ids to apply
    # them as bookkeeping below (the engine never decided these; the Narrator did).
    tm_captures: list[dict] = []
    tm_surrenders: list[dict] = []
    tm_join_ids: list[str] = []
    tm_resolved_offer_ids: list[str] = []
    _present_name_to_id: dict[str, str] = {}
    for _aid in present_set:
        _nm = (npcs_known.get(_aid) or {}).get("name", "").strip().lower()
        if _nm:
            _present_name_to_id[_nm] = _aid

    def _ref_id(entry: dict) -> str | None:
        _nid = entry.get("npc_id")
        if _nid and _nid in npcs_known:
            return _nid
        return _present_name_to_id.get((entry.get("name") or "").strip().lower())

    for _o in turn_meta.get("npc_tactical_outcomes") or []:
        _rid = _ref_id(_o)
        if not _rid:
            continue
        _outc = _o.get("outcome")
        if _outc == "surrender":
            tm_surrenders.append({"npc_id": _rid, "source": "narrator"})
        elif _outc == "taken_hostage":
            _cap = _present_name_to_id.get((_o.get("captor_name") or "").strip().lower())
            tm_captures.append({"hostage_id": _rid, "captor_id": _cap, "source": "narrator"})
    _pending_ids = {
        (o.get("npc_id") if isinstance(o, dict) else o) for o in crew_offers_pending
    }
    for _r in turn_meta.get("recruitment_resolutions") or []:
        _rid = _ref_id(_r)
        if not _rid:
            continue
        if _rid in _pending_ids:
            tm_resolved_offer_ids.append(_rid)
        if _r.get("decision") == "accepted":
            tm_join_ids.append(_rid)
    for _off in turn_meta.get("crew_offers") or []:
        _rid = _ref_id(_off)
        if _rid and _rid not in crew_invite_ids and _rid not in tm_join_ids:
            crew_invite_ids.append(_rid)

    # --- 3. Persist turn + clock (lockstep, before post-turn) --------------
    # Store the conditional addenda used in this narration inside the persisted turn_state
    # (_reroll_addenda key, ignored by the Narrator on replay) so the prose reroll re-runs with
    # the SAME prompt stack.
    turn_state["_reroll_addenda"] = list(extra_addenda)
    turn_index = await repo.append_turn(
        conn,
        campaign_id,
        player_input=player_action,
        narrator_prose=prose,
        agent_decisions=turn_state,
        scene_snapshot=scene,
        trace=trace_buf,
    )
    scene_npc_ages = {
        a["name"]: int(a["age_at_creation"]) for a in present_agents if "age_at_creation" in a
    }
    next_clock, _warnings = game_clock.compute_next_clock(
        clock,
        time_advancement=None,
        set_arc=None,
        scene_npc_ages=scene_npc_ages,
        turn_index=turn_index,
    )
    await repo.save_clock(conn, campaign_id, next_clock)
    await repo.append_clock_snapshot(
        conn, campaign_id, turn_index, game_clock.snapshot_of(next_clock, turn_index)
    )

    # ran_agent_ids goes to the post-turn so the Director does not duplicate the on-scene NPCs' log
    # append. Populated by the post-tick + mushi below (no on-scene agent pre-scripts this path).
    agents_map = await repo.get_npc_agents(conn, campaign_id)
    ran_agent_ids: set = set()

    # FASE 27. NPC-mind post-tick: in the narrator-author path each on-scene NPC reads the finished
    # prose and updates its OWN mind (emotion/relationship/goal/memory). Replaces the on-scene
    # agent's subjective bookkeeping. Runs after the prose is shown; best-effort.
    _post_snaps = []
    for aid, _data, _skip, _bn in enabled:
        if aid not in npcs_known:
            continue
        _snap = agents.to_narrator_mind_snapshot(npcs_known[aid])
        # The NPC's own factual record anchors its memory_note against absorbing a prose detail
        # that contradicts its established history (sibling count, origin, affiliation).
        _snap["self_record"] = npc_mind_post.known_facts_from_card(npcs_known[aid])
        _post_snaps.append((aid, _snap))
    if _post_snaps:
        yield {"type": "status", "phase": "npc_mind", "npcs": present_names}
        _mind_outs = await npc_mind_post.run_post_ticks(
            _post_snaps, prose=prose, player_input=player_action,
            scene_location=anchor_location,
        )
        for aid, out in _mind_outs:
            info = agents_map.get(aid)
            if not info:
                continue
            d = npc_mind_post.apply_npc_mind_output(
                info["data"], out, turn_index=turn_index, scene_location=anchor_location
            )
            await repo.update_story_card(conn, info["story_card_id"], d)
            ran_agent_ids.add(aid)

    # Persist the outgoing mushi call target (present via mushi). Logs at its OWN location
    # (physically far; only the voice comes over the snail), not the scene.
    if mushi_target_result is not None:
        m_data, m_out = mushi_target_result
        m_id = m_data.get("id")
        if m_id and m_id not in ran_agent_ids:
            await _persist_onscene_agent(
                conn, agents_map, m_id, m_out,
                scene_location=m_data.get("current_location", scene_location), turn_index=turn_index,
            )
            ran_agent_ids.add(m_id)

    # On-scene hostage captures -> status: captured. Two sources: taken_hostage in the Narrator's
    # turn_meta.npc_tactical_outcomes (tm_captures) + hostage_grab connect from the Director PRE
    # surprise_actions. Dedup by hostage. Applied before commit so it is durable with the narration.
    hostage_capture_report: list[dict] = []
    onscene_captures = tactical_actions.dedupe_captures(
        tactical_actions.hostage_captures_from_surprise(
            decisions.get("surprise_actions") or [], npcs_known,
        ),
        tm_captures,
    )
    if onscene_captures:
        hostage_capture_report = await _persist_hostage_captures(
            conn, campaign_id, onscene_captures, scene_mode="on_scene",
            turn_index=turn_index, fallback_location=anchor_location,
        )

    # On-scene surrenders -> status: surrendered. The subject is the actor itself (laid down arms),
    # a value distinct from captured. Voluntary; the next fate is the player's call.
    # FASE 27 narrator-author: surrender reported via turn_meta.npc_tactical_outcomes (tm_surrenders).
    surrender_report: list[dict] = []
    onscene_surrenders = list(tm_surrenders)
    if onscene_surrenders:
        surrender_report = await _persist_surrenders(
            conn, campaign_id, onscene_surrenders, scene_mode="on_scene", turn_index=turn_index,
        )

    old_day = int(clock["campaign_day"]) if clock else 0
    await conn.commit()  # narration durable even if post-turn/crystallizer fails

    # --- 4. Director POST-turn: deltas + events (2nd Director pass) --------
    yield {"type": "status", "phase": "director_post"}
    post_decisions: dict = {}
    post_report: dict = {}
    post_turn_record: dict = {}
    # Set when a terminal LLM error (quota/refusal) hits a post-narration pass; the prose stays
    # durable and still reveals, but turn_complete warns the player the world only partly updated.
    quota_interrupted: str | None = None
    jobs_report: dict = {
        "generated_npcs": [], "generated_ships": [], "ship_swaps": [],
        "skipped": [],
    }
    try:
        post_state = director.build_post_turn_state(
            player_action, director_state,
            prose=prose, turn_meta=turn_meta, agent_outputs=agent_outputs,
            pre_turn_decisions=decisions, scene=scene,
            active_directives=active_directives_text,
        )
        post_decisions = await director.call_post_turn(
            post_state,
            extra_addenda=director_post_addenda,
            cached_sections=director.post_turn_cached_sections(director_state),
        )
        # Scene location for the ship_swap audit crystal.
        post_decisions["_scene_location"] = scene.get("location", "")
        # card_corrections gate: only correct a card whose summary the Director received this turn.
        post_decisions["_cards_in_context"] = director.cards_with_summary(post_state)
        post_report = await post_turn.apply_post_turn(
            conn, campaign_id,
            decisions=post_decisions,
            player_card=state["player_card"],
            npcs=npcs_known,
            metadata=(state["campaign"].get("metadata") or {}),
            clock=clock,
            turn_index=turn_index,
            ran_agent_ids=ran_agent_ids,
            turn_meta=turn_meta,
            item_cards=state.get("item_cards") or {},
            ship_cards=state.get("ship_cards") or {},
            faction_cards=state.get("faction_cards") or {},
        )
        # tier-up regenerates fighting_style; a confirmed breakthrough fires the kind's
        # generator and applies the state patch. Best-effort. Breakthrough BEFORE fighting_style
        # (the style incorporates the breakthrough).
        if post_report.get("breakthrough"):
            try:
                post_report["breakthrough_generated"] = await breakthroughs.run(
                    conn, campaign_id,
                    breakthrough_event=post_report["breakthrough"], turn_index=turn_index,
                )
            except Exception as exc:  # noqa: BLE001 generator best-effort
                post_report["breakthrough_generated"] = {"error": f"{type(exc).__name__}: {exc}"}
        if post_report.get("tier_change"):
            try:
                post_report["fighting_style"] = await fighting_style.regenerate(
                    conn, campaign_id,
                    tier_change_event=post_report["tier_change"], turn_index=turn_index,
                    tier_before=tier_before, recent_combat_summary=prose[:800],
                )
            except Exception as exc:  # noqa: BLE001 consolidator best-effort
                post_report["fighting_style"] = {"error": f"{type(exc).__name__}: {exc}"}
        # Advance the clock (time_advancement) + position/fog/sea/News Coo (world_movement).
        nav_report, settle_new_day = await _apply_world_navigation(
            conn, campaign_id, post_decisions,
            base_clock=next_clock, turn_index=turn_index, arrival_slug=_arrival_slug,
        )
        if nav_report:
            post_report["navigation"] = nav_report
        # Settle the day advance (matured bounty + chaos decay) over the final range.
        day_report = await post_turn.settle_day_advance(
            conn, campaign_id, old_day=old_day, new_day=settle_new_day
        )
        # Nemesis Marine + News Coo. Runs after the settle (reads the settled bounty).
        nemesis_news_report = await _apply_nemesis_and_news(
            conn, campaign_id,
            director_state=director_state, scene=scene, clock=clock,
            final_day=settle_new_day, turn_index=turn_index,
            nemesis_update=post_decisions.get("nemesis_update"),
            nemesis_spawn=post_decisions.get("nemesis_spawn"),
            recent_act_summary=prose[:400],
        )
        if nemesis_news_report:
            post_report["nemesis_news"] = nemesis_news_report
        # Run the dispatched jobs, gated by the Director.
        jobs_report = await _run_dispatched_jobs(
            conn, campaign_id,
            dispatched_jobs=post_decisions.get("dispatched_jobs") or [],
            npcs_to_generate=(turn_meta or {}).get("npcs_to_generate") or [],
            items_to_generate=(turn_meta or {}).get("items_to_generate") or [],
            ships_to_generate=(turn_meta or {}).get("ships_to_generate") or [],
            inspector_warnings=post_decisions.get("inspector_warnings") or [],
            arc_context=_arc_context(director_state, scene, clock),
            npcs_known=npcs_known,
            item_cards=state.get("item_cards") or {},
            ship_cards=state.get("ship_cards") or {},
            player_card=state["player_card"],
            turn_index=turn_index,
            scene_location=scene.get("location", ""),
            anchor_location=anchor_location,
            scene_prose=prose,
        )
        # Bounty hunters: appearance generates NPCs, promoted marks the card. Gated by the Director's
        # bounty_hunter_events. Best-effort.
        bh_events = post_decisions.get("bounty_hunter_events") or []
        if bh_events:
            try:
                post_report["bounty_hunters"] = await _apply_bounty_hunters(
                    conn, campaign_id,
                    events=bh_events, arc_context=_arc_context(director_state, scene, clock),
                    scene=scene, turn_index=turn_index, crew_alliances=crew_alliances_list,
                )
            except Exception as exc:  # noqa: BLE001 hunters best-effort
                post_report["bounty_hunters"] = {"error": f"{type(exc).__name__}: {exc}"}
        # Evolution of hunters already promoted to parallel nemesis (parallel_nemesis_updates):
        # Director-driven, decoupled from confrontation. Best-effort.
        pnu_events = post_decisions.get("parallel_nemesis_updates") or []
        if pnu_events:
            try:
                post_report["parallel_nemeses"] = await _apply_parallel_nemesis_updates(
                    conn, campaign_id,
                    events=pnu_events, scene=scene, turn_index=turn_index,
                )
            except Exception as exc:  # noqa: BLE001 parallel nemesis best-effort
                post_report["parallel_nemeses"] = {"error": f"{type(exc).__name__}: {exc}"}
        # Apply this turn's crew changes (joins, resolved offers, new pending offers) and recompute
        # crew_alignment with the fresh roster. Runs after apply_post_turn and overwrites it.
        # FASE 27 (D6): recruitment decided by the Narrator, reported via turn_meta.
        _join_ids: list[str] = list(tm_join_ids)
        _resolved_offers: list[str] = list(tm_resolved_offer_ids)
        _reconcile_ids: list[str] = []
        # Re-invite of a present ex-member clears awaiting_reconciliation regardless of the
        # Narrator's accept/decline, so re-recruitment never gets stuck.
        _inv_id = crew.select_recruitment_target(
            decisions.get("player_recruitment_intent"), present_set
        )
        if _inv_id and crew.is_awaiting_reconciliation(npcs_known.get(_inv_id) or {}):
            _reconcile_ids.append(_inv_id)
        if _join_ids or _resolved_offers or crew_invite_ids or _reconcile_ids:
            try:
                post_report["crew"] = await _apply_crew_recruitment(
                    conn, campaign_id,
                    join_ids=_join_ids, resolved_offer_ids=_resolved_offers,
                    new_invite_ids=crew_invite_ids, pending_offers=crew_offers_pending,
                    player_alignment_value=player_alignment_value,
                    scene_location=scene.get("location", ""), turn_index=turn_index,
                    reconcile_ids=_reconcile_ids,
                )
            except Exception as exc:  # noqa: BLE001 recruitment best-effort
                post_report["crew"] = {"error": f"{type(exc).__name__}: {exc}"}
        # Poneglyphs + Ending Candidate Detector. Runs after jobs/nav/plots (world state
        # already settled). Best-effort.
        try:
            endgame_report = await _run_endgame(
                conn, campaign_id,
                director_state=director_state, scene=scene,
                dispatched_jobs=post_decisions.get("dispatched_jobs") or [],
                recent_act_summary=prose[:400], turn_index=turn_index,
            )
            if endgame_report:
                post_report["endgame"] = endgame_report
        except Exception as exc:  # noqa: BLE001 endgame best-effort
            post_report["endgame"] = {"error": f"{type(exc).__name__}: {exc}"}
        if hostage_capture_report:
            post_report["hostage_captures"] = hostage_capture_report
        if surrender_report:
            post_report["surrenders"] = surrender_report
        # Persist the PRE-turn communication effects the Narrator rendered (vivre_card_state_change
        # + carry mushi_call_active to the next turn). Rereads fresh. Best-effort.
        try:
            mushi_report = await _persist_mushi_vivre_pre(
                conn, campaign_id, decisions=decisions, turn_index=turn_index
            )
            if mushi_report:
                post_report["mushi_vivre"] = mushi_report
        except Exception as exc:  # noqa: BLE001 communication best-effort
            post_report["mushi_vivre"] = {"error": f"{type(exc).__name__}: {exc}"}
        # A Director training offer the player did not engage this turn becomes pending; the
        # Director withdraws a stale one via withdraw_pending_offer.
        await _persist_pending_offer(
            conn, campaign_id,
            new_offer=decisions.get("offer_training"),
            withdraw=bool(decisions.get("withdraw_pending_offer")),
            turn_index=turn_index,
        )
        post_turn_record = {
            "decisions": post_decisions, "report": post_report,
            "day_advance": day_report, "dispatched_jobs_run": jobs_report,
            # Director's thread-plant rationale (PRE), kept for the devtools panel + audit trail.
            "thread_reasoning": decisions.get("thread_reasoning"),
        }
        await repo.save_turn_post_turn(conn, campaign_id, turn_index, post_turn_record)
        await conn.commit()
    except (QuotaExceededError, ModelRefusalError) as exc:
        # Terminal errors are NOT best-effort: the durable narration still reveals below, but the
        # post-turn deltas/generators did not run. Flag instead of swallowing silently.
        quota_interrupted = type(exc).__name__
        post_report = {"error": f"{type(exc).__name__}: {exc}"}
    except Exception as exc:  # noqa: BLE001 non-terminal post-turn failure: durable narration stands
        post_report = {"error": f"{type(exc).__name__}: {exc}"}

    # --- 4.5 Auditor: final gate over the whole turn, before the player sees the prose ------
    # Runs after the generators (the cards exist to cross-check against the cast + memory) and
    # before the prose is revealed. Best-effort: on timeout/error the original prose (already made
    # durable by append_turn) is released untouched; a rewrite updates it in place.
    yield {"type": "status", "phase": "auditing"}
    audit_report: dict | None = None
    try:
        generated_for_audit: list[dict] = []
        for _gkey in ("generated_npcs", "generated_items", "generated_ships"):
            for _g in (jobs_report.get(_gkey) or []):
                _gid = _g.get("id")
                if not _gid:
                    continue
                _row = await repo.get_card_by_entity_id(conn, campaign_id, _gid)
                if _row is None:
                    _row = await repo.get_story_card(conn, campaign_id, _gid)
                if _row:
                    generated_for_audit.append(_row["data"])
        audit_crystals = await repo.get_all_crystals_for_narrator(conn, campaign_id)
        # In-scene NPCs with their FULL card (reloaded fresh so post-turn deltas show), so the
        # Auditor can reconcile a card whose descriptive fields drifted from the crystallized
        # memory (a freed captive whose appearance still reads "wearing handcuffs").
        _fresh_for_audit = await repo.get_npc_agents(conn, campaign_id)
        audit_scene_cards = [
            info["data"] for aid, info in _fresh_for_audit.items() if aid in present_set
        ]
        _player_sc_audit = await repo.get_player_story_card(conn, campaign_id)
        # Scene cast the engine currently holds, so the Auditor can reconcile presence against prose.
        audit_present_cast = [
            {"id": aid, "name": (npcs_known.get(aid) or {}).get("name", "")}
            for aid in sorted(present_set)
        ]
        # Context the Auditor needs to mint a missing card via the real generator (model decision).
        audit_mint_context = {
            "arc_context": _arc_context(director_state, scene, clock),
            "anchor_location": anchor_location,
            "npcs_known": npcs_known,
            "crystals": audit_crystals,
            "player_card": state["player_card"],
            "turn_index": turn_index,
        }
        final_prose, audit_report = await auditor.audit_prose(
            conn, campaign_id,
            prose=prose,
            player_action=player_action,
            scene=scene,
            turn_meta=turn_meta,
            prose_kind="turn",
            generated_cards=generated_for_audit,
            post_turn={"decisions": post_decisions, "report": post_report},
            cards_catalog=director.build_card_catalog(director_state),
            agents_catalog=director.build_agents_catalog(director_state),
            crystals=audit_crystals,
            scene_cards=audit_scene_cards,
            player_card=(_player_sc_audit or {}).get("data"),
            present_cast=audit_present_cast,
            generator_skips=jobs_report.get("skipped") or [],
            recent_turns_prose=narrator_recent_prose,
            game_clock=clock_light,
            mint_context=audit_mint_context,
            timeout_s=config.AUDIT_TIMEOUT_S,
        )
        # Scene-cast reconciliation from the Auditor: minted/re-presented NPCs join the frame,
        # merged/departed ones leave. Runs before the present_npc_ids write below (line ~2936).
        for _m in (audit_report.get("minted_npcs") or []):
            if _m.get("id"):
                present_set.add(_m["id"])
        for _pid in (audit_report.get("presence_add") or []):
            present_set.add(_pid)
        for _pid in (audit_report.get("presence_remove") or []):
            present_set.discard(_pid)
        if final_prose != prose:
            await repo.update_turn_prose(conn, campaign_id, turn_index, final_prose)
            prose = final_prose
        post_turn_record["audit"] = audit_report
        await repo.save_turn_post_turn(conn, campaign_id, turn_index, post_turn_record)
        await conn.commit()
    except (QuotaExceededError, ModelRefusalError) as exc:
        quota_interrupted = quota_interrupted or type(exc).__name__
        audit_report = {"error": f"{type(exc).__name__}: {exc}"}
    except Exception as exc:  # noqa: BLE001 auditor best-effort: the original prose stays durable
        audit_report = {"error": f"{type(exc).__name__}: {exc}"}

    yield {"type": "prose_delta", "text": prose}  # revealed after the audit gate

    # --- 5. Per-scene crystallizer: fires at the end of the scene ----------
    # The narrator signals scene_status (continua|fecha); the engine accumulates prose and
    # crystallizes the whole scene only when it closes or hits SCENE_TURN_CAP.
    scene_status = (turn_meta or {}).get("scene_status", "continua")
    # Scene buffer lives in metadata; reread fresh (the post-turn may have mutated + committed it).
    campaign_now = await repo.get_campaign(conn, campaign_id)
    meta_now = (campaign_now or {}).get("metadata") or {}
    scene_buf = meta_now.get("scene_buffer") or {}
    scene_start = int(scene_buf.get("open_since_turn_index") or 1)
    if scene_start > turn_index or scene_start < 1:  # guard against a corrupt buffer
        scene_start = turn_index
    scene_len = turn_index - scene_start + 1

    # A time-ellipsis closes the scene: the prior scene's first half is crystallized here and the
    # post-jump second half opens the next one (scene_buffer restarts next turn).
    _era_moved = False
    # The Narrator's scene_status governs closure. SCENE_TURN_CAP only NUDGES it (scene_length_notice
    # above); a far-off hard ceiling forces closure so long-term memory never stays pending forever.
    close_scene = (
        scene_status == "fecha" or scene_len >= SCENE_HARD_CAP or _time_ellipsis
    )

    created_ids: list = []
    applied_ids: list = []
    ignored: list = []
    new_crystals: list = []
    if close_scene:
        yield {"type": "status", "phase": "crystallizer"}
        scene_turns = await repo.get_turns_prose_range(conn, campaign_id, scene_start, turn_index)
        context_turns = await repo.get_turns_prose_range(
            conn, campaign_id, max(1, scene_start - CONTEXT_TURNS_FOR_CRYSTALLIZER), scene_start - 1
        )
        existing_crystals = await repo.get_all_crystals_for_crystallizer(conn, campaign_id)
        cryst = await crystallizer.crystallize_scene(
            scene_turns_prose=scene_turns,
            context_turns_prose=context_turns,
            existing_crystals=existing_crystals,
            scene_context=scene,
            game_clock=clock_light,
        )
        new_crystals = cryst["new_crystals"]
        created_ids = await repo.append_new_crystals(
            conn, campaign_id, new_crystals, source_turn_index=turn_index
        )
        applied_ids, ignored = await repo.apply_crystal_updates(
            conn, campaign_id, cryst["updated_crystals"], source_turn_index=turn_index
        )
        meta_now["scene_buffer"] = {"open_since_turn_index": turn_index + 1}
    else:
        # Scene still open: accumulate prose, do not crystallize yet.
        meta_now["scene_buffer"] = {"open_since_turn_index": scene_start}
    # Real scene/presence at turn end: source of the next turn's cast diff, the Director's
    # scene_current and the UI's present_npcs. An era transition already wrote the NEW era's
    # roster/scene in the post-turn; do not overwrite, and drop the marker so the diff stays mute
    # on the era's first turn (a cut by definition).
    if _era_moved:
        meta_now.pop("present_npc_ids_turn_index", None)
    else:
        # FASE 27: the Narrator may move the player to another sub-area within the turn. The Director
        # POST read the prose and reports where it ENDED via scene_end; persist that as the next turn's
        # opening so the location never trails the narration. Island moves go via world_movement.
        _se = post_decisions.get("scene_end")
        if isinstance(_se, dict):
            _se_slug = world_map.normalize_area_slug(_se.get("area_slug", ""))
            _se_loc = str(_se.get("location") or "").strip()
            if _se_slug:
                scene["area_slug"] = _se_slug
            if _se_loc:
                scene["location"] = _se_loc
        meta_now["scene"] = scene
        # Reconcile presence with NPCs materialized post-prose: a generated NPC (Director promotion,
        # Narrator npcs_to_generate, or unsignaled remediation) was written into this turn's prose but
        # was not in the pre-prose present_set, so the panel trailed the narrated cast by a turn. Their
        # current_location is already normalized to the scene anchor (so they also survive next turn).
        for _g in (jobs_report.get("generated_npcs") or []):
            _gid = _g.get("id")
            # Honor the generator's presence attest: an off-scene mention (present_in_scene=false)
            # gets a card but never joins the scene cast. Creatures/dedup default true.
            if _gid and _g.get("present_in_scene", True):
                present_set.add(_gid)
        # A model-deduped card (reused existing person, no new card) is also in the narrated cast:
        # its location was normalized to the scene anchor, so it joins the panel like a fresh one.
        for _dgid in (jobs_report.get("deduped_present_ids") or []):
            present_set.add(_dgid)
        meta_now["present_npc_ids"] = sorted(present_set)
        meta_now["present_npc_ids_turn_index"] = turn_index
    # FASE 30: a thread the Narrator resolved leaves the LLM projection but stays stored as HUD
    # history; touched threads stay open. Hook ids come from turn_meta.threads_resolved.
    _resolved_threads = {
        s for s in ((turn_meta or {}).get("threads_resolved") or [])
        if isinstance(s, str) and s.strip()
    }
    if _resolved_threads:
        plots.resolve_threads(meta_now, _resolved_threads, turn_index)
    # Roll the model-declared imagery into the anti-repetition ledger (fed back as "vary this" next turn).
    meta_now["imagery_ledger"] = _roll_imagery_ledger(
        meta_now.get("imagery_ledger"), turn_index=turn_index,
        terms=(turn_meta or {}).get("imagery_leaned_on") or [], window=OVERUSED_IMAGERY_WINDOW,
    )
    await repo.update_campaign_metadata(conn, campaign_id, meta_now)
    await conn.commit()

    # Header arc tracks the real world position. current_arc was seeded once and never rewritten,
    # so the header froze on the start island; derive it from the map each turn and persist on change.
    _arc_label = world_map.world_arc_label(meta_now)
    if _arc_label and _arc_label != ((campaign_now or {}).get("current_arc") or ""):
        await repo.update_campaign_arc(conn, campaign_id, _arc_label)
        await conn.commit()
        if campaign_now is not None:
            campaign_now["current_arc"] = _arc_label

    # Fresh state for the frontend header (age/scene/roster/arc). Without this the turn_complete
    # carried the pre-transition clock and never scene/present/arc, so an era advance only showed
    # in the UI after a reload.
    final_clock = await repo.get_clock(conn, campaign_id)
    # clock.current_arc was seeded once and never rewritten (set_arc disabled), so the clock payload
    # surfaced a stale arc while campaign.current_arc tracked the world. Keep them in step.
    if final_clock and _arc_label and final_clock.get("current_arc") != _arc_label:
        final_clock["current_arc"] = _arc_label
        await repo.save_clock(conn, campaign_id, final_clock)
        await conn.commit()
    fresh_agents = await repo.get_npc_agents(conn, campaign_id)
    # FASE 33: freeze the scene cast on close. Every NPC that shared the closing scene leaves the
    # frame; snapshot each (1 LLM) and set dormant so nothing runs off-frame until it returns and
    # reconciles. Crew (travels with the player), creatures (no mind) and the archived are spared.
    frozen_ids: set = set()
    if close_scene:
        # On a time-ellipsis the scene JUMPS: the Director already composed the post-jump cast (now
        # present) and moved the left-behind out. Freeze who was left behind (prior cast minus the
        # post-jump present), not the people who just arrived on-screen. A plain close freezes the
        # present cast (the whole scene leaves the frame).
        _freeze_source = (_prior_present_ids - present_set) if _time_ellipsis else present_set
        _freeze_candidates = []
        for i in sorted(_freeze_source):
            info = fresh_agents.get(i)
            if not info:
                continue
            d = info["data"]
            if (
                d.get("affiliation") == crew.CREW_AFFILIATION
                or d.get("entity_kind") == "creature"
                or (d.get("status") or "alive") in ("dead", "missing")
                or d.get("dormant")
            ):
                continue
            _freeze_candidates.append((i, info))
        if _freeze_candidates:
            _scene_tail = [
                e.get("prose", "") for e in recent_prose
                if int(e.get("turn_index") or 0) >= scene_start
            ]
            _scene_tail.append(prose)
            _last3 = [p for p in _scene_tail if p][-3:]
            _scene_prose_joined = "\n\n---\n\n".join(_last3)
            _dep_day = int((clock_light or {}).get("campaign_day") or 0)
            _dep_outs = await departure.run_departures(
                [(i, departure.card_view(info["data"])) for i, info in _freeze_candidates],
                scene_prose=_scene_prose_joined,
                location=scene.get("location", ""),
            )
            _dep_by_id = {aid: out for aid, out in _dep_outs}
            for i, info in _freeze_candidates:
                snapshot = departure.build_snapshot(
                    _dep_by_id.get(i),
                    left_at_turn=turn_index,
                    campaign_day=_dep_day,
                    location=info["data"].get("current_location", "") or scene.get("location", ""),
                    last_prose_excerpt=_last3,
                )
                frozen = departure.apply_departure(info["data"], snapshot)
                await repo.update_story_card(conn, info["story_card_id"], frozen)
                fresh_agents[i]["data"] = frozen
                frozen_ids.add(i)
            await conn.commit()
    # A canon-catalog NPC present in the scene wakes (drops dormant, enters play). The whole catalog
    # is born dormant; presence is the entry-into-play signal. A just-frozen NPC (in frozen_ids) stays
    # asleep: it reconciles on return, not here. A snapshot-carrier present but NOT frozen this turn
    # (a return that could not reconcile because the agent layer is off) thaws card-only.
    woke = False
    for i in (meta_now.get("present_npc_ids") or []):
        info = fresh_agents.get(i)
        if not info or not info["data"].get("dormant"):
            continue
        if info["data"].get("departure_snapshot") and i in frozen_ids:
            continue
        info["data"].pop("dormant", None)
        info["data"].pop("departure_snapshot", None)
        await repo.update_story_card(conn, info["story_card_id"], info["data"])
        woke = True
    if woke:
        await conn.commit()
    present_npcs = [
        {"name": fresh_agents[i]["data"].get("name", ""),
         "tier": fresh_agents[i]["data"].get("tier", ""),
         "affiliation": fresh_agents[i]["data"].get("affiliation", "")}
        for i in (meta_now.get("present_npc_ids") or []) if i in fresh_agents
    ]

    yield {
        "type": "turn_complete",
        "turn_index": turn_index,
        "prose": prose,
        "turn_meta": turn_meta,
        "scene_closed": close_scene,
        "quota_interrupted": quota_interrupted,
        "new_crystals": new_crystals,
        "created_crystal_ids": created_ids,
        "applied_update_ids": applied_ids,
        "ignored_updates": ignored,
        "clock": game_clock.light_clock(final_clock) if final_clock else None,
        "scene": meta_now.get("scene", {}),
        "present_npcs": present_npcs,
        "current_arc": (campaign_now or {}).get("current_arc"),
        "post_turn": post_report,
        # FASE 33 devtools: who reconciled on return / froze on close this turn.
        "evolutive_world": {
            "reconciled": [r.get("name", "") for r in returning_npcs],
            "frozen": sorted(frozen_ids),
        },
        "generated_npcs": jobs_report.get("generated_npcs", []) + (
            (post_report.get("bounty_hunters") or {}).get("spawned", []) if isinstance(post_report, dict) else []
        ),
        # New techniques registered this turn -> frontend toast.
        "techniques_registered": post_report.get("techniques_registered", []),
        # News Coo edition that arrived this turn (renderable markdown). None when no paper.
        "news_coo": _news_edition_of(post_report),
        # Arrival research summary (canonical briefing / invented context); None when no arrival.
        "island_research": research_report,
        # Mushi call arriving this turn (incoming) -> UI sound + indicator (only on arrival);
        # vivre card change -> refresh inventory. None when neither.
        "mushi_call": incoming_mushi or None,
        "vivre_card_change": (post_report.get("mushi_vivre") or {}).get("vivre_card_change") if isinstance(post_report, dict) else None,
        # belly/inventory changed this turn -> frontend refreshes the economy panel if open.
        "economy_changed": bool(
            isinstance(post_report, dict)
            and (post_report.get("belly") or post_report.get("inventory_changes") or jobs_report.get("generated_items"))
        ),
        # Fleet/hull changed (hull change, swap, or generated ship) -> refresh the ship panel if open.
        "ship_changed": bool(
            (isinstance(post_report, dict) and (post_report.get("hull_changes") or post_report.get("ship_swaps")))
            or jobs_report.get("generated_ships") or jobs_report.get("ship_swaps")
        ),
        # Faction reputation changed -> refresh the reputation panel if open.
        "faction_changed": bool(isinstance(post_report, dict) and post_report.get("faction_reputation")),
        # Alliance formed/broken -> refresh the alliances panel.
        "alliances_changed": bool(isinstance(post_report, dict) and post_report.get("crew_alliances")),
        # Crew changed (member in/out, pending offer, or dissatisfaction) -> refresh the Crew tab + toast.
        "crew_changed": bool(
            isinstance(post_report, dict)
            and (post_report.get("crew") or post_report.get("crew_dissatisfaction") or post_report.get("crew_departure"))
        ),
        # Mature ending candidates (UI offers) + revealed Poneglyphs + Laugh Tale.
        **_endgame_signals(post_report),
        # FASE 32: post-turn Auditor verdict + corrections (devtools "auditado" seal + reasoning).
        "audit": audit_report,
        "trace": trace_buf,
    }


# ======================================================================================
# META router (pergunta/lembre/esqueça). Does NOT advance the turn.
# ======================================================================================
def _game_context_brief(state: dict, recent_prose: list[dict]) -> dict:
    """game_context_brief for the router: arc/location/tier/bounty + last-turn summary + the player
    sheet (name/class/weapon/dream/fruit/traits/haki) so `pergunta` answers state from the sheet,
    not canon guesswork."""
    campaign = state.get("campaign") or {}
    clock = state.get("clock") or {}
    scene = state.get("scene") or {}
    player_card = state.get("player_card") or {}
    cc = player_card.get("character_creation") or {}
    pc = player_card.get("player_character") or {}
    ps = player_card.get("player_snapshot") or {}
    bounty = ps.get("bounty", 0)
    bounty_amount = (
        int(bounty.get("current_amount", 0) or 0) if isinstance(bounty, dict) else int(bounty or 0)
    )
    summary = (recent_prose[-1]["prose"] if recent_prose else "").strip().replace("\n", " ")
    if len(summary) > RECENT_SUMMARY_MAX_CHARS:
        summary = summary[:RECENT_SUMMARY_MAX_CHARS].rstrip() + "…"
    fruit = cc.get("devil_fruit") if isinstance(cc.get("devil_fruit"), dict) else {}
    traits = [t.get("name") for t in (cc.get("traits") or []) if isinstance(t, dict) and t.get("name")]
    return {
        "current_arc": campaign.get("current_arc") or clock.get("current_arc") or "",
        "location": scene.get("location", ""),
        "player_tier": ps.get("tier") or pc.get("tier", ""),
        "player_bounty": bounty_amount,
        "recent_turn_summary": summary,
        "player_sheet": {
            "name": player_card.get("name") or cc.get("name") or "",
            "class": pc.get("class") or cc.get("class_display") or "",
            "weapon": pc.get("weapon") or cc.get("weapon") or "",
            "dream": pc.get("dream") or cc.get("dream") or "",
            "devil_fruit": ps.get("fruit") or pc.get("fruit") or fruit.get("name_pt") or fruit.get("name_jp") or "",
            "devil_fruit_type": fruit.get("type") or "",
            "traits": traits,
            "haki": ps.get("haki") or pc.get("haki") or [],
        },
    }


async def run_meta_events(
    conn: aiosqlite.Connection, campaign_id: str, player_action: dict
) -> AsyncIterator[dict]:
    """Routes META input. pergunta returns OOC response_text; lembre creates directives; esqueça
    returns the active directives for the UI to deactivate. Direct DB mutation, no agents/narrator/
    crystallizer, no turn_index advance."""
    trace_buf = trace.start()
    state = await _load_state(conn, campaign_id)
    active_directives = await repo.get_active_directives(conn, campaign_id)
    recent_prose = await repo.get_recent_turns_prose(conn, campaign_id, 1)
    router_input = meta_router.build_router_input(
        player_action,
        active_directives=active_directives,
        game_context_brief=_game_context_brief(state, recent_prose),
    )

    yield {"type": "status", "phase": "meta_router"}
    result = await meta_router.call_meta_router(router_input)
    kind = result["kind"]

    if kind == "lembre":
        # source_turn_index = last played turn (next-1; 0 if no turn yet).
        last_idx = max(0, await repo.next_turn_index(conn, campaign_id) - 1)
        created: list[dict] = []
        for text in result["directives"]:
            did = await repo.create_directive(conn, campaign_id, text, source_turn_index=last_idx)
            created.append({"id": did, "text": text})
        await conn.commit()
        yield {"type": "meta_response", "kind": "lembre", "directives_created": created, "trace": trace_buf}
    elif kind == "esqueca":
        directives = await repo.get_active_directives(conn, campaign_id)
        yield {"type": "meta_response", "kind": "esqueca", "directives": directives, "trace": trace_buf}
    else:  # pergunta
        yield {"type": "meta_response", "kind": "pergunta", "response_text": result.get("response_text", ""), "trace": trace_buf}


# ======================================================================================
# Opening: campaign cold open (turn 1, no player action)
# ======================================================================================
async def run_opening_events(
    conn: aiosqlite.Connection, campaign_id: str, ooc_note: str | None = None
) -> AsyncIterator[dict]:
    """Surfacing wrapper: the opening also converts quota/refusal into a terminal structured event.
    The campaign stays playable (the opening is idempotent, best-effort)."""
    try:
        async for ev in _run_opening_events_inner(conn, campaign_id, ooc_note=ooc_note):
            yield ev
    except (QuotaExceededError, ModelRefusalError) as exc:
        yield turn_error_event(exc)


async def _run_opening_events_inner(
    conn: aiosqlite.Connection, campaign_id: str, ooc_note: str | None = None
) -> AsyncIterator[dict]:
    """Generates the campaign OPENING: the first prose beat before any player action. Runs the same
    trio as a normal turn: the Director composes the entry scene and cast from scratch (present_npc_ids
    starts empty), the chosen NPCs' agents act in their own lives (cold open, empty trigger), and the
    Narrator writes the beat with real briefings. The opening is a FREE entry scene: no milestone is
    marked. Persists as a turn + writes the composed scene/cast to metadata and wakes present dormant
    NPCs. ooc_note = player OOC instruction when the opening is regenerated."""
    trace_buf = trace.start()
    state = await _load_state(conn, campaign_id)
    player_card = state["player_card"]
    clock = state["clock"]
    clock_light = game_clock.light_clock(clock) if clock else None

    director_state = state
    director_pre_addenda: list[str] = []
    player_character = player_card["player_character"]
    player_snapshot = player_card["player_snapshot"]

    # Pre-turn snapshot: the opening is also rewindable/regenerable. Captured before any write, with
    # immediate commit; otherwise the INSERT holds the SQLite write lock across the opening's LLM
    # calls and any concurrent write dies with "database is locked".
    next_index = await repo.next_turn_index(conn, campaign_id)
    await world_snapshot.save_snapshot(
        conn, campaign_id, next_index, await world_snapshot.capture_world(conn, campaign_id)
    )
    await conn.commit()

    player_input: dict = {"type": "OPENING", "raw": ""}
    if ooc_note:
        player_input["ooc_note"] = ooc_note

    # --- 0. Director PRE-turn: composes the entry scene (empty present -> free cast) -----
    yield {"type": "status", "phase": "director"}
    pre_turn_state = director.build_pre_turn_state(
        player_input, director_state, [],
    )
    decisions = await director.call_pre_turn(
        pre_turn_state,
        extra_addenda=director_pre_addenda,
        cached_sections=director.pre_turn_cached_sections(director_state),
    )
    scene = decisions["scene"]
    mode = scene.get("mode", "A")
    scene_location = scene.get("location", "")
    # Mechanical location anchor (world "island/sub-area" slug + scene area_slug), not the Director's
    # prose. Present NPCs are anchored on it below; anchoring on prose diverged from off-scene slugs
    # and dropped the location-match to "elsewhere".
    anchor_location = world_map.scene_anchor_location(
        (state["campaign"].get("metadata") or {}).get("world"),
        scene.get("area_slug", ""), fallback=scene_location,
    )
    crew_present_ids = set(decisions.get("crew_present_in_scene") or [])
    npcs_known = state["npcs"]

    # Resolve the Director-chosen cast against known cards (anonymous cardless extras go to Opus via
    # active_cards). Respects skip_agent_call.
    resolved: list[tuple] = []
    for entry in decisions.get("npcs_in_scene") or []:
        aid = entry.get("agent_id") if isinstance(entry, dict) else None
        data = npcs_known.get(aid)
        if data is None:
            continue
        resolved.append((aid, data, bool(entry.get("skip_agent_call")), entry.get("briefing_note", "")))
    # Same authoritative-presence rule as a normal turn: never expel a listed NPC. Seed cast sits at
    # a bare island slug (no sub-area), so it never diverges anyway.
    present_set = {aid for aid, _d, _s, _bn in resolved}
    present_names = [data.get("name", "") for _aid, data, _s, _bn in resolved]
    # Creature (entity_kind=creature): present but no agent mind, rendered card-only.
    creatures = [(aid, data, bn) for aid, data, _skip, bn in resolved if data.get("entity_kind") == "creature"]
    enabled = [t for t in resolved if t[1].get("entity_kind") != "creature"]
    to_run = [(aid, data, bn) for aid, data, skip, bn in enabled if not skip]
    skipped = [(aid, data, bn) for aid, data, skip, bn in enabled if skip]

    # --- 1. Agents (cold open: each NPC acts in its own life, empty trigger) --------------
    # Independent parallel: the cold open is an instant of the world in motion, not a reactive
    # chain. Adult signals (recruitment/mushi/faction/alliance) do not apply; they stay None/empty.
    yield {"type": "status", "phase": "agents", "npcs": present_names}
    results: list[tuple[dict, dict]] = []
    if to_run:
        async def _one(aid: str, data: dict, bn: str) -> tuple[dict, dict]:
            others = _other_npcs(resolved, aid, {})
            sc = _scene_context(scene, player_snapshot, player_input, others, bn, "normal")
            inp = _onscene_agent_input(
                data, sc, mode, clock_light,
                npcs=npcs_known, present_ids=present_set, scene_location=anchor_location,
            )
            turn_out = await agents.call_npc_agent(inp)
            return data, turn_out

        results = list(await asyncio.gather(*[_one(aid, data, bn) for aid, data, bn in to_run]))

    npcs_in_scene: list[dict] = []
    crew_present: list[dict] = []

    def _route(briefing: dict, data: dict) -> None:
        if data.get("id") in crew_present_ids or data.get("affiliation") == "player_crew":
            crew_present.append(briefing)
        else:
            npcs_in_scene.append(briefing)

    for data, turn_out in results:
        _route(agents.to_narrator_briefing(data, turn_out), data)
    for _aid, data, bn in skipped:
        crew_present.append(_skipped_crew_briefing(data, bn))
    for _aid, data, bn in creatures:
        _route(_creature_briefing(data, bn), data)
    yield {"type": "agents_done", "npcs": present_names}

    # --- 2. Narrator: the cold open with the composed stage + real briefings --------------
    active_directives = await repo.get_active_directives(conn, campaign_id)
    turn_state = {
        "player_input": player_input,
        "scene": scene,
        "player_character": player_character,
        "npcs_in_scene": npcs_in_scene,
        "crew_present": crew_present,
        "off_screen_combat_periphery": [],
        "world_memory_relevant": decisions.get("world_memory_relevant", ""),
        "prior_crystals": [],
        "recent_turns_prose": [],
        "narrative_time_seconds": DEFAULT_NARRATIVE_TIME,
        "plot_armor_engaged": False,
        "game_clock": clock_light,
        "active_directives": [d["text"] for d in active_directives],
    }

    extra_addenda = [_NARRATOR_OPENING_ADDENDUM]

    yield {"type": "status", "phase": "narrator"}
    narr = await narrator.call_narrator(turn_state, extra_addenda=extra_addenda)
    prose = narr["prose"]

    # --- 2.5 Auditor: gate the cold open before the reveal --------------------------------
    # Same gate as a normal turn, scoped to the opening: form vices (§3.3) + player agency + a name
    # the entry scene staged as a character without a card (mint_npc). Minted/re-presented NPCs join
    # the composed cast below. Best-effort: on error the prose is revealed untouched.
    yield {"type": "status", "phase": "auditing"}
    audit_report: dict | None = None
    try:
        _open_crystals = await repo.get_all_crystals_for_narrator(conn, campaign_id)
        _open_fresh = await repo.get_npc_agents(conn, campaign_id)
        _open_scene_cards = [info["data"] for aid, info in _open_fresh.items() if aid in present_set]
        _open_psc = await repo.get_player_story_card(conn, campaign_id)
        _open_present_cast = [
            {"id": aid, "name": (npcs_known.get(aid) or {}).get("name", "")}
            for aid in sorted(present_set)
        ]
        _open_mint_context = {
            "arc_context": _arc_context(director_state, scene, clock),
            "anchor_location": anchor_location,
            "npcs_known": npcs_known,
            "crystals": _open_crystals,
            "player_card": state["player_card"],
            "turn_index": next_index,
        }
        final_prose, audit_report = await auditor.audit_prose(
            conn, campaign_id,
            prose=prose, player_action=player_input, scene=scene, turn_meta=narr.get("turn_meta"),
            prose_kind="opening",
            cards_catalog=director.build_card_catalog(director_state),
            agents_catalog=director.build_agents_catalog(director_state),
            crystals=_open_crystals,
            scene_cards=_open_scene_cards,
            player_card=(_open_psc or {}).get("data"),
            present_cast=_open_present_cast,
            game_clock=clock_light,
            mint_context=_open_mint_context,
        )
        for _m in (audit_report.get("minted_npcs") or []):
            if _m.get("id"):
                present_set.add(_m["id"])
        for _pid in (audit_report.get("presence_add") or []):
            present_set.add(_pid)
        for _pid in (audit_report.get("presence_remove") or []):
            present_set.discard(_pid)
        prose = final_prose
    except Exception as exc:  # noqa: BLE001 opening auditor best-effort
        audit_report = {"error": f"{type(exc).__name__}: {exc}"}

    yield {"type": "prose_delta", "text": prose}

    # --- 3. Persist turn + the composed scene/cast (UI/Map/next turn) ---------------------
    turn_state["_reroll_addenda"] = list(extra_addenda)  # prose reroll
    turn_index = await repo.append_turn(
        conn, campaign_id,
        player_input=player_input,
        narrator_prose=prose,
        agent_decisions=turn_state,
        scene_snapshot=scene,
        trace=trace_buf,
    )
    # Write the scene + present_npc_ids the Director composed. present_npc_ids_turn_index lets the
    # next turn compute the cast diff against the opening; scene_buffer opens the first scene at
    # turn 1 (the crystallizer includes the cold open). Post-snapshot: rewind reverts.
    campaign_now = await repo.get_campaign(conn, campaign_id)
    meta_open = dict((campaign_now or {}).get("metadata") or {})
    meta_open["scene"] = scene
    meta_open["present_npc_ids"] = sorted(present_set)
    meta_open["present_npc_ids_turn_index"] = turn_index
    meta_open["scene_buffer"] = {"open_since_turn_index": turn_index}
    # Opening fog: raise the islands the Director says this character plausibly already knows.
    _known_isles = decisions.get("opening_known_island_ids")
    if _known_isles and isinstance(meta_open.get("world"), dict):
        world_map.raise_islands_known(meta_open["world"], _known_isles)
    await repo.update_campaign_metadata(conn, campaign_id, meta_open)
    await conn.commit()

    # Header arc tracks the real world position (the Director may open the cold scene on an island
    # other than the seed's). Derive from the map and persist on change.
    _arc_label = world_map.world_arc_label(meta_open)
    if _arc_label and _arc_label != ((campaign_now or {}).get("current_arc") or ""):
        await repo.update_campaign_arc(conn, campaign_id, _arc_label)
        await conn.commit()
        if campaign_now is not None:
            campaign_now["current_arc"] = _arc_label
        # Keep the clock payload's arc in step with the world-derived label (it ships below).
        if isinstance(clock_light, dict):
            clock_light["current_arc"] = _arc_label

    # NPC present in the entry scene wakes (drops dormant, joins the off-scene tick) AND anchors
    # current_location on the world "island/" slug (anchor_location), not the scene prose. Cards are
    # born with no fixed location; being in the opening scene is the first anchor. Anchoring on prose
    # diverged from off-scene slugs and dropped the location-match to "elsewhere".
    fresh_agents = await repo.get_npc_agents(conn, campaign_id)
    changed = False
    for i in meta_open["present_npc_ids"]:
        info = fresh_agents.get(i)
        if not info:
            continue
        d = info["data"]
        touched = False
        if d.get("dormant"):
            d.pop("dormant", None)
            touched = True
        if anchor_location and d.get("current_location") != anchor_location:
            d["current_location"] = anchor_location
            touched = True
        if touched:
            await repo.update_story_card(conn, info["story_card_id"], d)
            changed = True
    if changed:
        await conn.commit()
    present_npcs = [
        {"name": fresh_agents[i]["data"].get("name", ""),
         "tier": fresh_agents[i]["data"].get("tier", ""),
         "affiliation": fresh_agents[i]["data"].get("affiliation", "")}
        for i in meta_open["present_npc_ids"] if i in fresh_agents
    ]

    yield {
        "type": "turn_complete",
        "turn_index": turn_index,
        "prose": prose,
        "turn_meta": narr["turn_meta"],
        "new_crystals": [],
        "audit": audit_report,
        # Composed scene/cast for the frontend header to populate on opening arrival.
        "scene": meta_open.get("scene", {}),
        "present_npcs": present_npcs,
        "current_arc": (campaign_now or {}).get("current_arc"),
        "clock": clock_light,
        "trace": trace_buf,
    }


async def run_opening(conn: aiosqlite.Connection, campaign_id: str) -> dict:
    """Non-streaming opening: consumes the generator and returns the turn_complete."""
    final: dict | None = None
    async for ev in run_opening_events(conn, campaign_id):
        if ev["type"] == "turn_complete":
            final = ev
    assert final is not None
    return final


# ======================================================================================
# Prose reroll (system command "regenerate narration")
# ======================================================================================
async def rerun_narrator_for_turn(
    conn: aiosqlite.Connection, campaign_id: str, turn_index: int,
    instruction: str | None = None,
) -> dict:
    """Re-runs the Narrator for the given turn with the SAME persisted input (turn_state +
    saved _reroll_addenda), discarding the old prose. Replaces only narrator_prose; does NOT
    re-apply the post-turn (deltas/events/crystals already happened). instruction = optional
    one-shot player note (not persisted).

    Restricted to the LAST turn: rerunning a mid-history turn would break the continuity of later
    turns that already read the old prose."""
    last = await repo.next_turn_index(conn, campaign_id) - 1
    if turn_index != last:
        raise ValueError(f"reroll só vale pro último turn (atual={last}, pedido={turn_index})")
    language.set_from_campaign(await repo.get_campaign(conn, campaign_id))
    turn_state = await repo.get_turn_state(conn, campaign_id, turn_index)
    if turn_state is None:
        raise LookupError(f"turn {turn_index} não encontrado na campanha '{campaign_id}'")
    # Separate the conditional addenda from the state going to the Narrator (engine-internal key).
    extra_addenda = turn_state.pop("_reroll_addenda", []) or []
    narr = await narrator.call_narrator(
        turn_state, extra_addenda=list(extra_addenda), reroll_note=instruction
    )
    prose = narr["prose"]
    # Restore the internal key and rewrite the turn_state intact (so a future reroll works).
    turn_state["_reroll_addenda"] = list(extra_addenda)
    await repo.update_turn_prose(conn, campaign_id, turn_index, prose)
    await repo.update_turn_state(conn, campaign_id, turn_index, turn_state)
    await conn.commit()
    return {"turn_index": turn_index, "prose": prose}


# ======================================================================================
# Turn rewind: undo one action, reverting the WORLD STATE too.
# Undoing the last turn restores the snapshot captured before it (story cards, crystals, clock,
# plots, directives, bounty, metadata) and deletes the turn. Regenerate = the caller rewinds and
# re-submits the SAME action through the whole pipeline; the world reacts again, no orphan prose.
# ======================================================================================
async def rewind_last_turn(
    conn: aiosqlite.Connection, campaign_id: str, turn_index: int
) -> dict:
    """Undoes the LAST turn: restores the pre-turn world snapshot + deletes the turn row. Returns
    the original player_input (for the caller to re-submit or restore in the composer). ValueError
    if not the last turn; LookupError without turn/snapshot (pre-0007 turns have no snapshot)."""
    last = await repo.next_turn_index(conn, campaign_id) - 1
    if turn_index != last:
        raise ValueError(f"rewind só vale pro último turn (atual={last}, pedido={turn_index})")
    cur = await conn.execute(
        "SELECT player_input FROM turns WHERE campaign_id = ? AND turn_index = ?",
        (campaign_id, turn_index),
    )
    row = await cur.fetchone()
    if row is None:
        raise LookupError(f"turn {turn_index} não encontrado na campanha '{campaign_id}'")
    player_input = json.loads(row[0]) if isinstance(row[0], str) else row[0]
    snapshot = await world_snapshot.get_snapshot(conn, campaign_id, turn_index)
    if snapshot is not None:
        await world_snapshot.restore_world(conn, campaign_id, snapshot)
    elif (player_input or {}).get("type") != "OPENING":
        raise LookupError(
            f"turn {turn_index} não tem snapshot de mundo (anterior ao suporte a rewind)"
        )
    # Opening without snapshot (recorded before openings snapshotted): the cold open does not mutate
    # the world (only Narrator + turn append), nothing to restore, only delete.
    await conn.execute(
        "DELETE FROM turns WHERE campaign_id = ? AND turn_index = ?",
        (campaign_id, turn_index),
    )
    await world_snapshot.delete_snapshots_from(conn, campaign_id, turn_index)
    await conn.commit()
    return {"turn_index": turn_index, "player_input": player_input}


async def run_turn(conn: aiosqlite.Connection, campaign_id: str, player_action: dict) -> dict:
    """Non-streaming: consumes the generator and returns the final payload. For DO it is
    turn_complete; for META meta_response; quota/refusal return the terminal error event, which
    the caller maps to the appropriate HTTP."""
    final: dict | None = None
    async for ev in run_turn_events(conn, campaign_id, player_action):
        if ev["type"] in ("turn_complete", "meta_response", *TURN_ERROR_TYPES):
            final = ev
    assert final is not None
    return final
