"""Timeskip: batch executor + cinematic recap (FASE 14.5/14.6).

Executor (Sonnet) returns per_agent[] retroactive logs + chaos-calibrated world_events[]. Recap
(Opus) is the return scene and counts as one turn. Triggered by a valid offer_training plus the
Director's timeskip_intent (accepted|requested). Post-skip tier-up is the Director's qualitative
call (player_tier_up); the engine only validates the range (clamp_tier_after: never tier-down,
cap +2, ceiling ABSURD).
"""
from __future__ import annotations

from .. import config
from ..db import repositories as repo
from ..proxy import client
from . import agent_state, fighting_style, game_clock, language

_EXECUTOR_PROMPT = "director_timeskip_executor_addendum.pt-br.md"
_RECAP_PROMPT = "director_timeskip_recap.pt-br.md"

_TIER_ORDER = ["NORMAL", "SKILLED", "STRONG", "ELITE", "MONSTER", "TITAN", "WORLD", "ABSURD"]
_AFFECTED_CAP = 16  # payload cost ceiling for the same-island fill (priority set never cut)

DAYS_PER_YEAR = game_clock.DAYS_PER_YEAR

# --------------------------------------------------------------------------------------
# Tool schemas
# --------------------------------------------------------------------------------------
EMIT_TIMESKIP_BATCH_TOOL = {
    "name": "emit_timeskip_batch",
    "description": (
        "Emite o batch retroativo do timeskip numa chamada UNICA, zero texto fora. "
        "Preencha `timeskip_pre_audit` PRIMEIRO (gate: copie literal do input e decida a "
        "eligibility de cada agente pelo status), depois `per_agent` (2-5 entries por agente "
        "free_life/confined; [] se no_new_events), depois `world_events` (calibrados pelo chaos)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "timeskip_pre_audit": {
                "type": "object",
                "description": "GATE obrigatorio — scratchpad. Engine ignora no runtime.",
                "properties": {
                    "duration_literal": {"type": "string"},
                    "chaos_bucket_literal": {"type": "string"},
                    "player_tier_literal": {"type": "string"},
                    "mentor_tier_literal": {"type": "string"},
                    "tier_up_decision": {
                        "type": "string",
                        "enum": ["plus_one", "plus_two", "stay_absurd"],
                    },
                    "agents_state_restatement": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "agent_id": {"type": "string"},
                                "tier_literal": {"type": "string"},
                                "status_literal": {"type": "string"},
                                "eligibility": {
                                    "type": "string",
                                    "enum": ["free_life", "confined", "no_new_events"],
                                },
                            },
                            "required": ["agent_id", "tier_literal", "status_literal", "eligibility"],
                        },
                    },
                },
                "required": [
                    "duration_literal", "chaos_bucket_literal",
                    "player_tier_literal", "mentor_tier_literal",
                    "tier_up_decision", "agents_state_restatement",
                ],
            },
            "player_tier_up": {
                "type": "object",
                "description": (
                    "Decisão QUALITATIVA do tier-up do player pós-skip. +1 default; +2 "
                    "raríssimo (mentor TITAN+ E duração longa E foco coerente); se o player "
                    "já é ABSURD, mantenha ABSURD. Nunca rebaixa, nunca pula mais de 2."
                ),
                "properties": {
                    "new_tier": {
                        "type": "string",
                        "enum": _TIER_ORDER,
                        "description": "Tier do player DEPOIS do skip (tier_current +1 ou +2).",
                    },
                    "reason": {
                        "type": "string",
                        "description": "1 frase factual: o que justifica o salto (duração + mentor + foco).",
                    },
                },
                "required": ["new_tier", "reason"],
            },
            "per_agent": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "agent_id": {"type": "string"},
                        "entries": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "action_summary": {"type": "string"},
                                    "when_hint": {"type": "string", "enum": ["inicio", "meio", "fim"]},
                                    "important": {"type": "boolean"},
                                },
                                "required": ["action_summary", "when_hint", "important"],
                            },
                        },
                    },
                    "required": ["agent_id", "entries"],
                },
            },
            "world_events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string"},
                        "scale": {"type": "string", "enum": ["minor", "regional", "major", "seismic"]},
                        "kind": {
                            "type": "string",
                            "enum": ["war", "promotion", "regime_change", "death", "rise", "news"],
                            "description": "Tipo do evento que voce escreveu: war|promotion|regime_change|death|rise|news.",
                        },
                        "when_hint": {"type": "string", "enum": ["inicio", "meio", "fim"]},
                    },
                    "required": ["summary", "scale", "kind", "when_hint"],
                },
            },
            "training_outcome": {
                "type": "string",
                "description": (
                    "1 frase factual do que o treino consolidou no player, base pro recap MOSTRAR "
                    "em acao (nunca cita tier). Sai mesmo quando o player ja esta no topo (consolidacao)."
                ),
            },
            "selected_agent_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Os agent_id do roster de entrada que o intervalo de fato afetou o bastante pra "
                    "merecer log retroativo. Voce escolhe QUAIS e QUANTOS; ignore quem seguiu vida "
                    "identica. per_agent[] cobre exatamente estes ids. Opcional; vazio = voce decide "
                    "so pelos per_agent."
                ),
            },
        },
        "required": ["timeskip_pre_audit", "player_tier_up", "per_agent", "world_events", "training_outcome"],
    },
}

