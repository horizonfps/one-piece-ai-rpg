"""Campaign API: create, list, load, run turns. WebSocket turn streams narrator
prose in deltas; POST turn is the non-streaming fallback."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from ..db import catalog
from ..db import connection
from ..db import repositories as repo
from ..db import seed as seed_mod
from ..pipeline import alliances
from ..pipeline import character_creation as cc
from ..pipeline import crew
from ..pipeline import economy
from ..pipeline import edit
from ..pipeline import endgame
from ..pipeline import faction
from ..pipeline import language
from ..pipeline import legend
from ..pipeline import mushi
from ..pipeline import plots
from ..pipeline import poneglyph
from ..pipeline import runner
from ..pipeline import ship
from ..pipeline import world_map

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


class CreateCampaignBody(BaseModel):
    name: str | None = None
    language: str | None = None


class TurnBody(BaseModel):
    type: str = "DO"            # DO = world action | META = out-of-character
    raw: str
    narrative_time_seconds: int | None = None


def _player_action(body: TurnBody) -> dict:
    pa: dict = {"type": body.type, "raw": body.raw}
    if body.narrative_time_seconds is not None:
        pa["narrative_time_seconds"] = body.narrative_time_seconds
    return pa


# --- CRUD ---
@router.post("")
async def create_campaign(body: CreateCampaignBody) -> dict:
    conn = await connection.connect()
    try:
        result = await seed_mod.seed_campaign(
            conn, name=body.name, campaign_language=body.language
        )
    finally:
        await conn.close()
    return result


@router.get("")
async def list_campaigns() -> dict:
    conn = await connection.connect()
    try:
        return {"campaigns": await repo.list_campaigns(conn)}
    finally:
        await conn.close()


@router.get("/{campaign_id}")
async def get_campaign(campaign_id: str) -> dict:
    conn = await connection.connect()
    try:
        campaign = await repo.get_campaign(conn, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="campaign_not_found")
        cards = await repo.get_story_cards(conn, campaign_id)
        player = next((c["data"] for c in cards if c["kind"] == "player"), None)
        npcs = {c["data"]["id"]: c["data"] for c in cards if c["kind"] == "npc_agent"}
        meta = campaign.get("metadata") or {}
        present = meta.get("present_npc_ids", [])
        present_npcs = [
            {"name": npcs[i]["name"], "tier": npcs[i].get("tier", ""), "affiliation": npcs[i].get("affiliation", "")}
            for i in present
            if i in npcs
        ]
        return {
            "campaign": {
                "id": campaign["id"],
                "name": campaign["name"],
                "current_arc": campaign.get("current_arc"),
                "created_at": campaign.get("created_at"),
                "language": campaign.get("language", "pt-br"),
            },
            "scene": meta.get("scene", {}),
            "present_npcs": present_npcs,
            "player": player,
            "turns": await repo.get_turns(conn, campaign_id),
            "crystals": await repo.get_all_crystals_for_crystallizer(conn, campaign_id),
            "clock": await repo.get_clock(conn, campaign_id),
        }
    finally:
        await conn.close()


@router.delete("/{campaign_id}")
async def delete_campaign(campaign_id: str) -> dict:
    """Delete the campaign and all dependent save state. 404 if missing."""
    conn = await connection.connect()
    try:
        ok = await repo.delete_campaign(conn, campaign_id)
        if not ok:
            raise HTTPException(status_code=404, detail="campaign_not_found")
        await conn.commit()
        return {"deleted": campaign_id}
    finally:
        await conn.close()


# --- Turn (non-streaming) ---
@router.post("/{campaign_id}/turn")
async def post_turn(campaign_id: str, body: TurnBody) -> dict:
    conn = await connection.connect()
    try:
        result = await runner.run_turn(conn, campaign_id, _player_action(body))
        # Quota exhaustion and model refusal are terminal events, not turns; map to HTTP.
        if result.get("type") == "quota_exceeded":
            headers = (
                {"Retry-After": str(result["retry_after_seconds"])}
                if result.get("retry_after_seconds")
                else None
            )
            raise HTTPException(status_code=503, detail=result["message"], headers=headers)
        if result.get("type") == "model_refusal":
            raise HTTPException(status_code=422, detail=result["message"])
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    finally:
        await conn.close()


# --- Character creation ---
class CharacterBody(BaseModel):
    name: str
    gender: str = ""
    appearance: str = ""                # free text: hair, eyes, build, clothes, marks
    weapon: str = ""                    # free text, no weapon catalog
    tier_alvo: str                      # NORMAL | SKILLED | STRONG (cap STRONG)
    class_id: str
    sub_focus: str | None = None        # style fighter sub-focus
    trait_ids: list[str] = []           # final hand after rerolls/edits
    devil_fruit_id: str | None = None   # None = no fruit
    dream: str = ""


@router.post("/{campaign_id}/character")
async def create_character(campaign_id: str, body: CharacterBody) -> dict:
    """Confirm the creation sheet: validate against catalogs and upsert the player card."""
    conn = await connection.connect()
    try:
        campaign = await repo.get_campaign(conn, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="campaign_not_found")
        language.set_from_campaign(campaign)
        traits = await catalog.get_traits(conn)
        classes = await catalog.get_classes(conn)
        fruits = await catalog.get_fruits(conn)
        sheet = body.model_dump()
        errors = cc.validate_sheet(sheet, traits, classes, fruits)
        if errors:
            raise HTTPException(status_code=422, detail={"errors": errors})
        card_data = cc.build_player_card(
            sheet, traits, classes, fruits, current_arc=campaign.get("current_arc")
        )
        existing = await repo.get_player_story_card(conn, campaign_id)
        if existing is not None:
            # Preserve seed-set public facts; build_player_card rebuilds the snapshot fresh
            # and would drop them.
            seed_facts = (existing["data"].get("player_snapshot") or {}).get("player_public_facts") or []
            if seed_facts:
                card_data["player_snapshot"]["player_public_facts"] = seed_facts
            await repo.update_story_card(conn, existing["id"], card_data)
            story_card_id = existing["id"]
        else:
            story_card_id = await repo.add_story_card(conn, campaign_id, "player", card_data)

        # Sync the clock: remap the placeholder age entry to the real name so NPCs
        # refer to the player by name at a coherent age.
        clock = await repo.get_clock(conn, campaign_id)
        if clock:
            by_age = dict(clock.get("active_characters_by_age") or {})
            placeholder_age = by_age.pop("[JOGADOR]", None)
            by_age[body.name] = (
                placeholder_age if placeholder_age is not None else clock.get("current_player_age")
            )
            clock["active_characters_by_age"] = by_age
            await repo.save_clock(conn, campaign_id, clock)

        await conn.commit()
        return {
            "campaign_id": campaign_id,
            "story_card_id": story_card_id,
            "player": card_data,
        }
    finally:
        await conn.close()


# --- Map & navigation ---
@router.get("/{campaign_id}/world")
async def get_world(campaign_id: str) -> dict:
    """Read-only world state for the map: islands with fog, player position, day counter."""
    conn = await connection.connect()
    try:
        campaign = await repo.get_campaign(conn, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="campaign_not_found")
        clock = await repo.get_clock(conn, campaign_id)
        return world_map.world_view(campaign.get("metadata") or {}, clock)
    finally:
        await conn.close()


# --- News Coo ---
@router.get("/{campaign_id}/news")
async def list_news(campaign_id: str) -> dict:
    """News Coo editions plus Marine nemesis state (read-only)."""
    conn = await connection.connect()
    try:
        campaign = await repo.get_campaign(conn, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="campaign_not_found")
        meta = campaign.get("metadata") or {}
        nem = meta.get("nemesis") or {}
        return {
            "editions": meta.get("news_editions") or [],
            "nemesis": {
                "current_nemesis_id": nem.get("current_nemesis_id"),
                "rank": nem.get("rank"),
                "spawn_threshold": nem.get("spawn_threshold"),
                "history": nem.get("nemesis_history") or [],
            },
        }
    finally:
        await conn.close()


# --- Communication: Den Den Mushi + Vivre Card ---
@router.get("/{campaign_id}/comms")
async def get_comms(campaign_id: str) -> dict:
    """Player communication state (read-only): paired mushis, vivre cards, active call.
    Card visual_state is re-derived live from owner status + vital_at_risk."""
    conn = await connection.connect()
    try:
        campaign = await repo.get_campaign(conn, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="campaign_not_found")
        player_sc = await repo.get_player_story_card(conn, campaign_id)
        psnap = ((player_sc or {}).get("data") or {}).get("player_snapshot") or {}
        npcs = {aid: info["data"] for aid, info in (await repo.get_npc_agents(conn, campaign_id)).items()}
        meta = campaign.get("metadata") or {}
        world = meta.get("world") or {}

        paired = []
        for p in (psnap.get("paired_mushis") or []):
            if not isinstance(p, dict) or not p.get("npc_id"):
                continue
            owner = npcs.get(p["npc_id"]) or {}
            paired.append({
                "npc_id": p["npc_id"], "name": owner.get("name", ""),
                "mushi_kind": p.get("mushi_kind", "baby"),
                "owner_status": owner.get("status", ""),
                "paired_at_turn_index": p.get("paired_at_turn_index"),
            })
        cards = []
        for v in (psnap.get("vivre_cards") or []):
            if not isinstance(v, dict) or not v.get("npc_id"):
                continue
            owner = npcs.get(v["npc_id"]) or {}
            # Live re-derive: the card stores the last narrated state; owner status may have changed.
            live = mushi.derive_vital_state(owner.get("status"), bool(owner.get("vital_at_risk")))
            owner_loc = owner.get("current_location", "")
            cards.append({
                "npc_id": v["npc_id"], "name": owner.get("name", ""),
                "visual_state": v.get("visual_state", live) or live,
                "origin_note": v.get("origin_note", ""),
                "owner_status": owner.get("status", ""),
                "owner_location": owner_loc,
                # Live bearing from player to the owner's island.
                "direction": mushi.vivre_card_direction(world, owner_loc, live),
                "received_at_turn_index": v.get("received_at_turn_index"),
            })
        return {
            "paired_mushis": paired,
            "vivre_cards": cards,
            "mushi_call_active": meta.get("mushi_call_active"),
            # Exotic mushi: black taps, white counter-tap, surveillance (only revealed with white active).
            "black_mushi_taps": mushi.director_black_taps(psnap, npcs),
            "white_mushi_active": mushi.white_mushi_active(psnap),
            "surveillance_on_player": mushi.surveillance_detected(psnap, meta),
            "buster_call_active": meta.get("buster_call_active"),
        }
    finally:
        await conn.close()


# --- Economy & inventory ---
@router.get("/{campaign_id}/economy")
async def get_economy(campaign_id: str) -> dict:
    """Player belly + bucket + inventory (read-only). Each entry resolves to its ITEM/FRUIT card."""
    conn = await connection.connect()
    try:
        campaign = await repo.get_campaign(conn, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="campaign_not_found")
        player_sc = await repo.get_player_story_card(conn, campaign_id)
        psnap = ((player_sc or {}).get("data") or {}).get("player_snapshot") or {}
        # Cards keyed by entity id (ITEM/FRUIT story_cards + NPCs, for fruit-on-card).
        cards_by_id: dict = {}
        for c in await repo.get_story_cards(conn, campaign_id):
            d = c["data"] or {}
            if d.get("id"):
                cards_by_id[d["id"]] = d

        belly = economy.belly_amount(psnap)
        inventory = []
        for e in (psnap.get("inventory") or []):
            if not isinstance(e, dict) or not e.get("item_card_id"):
                continue
            card = cards_by_id.get(e["item_card_id"]) or {}
            cs = card.get("current_state") or {}
            inventory.append({
                "item_card_id": e["item_card_id"],
                "name": card.get("name", ""),
                "subtype": card.get("subtype", ""),
                "summary": cs.get("summary_text", ""),
                "quantity": e.get("quantity"),
                "origin_note": e.get("origin_note", ""),
                "acquired_at_turn_index": e.get("acquired_at_turn_index"),
            })
        return {
            "belly": belly,
            "inventory": inventory,
        }
    finally:
        await conn.close()


class InventoryItemBody(BaseModel):
    name: str | None = None
    subtype: str | None = None
    summary: str | None = None
    quantity: int | None = None
    origin_note: str | None = None


def _resolve_inventory_item(psnap: dict, cards_by_id: dict, item_card_id: str) -> dict:
    """Shape one inventory row the way GET /economy does (card fields + entry fields)."""
    entry = next(
        (e for e in (psnap.get("inventory") or [])
         if isinstance(e, dict) and e.get("item_card_id") == item_card_id),
        {},
    )
    card = cards_by_id.get(item_card_id) or {}
    cs = card.get("current_state") or {}
    return {
        "item_card_id": item_card_id,
        "name": card.get("name", ""),
        "subtype": card.get("subtype", ""),
        "summary": cs.get("summary_text", ""),
        "quantity": entry.get("quantity"),
        "origin_note": entry.get("origin_note", ""),
        "acquired_at_turn_index": entry.get("acquired_at_turn_index"),
    }


@router.post("/{campaign_id}/inventory")
async def add_inventory_item(campaign_id: str, body: InventoryItemBody) -> dict:
    """Human-add an inventory item: mint a minimal ITEM card + an inventory entry on the player
    snapshot. Editing does not advance the turn; the next turn reads the new state."""
    conn = await connection.connect()
    try:
        player_sc = await repo.get_player_story_card(conn, campaign_id)
        if player_sc is None:
            raise HTTPException(status_code=404, detail="player_card_missing")
        name = (body.name or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="item_name_required")
        turn_index = max(0, await repo.next_turn_index(conn, campaign_id) - 1)
        card = economy.build_player_item_card(
            name, subtype=body.subtype or "", summary=body.summary or "", turn_index=turn_index
        )
        await repo.add_story_card(conn, campaign_id, "story_card", card)
        entry = economy.make_inventory_entry(
            card["id"], turn_index=turn_index,
            origin_note=body.origin_note or "", quantity=body.quantity,
        )
        new_data = edit.add_inventory_entry(player_sc["data"], entry)
        await repo.update_story_card(conn, player_sc["id"], new_data)
        await conn.commit()
        psnap = new_data.get("player_snapshot") or {}
        return {"item": _resolve_inventory_item(psnap, {card["id"]: card}, card["id"])}
    finally:
        await conn.close()


@router.patch("/{campaign_id}/inventory/{item_card_id}")
async def edit_inventory_item(campaign_id: str, item_card_id: str, body: InventoryItemBody) -> dict:
    """Edit an inventory item: entry fields (quantity/origin_note) on the player snapshot plus card
    fields (name/subtype/summary) on the ITEM story card."""
    conn = await connection.connect()
    try:
        player_sc = await repo.get_player_story_card(conn, campaign_id)
        if player_sc is None:
            raise HTTPException(status_code=404, detail="player_card_missing")
        patch = body.model_dump(exclude_unset=True)
        new_data, edited = edit.edit_inventory_entry(player_sc["data"], item_card_id, patch)
        if edited is None:
            raise HTTPException(status_code=404, detail="item_not_in_inventory")
        await repo.update_story_card(conn, player_sc["id"], new_data)

        resolved_card: dict = {}
        card_row = await repo.get_card_by_entity_id(conn, campaign_id, item_card_id)
        if card_row is not None:
            resolved_card = card_row["data"]
            card_patch = {k: patch[k] for k in ("name", "subtype", "summary") if k in patch}
            if card_patch:
                resolved_card = edit.merge_card_edit(card_row["data"], card_patch)
                await repo.update_story_card(conn, card_row["id"], resolved_card)
        await conn.commit()
        psnap = new_data.get("player_snapshot") or {}
        return {"item": _resolve_inventory_item(psnap, {item_card_id: resolved_card}, item_card_id)}
    finally:
        await conn.close()


@router.delete("/{campaign_id}/inventory/{item_card_id}")
async def delete_inventory_item(campaign_id: str, item_card_id: str) -> dict:
    """Remove an item from the player's inventory (the ITEM card stays in the acervo)."""
    conn = await connection.connect()
    try:
        player_sc = await repo.get_player_story_card(conn, campaign_id)
        if player_sc is None:
            raise HTTPException(status_code=404, detail="player_card_missing")
        new_data, removed = edit.remove_inventory_entry(player_sc["data"], item_card_id)
        if removed is None:
            raise HTTPException(status_code=404, detail="item_not_in_inventory")
        await repo.update_story_card(conn, player_sc["id"], new_data)
        await conn.commit()
        return {"removed": item_card_id}
    finally:
        await conn.close()


