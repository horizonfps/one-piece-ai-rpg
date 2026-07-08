"""Communication (Den Den Mushi + Vivre Card), pure logic.

No I/O / proxy / DB. Deterministic derivations the engine applies around the Director channels
(mushi calls, vivre_card_state_change) and the edit_primitives (pair/unpair/receive/remove).
State lives in JSON escape-hatch: `player_snapshot.paired_mushis[]` / `vivre_cards[]`,
`vital_at_risk` on the agent card, `metadata.mushi_call_active`.
"""
from __future__ import annotations

from . import agent_state
from . import world_map

# Vivre card visual states, derived live from status + vital_at_risk.
VITAL_STATES = ("white", "burning", "errant", "ashes")
# Pairable mushi kinds: baby (same island), standard (global), visual (global + transmits the
# caller's image).
_VALID_KINDS = ("baby", "standard", "visual")
# Global-range kinds, not barred by the baby island gate.
_GLOBAL_RANGE_KINDS = ("standard", "visual")
# Chaos magnitude of a Buster Call.
BUSTER_CALL_CHAOS_DELTA = 0.5


# ======================================================================================
# Range (cluster) and vital state derivation
# ======================================================================================
def cluster_of(location: str) -> str:
    """Baby mushi range cluster is the island. Baby is short-range: the caller must be on the
    same island as the player. `standard` ignores range (global)."""
    return agent_state.island_of(location)


def derive_vital_state(status: str | None, vital_at_risk: bool) -> str:
    """Vivre card vital state, in precedence: ashes (dead), burning (vital_at_risk), errant
    (missing), white. Computed live; capture alone does not trigger burning, only vital_at_risk."""
    s = (status or "alive").strip().lower()
    if s == "dead":
        return "ashes"
    if vital_at_risk:
        return "burning"
    if s == "missing":
        return "errant"
    return "white"


def vital_at_risk_for_visual(new_visual_state: str) -> bool | None:
    """Sync `agent.vital_at_risk` from the Director's visual_state: burning -> True, white ->
    False. errant/ashes leave the flag untouched (they derive from status)."""
    if new_visual_state == "burning":
        return True
    if new_visual_state == "white":
        return False
    return None


def vivre_card_direction(world: dict | None, owner_location: str, visual_state: str) -> dict | None:
    """Vivre Card direction on the map: where the card points, from the player position to the
    owner's island. Returns `{same_island, stable}` when on the same island, a bearing dict when
    a direction exists, or None when there is none (ashes, owner island without coords, or
    undefinable player position). `stable=False` only in errant (trembling needle)."""
    world = world or {}
    if visual_state == "ashes":
        return None
    stable = visual_state != "errant"
    target_island = world_map.island_id_of_location(owner_location or "")

    # Same island (land only): no direction.
    pos = (world.get("player") or {}).get("position") or {}
    if pos.get("kind") == "island" and target_island and pos.get("island_id") == target_island:
        return {"same_island": True, "stable": stable}

    bearing = world_map.compass_bearing(
        world_map.player_position_coords(world),
        world_map.island_coords(world, target_island) if target_island else None,
    )
    if bearing is None:
        return None
    return {"same_island": False, "stable": stable, "target_island_id": target_island, **bearing}


# ======================================================================================
# Player state reads
# ======================================================================================
def paired_mushi_ids(player_snapshot: dict | None) -> set:
    """NPC ids the player has a paired mushi with (gate for call_player/outgoing)."""
    return {
        p.get("npc_id") for p in ((player_snapshot or {}).get("paired_mushis") or [])
        if isinstance(p, dict) and p.get("npc_id")
    }


def paired_mushi_kind(player_snapshot: dict | None, npc_id: str) -> str | None:
    for p in ((player_snapshot or {}).get("paired_mushis") or []):
        if isinstance(p, dict) and p.get("npc_id") == npc_id:
            return p.get("mushi_kind", "baby")
    return None


def vivre_card_npc_ids(player_snapshot: dict | None) -> set:
    return {
        v.get("npc_id") for v in ((player_snapshot or {}).get("vivre_cards") or [])
        if isinstance(v, dict) and v.get("npc_id")
    }


def director_paired_mushis(player_snapshot: dict | None, npcs: dict) -> list[dict]:
    """Projection of `player.paired_mushis[]` for the Director: id, kind, owner's current cluster
    (for the baby range gate), and status. Owners missing from the roster still listed."""
    out: list[dict] = []
    for p in ((player_snapshot or {}).get("paired_mushis") or []):
        if not isinstance(p, dict) or not p.get("npc_id"):
            continue
        nid = p["npc_id"]
        owner = npcs.get(nid) or {}
        out.append({
            "npc_id": nid,
            "name": owner.get("name", ""),
            "mushi_kind": p.get("mushi_kind", "baby"),
            "owner_status": owner.get("status", ""),
            "owner_current_cluster": cluster_of(owner.get("current_location", "")),
        })
    return out


