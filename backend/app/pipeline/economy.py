"""Pure economy & inventory functions (FASE 17): player belly + inventory.

The Director emits a qualitative belly_delta (direction + tier) and inventory_events[] post-turn;
the engine samples a berry amount within the tier range and applies inventory mutations. No I/O,
no LLM (sample_belly_delta is deterministic given a random.Random).

Tier ranges/buckets are calibrated to the monetary scale of One Piece transactions, not the
bounty scale. Belly floor is 0.
"""
from __future__ import annotations

import random
import uuid

# --- belly ranges per tier (transaction monetary scale) ------------------------------
# Anchored to canon transaction magnitudes; tunable via playtesting.
BELLY_TIERS = ("small", "medium", "large", "massive", "absurd")
BELLY_TIER_RANGES: dict[str, tuple[int, int]] = {
    "small": (100, 50_000),
    "medium": (50_000, 1_000_000),
    "large": (1_000_000, 50_000_000),
    "massive": (50_000_000, 500_000_000),
    "absurd": (500_000_000, 10_000_000_000),
}

BELLY_DIRECTIONS = ("gain", "loss")
BELLY_SOURCES = ("action", "dialog", "meta")

# --- reading buckets derived from current belly (qualitative, no mechanical cap) ------
# Exclusive upper bounds; above the last = treasure. Player starts at 0.
BELLY_BUCKETS = ("broke", "surviving", "wealthy", "fortune", "treasure")
_BUCKET_THRESHOLDS: tuple[tuple[int, str], ...] = (
    (5_000, "broke"),
    (500_000, "surviving"),
    (30_000_000, "wealthy"),
    (1_000_000_000, "fortune"),
)


# --- belly: sample, bucket, apply ----------------------------------------------------
def belly_amount(snapshot: dict) -> int:
    """Read player_snapshot.belly as int (default 0; tolerates absence/garbage)."""
    try:
        return max(0, int(snapshot.get("belly", 0) or 0))
    except (TypeError, ValueError):
        return 0


def belly_bucket(belly: int) -> str:
    """Qualitative bucket of the current belly. No cap; a reading lens."""
    b = max(0, int(belly or 0))
    for threshold, bucket in _BUCKET_THRESHOLDS:
        if b < threshold:
            return bucket
    return "treasure"


def is_valid_belly_tier(tier) -> bool:
    return tier in BELLY_TIER_RANGES


def sample_belly_delta(tier: str, rng: random.Random | None = None) -> int:
    """Sample a uniform berry amount within the tier range. Invalid tier returns 0."""
    rng = rng or random
    lo, hi = BELLY_TIER_RANGES.get(tier, (0, 0))
    if hi <= 0:
        return 0
    return rng.randint(lo, hi)


def apply_belly_delta(
    belly: int, direction: str, tier: str, rng: random.Random | None = None
) -> tuple[int, int]:
    """Apply a belly_delta to the current belly. Returns (new_belly, signed_amount).

    gain adds, loss subtracts (floor 0). signed_amount is positive on gain, negative on loss.
    Invalid tier/direction is a no-op."""
    base = max(0, int(belly or 0))
    if not is_valid_belly_tier(tier) or direction not in BELLY_DIRECTIONS:
        return base, 0
    n = sample_belly_delta(tier, rng)
    if direction == "gain":
        return base + n, n
    new = max(0, base - n)
    return new, -(base - new)  # actual loss, bounded by what was there


def apply_exact_belly_delta(
    belly: int, direction: str, amount, tier: str | None = None, rng: random.Random | None = None
) -> tuple[int, int]:
    """Apply the Director-emitted EXACT berry amount (no engine dice roll). Falls back to a tier
    sampling only when no valid figure is emitted, so saves/omissions still work. Returns
    (new_belly, signed_amount); (belly, 0) if direction and the amount+tier fallback are unusable."""
    base = max(0, int(belly or 0))
    if direction not in BELLY_DIRECTIONS:
        return base, 0
    try:
        n = int(amount)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:  # no valid emitted figure -> fall back to the tier range
        if not is_valid_belly_tier(tier):
            return base, 0
        n = sample_belly_delta(tier, rng)
    if n <= 0:
        return base, 0
    if direction == "gain":
        return base + n, n
    new = max(0, base - n)
    return new, -(base - new)


# --- inventory -----------------------------------------------------------------------
INVENTORY_KINDS = ("acquired", "lost", "consumed", "given_away")


def make_inventory_entry(
    item_card_id: str,
    *,
    turn_index: int,
    origin_note: str = "",
    quantity: int | None = None,
) -> dict:
    """Build an inventory_entry. quantity is nullable: a stack carries the count, a unique item
    is null."""
    entry = {
        "item_card_id": item_card_id,
        "acquired_at_turn_index": int(turn_index),
        "origin_note": (origin_note or "").strip(),
    }
    if quantity is not None:
        try:
            entry["quantity"] = int(quantity)
        except (TypeError, ValueError):
            pass
    return entry