# --- Ship & Jolly Roger ---
@router.get("/{campaign_id}/fleet")
async def get_fleet(campaign_id: str) -> dict:
    """Crew fleet + Jolly Roger (read-only): active ship highlighted plus reserve."""
    conn = await connection.connect()
    try:
        campaign = await repo.get_campaign(conn, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="campaign_not_found")
        ship_cards: dict = {}
        for c in await repo.get_story_cards(conn, campaign_id, kind="story_card"):
            d = c["data"] or {}
            if d.get("id") and d.get("type") == "SHIP":
                ship_cards[d["id"]] = d
        crew = ship.get_crew(campaign.get("metadata") or {})

        def _full(entry: dict) -> dict:
            cid = entry.get("ship_card_id")
            card = ship_cards.get(cid) or {}
            cs = card.get("current_state") or {}
            return {
                "ship_card_id": cid,
                "name": card.get("name", ""),
                "subtype": card.get("subtype", ""),
                "hull_condition": cs.get("hull_condition", ""),
                "description": card.get("description", ""),
                "summary": cs.get("summary_text", ""),
                "role": entry.get("role", "reserve"),
                "acquired_at_turn_index": entry.get("acquired_at_turn_index"),
            }

        act = ship.active_entry(crew)
        return {
            "active": _full(act) if act else None,
            "reserve": [_full(e) for e in ship.reserve_entries(crew)],
            "jolly_roger": ship.jolly_roger_text(crew),
        }
    finally:
        await conn.close()


