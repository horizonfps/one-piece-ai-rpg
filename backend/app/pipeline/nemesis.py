"""Single evolving nemesis Marine (FASE 15.3).

The Director decides WHEN the Marine dispatches the nemesis (POST-turn nemesis_spawn) and drives
its trajectory (evolution, posture, fall) via nemesis_update; the engine only wires the life cycle
and applies the emitted milestone. Reuses the NPC Generator (role=nemesis_marine).

State lives in metadata.nemesis (JSON escape-hatch). Rank is narrative; the mechanical tier lives
on the card. A rank-up crossing a tier floor bumps the card tier (monotonic, never down).
"""
from __future__ import annotations

from ..db import repositories as repo
from . import npc_generator

TIER_ORDER = ("NORMAL", "SKILLED", "STRONG", "ELITE", "MONSTER", "TITAN", "WORLD", "ABSURD")

# Narrative rank to mechanical tier floor (crossing rank crosses tier).
RANK_LADDER = ("Capitão", "Comodoro", "Vice-Almirante", "Almirante", "Almirante de Frota")
_RANK_TIER_FLOOR = {
    "Capitão": "STRONG",
    "Comodoro": "ELITE",
    "Vice-Almirante": "MONSTER",
    "Almirante": "TITAN",
    "Almirante de Frota": "WORLD",
}

# Moral codes the generator may emit for a Marine card (validated on spawn).
_VALID_MORAL_CODES = ("absolute", "humane", "personal", "unclear", "lazy", "corrupt")

# Nemesis posture toward the player (Director's posture_shift channel). Default hostile on spawn.
POSTURES = ("hostile", "rival_respectful", "ally_leaning")


# --- tier/rank helpers ---------------------------------------------------------------
def _tier_index(tier: str) -> int:
    try:
        return TIER_ORDER.index(tier)
    except ValueError:
        return 0


def _max_tier(a: str, b: str) -> str:
    return a if _tier_index(a) >= _tier_index(b) else b


def _rank_floor_tier(rank: str) -> str:
    return _RANK_TIER_FLOOR.get(rank, "STRONG")


def _next_rank(rank: str) -> str:
    try:
        i = RANK_LADDER.index(rank)
    except ValueError:
        return RANK_LADDER[0]
    return RANK_LADDER[min(i + 1, len(RANK_LADDER) - 1)]


def _rank_coherent_with_tier(tier: str) -> str:
    """Fallback rank coherent with the generated tier (highest floor <= tier). Used only when the
    generator omitted a valid marine_rank."""
    chosen = RANK_LADDER[0]
    for rank in RANK_LADDER:
        if _tier_index(_rank_floor_tier(rank)) <= _tier_index(tier):
            chosen = rank
    return chosen


def build_nemesis_context(
    *, player_bounty: int, player_snapshot: dict, recent_act_summary: str
) -> dict:
    """nemesis_context contract for the npc_generator."""
    align = player_snapshot.get("alignment")
    if isinstance(align, dict):
        align_summary = f"{align.get('bucket', 'neutral')} ({align.get('value', 0.0)})"
    else:
        align_summary = "neutral (0.0)"
    return {
        "player_bounty": int(player_bounty or 0),
        "player_alignment_summary": align_summary,
        "player_recent_act_summary": (recent_act_summary or "ascensão recente do player")[:400],
    }


# --- apply the Director's milestone (engine executes only what the Director decided) --
_EVOLUTION_FACETS = ("rank_up", "power_growth", "new_lieutenant", "bigger_squad")
# defeated_on_scene only when the nemesis leaves play (tactical retreat is not an outcome).
_DEFEAT_OUTCOMES = ("captured", "dead", "missing")


