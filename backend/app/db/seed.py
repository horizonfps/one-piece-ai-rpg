"""Seed a playable campaign from a seed in seed_data/. Production starts in Foosha Village /
Dawn Island with the player at 17, about to set sail; the nw_isle seed is a test/smoke
scenario. A seed is a fixed canon-valid base: player placeholder + NPC minds + bootstrapped
game_clock. Dynamic NPC/island/arc content enters when the generators run."""
from __future__ import annotations

import json
from pathlib import Path

import aiosqlite

from . import repositories as repo
from .. import app_settings
from ..pipeline import language
from ..pipeline import world_map

SEED_DIR = Path(__file__).parent / "seed_data"
DEFAULT_SEED = "dawn_island"  # production starts in Foosha

DAYS_PER_YEAR = 365


def _seed_file(name: str, lang: str | None = None) -> Path:
    """Language variant of a seed_data file, falling back to the base (pt-br) file."""
    if lang and lang != language.DEFAULT_LANGUAGE:
        candidate = SEED_DIR / f"{name}.{lang}.json"
        if candidate.exists():
            return candidate
    return SEED_DIR / f"{name}.json"


def load_seed(seed_name: str = DEFAULT_SEED, lang: str | None = None) -> dict:
    return json.loads(_seed_file(f"{seed_name}_seed", lang).read_text(encoding="utf-8"))


def load_islands_catalog(lang: str | None = None) -> list[dict]:
    """Full-world island catalog (onepieceworldmap.com ingest). Shared geography/canon; fog is
    per-campaign. The 9 East Blue entries carry rich prose; the rest are minimal until
    arrival research enriches them."""
    data = json.loads(_seed_file("world_islands", lang).read_text(encoding="utf-8"))
    return data.get("islands") or []


def load_blank_slots() -> list[dict]:
    """Real drawn-but-uncatalogued landmasses (auto-detected from the map tiles). The engine
    anchors invented islands onto these so they get coords + a marker instead of a phantom. Blues
    only; the Grand Line uses the canon catalog."""
    data = json.loads((SEED_DIR / "blank_island_slots.json").read_text(encoding="utf-8"))
    return data.get("slots") or []


def load_factions_catalog(lang: str | None = None) -> list[dict]:
    """Seed catalog of trackable factions. Each entry becomes a story_card type=FACTION,
    the base for faction_reputations tracking."""
    data = json.loads(_seed_file("factions", lang).read_text(encoding="utf-8"))
    return data.get("factions") or []


def load_canon_world(lang: str | None = None) -> dict:
    """Canon world catalog: NPCs with full agent sheets + factions + named items. NPCs enter
    as npc_agent (inert until the Director pulls them); factions and items as story_card. The
    seed's village NPCs are not here (their live card evolves)."""
    path = _seed_file("canon_world", lang)
    if not path.exists():
        return {"npcs": [], "factions": [], "items": []}
    return json.loads(path.read_text(encoding="utf-8"))


def load_items_catalog(lang: str | None = None) -> list[dict]:
    """Seed catalog of canon ITEM cards. Each entry becomes a story_card type=ITEM, its own
    entity for the existence gate and inventory name resolution. New items enter via the
    item_generator."""
    data = json.loads(_seed_file("canonical_items", lang).read_text(encoding="utf-8"))
    return data.get("items") or []


STARTER_SHIP_ID = "starter-skiff"


_STARTER_SHIP_TEXT = {
    "pt-br": {
        "name": "Bote de Foosha",
        "description": (
            "Bote a remo de tábuas gastas, mastro curto e vela de pano remendada. Cabe duas pessoas "
            "e pouca carga; aguenta o East Blue, não a corrente que sobe a Reverse Mountain."
        ),
        "summary_text": "Em poder do player, ancorado no porto de Foosha, pronto pra zarpar.",
        "flags": ["bote", "raft-class"],
    },
    "en": {
        "name": "Foosha Dinghy",
        "description": (
            "A rowboat of worn planks, short mast and a patched cloth sail. Fits two people and "
            "little cargo; it can take the East Blue, not the current that climbs Reverse Mountain."
        ),
        "summary_text": "In the player's hands, anchored at Foosha's harbor, ready to set sail.",
        "flags": ["dinghy", "raft-class"],
    },
}


def _starter_ship_card(lang: str | None = None) -> dict:
    """The humble rowboat the player sets sail in (Luffy's dinghy parallel): a raft-class hull that
    handles a Blue but not the Grand Line current. A public SHIP story_card (data.type=SHIP); the
    crew fleet entry points at this id and the engine derives ship_speed_factor (0.7) from it."""
    text = _STARTER_SHIP_TEXT.get(lang or "") or _STARTER_SHIP_TEXT[language.DEFAULT_LANGUAGE]
    return {
        "id": STARTER_SHIP_ID,
        "type": "SHIP",
        "subtype": "bote",
        "speed_class": "raft",
        "name": text["name"],
        "aliases": [],
        "canonical": "generated",
        "description": text["description"],
        "current_state": {
            "summary_text": text["summary_text"],
            "hull_condition": "scarred",
            "flags": list(text["flags"]),
        },
        "state_history": [],
        "related_card_ids": [],
        "knowledge_tier_to_know_exists": "common",
        "knowledge_tier_to_know_details": "common",
    }


