"""Deterministic state side-effects of tactical actions; domain/persona gates already
validated upstream by the agent or Director.

Capture sources: `take_hostage` (agent action_type, on/off-scene) and `hostage_grab` in
`surprise_actions[]` with `player_perception_outcome == "connect"`. Captured hostage gets
`status: captured` at the captor's location. Whether a plot-armored NPC's capture proceeds is
the agent's/Narrator's call (the card's narrative_armor rides in their context), not an engine veto.

`surrender` sets the actor's own `status: surrendered` (voluntary; only while alive/injured).
`regroup` does not mutate status."""
from __future__ import annotations

from . import agent_state as ast

TACTICAL_ACTION_TYPES = frozenset({"surrender", "take_hostage", "regroup"})

# A corpse, a vanished NPC, or one already held cannot be taken hostage (mechanical only).
# Everything else (including a surrendered foe taken prisoner) is the Narrator's/Director's call.
_UNCAPTURABLE_STATUS = frozenset({"dead", "missing", "captured"})


def _is_capturable(hostage: dict | None) -> bool:
    """Mechanical guard only: a dead/missing/already-captured NPC cannot be taken hostage.
    Whether a plot-armored or surrendered NPC's capture proceeds is the agent's/Narrator's call."""
    if not isinstance(hostage, dict):
        return False
    return hostage.get("status", "alive") not in _UNCAPTURABLE_STATUS


def hostage_captures_from_surprise(surprise_actions, npcs: dict) -> list[dict]:
    """`hostage_grab` captures from `surprise_actions[]` with `player_perception_outcome ==
    "connect"`."""
    captures: list[dict] = []
    seen: set[str] = set()
    for s in surprise_actions or []:
        if not isinstance(s, dict) or s.get("type") != "hostage_grab":
            continue
        if s.get("player_perception_outcome") != "connect":
            continue
        hid = s.get("hostage_npc_id")
        actor_id = s.get("actor_npc_id")
        if not hid or hid == "player" or hid == actor_id or hid in seen:
            continue
        if not _is_capturable(npcs.get(hid)):
            continue
        seen.add(hid)
        captures.append({"hostage_id": hid, "captor_id": actor_id, "source": "hostage_grab"})
    return captures


def surrenders_from_agent_turns(actor_turns, npcs: dict) -> list[dict]:
    """`surrender` from `(actor_id, agent_turn)` pairs; the actor's own status changes. Only
    actors still standing (alive/injured); skips player and missing actors."""
    surrenders: list[dict] = []
    seen: set[str] = set()
    for actor_id, turn in actor_turns:
        if not isinstance(turn, dict) or turn.get("action_type") != "surrender":
            continue
        if not actor_id or actor_id == "player" or actor_id in seen:
            continue
        npc = npcs.get(actor_id)
        if not isinstance(npc, dict):
            continue
        if npc.get("status", "alive") in _UNCAPTURABLE_STATUS:
            continue
        seen.add(actor_id)
        surrenders.append({"npc_id": actor_id, "source": "surrender"})
    return surrenders


def dedupe_captures(*capture_lists) -> list[dict]:
    """Merge capture lists, deduping by `hostage_id` (first occurrence wins)."""
    out: list[dict] = []
    seen: set[str] = set()
    for lst in capture_lists:
        for cap in lst or []:
            hid = cap.get("hostage_id")
            if not hid or hid in seen:
                continue
            seen.add(hid)
            out.append(cap)
    return out


def apply_capture(
    hostage_data: dict,
    *,
    captor_id: str | None = None,
    captor_location: str | None = None,
    memory_note: str = "",
    scene_mode: str = "on_scene",
    turn_index: int,
) -> dict:
    """Set a hostage copy to `status: captured` at the captor's location. Logs only an
    LLM-authored memory_note when supplied; no factory prose. Pure; the caller persists."""
    data = dict(hostage_data)
    data["status"] = "captured"
    if captor_location:
        data["current_location"] = captor_location
    memory = (memory_note or "").strip()
    if memory:
        data = ast.append_log_entry(data, ast.make_log_entry(
            turn_index=turn_index,
            action_summary=memory,
            location=data.get("current_location", ""),
            scene_mode=scene_mode,
            npcs_involved=[captor_id] if captor_id else [],
            important=True,
            source="self",
        ))
    data["last_tick_index"] = turn_index
    data["last_updated_turn_index"] = turn_index
    return data


def apply_surrender(
    npc_data: dict,
    *,
    memory_note: str = "",
    scene_mode: str = "on_scene",
    turn_index: int,
) -> dict:
    """Set an NPC copy to `status: surrendered`. Logs only an LLM-authored memory_note when
    supplied; no factory prose. No location change, no armor clamp. Pure; the caller persists."""
    data = dict(npc_data)
    data["status"] = "surrendered"
    memory = (memory_note or "").strip()
    if memory:
        data = ast.append_log_entry(data, ast.make_log_entry(
            turn_index=turn_index,
            action_summary=memory,
            location=data.get("current_location", ""),
            scene_mode=scene_mode,
            npcs_involved=[],
            important=True,
            source="self",
        ))
    data["last_tick_index"] = turn_index
    data["last_updated_turn_index"] = turn_index
    return data