def apply_nemesis_update(
    card: dict, nemesis_state: dict, update: dict, *, turn_index: int
) -> tuple[dict, dict, dict]:
    """Apply ONE trajectory milestone the Director emitted (parsed nemesis_update). Pure:
    returns (new_card, new_state, report). Never drops tier or rank.

    defeated_on_scene with outcome dead/missing sets the card status; run_nemesis archives it next."""
    new_card = dict(card)
    state = dict(nemesis_state)
    kind = update.get("change_kind")
    report: dict = {"change_kind": kind}

    if kind == "evolved":
        facet = update.get("evolution_facet")
        report["on_scene"] = update.get("on_scene")
        if facet == "rank_up":
            old_rank = state.get("rank") or _rank_coherent_with_tier(new_card.get("tier", "STRONG"))
            old_idx = RANK_LADDER.index(old_rank) if old_rank in RANK_LADDER else 0
            emitted = (update.get("new_rank") or "").strip()
            # honor the Director's rank; enforce monotonicity (never below the current rank)
            if emitted in RANK_LADDER and RANK_LADDER.index(emitted) >= old_idx:
                new_rank = emitted
            else:
                new_rank = _next_rank(old_rank)
            state["rank"] = new_rank
            new_card["marine_rank"] = new_rank
            report["new_rank"] = new_rank
            bumped = _max_tier(new_card.get("tier", "STRONG"), _rank_floor_tier(new_rank))
            if bumped != new_card.get("tier"):
                report["new_tier"] = bumped
                new_card["tier"] = bumped
                cs = dict(new_card.get("current_state") or {})
                cs["tier"] = bumped
                new_card["current_state"] = cs
        elif facet == "power_growth":
            powers = list(new_card.get("acquired_powers") or [])
            powers.append({"turn_index": turn_index, "note": (update.get("rationale") or "")[:240]})
            new_card["acquired_powers"] = powers
            report["facet"] = "power_growth"
        elif facet == "new_lieutenant":
            new_card["has_named_lieutenant"] = True
            report["facet"] = "new_lieutenant"
        elif facet == "bigger_squad":
            new_card["squad_size"] = int(new_card.get("squad_size") or 1) + 1
            report["squad_size"] = new_card["squad_size"]
        state["evolution_count"] = int(state.get("evolution_count") or 0) + 1
        state["last_evolution_turn"] = turn_index

    elif kind == "posture_shift":
        posture = update.get("new_posture")
        if posture in POSTURES:
            state["posture"] = posture
            new_card["nemesis_posture"] = posture
            report["new_posture"] = posture

    elif kind == "defeated_on_scene":
        # Nemesis left play this scene (captured/dead/missing). Tactical retreat is `clash`.
        outcome = update.get("outcome")
        report["outcome"] = outcome
        if outcome in ("captured", "dead", "missing"):
            new_card["status"] = outcome
            new_card["last_defeat"] = {"turn_index": turn_index, "outcome": outcome}

    elif kind == "clash":
        # Encounter without a fall; logged below, no state mutation.
        report["clash"] = True

    history = list(new_card.get("evolution_log") or [])
    history.append({"turn_index": turn_index, **report})
    new_card["evolution_log"] = history
    return new_card, state, report


# --- Parallel nemesis (FASE 20): promoted hunter with its own evolutionary trajectory --
# Reuses the nemesis Marine model, decoupled from confrontation (grows off-scene). Differs in two
# ways: state lives on the hunter's own card (N instances), and there is no Marine rank; the scale
# jump is the `escalada` facet, bumping one tier step. Permadeath leaves no substitute.
PARALLEL_EVOLUTION_FACETS = ("power_growth", "new_lieutenant", "bigger_squad", "escalada")


def _next_tier(tier: str) -> str:
    """Bump one step on the global tier scale (monotonic, saturates at ABSURD)."""
    return TIER_ORDER[min(_tier_index(tier) + 1, len(TIER_ORDER) - 1)]