class JollyRogerBody(BaseModel):
    description: str = ""  # free text; empty clears the flag


@router.post("/{campaign_id}/jolly-roger")
async def set_jolly_roger(campaign_id: str, body: JollyRogerBody) -> dict:
    """Declare/edit the crew's Jolly Roger; the Narrator reads it in flag/recognition scenes."""
    conn = await connection.connect()
    try:
        campaign = await repo.get_campaign(conn, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="campaign_not_found")
        meta = dict(campaign.get("metadata") or {})
        turn_index = max(0, await repo.next_turn_index(conn, campaign_id) - 1)
        meta["crew"] = ship.set_jolly_roger(ship.get_crew(meta), body.description, turn_index=turn_index)
        await repo.update_campaign_metadata(conn, campaign_id, meta)
        await conn.commit()
        return {"jolly_roger": ship.jolly_roger_text(meta["crew"])}
    finally:
        await conn.close()


# --- Faction reputation ---
@router.get("/{campaign_id}/factions")
async def get_factions(campaign_id: str) -> dict:
    """Per-faction institutional reputation (read-only): player + crew values with buckets,
    plus named NPCs with their own accumulated reputation."""
    conn = await connection.connect()
    try:
        campaign = await repo.get_campaign(conn, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="campaign_not_found")
        cards = await repo.get_story_cards(conn, campaign_id)
        player_data = next((c["data"] for c in cards if c["kind"] == "player"), None) or {}
        psnap = player_data.get("player_snapshot") or {}
        faction_cards = {
            (c["data"] or {}).get("id"): c["data"]
            for c in cards
            if c["kind"] == "story_card" and (c["data"] or {}).get("type") == "FACTION" and (c["data"] or {}).get("id")
        }
        npc_cards = [c["data"] for c in cards if c["kind"] == "npc_agent"]

        player_reps = faction.reputations_of(psnap)
        crew_reps = faction.compute_crew_reputations(
            player_reps,
            [faction.reputations_of(d) for d in npc_cards if d.get("affiliation") == "player_crew"],
        )
        factions = []
        for fid, card in faction_cards.items():
            pv = faction.clamp_reputation(player_reps.get(fid, 0.0))
            cv = faction.clamp_reputation(crew_reps.get(fid, 0.0))
            factions.append({
                "faction_id": fid,
                "name": (card or {}).get("name", fid),
                "player_value": pv,
                "player_bucket": faction.reputation_bucket(pv),
                "crew_value": cv,
                "crew_bucket": faction.reputation_bucket(cv),
            })
        factions.sort(key=lambda e: e["player_value"])

        npcs = []
        for d in npc_cards:
            summary = faction.reputation_summary(faction.reputations_of(d), faction_cards, include_neutral=True)
            if summary:
                npcs.append({"id": d.get("id"), "name": d.get("name", ""), "reputations": summary})
        return {"factions": factions, "npcs": npcs}
    finally:
        await conn.close()


