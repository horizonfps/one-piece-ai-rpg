"""Game clock: pure deterministic logic (no I/O).

Takes the current clock (or None) and returns the next one without persisting; the runner loads
and saves it. The Narrator and crystallizer never do age/date math; they always read the clock.
"""
from __future__ import annotations

import copy

DAYS_PER_YEAR = 365  # no leap years


def bootstrap_clock(initial_player_age: int, initial_arc: str | None = None) -> dict:
    """Initial clock. Day 1 is campaign_day 0; player_birth_day is negative age in days."""
    return {
        "campaign_day": 0,
        "current_player_age": initial_player_age,
        "current_arc": initial_arc,
        "active_characters_by_age": {"[JOGADOR]": initial_player_age},
        "player_birth_day": -initial_player_age * DAYS_PER_YEAR,
        "last_updated_at_turn_index": 0,
    }


def compute_next_clock(
    current_clock: dict | None,
    *,
    time_advancement: dict | None,
    set_arc: str | None,
    scene_npc_ages: dict[str, int],
    turn_index: int,
    initial_player_age: int | None = None,
) -> tuple[dict, list[str]]:
    """Compute the next clock without persisting. Does not mutate current_clock.

    time_advancement: {set_player_age} XOR {advance_days} (or None for no advance).
    scene_npc_ages: declared scene ages (declared wins over computed, with a warning).
    Returns (new_clock, warnings).
    """
    warnings: list[str] = []

    if current_clock is None:
        if initial_player_age is None:
            raise RuntimeError(
                "Clock não inicializado e initial_player_age não fornecido. "
                "Primeira cena precisa declarar a idade do jogador."
            )
        clock = bootstrap_clock(initial_player_age, set_arc)
    else:
        clock = copy.deepcopy(current_clock)

    ta = time_advancement or {}
    has_set_age = ta.get("set_player_age") is not None
    has_advance_days = ta.get("advance_days") is not None
    if has_set_age and has_advance_days:
        raise ValueError("time_advancement não pode ter set_player_age E advance_days juntos.")

    days_advanced = 0
    if has_set_age:
        new_age = int(ta["set_player_age"])
        delta_years = new_age - clock["current_player_age"]
        if delta_years < 0:
            raise ValueError(
                f"set_player_age={new_age} < current_player_age={clock['current_player_age']}. "
                "Tempo não anda pra trás."
            )
        days_advanced = delta_years * DAYS_PER_YEAR
    elif has_advance_days:
        days_advanced = int(ta["advance_days"])
        if days_advanced < 0:
            raise ValueError("advance_days não pode ser negativo.")

    if days_advanced > 0:
        clock["campaign_day"] += days_advanced
        delta_years = days_advanced // DAYS_PER_YEAR
        clock["current_player_age"] = (
            (clock["campaign_day"] - clock["player_birth_day"]) // DAYS_PER_YEAR
        )
        for npc_name in list(clock["active_characters_by_age"].keys()):
            if npc_name == "[JOGADOR]":
                clock["active_characters_by_age"][npc_name] = clock["current_player_age"]
            else:
                clock["active_characters_by_age"][npc_name] += delta_years

    for npc_name, declared_age in scene_npc_ages.items():
        existing = clock["active_characters_by_age"].get(npc_name)
        if existing is None:
            clock["active_characters_by_age"][npc_name] = declared_age
        elif existing != declared_age:
            warnings.append(
                f"NPC {npc_name}: idade declarada={declared_age} difere do calculado={existing}. "
                "Aplicando declarado."
            )
            clock["active_characters_by_age"][npc_name] = declared_age

    if set_arc is not None and set_arc != clock["current_arc"]:
        clock["current_arc"] = set_arc

    clock["last_updated_at_turn_index"] = turn_index
    return clock, warnings


def light_clock(clock: dict) -> dict:
    """Light version for the turn_state (without last_updated_at_turn_index)."""
    return {
        "campaign_day": clock["campaign_day"],
        "current_player_age": clock["current_player_age"],
        "current_arc": clock["current_arc"],
        "active_characters_by_age": dict(clock["active_characters_by_age"]),
        "player_birth_day": clock["player_birth_day"],
    }


def snapshot_of(clock: dict, turn_index: int) -> dict:
    return {
        "turn_index": turn_index,
        "campaign_day": clock["campaign_day"],
        "player_age": clock["current_player_age"],
        "arc": clock["current_arc"],
        "characters_by_age": dict(clock["active_characters_by_age"]),
    }