def apply_parallel_nemesis_update(
    card: dict, update: dict, *, turn_index: int
) -> tuple[dict, dict]:
    """Apply ONE trajectory milestone the Director emitted for a parallel-nemesis hunter
    (parallel_nemesis_updates[]). Pure: returns (new_card, report). Mirrors apply_nemesis_update
    but all state lives on the card and there is no Marine rank (the scale jump is `escalada`).
    Decoupled from confrontation: evolved with on_scene=False grows off-scene. defeated_on_scene
    dead/missing sets the status; the runner archives it."""
    new_card = dict(card)
    kind = update.get("change_kind")
    report: dict = {"change_kind": kind, "hunter_npc_id": new_card.get("id")}

    if kind == "evolved":
        facet = update.get("evolution_facet")
        report["on_scene"] = update.get("on_scene")
        report["facet"] = facet
        if facet == "escalada":
            bumped = _next_tier(new_card.get("tier", "STRONG"))
            new_card["tier"] = bumped
            cs = dict(new_card.get("current_state") or {})
            cs["tier"] = bumped
            new_card["current_state"] = cs
            report["new_tier"] = bumped
        elif facet == "power_growth":
            powers = list(new_card.get("acquired_powers") or [])
            powers.append({"turn_index": turn_index, "note": (update.get("rationale") or "")[:240]})
            new_card["acquired_powers"] = powers
        elif facet == "new_lieutenant":
            new_card["has_named_lieutenant"] = True
        elif facet == "bigger_squad":
            new_card["squad_size"] = int(new_card.get("squad_size") or 1) + 1
            report["squad_size"] = new_card["squad_size"]
        new_card["nemesis_paralelo_evolution_count"] = (
            int(new_card.get("nemesis_paralelo_evolution_count") or 0) + 1
        )
        new_card["last_evolution_turn"] = turn_index

    elif kind == "posture_shift":
        posture = update.get("new_posture")
        if posture in POSTURES:
            new_card["nemesis_posture"] = posture
            report["new_posture"] = posture

    elif kind == "defeated_on_scene":
        outcome = update.get("outcome")
        report["outcome"] = outcome
        if outcome in ("captured", "dead", "missing"):
            new_card["status"] = outcome
            new_card["last_defeat"] = {"turn_index": turn_index, "outcome": outcome}

    elif kind == "clash":
        report["clash"] = True

    history = list(new_card.get("evolution_log") or [])
    history.append({"turn_index": turn_index, **report})
    new_card["evolution_log"] = history
    return new_card, report


# --- life cycle (orchestration with I/O) ---------------------------------------------
async def run_nemesis(
    conn,
    campaign_id: str,
    *,
    metadata: dict,
    player_bounty: int,
    scene: dict,
    day: int,
    turn_index: int,
    recent_act_summary: str,
    player_snapshot: dict,
    arc_context: dict,
    director_update: dict | None = None,
    spawn_decision: dict | None = None,
) -> tuple[dict, dict]:
    """Run the spawn (Director's nemesis_spawn) + apply the Director's trajectory milestone +
    permadeath. Returns (nemesis_state, report). Does NOT persist metadata; the caller writes
    metadata.nemesis once.

    director_update is the parsed POST-turn nemesis_update; spawn_decision is the parsed
    nemesis_spawn (both None on most turns)."""
    state = dict(metadata.get("nemesis") or {})
    report: dict = {}

    current_id = state.get("current_nemesis_id")
    agents_map = await repo.get_npc_agents(conn, campaign_id) if current_id else {}

    # (1) Apply the Director's milestone before the permadeath check; defeated_on_scene
    # dead/missing sets the status that step (2) archives.
    if current_id and isinstance(director_update, dict):
        info = agents_map.get(current_id)
        if info is not None:
            card = info.get("data") or {}
            new_card, state, evo = apply_nemesis_update(card, state, director_update, turn_index=turn_index)
            await repo.update_story_card(conn, info["story_card_id"], new_card)
            agents_map[current_id]["data"] = new_card
            report["update"] = evo

    # (2) Permadeath: active nemesis with dead/missing status archives + opens the substitute gap.
    # Covers both defeated_on_scene above and external signals (off-scene resolver, edit).
    if current_id:
        info = agents_map.get(current_id)
        status = ((info or {}).get("data") or {}).get("status", "alive")
        if info is None or status in ("dead", "missing"):
            card = (info or {}).get("data") or {}
            state.setdefault("nemesis_history", []).append({
                "npc_id": current_id,
                "killed_at_day": day,
                "last_rank": state.get("rank", ""),
                "archetype": card.get("subtype", ""),
                "traits": list(card.get("traits") or []),
            })
            state["current_nemesis_id"] = None
            # Substitute pending: the Director decides WHEN the Marine reacts via nemesis_spawn.
            state["substitute_pending"] = True
            report["permadeath"] = {"npc_id": current_id, "substitute_pending": True}
            current_id = None

    # (3) Spawn: the Director decides WHEN via nemesis_spawn; the engine only executes it,
    # guarded so we never double-spawn while a nemesis is active.
    if spawn_decision and not state.get("current_nemesis_id"):
        spawned = await _spawn_nemesis(
            conn, campaign_id,
            state=state, player_bounty=player_bounty, player_snapshot=player_snapshot,
            recent_act_summary=recent_act_summary, arc_context=arc_context, scene=scene,
            turn_index=turn_index, previous_history=state.get("nemesis_history") or [],
            spawn_decision=spawn_decision,
        )
        if spawned:
            state = spawned["state"]
            report["spawned"] = {
                "npc_id": spawned["npc_id"], "name": spawned["name"],
                "tier": spawned["tier"], "rank": state.get("rank"),
                "is_substitute": spawned["is_substitute"],
            }
            state["substitute_pending"] = False
        else:
            report["spawn_failed"] = True

    return state, report