# --- Living legend (wanted posters) ---
@router.get("/{campaign_id}/legend")
async def get_legend(campaign_id: str) -> dict:
    """Wanted-poster gallery (read-only): public myth per target (player + crewmates) with
    current bounty and the full update history."""
    conn = await connection.connect()
    try:
        campaign = await repo.get_campaign(conn, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="campaign_not_found")
        meta = campaign.get("metadata") or {}
        cards = await repo.get_story_cards(conn, campaign_id)
        player_data = next((c["data"] for c in cards if c["kind"] == "player"), None) or {}
        npcs = {
            (c["data"] or {}).get("id"): c["data"]
            for c in cards if c["kind"] == "npc_agent" and (c["data"] or {}).get("id")
        }

        def _bounty_int(b) -> int:
            return int(b.get("current_amount", 0) or 0) if isinstance(b, dict) else int(b or 0)

        state = legend.legend_state_of(meta)
        player_id = player_data.get("id", "player")
        pc = player_data.get("player_character") or {}
        psnap = player_data.get("player_snapshot") or {}

        def _target(card_id: str, name: str, bounty: int, is_player: bool) -> dict:
            entry = state.get(card_id) or {}
            return {
                "card_id": card_id,
                "name": entry.get("target_name") or name,
                "is_player": is_player,
                "bounty": bounty,
                "epithet": entry.get("epithet"),
                "public_image": entry.get("public_image", ""),
                "divergence_note": entry.get("divergence_note"),
                "poster_note": entry.get("poster_note"),
                "wanted_status": entry.get("wanted_status", "none"),
                "updated_at_turn_index": entry.get("updated_at_turn_index"),
                "history": entry.get("history") or [],
            }

        targets = [_target(player_id, pc.get("name", ""), _bounty_int(psnap.get("bounty")), True)]
        for nid, d in npcs.items():
            if d.get("affiliation") != "player_crew" and nid not in state:
                continue
            targets.append(_target(nid, d.get("name", ""), _bounty_int(d.get("bounty")), False))
        return {"targets": targets}
    finally:
        await conn.close()


class LegendEditBody(BaseModel):
    epithet: str | None = None
    public_image: str | None = None
    divergence_note: str | None = None
    poster_note: str | None = None
    wanted_status: str | None = None


@router.patch("/{campaign_id}/legend/{card_id}")
async def edit_legend(campaign_id: str, card_id: str, body: LegendEditBody) -> dict:
    """Human inline edit of a wanted poster. Fields sent overwrite (empty string clears);
    creates the entry when absent (player or existing NPC only)."""
    conn = await connection.connect()
    try:
        campaign = await repo.get_campaign(conn, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="campaign_not_found")
        meta = dict(campaign.get("metadata") or {})
        cards = await repo.get_story_cards(conn, campaign_id)
        player_data = next((c["data"] for c in cards if c["kind"] == "player"), None) or {}
        player_id = player_data.get("id", "player")
        npcs = {
            (c["data"] or {}).get("id"): c["data"]
            for c in cards if c["kind"] == "npc_agent" and (c["data"] or {}).get("id")
        }
        if card_id != player_id and card_id not in npcs:
            raise HTTPException(status_code=404, detail="target_not_found")
        name = (
            (player_data.get("player_character") or {}).get("name", "")
            if card_id == player_id else npcs[card_id].get("name", "")
        )
        patch = {}
        for f in ("epithet", "public_image", "divergence_note", "poster_note", "wanted_status"):
            v = getattr(body, f)
            if v is not None:
                patch[f] = v
        entry = legend.apply_human_edit(meta, card_id, patch, target_name=name)
        await repo.update_campaign_metadata(conn, campaign_id, meta)
        await conn.commit()
        return {"entry": entry}
    finally:
        await conn.close()


@router.delete("/{campaign_id}/legend/{card_id}")
async def delete_legend(campaign_id: str, card_id: str) -> dict:
    """Remove a wanted-poster entry entirely (myth, poster and history)."""
    conn = await connection.connect()
    try:
        campaign = await repo.get_campaign(conn, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="campaign_not_found")
        meta = dict(campaign.get("metadata") or {})
        if not legend.remove_entry(meta, card_id):
            raise HTTPException(status_code=404, detail="poster_not_found")
        await repo.update_campaign_metadata(conn, campaign_id, meta)
        await conn.commit()
        return {"ok": True}
    finally:
        await conn.close()


# --- Continuity threads (foreshadow pool) ---
class ThreadBody(BaseModel):
    description: str | None = None
    theme_tag: str | None = None
    where_hint: str | None = None
    source_island_name: str | None = None


@router.get("/{campaign_id}/threads")
async def list_threads(campaign_id: str) -> dict:
    """Open continuity threads (read-only): planted hooks with age, origin and planter."""
    conn = await connection.connect()
    try:
        campaign = await repo.get_campaign(conn, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="campaign_not_found")
        turn_index = max(0, await repo.next_turn_index(conn, campaign_id) - 1)
        return {"threads": plots.list_threads(campaign.get("metadata") or {}, turn_index)}
    finally:
        await conn.close()


@router.post("/{campaign_id}/threads")
async def create_thread(campaign_id: str, body: ThreadBody) -> dict:
    """Plant a human-authored continuity thread in the foreshadow pool."""
    conn = await connection.connect()
    try:
        campaign = await repo.get_campaign(conn, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="campaign_not_found")
        description = (body.description or "").strip()
        if not description:
            raise HTTPException(status_code=422, detail="thread_description_required")
        meta = dict(campaign.get("metadata") or {})
        turn_index = max(0, await repo.next_turn_index(conn, campaign_id) - 1)
        existing = {
            h.get("hook_id") for h in (meta.get("foreshadow_pool") or []) if isinstance(h, dict)
        }
        hook_id = f"human_thread_{turn_index}"
        n = 2
        while hook_id in existing:
            hook_id = f"human_thread_{turn_index}_{n}"
            n += 1
        hook = plots.plant_thread(
            meta,
            hook_summary=description,
            theme_tag=body.theme_tag or "",
            where_hint=body.where_hint or "",
            source_name=body.source_island_name or "",
            turn_index=turn_index,
            planter="human",
            hook_id=hook_id,
        )
        await repo.update_campaign_metadata(conn, campaign_id, meta)
        await conn.commit()
        return {"thread": hook}
    finally:
        await conn.close()


