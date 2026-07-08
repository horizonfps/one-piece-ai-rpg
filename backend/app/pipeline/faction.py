"""Faction reputation (FASE 19): pure functions (no I/O, no proxy, no DB).

Institutional standing of player/crew/NPC toward trackable factions (FACTION cards). Single
respect-vs-hostility axis, float [-2.0, +2.0], bucket ally/neutral/hostile. Sparse map: only a
faction with accumulated delta has an entry; absence is implicit neutral.

Pattern-twin of alignment (captain weight 3x) but float-guideline (no snap-to-enum) and
multi-faction over a sparse map.
"""
from __future__ import annotations

REPUTATION_MIN, REPUTATION_MAX = -2.0, 2.0
ALLY_THRESHOLD = 0.5
HOSTILE_THRESHOLD = -0.5
CAPTAIN_WEIGHT = 3.0

# Categorical tier to anchor magnitude. Used only in gate reconstruction; the real value is the
# Director's float-guideline, not derived here.
TIER_MAGNITUDE = {"small": 0.1, "medium": 0.3, "large": 0.7, "top": 1.5}

# Recruitment modifier per crossed-reputation bucket; consumed in the recruitment roll.
RECRUITMENT_MULTIPLIER = {"ally": 1.5, "neutral": 1.0, "hostile": 0.3}

# NPC declared affiliation to seed-card faction_id (when the affiliation is not itself the card id).
_AFFILIATION_TO_FACTION = {
    "marine": "marinha",
    "marines": "marinha",
    "marinha": "marinha",
    "marine_hq": "marinha",
    "navy": "marinha",
    "revolutionary": "revolution",
    "revolutionary_army": "revolution",
    "revolution": "revolution",
    "cipher_pol": "cipher_pol",
    "cp0": "cipher_pol",
    "world_government": "world_government",
    "wg": "world_government",
    "cross_guild": "cross_guild",
}


# --- scale / bucket ------------------------------------------------------------------
def clamp_reputation(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(REPUTATION_MIN, min(REPUTATION_MAX, round(v, 4)))


def reputation_bucket(value) -> str:
    v = clamp_reputation(value)
    if v >= ALLY_THRESHOLD:
        return "ally"
    if v <= HOSTILE_THRESHOLD:
        return "hostile"
    return "neutral"


# --- sparse reputation map -----------------------------------------------------------
def reputations_of(snapshot_or_card: dict | None) -> dict:
    """Read the sparse faction_reputations map (player_snapshot or NPC card). Always a dict of
    floats. Absent returns {} (all implicit neutral)."""
    reps = (snapshot_or_card or {}).get("faction_reputations")
    if not isinstance(reps, dict):
        return {}
    return {k: float(v) for k, v in reps.items() if isinstance(v, (int, float))}


def apply_reputation_delta(reps: dict | None, faction_id: str, value) -> dict:
    """Add value to the faction_id entry (creating if absent), clamp [-2,2]. Cumulative: standing
    emerges from the sum. Returns a new copy."""
    out = dict(reps or {})
    fid = (faction_id or "").strip()
    if not fid:
        return out
    try:
        delta = float(value or 0.0)
    except (TypeError, ValueError):
        return out
    out[fid] = clamp_reputation(out.get(fid, 0.0) + delta)
    return out


def compute_crew_reputations(player_reps: dict | None, member_reps: list[dict] | None) -> dict:
    """Derived crew.faction_reputations (captain weight 3, others 1), over every faction in any
    map. Sparse multi-faction. No members returns the captain's reputation. Recomputed on each
    read, not persisted."""
    member_maps = [m for m in (member_reps or []) if isinstance(m, dict)]
    player_reps = player_reps or {}
    faction_ids: set = set(player_reps)
    for m in member_maps:
        faction_ids.update(m)
    n = len(member_maps)
    denom = CAPTAIN_WEIGHT + n
    out: dict = {}
    for fid in faction_ids:
        weighted = CAPTAIN_WEIGHT * float(player_reps.get(fid, 0.0) or 0.0)
        weighted += sum(float(m.get(fid, 0.0) or 0.0) for m in member_maps)
        out[fid] = clamp_reputation(weighted / denom)
    return out


# --- NPC faction resolution + institutional_standing ---------------------------------
def resolve_npc_faction_id(npc: dict | None, faction_card_ids: set | None) -> str | None:
    """Trackable faction_id of the NPC, or None. Prefers an explicit card faction_id; else maps
    affiliation or uses an affiliation that already is a card id. Returns only if the id matches a
    present FACTION card."""
    ids = faction_card_ids or set()
    explicit = ((npc or {}).get("faction_id") or "").strip()
    if explicit and explicit in ids:
        return explicit
    aff = ((npc or {}).get("affiliation") or "").strip()
    if not aff:
        return None
    mapped = _AFFILIATION_TO_FACTION.get(aff.lower(), aff)
    return mapped if mapped in ids else None


def build_institutional_standing(
    npc: dict | None, crew_reputations: dict | None, faction_card_ids: set | None
) -> dict | None:
    """Agent institutional_standing: the NPC faction's stance toward the player crew. None when the
    NPC has no trackable faction (the addendum stays silent and the agent acts by the master)."""
    fid = resolve_npc_faction_id(npc, faction_card_ids)
    if not fid:
        return None
    value = clamp_reputation((crew_reputations or {}).get(fid, 0.0))
    return {
        "your_faction_id": fid,
        "player_crew_reputation": value,
        "bucket": reputation_bucket(value),
    }


# --- consumers -----------------------------------------------------------------------
def recruitment_multiplier(bucket: str) -> float:
    """Recruitment modifier per crossed-reputation bucket. Crosses with the acceptance sigmoid (no
    double-counting). NPC with no trackable faction returns x1.0."""
    return RECRUITMENT_MULTIPLIER.get(bucket, 1.0)


def reputation_summary(
    reps: dict | None, faction_cards: dict | None = None, *, include_neutral: bool = False
) -> list[dict]:
    """List of {faction_id, name, value, bucket} for the Narrator/inspector. By default only
    non-neutral factions; include_neutral=True lists all with an entry. Sorted by ascending value
    (most hostile first)."""
    cards = faction_cards or {}
    out: list[dict] = []
    for fid, v in (reps or {}).items():
        b = reputation_bucket(v)
        if not include_neutral and b == "neutral":
            continue
        out.append({
            "faction_id": fid,
            "name": (cards.get(fid) or {}).get("name", fid),
            "value": clamp_reputation(v),
            "bucket": b,
        })
    out.sort(key=lambda e: e["value"])
    return out