EMIT_RECAP_TOOL = {
    "name": "emit_recap",
    "description": (
        "Emite a prosa do recap de timeskip. UMA chamada. A prosa segue TODAS as regras do "
        "director_timeskip_recap: 3 movimentos (treino -> mundo em paralelo -> chegada), "
        "~1200-1500 palavras, prosa pura PT-BR, sem JSON/markdown/heading/bullet/divisoria. "
        "Player NUNCA morre, mundo NUNCA encerra, tier-up se MANIFESTA em acao (nunca anunciado "
        "como stat), sem pergunta ao jogador, sem nota do narrador."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"prose": {"type": "string"}},
        "required": ["prose"],
    },
}


# --------------------------------------------------------------------------------------
# Trigger: skip params (pure). Player engagement is the Director's timeskip_intent call.
# --------------------------------------------------------------------------------------
def skip_params_from_offer(offer: dict | None) -> dict:
    """Build skip { duration, duration_days, focus, mentor_id } from the Director's vetted
    offer_training. duration_days is the Director's integer (advances the clock); duration is the
    free text for prose."""
    offer = offer or {}
    dd = offer.get("duration_days")
    return {
        "duration": offer.get("duration_hint") or "",
        "duration_days": int(dd) if isinstance(dd, (int, float)) and dd else None,
        "focus": offer.get("focus_hint") or "",
        "mentor_id": offer.get("mentor_npc_id"),
    }


def clamp_tier_after(tier_before: str, new_tier_emitted: str | None) -> str:
    """Range guardrail for the post-skip tier-up: the Director decides, the engine validates the
    range (never tier-down, cap +2, ceiling ABSURD). Keeping the same tier is a legitimate call.
    Missing/invalid emission falls back to +1."""
    if tier_before not in _TIER_ORDER:
        return tier_before
    idx = _TIER_ORDER.index(tier_before)
    if new_tier_emitted in _TIER_ORDER:
        emitted_idx = _TIER_ORDER.index(new_tier_emitted)
        target = min(max(emitted_idx, idx), idx + 2)  # never down; keep allowed; cap +2
        return _TIER_ORDER[min(target, len(_TIER_ORDER) - 1)]
    if idx >= len(_TIER_ORDER) - 1:
        return tier_before  # already ABSURD; no valid emission
    return _TIER_ORDER[idx + 1]  # fallback +1 when the Director emitted no valid tier


# --------------------------------------------------------------------------------------
# Affected-agent selection + executor input build
# --------------------------------------------------------------------------------------
def _relationship(data: dict, mentor_id: str | None) -> str:
    if mentor_id and data.get("id") == mentor_id:
        return "mentor"
    if data.get("affiliation") == "player_crew":
        return "crewmate"
    if data.get("narrative_armor") == "nemesis_armor":
        return "nemesis"
    return "conhecido"