def director_vivre_cards(player_snapshot: dict | None, npcs: dict) -> list[dict]:
    """Projection of `player.vivre_cards[]` for the Director: id, stored visual_state, owner
    status (so the Director can detect a transition into vivre_card_state_change)."""
    out: list[dict] = []
    for v in ((player_snapshot or {}).get("vivre_cards") or []):
        if not isinstance(v, dict) or not v.get("npc_id"):
            continue
        nid = v["npc_id"]
        owner = npcs.get(nid) or {}
        out.append({
            "npc_id": nid,
            "name": owner.get("name", ""),
            "visual_state": v.get("visual_state", "white"),
            "owner_status": owner.get("status", ""),
        })
    return out


# ======================================================================================
# edit_primitives (POST): mutate the player_snapshot in place
# ======================================================================================
def apply_pair_mushi(snapshot: dict, *, npc_id: str, mushi_kind: str, location: str, turn_index: int) -> bool:
    """Add or update a mushi pairing (dedup by npc_id). True if changed."""
    if not npc_id:
        return False
    paired = list(snapshot.get("paired_mushis") or [])
    kind = mushi_kind if mushi_kind in _VALID_KINDS else "baby"
    for p in paired:
        if isinstance(p, dict) and p.get("npc_id") == npc_id:
            if p.get("mushi_kind") == kind:
                return False
            p["mushi_kind"] = kind  # re-paired with a different kind
            snapshot["paired_mushis"] = paired
            return True
    paired.append({
        "npc_id": npc_id, "mushi_kind": kind,
        "paired_at_turn_index": turn_index, "paired_at_location": location or "",
    })
    snapshot["paired_mushis"] = paired
    return True


def apply_unpair_mushi(snapshot: dict, *, npc_id: str) -> bool:
    paired = list(snapshot.get("paired_mushis") or [])
    new = [p for p in paired if not (isinstance(p, dict) and p.get("npc_id") == npc_id)]
    if len(new) == len(paired):
        return False
    snapshot["paired_mushis"] = new
    return True


def apply_receive_vivre_card(
    snapshot: dict, *, npc_id: str, origin_note: str, location: str, turn_index: int, visual_state: str
) -> bool:
    """Player receives a vivre card. Dedup: one per NPC. Initial `visual_state` is derived by the
    caller from the owner's status/vital_at_risk."""
    if not npc_id:
        return False
    cards = list(snapshot.get("vivre_cards") or [])
    if any(isinstance(v, dict) and v.get("npc_id") == npc_id for v in cards):
        return False
    cards.append({
        "npc_id": npc_id,
        "received_at_turn_index": turn_index,
        "received_from_location": location or "",
        "origin_note": origin_note or "",
        "visual_state": visual_state if visual_state in VITAL_STATES else "white",
    })
    snapshot["vivre_cards"] = cards
    return True


def apply_remove_vivre_card(snapshot: dict, *, npc_id: str) -> bool:
    cards = list(snapshot.get("vivre_cards") or [])
    new = [v for v in cards if not (isinstance(v, dict) and v.get("npc_id") == npc_id)]
    if len(new) == len(cards):
        return False
    snapshot["vivre_cards"] = new
    return True


# ======================================================================================
# Exotic Den Den Mushi (visual / black / white) + Buster Call (golden/silver)
# ======================================================================================
def is_global_range(kind: str | None) -> bool:
    """True if the mushi reaches beyond the island (standard/visual). baby is short-range."""
    return (kind or "baby") in _GLOBAL_RANGE_KINDS


def is_visual(kind: str | None) -> bool:
    """Visual Den Den Mushi: the call transmits the caller's image, not only voice."""
    return kind == "visual"


# ---- Black Den Den Mushi: interception (player taps NPC calls) -------------------------
def black_mushi_taps(player_snapshot: dict | None) -> list[dict]:
    """Player's active taps: each points to an NPC whose communications the player can
    intercept."""
    return [
        t for t in ((player_snapshot or {}).get("black_mushi_taps") or [])
        if isinstance(t, dict) and t.get("target_npc_id")
    ]


def tapped_npc_ids(player_snapshot: dict | None) -> set:
    return {t["target_npc_id"] for t in black_mushi_taps(player_snapshot)}


def apply_plant_black_mushi(snapshot: dict, *, target_npc_id: str, location: str, turn_index: int) -> bool:
    """Player plants a black mushi tapping `target_npc_id` (dedup by target). True if changed."""
    if not target_npc_id:
        return False
    taps = list(snapshot.get("black_mushi_taps") or [])
    if any(isinstance(t, dict) and t.get("target_npc_id") == target_npc_id for t in taps):
        return False
    taps.append({
        "target_npc_id": target_npc_id,
        "planted_at_location": location or "",
        "planted_at_turn_index": turn_index,
    })
    snapshot["black_mushi_taps"] = taps
    return True