async def seed_campaign(
    conn: aiosqlite.Connection, *, name: str | None = None, seed_name: str = DEFAULT_SEED,
    campaign_language: str | None = None,
) -> dict:
    """Create a full playable campaign and commit. Returns {campaign_id, scene, ...}.
    seed_name picks the seed (dawn_island = production; nw_isle = adult test).
    campaign_language freezes the prose language; default comes from app settings."""
    if campaign_language not in language.SUPPORTED_LANGUAGES:
        campaign_language = app_settings.load()["language"]
    data = load_seed(seed_name, campaign_language)
    # The seed no longer scripts the stage: scene/present_npc_ids start empty and the opening
    # runs the Director to compose the first scene and cast from the canon catalog. The seed is
    # a factual marker: initial player age + start_location (only for the map's initial fog).
    start_location = data.get("start_location") or (data.get("scene") or {}).get("location", "")

    # Post-turn world state in metadata (player alignment/bounty live in player_snapshot).
    # Defaults overridable by the seed's world_state block.
    ws = data.get("world_state") or {}
    metadata = {
        # Empty: the opening composes and persists scene + present_npc_ids.
        "scene": {},
        "present_npc_ids": [],
        "chaos_meter": ws.get("chaos_meter") or {"value": 0.3, "bucket": "restless"},
        "crew_alignment": ws.get("crew_alignment") or {"value": 0.9, "bucket": "good"},
        "events_background": ws.get("events_background") or [],
        # Map & position: player position + island catalog with per-campaign fog, derived from
        # start_location. day_counter is not here (it is game_clock.campaign_day).
        "world": world_map.build_initial_world(
            load_islands_catalog(campaign_language), start_location, load_blank_slots()
        ),
    }
    # Starter boat: the humble skiff the player sets sail in (raft-class, ship_speed_factor 0.7).
    ship_card = _starter_ship_card(campaign_language)
    metadata["crew"] = {
        "fleet": [{"ship_card_id": ship_card["id"], "role": "active", "acquired_at_turn_index": 0}],
        "jolly_roger": None,
    }
    world_map.refresh_player_ship_speed(metadata, {ship_card["id"]: ship_card})
    cid = await repo.create_campaign(
        conn,
        name or data["campaign_name"],
        current_arc=data["current_arc"],
        metadata=metadata,
        language=campaign_language,
    )

    await repo.add_story_card(
        conn,
        cid,
        "player",
        {
            "player_character": data["player_character"],
            "player_snapshot": data["player_snapshot"],
            "crew_snapshot": data["crew_snapshot"],
        },
    )
    for npc in data["npcs"]:
        await repo.add_story_card(conn, cid, "npc_agent", npc)

    # FACTION cards: enter as story_cards type=FACTION, inert until the Director emits a delta.
    for fac in load_factions_catalog(campaign_language):
        await repo.add_story_card(conn, cid, "story_card", fac)

    # Canon ITEM cards: enter as story_cards type=ITEM, inert until referenced or acquired.
    for item in load_items_catalog(campaign_language):
        await repo.add_story_card(conn, cid, "story_card", item)

    # Canon world catalog: NPCs enter as npc_agent; factions and items as story_card. Inert
    # until the Director references them (active_cards is the existence gate).
    canon = load_canon_world(campaign_language)
    for npc in canon["npcs"]:
        await repo.add_story_card(conn, cid, "npc_agent", npc)
    for fac in canon["factions"]:
        await repo.add_story_card(conn, cid, "story_card", fac)
    for item in canon["items"]:
        await repo.add_story_card(conn, cid, "story_card", item)

    # Starter SHIP card (data.type=SHIP); the crew fleet entry in metadata points at its id.
    await repo.add_story_card(conn, cid, "story_card", ship_card)

    age = int(data["initial_player_age"])
    by_age: dict[str, int] = {"[JOGADOR]": age}
    for npc in data["npcs"]:
        if "age_at_creation" in npc:
            by_age[npc["name"]] = int(npc["age_at_creation"])

    clock = {
        "campaign_day": 0,
        "current_player_age": age,
        "current_arc": data["current_arc"],
        "active_characters_by_age": by_age,
        "player_birth_day": -age * DAYS_PER_YEAR,
        "last_updated_at_turn_index": 0,
    }
    await repo.save_clock(conn, cid, clock)
    await repo.append_clock_snapshot(
        conn,
        cid,
        0,
        {
            "turn_index": 0,
            "campaign_day": clock["campaign_day"],
            "player_age": clock["current_player_age"],
            "arc": clock["current_arc"],
            "characters_by_age": dict(by_age),
        },
    )

    await conn.commit()
    # Empty scene: the stage does not exist yet (the opening composes it). Stable shape for the caller.
    return {"campaign_id": cid, "name": name or data["campaign_name"], "scene": {}}