def _recent_slice(data: dict, n: int = 2) -> list[str]:
    out: list[str] = []
    for e in reversed(data.get("personal_event_log") or []):
        if isinstance(e, dict) and (e.get("action_summary") or "").strip():
            out.append(e["action_summary"].strip())
            if len(out) >= n:
                break
    return list(reversed(out))


def _agent_entry(data: dict, mentor_id: str | None) -> dict:
    return {
        "id": data.get("id", ""),
        "tier": data.get("tier", ""),
        "status": data.get("status", "alive"),
        "affiliation": data.get("affiliation", ""),
        "narrative_armor": data.get("narrative_armor", "none"),
        "role_brief": (data.get("description") or data.get("current_goal") or "").strip(),
        "voice_notes": data.get("voice_notes", ""),
        "relationship_to_player": _relationship(data, mentor_id),
        "recent_log_slice": _recent_slice(data),
    }


def select_affected_agents(
    npcs: dict, *, mentor_id: str | None, scene_location: str, cost_cap: int = _AFFECTED_CAP
) -> list[dict]:
    """Candidate roster for the executor: mentor + crew + nemesis (always) + same-island NPCs. The
    executor decides who the interval actually moved (selected_agent_ids / per_agent entries vs
    no_new_events). cost_cap only bounds the same-island fill (payload ceiling); it never cuts the
    priority set. Dead/missing are included (the executor emits no_new_events)."""
    island = agent_state.island_of(scene_location)
    priority: list[dict] = []
    nearby: list[dict] = []
    seen: set = set()
    for aid, data in npcs.items():
        if aid in seen:
            continue
        rel = _relationship(data, mentor_id)
        if (mentor_id and aid == mentor_id) or rel in ("crewmate", "nemesis"):
            priority.append(data)
            seen.add(aid)
        elif island and agent_state.island_of(data.get("current_location", "")) == island:
            nearby.append(data)
    budget = max(0, cost_cap - len(priority))
    ordered = priority + nearby[:budget]
    return [_agent_entry(d, mentor_id) for d in ordered]


def _bounty_amount(player_snapshot: dict) -> int:
    b = player_snapshot.get("bounty", 0)
    return int(b.get("current_amount", 0) or 0) if isinstance(b, dict) else int(b or 0)


def build_executor_input(skip: dict, player_card: dict, chaos: dict, affected_agents: list[dict]) -> dict:
    pc = player_card.get("player_character") or {}
    ps = player_card.get("player_snapshot") or {}
    return {
        "skip": skip,
        "player_snapshot": {
            "name": pc.get("name", "") or player_card.get("name", ""),
            "tier_current": ps.get("tier") or pc.get("tier", ""),
            "bounty_current": _bounty_amount(ps),
        },
        "world": {"chaos_meter": chaos or {"value": 0.0, "bucket": "calm"}},
        "affected_agents": affected_agents,
    }


def parse_executor(emitted: dict | None) -> dict:
    """Normalize emit_timeskip_batch: drop the gate, coerce per_agent/world_events to dict lists,
    expose player_tier_up (dict or None; the engine validates the range later)."""
    emitted = emitted or {}
    per_agent = [a for a in (emitted.get("per_agent") or []) if isinstance(a, dict)]
    world_events = [w for w in (emitted.get("world_events") or []) if isinstance(w, dict)]
    tier_up = emitted.get("player_tier_up")
    tier_up = tier_up if isinstance(tier_up, dict) else None
    return {
        "per_agent": per_agent,
        "world_events": world_events,
        "player_tier_up": tier_up,
        "selected_agent_ids": [s for s in (emitted.get("selected_agent_ids") or []) if isinstance(s, str)],
        "training_outcome": (emitted.get("training_outcome") or "").strip(),
    }


