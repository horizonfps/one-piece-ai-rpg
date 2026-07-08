"""Crew system, pure functions (no I/O, proxy, or DB).

Membership and dissatisfaction. Recruitment is the Narrator's call (turn_meta.recruitment_
resolutions); the engine only applies join/leave and re-recruitment gating. Dissatisfaction
accumulates via the Director channel with passive decay here. Membership markers live in the
NPC card's data_json (affiliation: player_crew).
"""
from __future__ import annotations

from . import language
from . import world_state

# --- affiliation / membership --------------------------------------------------------
CREW_AFFILIATION = "player_crew"
EX_CREW_AFFILIATION = "ex_player_crew"
DEFAULT_PLAYER_ID = "player"

# Crew soft cap: above this, the entity signals a fleet/alliance.
SOFT_CAP = 10

# --- dissatisfaction -----------------------------------------------------------------
DISSATISFACTION_MIN, DISSATISFACTION_MAX = 0.0, 1.0

_ARCHIVED_STATUSES = ("dead", "missing")


# =====================================================================================
# Numeric coercion (mirrors world_state._coerce_value: reads .value of a state object)
# =====================================================================================
def _coerce(value) -> float:
    if isinstance(value, dict):
        try:
            return float(value.get("value", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


# =====================================================================================
# NPC alignment / bond accessors (used by membership + roster summary)
# =====================================================================================
def npc_alignment_value(npc: dict) -> float:
    """NPC alignment (from `alignment_baseline`)."""
    return _coerce((npc or {}).get("alignment_baseline", (npc or {}).get("alignment", 0.0)))


def bond_with_player(npc: dict, player_id: str = DEFAULT_PLAYER_ID) -> tuple[int, float]:
    """`(bond_tier, affinity)` of the NPC->player relationship (0/0.0 if absent)."""
    rel = ((npc or {}).get("relationships") or {}).get(player_id) or {}
    return int(rel.get("bond_tier", 0) or 0), float(rel.get("affinity", 0.0) or 0.0)


# =====================================================================================
# Membership: roster, soft cap, join/leave, re-recruit gate
# =====================================================================================
def is_member(npc: dict) -> bool:
    return ((npc or {}).get("affiliation") or "") == CREW_AFFILIATION


def crew_roster(npcs: dict) -> list[dict]:
    """Active members of the player's crew."""
    return [d for d in (npcs or {}).values() if is_member(d)]


def crew_size(npcs: dict) -> int:
    return len(crew_roster(npcs))


def is_fleet_tier(size: int) -> bool:
    """Past the soft cap, the entity becomes a fleet/alliance."""
    return int(size or 0) > SOFT_CAP


def member_alignment_values(npcs: dict) -> list[float]:
    """Member alignments, for recomputing crew_alignment."""
    return [npc_alignment_value(d) for d in crew_roster(npcs)]


def recompute_crew_alignment(player_alignment, npcs: dict) -> dict:
    """`crew_alignment` (captain weighted 3x) from the current roster. State object."""
    return world_state.compute_crew_alignment(alignment_scalar(player_alignment), member_alignment_values(npcs))


def can_recruit(npc: dict, *, allow_reconcile: bool = False) -> tuple[bool, str]:
    """Can this NPC be recruited? Blocks already-member, dead/missing, and an ex-crewmate still
    awaiting reconciliation. `allow_reconcile=True` releases the awaiting ex-crewmate, used when
    the player's in-person re-invite is itself the reconciliation scene."""
    npc = npc or {}
    aff = npc.get("affiliation") or ""
    if aff == CREW_AFFILIATION:
        return False, "already_member"
    status = npc.get("status", "alive")
    if status in _ARCHIVED_STATUSES:
        return False, f"unavailable:{status}"
    if aff == EX_CREW_AFFILIATION and npc.get("awaiting_reconciliation") and not allow_reconcile:
        return False, "awaiting_reconciliation"
    return True, "ok"


def is_awaiting_reconciliation(npc: dict) -> bool:
    """Ex-crewmate who left and has not reconciled (blocked from normal re-recruitment)."""
    npc = npc or {}
    return (npc.get("affiliation") or "") == EX_CREW_AFFILIATION and bool(npc.get("awaiting_reconciliation"))


_MEMBER_SUMMARY_PREFIX = "Tripulante do bando do jogador"
_EX_MEMBER_SUMMARY_PREFIX = "Ex-tripulante do bando do jogador"
_HISTORY_MARKER = "Antes: "


def _rewrite_summary(out: dict, new_summary: str, previous: str) -> None:
    """Rewrite `current_state.summary_text` (fresh copy of current_state). The previous summary
    becomes historical context; if it was already a membership summary generated here, keep only
    the history it carried instead of nesting."""
    cs = dict(out.get("current_state") or {})
    prev = (previous or "").strip()
    if prev.startswith((_MEMBER_SUMMARY_PREFIX, _EX_MEMBER_SUMMARY_PREFIX)):
        i = prev.find(_HISTORY_MARKER)
        prev = prev[i:] if i >= 0 else ""
    elif prev:
        prev = f"{_HISTORY_MARKER}{prev}"
    cs["summary_text"] = f"{new_summary} {prev}".strip() if prev else new_summary
    out["current_state"] = cs


def add_member(npc: dict, *, turn_index: int, role: str = "crewmate", specialty: str | None = None) -> dict:
    """Promote the NPC to member. Clears ex-member flags and rewrites `summary_text` to assert
    current membership (a stale summary would contradict the affiliation in every agent prompt).
    Fresh copy."""
    out = dict(npc or {})
    prev_summary = ((npc or {}).get("current_state") or {}).get("summary_text", "")
    out["affiliation"] = CREW_AFFILIATION
    out["joined_crew_at_turn_index"] = turn_index
    out["crew_role"] = role
    if specialty and not out.get("specialty"):
        out["specialty"] = specialty
    out["dissatisfaction"] = clamp_dissatisfaction(out.get("dissatisfaction", 0.0))
    out.pop("left_crew_at_turn_index", None)
    out.pop("departure_reason", None)
    out.pop("awaiting_reconciliation", None)
    _rewrite_summary(out, f"{_MEMBER_SUMMARY_PREFIX} (desde o turn {turn_index}).", prev_summary)
    return out


def remove_member(npc: dict, *, turn_index: int, reason: str = "") -> dict:
    """Demote the member to ex-crewmate (blocks re-recruitment until reconciliation). Rewrites
    `summary_text` to assert the departure, preserving pre-membership history. Fresh copy."""
    out = dict(npc or {})
    prev_summary = ((npc or {}).get("current_state") or {}).get("summary_text", "")
    out["affiliation"] = EX_CREW_AFFILIATION
    out["left_crew_at_turn_index"] = turn_index
    out["departure_reason"] = reason or ""
    out["awaiting_reconciliation"] = True
    out.pop("crew_role", None)
    motivo = f": {reason}" if reason else ""
    _rewrite_summary(
        out, f"{_EX_MEMBER_SUMMARY_PREFIX} (saiu no turn {turn_index}{motivo}).", prev_summary
    )
    return out


def mark_reconciled(npc: dict) -> dict:
    """Clear the reconciliation gate so the ex-crewmate can return."""
    out = dict(npc or {})
    out["awaiting_reconciliation"] = False
    return out


# =====================================================================================
# Dissatisfaction: clamp / delta / decay / bucket
# =====================================================================================
def clamp_dissatisfaction(value) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(max(DISSATISFACTION_MIN, min(DISSATISFACTION_MAX, x)), 4)


def dissatisfaction_of(npc: dict) -> float:
    return clamp_dissatisfaction((npc or {}).get("dissatisfaction", 0.0))


def apply_dissatisfaction_delta(npc: dict, value) -> dict:
    """Add `value` (signed) to the member's dissatisfaction, clamp [0,1]. Fresh copy. Sign and
    magnitude come from the Director; the engine only accumulates and clamps."""
    out = dict(npc or {})
    out["dissatisfaction"] = clamp_dissatisfaction(dissatisfaction_of(npc) + _coerce(value))
    return out


def dissatisfaction_bucket(value) -> str:
    """Qualitative bucket for UI/Narrator (no gate threshold; departure is the Director's call)."""
    x = clamp_dissatisfaction(value)
    if x < 0.25:
        return "content"
    if x < 0.5:
        return "uneasy"
    if x < 0.75:
        return "frustrated"
    return "at_breaking_point"


# =====================================================================================
# Summary for turn_state (Narrator/Director) + UI
# =====================================================================================
def roster_summary(npcs: dict, *, player_id: str = DEFAULT_PLAYER_ID) -> list[dict]:
    """Light crew summary for turn_state and inspector: name, specialty, bond_tier, dissatisfaction
    (value + bucket), status."""
    out: list[dict] = []
    for d in crew_roster(npcs):
        bond_tier, _aff = bond_with_player(d, player_id)
        out.append({
            "id": d.get("id", ""),
            "name": d.get("name", ""),
            "specialty": d.get("specialty") or d.get("class") or "",
            "crew_role": d.get("crew_role", "crewmate"),
            "bond_tier": bond_tier,
            "alignment": round(npc_alignment_value(d), 4),
            "dissatisfaction": dissatisfaction_of(d),
            "dissatisfaction_bucket": dissatisfaction_bucket(dissatisfaction_of(d)),
            "status": d.get("status", "alive"),
        })
    return out


# =====================================================================================
# Director-classified intent selection (runtime guards on LLM output)
# =====================================================================================
def select_recruitment_target(intent, present_ids) -> str | None:
    """`target_npc_id` of a player invite, only if the target is present in the scene. Guards
    against a missing or hallucinated id. None otherwise."""
    tid = intent.get("target_npc_id") if isinstance(intent, dict) else None
    return tid if tid and tid in (present_ids or set()) else None


def select_offer_response(response, pending_offers) -> tuple[str | None, str | None]:
    """`(kind, target_npc_id)` of a player's response to a pending offer, only if `kind` is
    accept/reject and the target is actually a pending offer. `(None, None)` otherwise."""
    if not isinstance(response, dict):
        return None, None
    kind = response.get("response")
    tid = response.get("target_npc_id")
    if kind in ("accept", "reject") and any(
        isinstance(o, dict) and o.get("npc_id") == tid for o in (pending_offers or [])
    ):
        return kind, tid
    return None, None


# =====================================================================================
# NPC->player offers (action_type invite_to_crew): pending queue in metadata.crew_offers
# =====================================================================================
def invites_from_agent_turns(turns) -> list[str]:
    """IDs of NPCs who asked to join the crew (action_type `invite_to_crew`). `turns`: iterable
    of `(agent_id, output)`."""
    out: list[str] = []
    for aid, output in turns:
        if aid and isinstance(output, dict) and output.get("action_type") == "invite_to_crew":
            out.append(aid)
    return out


def add_pending_offer(offers, npc_id: str, npc_name: str, *, turn_index: int) -> list[dict]:
    """Append an NPC->player offer (dedup by npc_id). Returns a new list."""
    out = [o for o in (offers or []) if isinstance(o, dict) and o.get("npc_id") != npc_id]
    out.append({"npc_id": npc_id, "npc_name": npc_name or "", "offered_at_turn_index": turn_index})
    return out


def remove_pending_offer(offers, npc_id: str) -> list[dict]:
    return [o for o in (offers or []) if isinstance(o, dict) and o.get("npc_id") != npc_id]


def prune_pending_offers(offers, npcs: dict) -> list[dict]:
    """Remove orphan offers: target gone, dead/missing, or already a member. Keeps the rest in
    order. Prevents zombie offers from piling up."""
    out: list[dict] = []
    for o in offers or []:
        if not (isinstance(o, dict) and o.get("npc_id")):
            continue
        npc = (npcs or {}).get(o["npc_id"])
        if npc is None:
            continue
        if npc.get("status", "alive") in _ARCHIVED_STATUSES:
            continue
        if is_member(npc):
            continue
        out.append(o)
    return out


def pending_offer_names(offers) -> list[str]:
    return [o.get("npc_name", "") for o in (offers or []) if isinstance(o, dict) and o.get("npc_name")]


def current_crew_alignment_value(metadata: dict | None, player_alignment) -> float:
    """Persisted `crew_alignment` value, falling back to the captain's alignment."""
    ca = (metadata or {}).get("crew_alignment")
    if isinstance(ca, dict) and "value" in ca:
        return _coerce(ca)
    return _coerce(player_alignment)


def alignment_scalar(value) -> float:
    """Alignment scalar (reads `.value` of a state object, a bare number, or 0.0)."""
    return _coerce(value)


# =====================================================================================
# Audit crystals (world_fact): recruitment / departure
# =====================================================================================
def recruit_audit_crystal(npc_name: str, *, location: str = "", accepted: bool = True) -> dict:
    if accepted:
        fact = language.engine_str(
            "crew_member_joined", name=npc_name or language.engine_str("fallback_new_companion")
        )
    else:
        fact = language.engine_str(
            "crew_invite_refused", name=npc_name or language.engine_str("fallback_someone")
        )
    return {
        "category": "world_fact", "fact": fact,
        "characters": [npc_name] if npc_name else [], "location": location or "", "participants": [],
    }


def departure_audit_crystal(npc_name: str, *, reason: str = "", location: str = "") -> dict:
    why = f" ({reason})" if reason else ""
    return {
        "category": "world_fact",
        "fact": language.engine_str(
            "crew_member_left",
            name=npc_name or language.engine_str("fallback_companion"),
            why=why,
        ),
        "characters": [npc_name] if npc_name else [], "location": location or "", "participants": [],
    }
