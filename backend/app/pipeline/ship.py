"""Pure ship & Jolly Roger functions (FASE 18): the crew fleet + hull state.

The Director emits hull_condition_change_events[] and ship_swap_events[] post-turn; the engine
applies them to the SHIP card and the crew fleet. State (JSON escape-hatch): SHIP card = a
story_cards row (data.type=SHIP); fleet + flag live in metadata.crew.

Invariant: once the crew has a SHIP card, exactly 1 fleet entry has role=active at any time. The
Jolly Roger is crew-level and follows the active ship on swaps. No I/O, no LLM.
"""
from __future__ import annotations

# --- enums ---------------------------------------------------------------------------
HULL_CONDITIONS = ("pristine", "scarred", "damaged", "broken")
SWAP_KINDS = ("acquired", "upgraded", "wrecked_replacement", "lost_and_recovered")
DISPOSITIONS = ("dismantled", "sunken", "sold", "abandoned", "given_away")

# Previous-ship dispositions that remove it from the fleet; abandoned and null go to reserve.
_DISPOSITION_REMOVES = frozenset({"sunken", "sold", "given_away", "dismantled"})


# --- fleet reads (metadata.crew) -----------------------------------------------------
def get_crew(metadata: dict) -> dict:
    """Read metadata.crew into a normalized {fleet, jolly_roger} shape (empty default). Tolerates
    absence/garbage."""
    crew = (metadata or {}).get("crew")
    if not isinstance(crew, dict):
        return {"fleet": [], "jolly_roger": None}
    return {
        "fleet": [e for e in (crew.get("fleet") or []) if isinstance(e, dict) and e.get("ship_card_id")],
        "jolly_roger": crew.get("jolly_roger"),
    }


def fleet_entries(crew: dict) -> list[dict]:
    return [e for e in (crew.get("fleet") or []) if isinstance(e, dict) and e.get("ship_card_id")]


def active_entry(crew: dict) -> dict | None:
    for e in fleet_entries(crew):
        if e.get("role") == "active":
            return e
    return None


def reserve_entries(crew: dict) -> list[dict]:
    return [e for e in fleet_entries(crew) if e.get("role") != "active"]


def active_ship_id(crew: dict) -> str | None:
    act = active_entry(crew)
    return act.get("ship_card_id") if act else None


def jolly_roger_text(crew: dict) -> str:
    """Declared Jolly Roger description (empty = bare mast)."""
    jr = crew.get("jolly_roger")
    if isinstance(jr, dict):
        return (jr.get("description") or "").strip()
    if isinstance(jr, str):
        return jr.strip()
    return ""


# --- SHIP card mutations -------------------------------------------------------------
def apply_hull_change(card_data: dict, new_condition: str) -> dict:
    """Apply a hull_condition_change_event to the SHIP card (new copy). new_condition off-enum is
    a no-op."""
    data = dict(card_data)
    if new_condition not in HULL_CONDITIONS:
        return data
    cs = dict(data.get("current_state") or {})
    cs["hull_condition"] = new_condition
    data["current_state"] = cs
    return data


def apply_disposition(card_data: dict, disposition: str | None) -> dict:
    """Record the previous ship's fate on the SHIP card (new copy): current_state.disposition +
    flag. sunken forces hull_condition=broken. Off-enum disposition is a no-op."""
    data = dict(card_data)
    if disposition not in DISPOSITIONS:
        return data
    cs = dict(data.get("current_state") or {})
    cs["disposition"] = disposition
    flags = [f for f in (cs.get("flags") or []) if isinstance(f, str)]
    if disposition not in flags:
        flags.append(disposition)
    cs["flags"] = flags
    if disposition == "sunken":
        cs["hull_condition"] = "broken"
    data["current_state"] = cs
    return data


# --- fleet mutation (ship swap) ------------------------------------------------------
def make_fleet_entry(ship_card_id: str, *, role: str, turn_index: int) -> dict:
    return {"ship_card_id": ship_card_id, "role": role, "acquired_at_turn_index": int(turn_index)}