@router.patch("/{campaign_id}/threads/{hook_id}")
async def edit_thread(campaign_id: str, hook_id: str, body: ThreadBody) -> dict:
    """Human inline edit of a thread. Fields sent overwrite; the description never clears."""
    conn = await connection.connect()
    try:
        campaign = await repo.get_campaign(conn, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="campaign_not_found")
        patch = body.model_dump(exclude_unset=True)
        if patch.get("description") is not None and not str(patch["description"]).strip():
            raise HTTPException(status_code=422, detail="thread_description_required")
        meta = dict(campaign.get("metadata") or {})
        hook = plots.edit_thread(meta, hook_id, patch)
        if hook is None:
            raise HTTPException(status_code=404, detail="thread_not_found")
        await repo.update_campaign_metadata(conn, campaign_id, meta)
        await conn.commit()
        return {"thread": hook}
    finally:
        await conn.close()


@router.delete("/{campaign_id}/threads/{hook_id}")
async def delete_thread(campaign_id: str, hook_id: str) -> dict:
    """Remove a thread from the foreshadow pool."""
    conn = await connection.connect()
    try:
        campaign = await repo.get_campaign(conn, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="campaign_not_found")
        meta = dict(campaign.get("metadata") or {})
        if not plots.remove_thread(meta, hook_id):
            raise HTTPException(status_code=404, detail="thread_not_found")
        await repo.update_campaign_metadata(conn, campaign_id, meta)
        await conn.commit()
        return {"ok": True}
    finally:
        await conn.close()


# --- Crew alliances & bounty hunters ---
@router.get("/{campaign_id}/alliances")
async def get_alliances(campaign_id: str) -> dict:
    """Active crew alliances (read-only) with resolved display names, plus a digest of
    recent bounty-hunter encounters."""
    conn = await connection.connect()
    try:
        campaign = await repo.get_campaign(conn, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="campaign_not_found")
        meta = campaign.get("metadata") or {}
        cards = await repo.get_story_cards(conn, campaign_id)
        npcs = {
            (c["data"] or {}).get("id"): c["data"]
            for c in cards if c["kind"] == "npc_agent" and (c["data"] or {}).get("id")
        }
        faction_cards = {
            (c["data"] or {}).get("id"): c["data"]
            for c in cards
            if c["kind"] == "story_card" and (c["data"] or {}).get("type") == "FACTION" and (c["data"] or {}).get("id")
        }
        return {
            "alliances": alliances.narrator_alliance_summary(
                alliances.crew_alliances_of(meta), faction_cards, npcs
            ),
            "recent_bounty_hunters": alliances.recent_bounty_hunter_encounters(meta),
        }
    finally:
        await conn.close()


# --- Crew ---
@router.get("/{campaign_id}/crew")
async def get_crew(campaign_id: str) -> dict:
    """Crew roster (read-only): specialty/bond/discontent/status per member, crew_alignment
    bucket, pending NPC join offers, and fleet flag past the soft cap."""
    conn = await connection.connect()
    try:
        campaign = await repo.get_campaign(conn, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="campaign_not_found")
        meta = campaign.get("metadata") or {}
        cards = await repo.get_story_cards(conn, campaign_id)
        player_data = next((c["data"] for c in cards if c["kind"] == "player"), None) or {}
        psnap = player_data.get("player_snapshot") or {}
        npcs = {
            (c["data"] or {}).get("id"): c["data"]
            for c in cards if c["kind"] == "npc_agent" and (c["data"] or {}).get("id")
        }
        align = crew.recompute_crew_alignment(psnap.get("alignment"), npcs)
        size = crew.crew_size(npcs)
        return {
            "members": crew.roster_summary(npcs),
            "crew_alignment": align,
            "size": size,
            "is_fleet": crew.is_fleet_tier(size),
            "soft_cap": crew.SOFT_CAP,
            "pending_offers": [
                o for o in (meta.get("crew_offers") or []) if isinstance(o, dict)
            ],
        }
    finally:
        await conn.close()


class CrewOfferBody(BaseModel):
    accept: bool


@router.post("/{campaign_id}/crew/offers/{npc_id}")
async def respond_crew_offer(campaign_id: str, npc_id: str, body: CrewOfferBody) -> dict:
    """Respond to an NPC-initiated join offer. Accept promotes the NPC to member and recomputes
    crew_alignment; reject just drops the offer."""
    conn = await connection.connect()
    try:
        campaign = await repo.get_campaign(conn, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="campaign_not_found")
        meta = dict(campaign.get("metadata") or {})
        offers = [o for o in (meta.get("crew_offers") or []) if isinstance(o, dict)]
        if not any(o.get("npc_id") == npc_id for o in offers):
            raise HTTPException(status_code=404, detail="offer_not_found")
        turn_index = max(0, await repo.next_turn_index(conn, campaign_id) - 1)
        joined = None
        if body.accept:
            agents_map = await repo.get_npc_agents(conn, campaign_id)
            info = agents_map.get(npc_id)
            if info is None:
                # Orphan offer: clear the queue instead of promoting a ghost.
                meta["crew_offers"] = crew.remove_pending_offer(offers, npc_id)
                await repo.update_campaign_metadata(conn, campaign_id, meta)
                await conn.commit()
                raise HTTPException(status_code=404, detail="npc_not_found")
            # Eligibility gate: a dead/missing NPC isn't promoted; clear the offer and 409.
            ok, why = crew.can_recruit(info["data"], allow_reconcile=True)
            if not ok:
                meta["crew_offers"] = crew.remove_pending_offer(offers, npc_id)
                await repo.update_campaign_metadata(conn, campaign_id, meta)
                await conn.commit()
                raise HTTPException(status_code=409, detail=f"npc_not_recruitable: {why}")
            data = crew.add_member(info["data"], turn_index=turn_index)
            await repo.update_story_card(conn, info["story_card_id"], data)
            await repo.append_new_crystals(
                conn, campaign_id,
                [crew.recruit_audit_crystal(data.get("name", ""), accepted=True)],
                source_turn_index=turn_index,
            )
            joined = {"id": npc_id, "name": data.get("name", "")}
        meta["crew_offers"] = crew.remove_pending_offer(offers, npc_id)
        # Recompute crew_alignment with the fresh roster.
        npcs = {
            aid: i["data"] for aid, i in (await repo.get_npc_agents(conn, campaign_id)).items()
        }
        player_card = await repo.get_player_story_card(conn, campaign_id)
        psnap = (player_card or {}).get("data", {}).get("player_snapshot", {}) if player_card else {}
        meta["crew_alignment"] = crew.recompute_crew_alignment(psnap.get("alignment"), npcs)
        await repo.update_campaign_metadata(conn, campaign_id, meta)
        await conn.commit()
        return {"accepted": body.accept, "joined": joined, "crew_alignment": meta["crew_alignment"]}
    finally:
        await conn.close()