def apply_remove_black_mushi(snapshot: dict, *, target_npc_id: str) -> bool:
    taps = list(snapshot.get("black_mushi_taps") or [])
    new = [t for t in taps if not (isinstance(t, dict) and t.get("target_npc_id") == target_npc_id)]
    if len(new) == len(taps):
        return False
    snapshot["black_mushi_taps"] = new
    return True


def director_black_taps(player_snapshot: dict | None, npcs: dict) -> list[dict]:
    """Projection for the Director: tapped targets (id, name, status). The Director decides if an
    interceptable transmission exists this turn (target communicating off-scene)."""
    out: list[dict] = []
    for t in black_mushi_taps(player_snapshot):
        nid = t["target_npc_id"]
        owner = npcs.get(nid) or {}
        out.append({"target_npc_id": nid, "name": owner.get("name", ""), "owner_status": owner.get("status", "")})
    return out


# ---- White Den Den Mushi: counter-surveillance (detects taps on the player) ------------
def white_mushi_active(player_snapshot: dict | None) -> bool:
    """White mushi on means the player sweeps their own line. When active, the Director may emit a
    surveillance alert if someone is tapping the player."""
    return bool((player_snapshot or {}).get("white_mushi_active"))


def apply_set_white_mushi(snapshot: dict, *, active: bool) -> bool:
    cur = bool(snapshot.get("white_mushi_active"))
    if cur == bool(active):
        return False
    if active:
        snapshot["white_mushi_active"] = True
    else:
        snapshot.pop("white_mushi_active", None)
    return True


def taps_on_player(metadata: dict | None) -> list[dict]:
    """Taps NPCs planted on the player (Director-driven). The white mushi detects them; without
    it active the player does not know they are being heard."""
    return [
        t for t in ((metadata or {}).get("taps_on_player") or [])
        if isinstance(t, dict) and t.get("watcher_npc_id")
    ]


def apply_plant_tap_on_player(metadata: dict, *, watcher_npc_id: str, turn_index: int, note: str = "") -> bool:
    """An NPC starts tapping the player (dedup by watcher). The player only learns if the white
    mushi is active. True if changed."""
    if not watcher_npc_id:
        return False
    taps = list(metadata.get("taps_on_player") or [])
    if any(isinstance(t, dict) and t.get("watcher_npc_id") == watcher_npc_id for t in taps):
        return False
    taps.append({"watcher_npc_id": watcher_npc_id, "planted_at_turn_index": int(turn_index), "note": note or ""})
    metadata["taps_on_player"] = taps
    return True


def apply_remove_tap_on_player(metadata: dict, *, watcher_npc_id: str) -> bool:
    taps = list(metadata.get("taps_on_player") or [])
    new = [t for t in taps if not (isinstance(t, dict) and t.get("watcher_npc_id") == watcher_npc_id)]
    if len(new) == len(taps):
        return False
    metadata["taps_on_player"] = new
    return True


def surveillance_detected(player_snapshot: dict | None, metadata: dict | None) -> bool:
    """True when the player's white mushi is active and at least one tap is on them: the case
    where the Director should alert the player."""
    return white_mushi_active(player_snapshot) and bool(taps_on_player(metadata))


# ---- Golden/Silver Den Den Mushi: Buster Call trigger ----------------------------------
def apply_buster_call(
    metadata: dict, *, target_island: str, ordered_by_npc_id: str | None, reason: str, turn_index: int
) -> dict:
    """Register an in-progress Buster Call (`metadata.buster_call_active`), a flag the Narrator
    renders and the world consumes. Returns a report with the suggested `chaos_delta`; chaos
    itself is applied by the Director's chaos channel, not duplicated here."""
    active = {
        "target_island": target_island or "",
        "ordered_by_npc_id": ordered_by_npc_id or "",
        "reason": reason or "",
        "triggered_at_turn_index": int(turn_index),
    }
    metadata["buster_call_active"] = active
    return {"applied": True, "active": active, "chaos_delta": BUSTER_CALL_CHAOS_DELTA}


def apply_vivre_card_state_change(snapshot: dict, change: dict | None) -> dict:
    """Apply `vivre_card_state_change` to the inventory: update the card's `visual_state`; on
    ashes, remove it (disintegrates, leaves the inventory). Only acts if the player holds that
    NPC's card. Returns a report of what changed."""
    out = {"applied": False, "removed": False, "npc_id": None, "new_visual_state": None}
    if not isinstance(change, dict):
        return out
    npc_id = change.get("npc_id")
    new_state = change.get("new_visual_state")
    if not npc_id or new_state not in VITAL_STATES:
        return out
    cards = list(snapshot.get("vivre_cards") or [])
    idx = next(
        (i for i, v in enumerate(cards) if isinstance(v, dict) and v.get("npc_id") == npc_id), None
    )
    if idx is None:
        return out
    out["npc_id"] = npc_id
    out["new_visual_state"] = new_state
    if new_state == "ashes":
        cards.pop(idx)
        out["removed"] = True
    else:
        cards[idx] = {**cards[idx], "visual_state": new_state}
    snapshot["vivre_cards"] = cards
    out["applied"] = True
    return out
