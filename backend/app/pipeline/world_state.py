"""Pure world-state functions: clamp, bucket, snap-to-enum, crew_alignment, bounty sampling,
chaos decay.

No I/O, no global state: independently testable. The post-turn executor and repositories call
these; they never touch the DB.
"""
from __future__ import annotations

import random

# --- magnitude enums -----------------------------------------------------------------
ALIGNMENT_VALUES = (-1.5, -1.0, -0.5, -0.2, 0.2, 0.5, 1.0, 1.5)
CHAOS_VALUES = (-0.5, -0.3, -0.15, -0.05, 0.05, 0.15, 0.3, 0.5)
CREW_ALIGNMENT_VALUES = ALIGNMENT_VALUES
BOUNTY_TIERS = ("small", "medium", "large", "massive", "absurd")

# --- bounty ranges per tier ----------------------------------------------------------
BOUNTY_TIER_RANGES: dict[str, tuple[int, int]] = {
    "small": (1_000_000, 10_000_000),
    "medium": (10_000_000, 50_000_000),
    "large": (50_000_000, 300_000_000),
    "massive": (300_000_000, 1_000_000_000),
    "absurd": (1_000_000_000, 6_000_000_000),
}

ALIGNMENT_MIN, ALIGNMENT_MAX = -2.0, 2.0
CHAOS_MIN, CHAOS_MAX = 0.0, 1.0


# --- alignment -----------------------------------------------------------------------
def clamp_alignment(value: float) -> float:
    return max(ALIGNMENT_MIN, min(ALIGNMENT_MAX, round(float(value), 4)))


def alignment_bucket(value: float) -> str:
    if value >= 0.5:
        return "good"
    if value <= -0.5:
        return "evil"
    return "neutral"


# --- chaos ---------------------------------------------------------------------------
def clamp_chaos(value: float) -> float:
    return max(CHAOS_MIN, min(CHAOS_MAX, round(float(value), 4)))


def chaos_bucket(value: float) -> str:
    if value < 0.25:
        return "calm"
    if value < 0.50:
        return "restless"
    if value < 0.75:
        return "volatile"
    return "apocalyptic"


# --- snap-to-enum (defense: snap a magnitude to the nearest valid bucket) ------------
def _snap(value: float, allowed: tuple[float, ...]) -> float:
    return min(allowed, key=lambda a: abs(a - float(value)))


def snap_alignment_delta(value: float) -> float:
    return _snap(value, ALIGNMENT_VALUES)


def snap_chaos_delta(value: float) -> float:
    return _snap(value, CHAOS_VALUES)


def is_valid_alignment_delta(value) -> bool:
    return isinstance(value, (int, float)) and any(abs(value - a) < 1e-6 for a in ALIGNMENT_VALUES)


def is_valid_chaos_delta(value) -> bool:
    return isinstance(value, (int, float)) and any(abs(value - a) < 1e-6 for a in CHAOS_VALUES)


# --- alignment / chaos state objects -------------------------------------------------
def make_alignment(value: float) -> dict:
    v = clamp_alignment(value)
    return {"value": v, "bucket": alignment_bucket(v)}


def make_chaos(value: float) -> dict:
    v = clamp_chaos(value)
    return {"value": v, "bucket": chaos_bucket(v)}


def apply_alignment_delta(current: dict | float | None, delta_value: float) -> dict:
    """Add the delta to the current alignment, with clamp and bucket recompute."""
    base = _coerce_value(current)
    return make_alignment(base + snap_alignment_delta(delta_value))


def apply_chaos_delta(current: dict | float | None, delta_value: float) -> dict:
    base = _coerce_value(current)
    return make_chaos(base + snap_chaos_delta(delta_value))


def _coerce_value(current: dict | float | None) -> float:
    """Read `.value` of a state object, a bare number, or 0.0."""
    if isinstance(current, dict):
        try:
            return float(current.get("value", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0
    if isinstance(current, (int, float)):
        return float(current)
    return 0.0


# --- crew_alignment (weighted mean, captain weighted 3x) -----------------------------
def compute_crew_alignment(player_value: float, member_values: list[float]) -> dict:
    """`(3*player + sum(members)) / (3 + n_members)`. No members means captain only."""
    members = [float(v) for v in member_values if isinstance(v, (int, float))]
    n = len(members)
    weighted = 3.0 * float(player_value) + sum(members)
    value = weighted / (3 + n)
    return make_alignment(value)


# --- bounty (narrative delay) --------------------------------------------------------
def sample_bounty_delta(tier: str, rng: random.Random | None = None) -> int:
    """Uniform random within the tier range. Invalid tier returns 0."""
    rng = rng or random
    lo, hi = BOUNTY_TIER_RANGES.get(tier, (0, 0))
    if hi <= 0:
        return 0
    return rng.randint(lo, hi)


def coerce_bounty_amount(emitted, tier: str, rng: random.Random | None = None) -> int:
    """Honor the Director-emitted EXACT bounty figure, clamped to the tier's range. A missing or
    invalid figure falls back to a tier sampling (saves/omissions still work). Invalid tier -> 0."""
    lo, hi = BOUNTY_TIER_RANGES.get(tier, (0, 0))
    if hi <= 0:
        return 0
    try:
        v = int(emitted)
    except (TypeError, ValueError):
        v = 0
    if v <= 0:
        return sample_bounty_delta(tier, rng)
    return max(lo, min(hi, v))


def round_bounty(amount: int) -> int:
    """Round to 2 significant figures (half-up): canon-looking bounty numbers, not raw randint
    output. Half-up over banker's rounding so a gain on a .5 boundary moves the poster up."""
    amount = int(amount)
    if amount <= 0:
        return 0
    step = 10 ** max(0, len(str(amount)) - 2)
    return int((amount + step // 2) // step * step)


def tier_for_amount(amount: int) -> str:
    """Coarsest tier whose floor the amount clears (a consolidated jump may outgrow its parts)."""
    amount = int(amount)
    for tier in reversed(BOUNTY_TIERS):
        if amount >= BOUNTY_TIER_RANGES[tier][0]:
            return tier
    return "small"


def scheduled_day_from_delay(current_day: int, delay_days=None, rng: random.Random | None = None) -> int:
    """Publish day = current_day + delay. delay_days is the Director's call (how long the news takes
    to circulate to the player's position); None/invalid falls back to a 1-3 day sortition."""
    if isinstance(delay_days, int) and not isinstance(delay_days, bool) and delay_days >= 0:
        return int(current_day) + delay_days
    rng = rng or random
    return int(current_day) + rng.randint(1, 3)