# --- Endgame & Laugh Tale ---
@router.get("/{campaign_id}/ending")
async def get_ending(campaign_id: str) -> dict:
    """Endgame state (read-only): reached ending milestones plus endgame world flags. The game
    stays open; endings are Director-detected, never a hard stop."""
    conn = await connection.connect()
    try:
        campaign = await repo.get_campaign(conn, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="campaign_not_found")
        flags = endgame.endgame_state(campaign.get("metadata") or {})
        return {
            "endings_reached": flags["endings_reached"],
            "world_flags": {k: flags[k] for k in endgame.default_world_flags()},
        }
    finally:
        await conn.close()


@router.get("/{campaign_id}/poneglyphs")
async def get_poneglyphs(campaign_id: str) -> dict:
    """Discovered poneglyphs (ITEM cards subtype=poneglyph): kind, transcription/translation
    flags and revealed content when legible (read-only)."""
    conn = await connection.connect()
    try:
        campaign = await repo.get_campaign(conn, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="campaign_not_found")
        cards = await repo.get_story_cards(conn, campaign_id)
        item_cards = {
            (c["data"] or {}).get("id"): c["data"]
            for c in cards
            if c["kind"] == "story_card" and (c["data"] or {}).get("type") == "ITEM" and (c["data"] or {}).get("id")
        }
        out = []
        for c in poneglyph.poneglyph_cards(item_cards):
            st = c.get("current_state") or {}
            out.append({
                "id": c.get("id"), "name": c.get("name", ""),
                "poneglyph_kind": st.get("poneglyph_kind"),
                "transcribed_by_player": bool(st.get("transcribed_by_player")),
                "translated": bool(st.get("translated")),
                "content_revealed": st.get("content_revealed"),
            })
        flags = endgame.endgame_state(campaign.get("metadata") or {})
        return {"poneglyphs": out, "laugh_tale_revealed": bool(flags["laugh_tale_revealed"])}
    finally:
        await conn.close()


# --- Memory Inspector ---
@router.get("/{campaign_id}/cards")
async def list_cards(campaign_id: str, kind: str | None = None) -> dict:
    """Card summaries for the Memory Inspector (read-only). `?kind=` filters by type."""
    conn = await connection.connect()
    try:
        return {"cards": await repo.list_cards(conn, campaign_id, kind)}
    finally:
        await conn.close()


@router.get("/{campaign_id}/search")
async def search_memory(
    campaign_id: str, q: str = "", kind: str | None = None, category: str | None = None
) -> dict:
    """FTS5 text search over crystals + cards. `kind` filters cards; `category` filters
    crystals. Empty query returns empty lists."""
    conn = await connection.connect()
    try:
        return {
            "query": q,
            "cards": await repo.search_cards(conn, campaign_id, q, kind=kind),
            "crystals": await repo.search_crystals(conn, campaign_id, q, category=category),
        }
    finally:
        await conn.close()


# --- META directives ---
@router.get("/{campaign_id}/directives")
async def list_directives(campaign_id: str) -> dict:
    """All directives (active and deactivated) for the forget panel."""
    conn = await connection.connect()
    try:
        return {"directives": await repo.get_all_directives(conn, campaign_id)}
    finally:
        await conn.close()


@router.post("/{campaign_id}/directives/{directive_id}/deactivate")
async def deactivate_directive(campaign_id: str, directive_id: str) -> dict:
    """Soft-delete the chosen directive (forget panel)."""
    conn = await connection.connect()
    try:
        ok = await repo.deactivate_directive(conn, campaign_id, directive_id)
        if not ok:
            raise HTTPException(status_code=404, detail="directive_not_found")
        await conn.commit()
        return {"deactivated": directive_id}
    finally:
        await conn.close()


# --- System commands ---
# No parsed slash-commands; commands are contextual UI actions.
class RerollProseBody(BaseModel):
    instruction: str = ""  # optional one-shot player note for this regen