async def call_executor(executor_input: dict, *, retries: int = 1) -> dict:
    """Run the batch executor (Sonnet, DIRECTOR_TEMPERATURE). Fallback = empty batch."""
    instructions = (config.PROMPTS_DIR / _EXECUTOR_PROMPT).read_text(encoding="utf-8")
    last_exc: Exception | None = None
    for _attempt in range(retries + 1):
        try:
            emitted = await client.call_tool(
                model=config.DIRECTOR_MODEL,
                instructions=instructions,
                tag="timeskip-executor",
                sections=[("TIMESKIP-EXECUTOR-INPUT", executor_input)],
                volatile_instructions=language.output_directive(),
                tool=EMIT_TIMESKIP_BATCH_TOOL,
                tool_name="emit_timeskip_batch",
                temperature=config.DIRECTOR_TEMPERATURE,
                max_tokens=5000,
                trace_label="Timeskip · executor",
            )
            return parse_executor(emitted)
        except Exception as e:  # noqa: BLE001  retry covers truncation/parse
            last_exc = e
    if last_exc is not None:
        raise last_exc
    return {"per_agent": [], "world_events": []}


# --------------------------------------------------------------------------------------
# Recap (Opus): input + call
# --------------------------------------------------------------------------------------
def _trait_names(player_card: dict) -> list[str]:
    cc = player_card.get("character_creation") or {}
    out: list[str] = []
    for t in cc.get("traits") or []:
        if isinstance(t, dict) and t.get("name"):
            out.append(t["name"])
        elif isinstance(t, str) and t.strip():
            out.append(t.strip())
    return out


def _signature_items(player_card: dict) -> list[str]:
    cc = player_card.get("character_creation") or {}
    pc = player_card.get("player_character") or {}
    items: list[str] = []
    weapon = cc.get("weapon") or pc.get("weapon")
    if weapon:
        items.append(str(weapon))
    df = cc.get("devil_fruit") or {}
    fruit = df.get("name_jp") or (player_card.get("player_snapshot") or {}).get("fruit") or pc.get("fruit")
    if fruit:
        items.append(str(fruit))
    return items


def build_recap_input(
    *,
    skip: dict,
    player_card: dict,
    tier_before: str,
    tier_after: str,
    fighting_style_before: str,
    power_growth: str,
    current_age: int,
    mentor: dict | None,
    crew_during_skip: list[dict],
    world_events: list[dict],
    scene: dict,
    chaos_bucket: str,
) -> dict:
    pc = player_card.get("player_character") or {}
    ps = player_card.get("player_snapshot") or {}
    df = (player_card.get("character_creation") or {}).get("devil_fruit") or {}
    fruit = df.get("name_jp") or ps.get("fruit") or pc.get("fruit")
    return {
        "skip": {
            "duration": skip.get("duration", ""),
            "focus": skip.get("focus", ""),
            "mentor_present": mentor is not None,
        },
        "player_character": {
            "name": pc.get("name", "") or player_card.get("name", ""),
            "tier_before": tier_before,
            "tier_after": tier_after,
            "fruit": fruit,
            "haki": ps.get("haki") or pc.get("haki", []),
            "fighting_style_before": fighting_style_before or "",
            "traits_active": _trait_names(player_card),
            "current_age": current_age,
            "signature_items": _signature_items(player_card),
            "power_growth": power_growth or "",
        },
        "mentor": mentor,
        "crew_during_skip": crew_during_skip,
        "world_during_skip": [
            {"summary": w.get("summary", ""), "kind": w.get("kind", "news")}
            for w in world_events if (w.get("summary") or "").strip()
        ],
        "arrival": {
            "location": scene.get("location", ""),
            "ambient": scene.get("ambient", ""),
            "scene_hook": scene.get("arrival_hook", ""),
        },
        "chaos_meter": chaos_bucket,
    }


async def call_recap(recap_input: dict, *, model: str | None = None, retries: int = 1) -> str:
    """Run the recap (Opus by default). Returns prose, or '' on failure. model lets the caller
    degrade to a cheaper model on a second pass instead of falling back to a template."""
    instructions = (config.PROMPTS_DIR / _RECAP_PROMPT).read_text(encoding="utf-8")
    last_exc: Exception | None = None
    for _attempt in range(retries + 1):
        try:
            emitted = await client.call_tool(
                model=model or config.NARRATOR_MODEL,
                instructions=instructions,
                tag="timeskip-recap",
                sections=[("TIMESKIP-RECAP-INPUT", recap_input)],
                volatile_instructions=language.output_directive(),
                tool=EMIT_RECAP_TOOL,
                tool_name="emit_recap",
                max_tokens=4500,
                trace_label="Timeskip · recap",
            )
            prose = (emitted.get("prose") or "").strip() if isinstance(emitted, dict) else ""
            if prose:
                return prose
        except Exception as e:  # noqa: BLE001  retry covers truncation/parse
            last_exc = e
    if last_exc is not None:
        raise last_exc
    return ""