async def _spawn_nemesis(
    conn,
    campaign_id: str,
    *,
    state: dict,
    player_bounty: int,
    player_snapshot: dict,
    recent_act_summary: str,
    arc_context: dict,
    scene: dict,
    turn_index: int,
    previous_history: list,
    spawn_decision: dict | None = None,
) -> dict | None:
    """Generate + persist the nemesis via npc_generator (role=nemesis_marine). A substitute may
    know the predecessor (revenge hook) when there is history. Mutates state in-place."""
    is_substitute = bool(previous_history)
    ctx = build_nemesis_context(
        player_bounty=player_bounty, player_snapshot=player_snapshot, recent_act_summary=recent_act_summary,
    )
    context_line = "Marine designado para caçar o player após a ascensão recente do bounty."
    if is_substitute:
        prev = previous_history[-1]
        context_line = (
            "Marine designado como sucessor após a queda do nemesis anterior — pode ser "
            f"conhecido dele (vingança como gancho). Predecessor: archetype {prev.get('archetype', '?')}."
        )
    entry = {
        "name": None,
        "role": "nemesis_marine",
        "context": context_line,
    }
    npc_input = npc_generator.build_npc_input(
        entry,
        arc_context=arc_context,
        affiliation_hint="marine",
        expected_recurrence="high",
        nemesis_context=ctx,
    )
    # No cast-dedup block here on purpose: the nemesis identity is fixed engine-side, spawned once.
    parsed = await npc_generator.call_generate_npc(npc_input)
    if not parsed:
        return None
    merged = npc_generator.merge_card_agent(parsed["card"], parsed["agent"], turn_index=turn_index)
    # Nemesis identity fixed by the engine.
    merged["affiliation"] = "marine"
    if merged.get("narrative_armor") not in ("nemesis_armor", "canon_top_armor"):
        merged["narrative_armor"] = "nemesis_armor"
    merged["role"] = "nemesis_marine"
    origin = (spawn_decision.get("origin_location") if isinstance(spawn_decision, dict) else None) or ""
    merged["current_location"] = merged.get("current_location") or origin.strip() or scene.get("location", "")
    # Honor the generator's emitted moral_code / marine_rank; fall back only if absent/invalid.
    emitted_code = (merged.get("moral_code") or "").strip()
    moral_code = emitted_code if emitted_code in _VALID_MORAL_CODES else "personal"
    merged["moral_code"] = moral_code  # emitted by the generator, fixed at creation
    emitted_posture = (spawn_decision.get("initial_posture") if isinstance(spawn_decision, dict) else None) or ""
    posture = emitted_posture if emitted_posture in POSTURES else "hostile"
    merged["nemesis_posture"] = posture  # Director's spawn posture; fallback hostile
    emitted_rank = (merged.get("marine_rank") or "").strip()
    rank = emitted_rank if emitted_rank in RANK_LADDER else _rank_coherent_with_tier(merged.get("tier", "STRONG"))
    merged["marine_rank"] = rank

    scid = await repo.add_story_card(conn, campaign_id, "npc_agent", merged)
    state["current_nemesis_id"] = merged.get("id")
    state["rank"] = rank
    state["moral_code"] = moral_code
    state["posture"] = merged["nemesis_posture"]
    state["evolution_count"] = int(state.get("evolution_count") or 0)
    return {
        "story_card_id": scid,
        "npc_id": merged.get("id"),
        "name": merged.get("name"),
        "tier": merged.get("tier"),
        "is_substitute": is_substitute,
        "state": state,
    }