@router.post("/{campaign_id}/turns/{turn_index}/reroll-prose")
async def reroll_prose(
    campaign_id: str, turn_index: int, body: RerollProseBody | None = None
) -> dict:
    """Regenerate the last turn's narration: re-run the Narrator on the same persisted input,
    discarding the old prose. Deltas/events are not re-applied (the world already reacted).
    Optional `instruction` guides the rewrite (not persisted). 409 if not the last turn; 404 if gone."""
    conn = await connection.connect()
    try:
        instruction = (body.instruction if body else "").strip() or None
        return await runner.rerun_narrator_for_turn(
            conn, campaign_id, turn_index, instruction=instruction
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    finally:
        await conn.close()


@router.post("/{campaign_id}/turns/{turn_index}/rewind")
async def rewind_turn(campaign_id: str, turn_index: int) -> dict:
    """Undo the last turn, reverting world state via the pre-turn snapshot and deleting the turn.
    Returns the original player_input for the composer. 409 if not the last turn; 404 if no
    turn/snapshot."""
    conn = await connection.connect()
    try:
        return await runner.rewind_last_turn(conn, campaign_id, turn_index)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    finally:
        await conn.close()


# --- Global edit mode ---
# Inline inspector edits do not advance the turn or re-crystallize; they only persist, and
# the next turn reads the new state. Each endpoint validates the entity (404) and returns it.
class CardEditBody(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None
    subtype: str | None = None
    base_backstory: str | None = None
    age_at_creation: int | None = None
    race: str | None = None
    class_: str | None = Field(default=None, alias="class")
    affiliation: str | None = None
    current_goal: str | None = None
    mood: str | None = None
    long_term_dream: str | None = None
    devil_fruit: str | None = None
    summary: str | None = None          # current_state.summary_text
    tier: str | None = None             # full NPC tier ladder; validated
    hull_condition: str | None = None   # SHIP hull condition; validated
    expressiveness: str | None = None   # alto|medio|contido; validated
    knowledge_clearance: str | None = None             # validated knowledge tier
    knowledge_tier_to_know_exists: str | None = None   # validated knowledge tier
    knowledge_tier_to_know_details: str | None = None  # validated knowledge tier
    narrative_armor: str | None = None  # validated
    alignment_baseline: float | None = None  # [-2, 2], clamped
    appearance: dict | None = None      # build_and_age/face_and_hair/clothing/distinctive_mark
    personality: dict | None = None     # disposition/shows_as
    history: dict | None = None         # origin/defining_event/central_bond
    aliases: list[str] | None = None
    traits: list[str] | None = None
    voice_notes: list[str] | None = None
    notable_traits: list[str] | None = None
    haki_profile: list[str] | None = None  # validated against HAKI types
    flags: list[str] | None = None      # current_state.flags


@router.get("/{campaign_id}/cards/{story_card_id}")
async def get_card(campaign_id: str, story_card_id: str) -> dict:
    """Full card data for the inline editor. Accepts the row PK or the entity id."""
    conn = await connection.connect()
    try:
        card = await repo.get_story_card(conn, campaign_id, story_card_id)
        if card is None:
            card = await repo.get_card_by_entity_id(conn, campaign_id, story_card_id)
        if card is None:
            raise HTTPException(status_code=404, detail="card_not_found")
        return {"story_card_id": card["id"], "kind": card["kind"], "data": card["data"]}
    finally:
        await conn.close()


@router.patch("/{campaign_id}/cards/{story_card_id}")
async def edit_card(campaign_id: str, story_card_id: str, body: CardEditBody) -> dict:
    """Edit a card (NPC/ITEM/SHIP/FACTION) inline. Whitelisted merge; unsent fields stay intact.
    Accepts the row PK or the entity id (fleet entries reference the entity id). The player has
    its own route."""
    conn = await connection.connect()
    try:
        card = await repo.get_story_card(conn, campaign_id, story_card_id)
        if card is None:
            card = await repo.get_card_by_entity_id(conn, campaign_id, story_card_id)
        if card is None:
            raise HTTPException(status_code=404, detail="card_not_found")
        if card["kind"] == "player":
            raise HTTPException(status_code=400, detail="use_player_endpoint")
        patch = body.model_dump(exclude_unset=True, by_alias=True)
        new_data = edit.merge_card_edit(card["data"], patch)
        await repo.update_story_card(conn, card["id"], new_data)
        await conn.commit()
        return {"story_card_id": card["id"], "data": new_data}
    finally:
        await conn.close()


class PlayerEditBody(BaseModel):
    name: str | None = None
    gender: str | None = None
    weapon: str | None = None
    dream: str | None = None
    appearance: str | None = None
    tier: str | None = None             # full tier ladder; validated
    alignment_value: float | None = None  # -2.0..2.0; snapshot.alignment
    belly: int | None = None            # >=0; snapshot.belly


@router.patch("/{campaign_id}/player")
async def edit_player(campaign_id: str, body: PlayerEditBody) -> dict:
    """Edit the player sheet inline. Mirrors the name into the clock so NPCs keep
    referring to the player by name."""
    conn = await connection.connect()
    try:
        player_sc = await repo.get_player_story_card(conn, campaign_id)
        if player_sc is None:
            raise HTTPException(status_code=404, detail="player_card_missing")
        patch = body.model_dump(exclude_unset=True)
        old_name = player_sc["data"].get("name")
        new_data = edit.apply_player_edit(player_sc["data"], patch)
        await repo.update_story_card(conn, player_sc["id"], new_data)

        new_name = new_data.get("name")
        if new_name and new_name != old_name:
            clock = await repo.get_clock(conn, campaign_id)
            if clock:
                by_age = dict(clock.get("active_characters_by_age") or {})
                age = by_age.pop(old_name, clock.get("current_player_age"))
                by_age[new_name] = age
                clock["active_characters_by_age"] = by_age
                await repo.save_clock(conn, campaign_id, clock)

        await conn.commit()
        return {"player": new_data}
    finally:
        await conn.close()


@router.get("/{campaign_id}/techniques")
async def list_techniques(campaign_id: str) -> dict:
    """Registered custom techniques (player + crew/nemesis) for the editable inspector."""
    conn = await connection.connect()
    try:
        campaign = await repo.get_campaign(conn, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="campaign_not_found")
        player_sc = await repo.get_player_story_card(conn, campaign_id)
        psnap = ((player_sc or {}).get("data") or {}).get("player_snapshot") or {}
        npcs = {aid: info["data"] for aid, info in (await repo.get_npc_agents(conn, campaign_id)).items()}
        return {"techniques": edit.list_techniques(psnap, npcs)}
    finally:
        await conn.close()


async def _edit_or_remove_technique(conn, campaign_id, technique_id, patch, *, remove):
    """Find the technique (player snapshot or NPC card), apply edit/removal, persist the owner.
    Returns the affected entry or None if the id is unknown."""
    player_sc = await repo.get_player_story_card(conn, campaign_id)
    if player_sc is not None:
        data = player_sc["data"]
        snap = data.get("player_snapshot") or {}
        techs = snap.get("techniques") or []
        new_techs, affected = (
            edit.remove_technique(techs, technique_id) if remove
            else edit.edit_technique(techs, technique_id, patch)
        )
        if affected is not None:
            snap["techniques"] = new_techs
            data["player_snapshot"] = snap
            await repo.update_story_card(conn, player_sc["id"], data)
            return affected
    for _aid, info in (await repo.get_npc_agents(conn, campaign_id)).items():
        data = info["data"]
        techs = data.get("techniques") or []
        new_techs, affected = (
            edit.remove_technique(techs, technique_id) if remove
            else edit.edit_technique(techs, technique_id, patch)
        )
        if affected is not None:
            data["techniques"] = new_techs
            await repo.update_story_card(conn, info["story_card_id"], data)
            return affected
    return None


class TechniqueEditBody(BaseModel):
    name: str | None = None
    description: str | None = None


@router.patch("/{campaign_id}/techniques/{technique_id}")
async def edit_technique_endpoint(campaign_id: str, technique_id: str, body: TechniqueEditBody) -> dict:
    """Edit name/description of a technique (player or owning NPC)."""
    conn = await connection.connect()
    try:
        affected = await _edit_or_remove_technique(
            conn, campaign_id, technique_id, body.model_dump(exclude_unset=True), remove=False
        )
        if affected is None:
            raise HTTPException(status_code=404, detail="technique_not_found")
        await conn.commit()
        return {"technique": affected}
    finally:
        await conn.close()


@router.delete("/{campaign_id}/techniques/{technique_id}")
async def delete_technique_endpoint(campaign_id: str, technique_id: str) -> dict:
    """Remove a technique from its owner's registry (player or NPC)."""
    conn = await connection.connect()
    try:
        affected = await _edit_or_remove_technique(conn, campaign_id, technique_id, {}, remove=True)
        if affected is None:
            raise HTTPException(status_code=404, detail="technique_not_found")
        await conn.commit()
        return {"removed": technique_id}
    finally:
        await conn.close()


# --- Player breakthroughs + fruit_usage_log (editable inspector) ---
async def _mutate_player_breakthrough(conn, campaign_id, kind, patch, *, remove):
    player_sc = await repo.get_player_story_card(conn, campaign_id)
    if player_sc is None:
        raise HTTPException(status_code=404, detail="player_card_missing")
    new_data, affected = (
        edit.remove_breakthrough(player_sc["data"], kind) if remove
        else edit.edit_breakthrough(player_sc["data"], kind, patch)
    )
    if affected is None:
        raise HTTPException(status_code=404, detail="breakthrough_not_found")
    await repo.update_story_card(conn, player_sc["id"], new_data)
    await conn.commit()
    return new_data


class BreakthroughEditBody(BaseModel):
    description: str


@router.patch("/{campaign_id}/breakthroughs/{kind}")
async def edit_breakthrough_endpoint(campaign_id: str, kind: str, body: BreakthroughEditBody) -> dict:
    """Edit a player breakthrough's description, mirroring the derived fields the Narrator reads."""
    conn = await connection.connect()
    try:
        new_data = await _mutate_player_breakthrough(
            conn, campaign_id, kind, body.model_dump(exclude_unset=True), remove=False
        )
        return {"player": new_data}
    finally:
        await conn.close()


@router.delete("/{campaign_id}/breakthroughs/{kind}")
async def delete_breakthrough_endpoint(campaign_id: str, kind: str) -> dict:
    """Remove a player breakthrough and clear its derived mirrors."""
    conn = await connection.connect()
    try:
        new_data = await _mutate_player_breakthrough(conn, campaign_id, kind, {}, remove=True)
        return {"player": new_data, "removed": kind}
    finally:
        await conn.close()


async def _mutate_player_fruit_usage(conn, campaign_id, index, patch, *, remove):
    player_sc = await repo.get_player_story_card(conn, campaign_id)
    if player_sc is None:
        raise HTTPException(status_code=404, detail="player_card_missing")
    new_data, affected = (
        edit.remove_fruit_usage(player_sc["data"], index) if remove
        else edit.edit_fruit_usage(player_sc["data"], index, patch)
    )
    if affected is None:
        raise HTTPException(status_code=404, detail="fruit_usage_entry_not_found")
    await repo.update_story_card(conn, player_sc["id"], new_data)
    await conn.commit()
    return new_data


class FruitUsageEditBody(BaseModel):
    usage_summary: str


@router.patch("/{campaign_id}/fruit-usage/{index}")
async def edit_fruit_usage_endpoint(campaign_id: str, index: int, body: FruitUsageEditBody) -> dict:
    """Edit the usage_summary of a player fruit_usage_log entry."""
    conn = await connection.connect()
    try:
        new_data = await _mutate_player_fruit_usage(
            conn, campaign_id, index, body.model_dump(exclude_unset=True), remove=False
        )
        return {"player": new_data}
    finally:
        await conn.close()


@router.delete("/{campaign_id}/fruit-usage/{index}")
async def delete_fruit_usage_endpoint(campaign_id: str, index: int) -> dict:
    """Remove a player fruit_usage_log entry."""
    conn = await connection.connect()
    try:
        new_data = await _mutate_player_fruit_usage(conn, campaign_id, index, {}, remove=True)
        return {"player": new_data, "removed_index": index}
    finally:
        await conn.close()


class CrystalEditBody(BaseModel):
    fact: str | None = None
    category: str | None = None
    location: str | None = None


@router.patch("/{campaign_id}/crystals/{crystal_id}")
async def edit_crystal(campaign_id: str, crystal_id: str, body: CrystalEditBody) -> dict:
    """Edit a memory crystal inline. Reuses the crystallizer update path, which syncs FTS
    via triggers."""
    conn = await connection.connect()
    try:
        patch = body.model_dump(exclude_unset=True)
        if not patch:
            raise HTTPException(status_code=400, detail="nothing_to_edit")
        turn_index = max(0, await repo.next_turn_index(conn, campaign_id) - 1)
        applied, ignored = await repo.apply_crystal_updates(
            conn, campaign_id, [{"id": crystal_id, **patch}], source_turn_index=turn_index
        )
        if not applied:
            raise HTTPException(status_code=404, detail="crystal_not_found")
        await conn.commit()
        return {"crystal_id": crystal_id, **patch}
    finally:
        await conn.close()


@router.delete("/{campaign_id}/crystals/{crystal_id}")
async def delete_crystal(campaign_id: str, crystal_id: str) -> dict:
    """Remove a memory crystal. FTS is synced by the delete trigger."""
    conn = await connection.connect()
    try:
        ok = await repo.delete_crystal(conn, campaign_id, crystal_id)
        if not ok:
            raise HTTPException(status_code=404, detail="crystal_not_found")
        await conn.commit()
        return {"deleted": crystal_id}
    finally:
        await conn.close()


class TurnProseBody(BaseModel):
    prose: str


@router.patch("/{campaign_id}/turns/{turn_index}/prose")
async def edit_turn_prose(campaign_id: str, turn_index: int, body: TurnProseBody) -> dict:
    """Edit the narration of any persisted turn (manual edit; distinct from reroll). Writes the
    text as-is, leaving deltas/crystals untouched. 404 if the turn is missing."""
    conn = await connection.connect()
    try:
        ok = await repo.update_turn_prose(conn, campaign_id, turn_index, body.prose)
        if not ok:
            raise HTTPException(status_code=404, detail="turn_not_found")
        await conn.commit()
        return {"turn_index": turn_index, "prose": body.prose}
    finally:
        await conn.close()


# --- Turn (streaming via WebSocket) ---
@router.websocket("/{campaign_id}/turn")
async def ws_turn(websocket: WebSocket, campaign_id: str) -> None:
    await websocket.accept()
    conn = await connection.connect()
    try:
        # Cold open: with no turns yet, the Narrator streams the first beat before the first
        # action. Idempotent (runs only at 0 turns); best-effort (failure won't drop the socket).
        try:
            if await repo.next_turn_index(conn, campaign_id) == 1:
                async for ev in runner.run_opening_events(conn, campaign_id):
                    await websocket.send_json(ev)
        except Exception as exc:  # noqa: BLE001 return the error to the client without dropping the socket
            await websocket.send_json({"type": "error", "error": f"{type(exc).__name__}: {exc}"})
        while True:
            msg = await websocket.receive_json()
            player_action = {
                "type": msg.get("type", "DO"),
                "raw": msg.get("raw", ""),
            }
            if msg.get("narrative_time_seconds") is not None:
                player_action["narrative_time_seconds"] = msg["narrative_time_seconds"]
            # Regen: player OOC note for re-running the same action.
            if (msg.get("ooc_note") or "").strip():
                player_action["ooc_note"] = str(msg["ooc_note"]).strip()
            try:
                if player_action["type"] == "OPENING":
                    # Opening regen: rewind left the campaign at 0 turns; re-run the cold open
                    # (skips the DO pipeline).
                    if await repo.next_turn_index(conn, campaign_id) != 1:
                        await websocket.send_json({
                            "type": "error",
                            "error": "abertura já existe — regenerar exige rewind antes",
                        })
                        continue
                    events = runner.run_opening_events(
                        conn, campaign_id, ooc_note=player_action.get("ooc_note")
                    )
                else:
                    events = runner.run_turn_events(conn, campaign_id, player_action)
                async for ev in events:
                    await websocket.send_json(ev)
            except Exception as exc:  # noqa: BLE001 return the error to the client without dropping the socket
                await websocket.send_json({"type": "error", "error": f"{type(exc).__name__}: {exc}"})
    except WebSocketDisconnect:
        pass
    finally:
        await conn.close()