def apply_swap(
    crew: dict,
    *,
    new_ship_card_id: str,
    previous_ship_card_id: str | None = None,
    previous_ship_disposition: str | None = None,
    swap_kind: str = "acquired",
    turn_index: int,
) -> tuple[dict, dict]:
    """Apply a ship swap to the fleet (new copy). Returns (new_crew, report).

    Enforces the exactly-1-active invariant: the new ship becomes active; the previous one goes to
    reserve (disposition null/abandoned) or leaves the fleet; any other active is demoted. The
    Jolly Roger is untouched (crew-level)."""
    fleet = [dict(e) for e in fleet_entries(crew)]
    report = {
        "swap_kind": swap_kind,
        "new_ship_card_id": new_ship_card_id,
        "previous_ship_card_id": previous_ship_card_id,
        "previous_ship_disposition": previous_ship_disposition,
        "previous_role": None,
    }

    # 1. Previous ship: leaves the fleet or becomes reserve.
    if previous_ship_card_id:
        if previous_ship_disposition in _DISPOSITION_REMOVES:
            fleet = [e for e in fleet if e.get("ship_card_id") != previous_ship_card_id]
            report["previous_role"] = "removed"
        else:
            for e in fleet:
                if e.get("ship_card_id") == previous_ship_card_id:
                    e["role"] = "reserve"
            report["previous_role"] = "reserve"

    # 2. Demote any remaining active that is not the new ship (1-active invariant).
    for e in fleet:
        if e.get("role") == "active" and e.get("ship_card_id") != new_ship_card_id:
            e["role"] = "reserve"

    # 3. Promote (or insert) the new ship as active.
    existing = next((e for e in fleet if e.get("ship_card_id") == new_ship_card_id), None)
    if existing is not None:
        existing["role"] = "active"
    else:
        fleet.append(make_fleet_entry(new_ship_card_id, role="active", turn_index=turn_index))

    return {"fleet": fleet, "jolly_roger": crew.get("jolly_roger")}, report


# --- fleet summary for the briefing --------------------------------------------------
def _ship_brief(entry: dict, ship_cards: dict) -> dict:
    cid = entry.get("ship_card_id")
    card = ship_cards.get(cid) or {}
    cs = card.get("current_state") or {}
    return {
        "ship_card_id": cid,
        "name": card.get("name", ""),
        "hull_condition": cs.get("hull_condition", ""),
        "subtype": card.get("subtype", ""),
    }


def fleet_summary(crew: dict, ship_cards: dict | None = None) -> dict:
    """Fleet summary for the Director briefing (crew_fleet contract): active ship + reserve count +
    reserve list + short Jolly Roger. ship_cards resolves name/hull."""
    ship_cards = ship_cards or {}
    act = active_entry(crew)
    reserve = reserve_entries(crew)
    return {
        "active": _ship_brief(act, ship_cards) if act else None,
        "reserve_count": len(reserve),
        "reserve": [_ship_brief(e, ship_cards) for e in reserve],
        "jolly_roger": jolly_roger_text(crew),
    }


def active_ship_brief(crew: dict, ship_cards: dict | None = None) -> dict | None:
    """Active ship brief for the Narrator turn_state. None if there is no ship."""
    act = active_entry(crew)
    return _ship_brief(act, ship_cards or {}) if act else None


# --- Jolly Roger ---------------------------------------------------------------------
def set_jolly_roger(crew: dict, description: str, *, turn_index: int) -> dict:
    """Declare/edit the Jolly Roger (new crew copy). An empty description clears the flag.
    Preserves the fleet."""
    desc = (description or "").strip()
    jr = {"description": desc, "declared_at_turn_index": int(turn_index)} if desc else None
    return {"fleet": fleet_entries(crew), "jolly_roger": jr}


# --- unsignaled-ship remediation -----------------------------------------------------
def _flag_is_true(value) -> bool:
    if value is True:
        return True
    return isinstance(value, str) and value.strip().lower().startswith("true")


def synthesize_unsignaled_ship_acquisitions(
    inspector_warnings: list[dict] | None, *, turn_index: int
) -> tuple[list[dict], list[dict]]:
    """Remediation for a ship the player took possession of in prose that the Narrator never
    flagged in ships_to_generate. Each unsignaled_ship warning carrying acquired_by_player becomes
    a synthetic (ship_generator job, ships_to_generate entry) pair, so the existing generate+swap
    path materializes the card and applies the swap. The engine coins the ship id; the Director
    forges none. Returns (jobs, entries) parallel-ordered for the runner's pairing."""
    jobs: list[dict] = []
    entries: list[dict] = []
    for w in inspector_warnings or []:
        if not isinstance(w, dict) or w.get("kind") != "unsignaled_ship":
            continue
        if not _flag_is_true(w.get("acquired_by_player")):
            continue
        name = (w.get("tentative_name") or "").strip()
        ref = name or f"unsignaled-ship-{len(jobs)}"
        hull = w.get("initial_hull_condition")
        context = (w.get("context") or "").strip()
        hint = (w.get("subtype_hint") or "").strip()
        if hint:
            context = f"{context}\nPorte/classe pela prosa: {hint}".strip()
        swap_kind = (w.get("swap_kind") or "").strip()
        if swap_kind not in SWAP_KINDS:
            swap_kind = "acquired"
        entries.append({
            "tentative_name": name or None,
            "name": name or None,
            "context": context,
            "ship_acquisition": (w.get("ship_acquisition") or "").strip() or None,
            "acquired_by_player": True,
            "initial_hull_condition": hull if hull in HULL_CONDITIONS else None,
        })
        jobs.append({
            "kind": "ship_generator",
            "input_ref": ref,
            "previous_ship_card_id": (w.get("previous_ship_card_id") or "").strip() or None,
            "previous_ship_disposition": (w.get("previous_ship_disposition") or "").strip() or None,
            "swap_kind": swap_kind,
        })
    return jobs, entries