# --------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------
async def apply_timeskip(
    conn,
    campaign_id: str,
    *,
    skip: dict,
    scene: dict,
    clock: dict | None,
    turn_index: int,
    npcs: dict,
) -> dict:
    """Run the full fast-forward and return {prose, report, final_clock}. Best-effort: each pass is
    shielded, so one failure does not drop the turn.

    Order: executor batch, retroactive logs, clock advance, tier-up + fighting_style, recap,
    timeskip_log. npcs is the already-loaded state snapshot.
    """
    report: dict = {"skip": skip}
    mentor_id = skip.get("mentor_id")
    scene_location = scene.get("location", "")

    # Fresh player + metadata (tick/post may have touched them).
    player_sc = await repo.get_player_story_card(conn, campaign_id)
    player_card = player_sc["data"] if player_sc else {}
    ps = player_card.get("player_snapshot") or {}
    tier_before = ps.get("tier") or (player_card.get("player_character") or {}).get("tier", "")
    old_fighting_style = (ps.get("fighting_style") or {}).get("summary", "") if isinstance(ps.get("fighting_style"), dict) else ""

    campaign = await repo.get_campaign(conn, campaign_id)
    metadata = dict((campaign or {}).get("metadata") or {})
    chaos = metadata.get("chaos_meter") or {"value": 0.0, "bucket": "calm"}

    # (1) Executor batch. Always called (even with an empty roster) so player_tier_up is the
    # executor's decision, never an engine fallback.
    affected = select_affected_agents(npcs, mentor_id=mentor_id, scene_location=scene_location)
    executor_out = await call_executor(
        build_executor_input(skip, player_card, chaos, affected)
    )
    selected = set(executor_out.get("selected_agent_ids") or [])
    report["affected_agents"] = [a["id"] for a in affected if not selected or a["id"] in selected]
    report["world_events"] = executor_out["world_events"]

    # (2) Retroactive per-agent logs (off_scene) -----------------------------------------
    agents_map = await repo.get_npc_agents(conn, campaign_id)
    logged = 0
    for pa in executor_out["per_agent"]:
        aid = pa.get("agent_id")
        info = agents_map.get(aid)
        entries = pa.get("entries") or []
        if not info or not entries:
            continue
        data = info["data"]
        loc = data.get("current_location", "")
        for e in entries:
            if not isinstance(e, dict) or not (e.get("action_summary") or "").strip():
                continue
            data = agent_state.append_log_entry(data, agent_state.make_log_entry(
                turn_index=turn_index,
                action_summary=e["action_summary"].strip(),
                location=loc,
                scene_mode="off_scene",
                important=bool(e.get("important")),
                source="self",
            ))
            logged += 1
        await repo.update_story_card(conn, info["story_card_id"], data)
    report["log_entries_applied"] = logged

    # (3) Advance the clock by the duration (the Director's integer) ----------------------
    days = int(skip.get("duration_days") or 0)
    final_clock = clock
    if clock and days > 0:
        final_clock, _w = game_clock.compute_next_clock(
            clock, time_advancement={"advance_days": days}, set_arc=None,
            scene_npc_ages={}, turn_index=turn_index,
        )
        await repo.save_clock(conn, campaign_id, final_clock)
        await repo.append_clock_snapshot(
            conn, campaign_id, turn_index, game_clock.snapshot_of(final_clock, turn_index)
        )
    report["advanced_days"] = days
    current_age = int((final_clock or {}).get("current_player_age", 0))

    # (4) Tier-up: Director decides (player_tier_up), engine validates range + regen fighting_style
    mentor_data = npcs.get(mentor_id) if mentor_id else None
    tier_up_emitted = executor_out.get("player_tier_up") or {}
    tier_after = clamp_tier_after(tier_before, tier_up_emitted.get("new_tier"))
    power_growth = ""
    if tier_after != tier_before:
        new_data = dict(player_card)
        psnap = dict(new_data.get("player_snapshot") or {})
        psnap["tier"] = tier_after
        psnap["fighting_style_regen_pending"] = True
        new_data["player_snapshot"] = psnap
        await repo.update_story_card(conn, player_sc["id"], new_data)
        reason = (tier_up_emitted.get("reason") or "").strip() or f"Timeskip: {skip.get('duration','')} — {skip.get('focus','')}"
        tier_change_event = {"new_tier": tier_after, "reason": reason}
        try:
            fs = await fighting_style.regenerate(
                conn, campaign_id,
                tier_change_event=tier_change_event, turn_index=turn_index,
                tier_before=tier_before,
                recent_combat_summary=f"Treino de timeskip focado em {skip.get('focus','')}.",
            )
            power_growth = fs.get("summary", "") if isinstance(fs, dict) else ""
            report["fighting_style"] = fs
        except Exception as exc:  # noqa: BLE001  consolidator is best-effort
            report["fighting_style"] = {"error": f"{type(exc).__name__}: {exc}"}
    report["tier_before"] = tier_before
    report["tier_after"] = tier_after
    if not power_growth:  # no regen (tier unchanged / regen failed): the executor's factual outcome
        power_growth = (executor_out.get("training_outcome") or "").strip()

    # (5) Recap cinematic (Opus) ----------------------------------------------------------
    mentor_block = None
    if mentor_data:
        mentor_block = {
            "name": mentor_data.get("name", ""),
            "tier": mentor_data.get("tier", ""),
            "voice_notes": mentor_data.get("voice_notes", ""),
            "what_they_taught": skip.get("focus", ""),
        }
    crew_block = []
    by_id = {a.get("agent_id"): a for a in executor_out["per_agent"] if isinstance(a, dict)}
    for entry in affected:
        if entry.get("relationship_to_player") != "crewmate":
            continue
        data = npcs.get(entry["id"]) or {}
        during = [
            e["action_summary"].strip()
            for e in (by_id.get(entry["id"], {}).get("entries") or [])
            if isinstance(e, dict) and (e.get("action_summary") or "").strip()
        ]
        crew_block.append({
            "name": data.get("name", ""),
            "role": data.get("class") or data.get("affiliation", ""),
            "during_skip": during,
        })

    recap_input = build_recap_input(
        skip=skip, player_card=player_card,
        tier_before=tier_before, tier_after=tier_after,
        fighting_style_before=old_fighting_style, power_growth=power_growth,
        current_age=current_age, mentor=mentor_block,
        crew_during_skip=crew_block, world_events=executor_out["world_events"],
        scene=scene, chaos_bucket=(chaos or {}).get("bucket", "calm"),
    )
    prose = ""
    try:
        prose = await call_recap(recap_input)
    except Exception as exc:  # noqa: BLE001  recap is best-effort
        report["recap_error"] = f"{type(exc).__name__}: {exc}"
    if not prose:  # cheap degraded retry, still LLM-authored, never a template
        try:
            prose = await call_recap(recap_input, model=config.AGENT_MODEL)
            report["recap_degraded"] = True
        except Exception as exc:  # noqa: BLE001
            report["recap_error2"] = f"{type(exc).__name__}: {exc}"
    if not prose:
        report["recap_failed"] = True

    # (6) timeskip_log (editable) ---------------------------------------------------------
    world = dict(metadata.get("world") or {})
    log = list(world.get("timeskip_log") or [])
    log.append({
        "started_at_turn_index": turn_index,
        "duration": skip.get("duration", ""),
        "mentor_id": mentor_id,
        "focus": skip.get("focus", ""),
        "tier_before": tier_before,
        "tier_after": tier_after,
        "recap_summary": prose[:600],
    })
    world["timeskip_log"] = log
    metadata["world"] = world
    # Clear the consumed pending offer only when the recap landed; a failed recap keeps it for retry.
    if prose:
        metadata.pop("pending_offer_training", None)
    await repo.update_campaign_metadata(conn, campaign_id, metadata)

    report["prose"] = prose
    return {"prose": prose, "report": report, "final_clock": final_clock}