def build_player_item_card(
    name: str,
    *,
    subtype: str = "",
    summary: str = "",
    turn_index: int = 0,
    item_card_id: str | None = None,
) -> dict:
    """Minimal ITEM StoryCard for a human-added inventory item. Mirrors the generator shape so the
    economy panel and Narrator read it uniformly. common knowledge tiers = openly known."""
    summary = (summary or "").strip()
    return {
        "id": item_card_id or uuid.uuid4().hex,
        "type": "ITEM",
        "canonical": "generated",
        "name": name.strip(),
        "subtype": (subtype or "").strip() or "misc",
        "aliases": [],
        "description": summary,
        "current_state": {"summary_text": summary, "flags": []},
        "state_history": [],
        "related_card_ids": [],
        "knowledge_tier_to_know_exists": "common",
        "knowledge_tier_to_know_details": "common",
        "created_at_turn_index": int(turn_index),
        "last_updated_turn_index": int(turn_index),
    }


def _find_entry(inventory: list[dict], item_card_id: str) -> dict | None:
    for e in inventory:
        if isinstance(e, dict) and e.get("item_card_id") == item_card_id:
            return e
    return None


def apply_inventory_event(
    inventory: list[dict], event: dict, *, turn_index: int
) -> tuple[list[dict], dict | None]:
    """Apply an inventory_event to the inventory (new copy). Returns (new_inventory, applied|None).
    acquired creates/increments an entry; lost/given_away/consumed decrement a stack or remove a
    unique item. The existence gate is the caller's job. Malformed event is a no-op."""
    kind = event.get("kind") if isinstance(event, dict) else None
    item_id = (event.get("item_card_id") or "").strip() if isinstance(event, dict) else ""
    if kind not in INVENTORY_KINDS or not item_id:
        return list(inventory), None

    inv = [dict(e) for e in inventory if isinstance(e, dict)]
    qty = event.get("quantity")
    qty = int(qty) if isinstance(qty, int) else None
    existing = _find_entry(inv, item_id)

    if kind == "acquired":
        if existing is not None and qty is not None and "quantity" in existing:
            existing["quantity"] = int(existing.get("quantity", 0)) + abs(qty)
            applied = {"kind": kind, "item_card_id": item_id, "quantity": existing["quantity"]}
        elif existing is not None:
            # Unique item already held (re-acquisition): idempotent no-op.
            applied = {"kind": kind, "item_card_id": item_id, "noop": "já no inventário"}
        else:
            inv.append(make_inventory_entry(
                item_id, turn_index=turn_index,
                origin_note=event.get("reason", ""),
                quantity=(abs(qty) if qty is not None else None),
            ))
            applied = {"kind": kind, "item_card_id": item_id, "quantity": qty}
        return inv, applied

    # lost / consumed / given_away: removal
    if existing is None:
        return inv, {"kind": kind, "item_card_id": item_id, "noop": "não estava no inventário"}

    if qty is not None and "quantity" in existing:
        remaining = int(existing.get("quantity", 0)) - abs(qty)
        if remaining > 0:
            existing["quantity"] = remaining
            return inv, {"kind": kind, "item_card_id": item_id, "quantity": remaining}
    # unique item or emptied stack: remove the whole entry
    inv = [e for e in inv if e.get("item_card_id") != item_id]
    return inv, {"kind": kind, "item_card_id": item_id, "removed": True}


ITEM_POSSESSION_STATES = ("held_by_player", "lost", "consumed", "given_away")


def apply_item_possession(card_data: dict, state: str, *, turn_index: int) -> dict:
    """Record the possession fate on the ITEM card (new copy): current_state.possession + flag,
    mirroring ship.apply_disposition. Off-enum state is a no-op."""
    data = dict(card_data)
    if state not in ITEM_POSSESSION_STATES:
        return data
    cs = dict(data.get("current_state") or {})
    cs["possession"] = {"state": state, "turn_index": int(turn_index)}
    flags = [
        f for f in (cs.get("flags") or [])
        if isinstance(f, str) and f not in ITEM_POSSESSION_STATES
    ]
    if state != "held_by_player":
        flags.append(state)
    cs["flags"] = flags
    data["current_state"] = cs
    return data


def inventory_ids(inventory: list[dict]) -> set[str]:
    """Set of item_card_id present in the inventory (gate for lost/consumed/given_away)."""
    return {
        e["item_card_id"] for e in inventory
        if isinstance(e, dict) and e.get("item_card_id")
    }


def inventory_summary(inventory: list[dict], cards_by_id: dict[str, dict] | None = None) -> str:
    """Short inventory summary for the briefing/turn_state: card name + stack quantity. Unlimited
    inventory, compact list. Empty returns ''."""
    cards_by_id = cards_by_id or {}
    parts: list[str] = []
    for e in inventory:
        if not isinstance(e, dict) or not e.get("item_card_id"):
            continue
        cid = e["item_card_id"]
        card = cards_by_id.get(cid) or {}
        name = card.get("name") or cid
        qty = e.get("quantity")
        parts.append(f"{name} (x{qty})" if isinstance(qty, int) else str(name))
    return "; ".join(parts)
