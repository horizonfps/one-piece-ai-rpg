"""FASE 27. NPC-mind post-tick (Sonnet 4.6). Runs AFTER the Narrator authored the scene: each
on-scene NPC reads the finished prose and updates its OWN mind (emotion, relationship to the
player, goal progress, a memory of what happened). No prose, no tactics — the scene already
exists. Replaces the on-scene agent's subjective bookkeeping in the narrator-author path."""
from __future__ import annotations

import asyncio

from .. import config
from . import agent_state
from . import language
from ..proxy import client

_PROMPT_FILES = ["npc_mind_addendum.pt-br.md"]
MAX_TOKENS = 1024
POST_TICK_CONCURRENCY = 8

_REL_DELTA = {
    "type": "object",
    "properties": {
        "target_npc_id": {"type": "string"},
        "value": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["target_npc_id", "value", "reason"],
}

_BOND_TIER_CHANGE = {
    "type": "object",
    "properties": {
        "target_npc_id": {"type": "string"},
        "bond_tier": {"type": "integer", "enum": [0, 1, 2]},
        "reason": {"type": "string"},
    },
    "required": ["target_npc_id", "bond_tier"],
}

EMIT_TOOL = {
    "name": "emit_npc_mind",
    "description": (
        "Você É este NPC, relendo a cena que acabou de acontecer (a prosa final). Registre como "
        "ela mexeu com você: emoção em que ficou, mudança de relação com o jogador, avanço do seu "
        "objetivo, e a lembrança que guarda. Nota factual em termos do mundo, sem prosa, sem "
        "decidir nada que a cena não mostrou. Preencha pre_emit_audit PRIMEIRO."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pre_emit_audit": {
                "type": "object",
                "description": (
                    "Compromisso de estilo dos campos de texto (goal_progress, memory_note, "
                    "relationship_delta.reason, bond_tier_change.reason, emotion). Emita cada "
                    "gate e honre-o."
                ),
                "properties": {
                    "diegese": {
                        "type": "string",
                        "enum": ["penso_em_termos_do_mundo_sem_rotulos_do_sistema"],
                        "description": (
                            "Não conheço log, slice, tick, turn, card, afinidade, campanha. "
                            "A lembrança é do que vivi, em palavra do mundo."
                        ),
                    },
                    "fidelidade_factual": {
                        "type": "string",
                        "enum": ["priorizo_meu_registro_e_anoto_divergencia_como_estranheza"],
                        "description": (
                            "Se a prosa contradisse um fato meu (irmãos, origem, afiliação), "
                            "mantenho meu self_record e trato a divergência como confusão de "
                            "terceiro, não como revisão da minha própria história."
                        ),
                    },
                    "afirmacao_direta": {
                        "type": "string",
                        "enum": ["afirmo_o_que_e_sem_par_de_negacao"],
                        "description": (
                            "Digo direto o que houve. Não nego uma hipótese antes de revelar a "
                            "verdadeira, não afirmo e nego o oposto em seguida, nem enfileiro "
                            "negações. Uma afirmação positiva basta."
                        ),
                    },
                    "pontuacao": {
                        "type": "string",
                        "enum": ["sem_travessao_separo_com_virgula_ou_ponto"],
                        "description": (
                            "Campo é nota factual, não prosa; travessão é recurso do Narrador. "
                            "Separo com vírgula ou ponto."
                        ),
                    },
                    "sem_aforismo": {
                        "type": "string",
                        "enum": ["fecho_no_fato_concreto_sem_sentenca_veredicto"],
                        "description": (
                            "Não fecho o campo com máxima, moral ou veredicto curto que pesa a "
                            "cena. O último fato basta."
                        ),
                    },
                },
                "required": [
                    "diegese", "fidelidade_factual", "afirmacao_direta", "pontuacao",
                    "sem_aforismo",
                ],
            },
            "emotion": {
                "type": "string",
                "description": "Em uma palavra ou frase curta, como você fica ao fim da cena.",
            },
            "relationship_delta": {
                "type": "array",
                "items": _REL_DELTA,
                "description": (
                    "Mudança na sua relação com quem importou na cena (use 'player' como "
                    "target_npc_id pro jogador). value pequeno e qualitativo. [] se nada mudou."
                ),
            },
            "bond_tier_change": {
                "type": "array",
                "items": _BOND_TIER_CHANGE,
                "description": (
                    "Só quando você sente que o laço mudou de patamar nesta cena (conhecido "
                    "para próximo, ou um laço rompido): bond_tier 0, 1 ou 2, use 'player' pro "
                    "jogador. [] na esmagadora maioria das cenas. A afinidade não promove "
                    "sozinha; quem decide o salto é você."
                ),
            },
            "goal_progress": {
                "type": "string",
                "description": "1 frase: como seu objetivo avançou, travou ou mudou nesta cena. Vazio se nada.",
            },
            "memory_note": {
                "type": "string",
                "description": "1 frase factual: o que você guarda desta cena. É a sua lembrança dela.",
            },
            "important": {
                "type": "boolean",
                "description": "true se esta cena foi um marco que você lembraria por muito tempo.",
            },
        },
        "required": ["emotion", "relationship_delta", "goal_progress", "memory_note", "important"],
    },
}


def _instructions() -> str:
    parts = [(config.PROMPTS_DIR / f).read_text(encoding="utf-8") for f in _PROMPT_FILES]
    return "\n\n---\n\n".join(parts)


def known_facts_from_card(data: dict) -> dict:
    """The NPC's own factual record: the anchor against absorbing a prose detail that contradicts
    its established history (origin, central bond, affiliation). Rides inside the mind snapshot."""
    hist = data.get("history") or {}
    return {
        "base_backstory": data.get("base_backstory", ""),
        "origin": hist.get("origin", ""),
        "central_bond": hist.get("central_bond", ""),
        "affiliation": data.get("affiliation", ""),
    }


def _mind_input(snapshot: dict, *, prose: str, player_input: dict, scene_location: str) -> dict:
    return {
        "you": snapshot,
        "scene_location": scene_location,
        "player_did": player_input.get("raw", ""),
        "final_scene_prose": prose,
    }


async def run_npc_mind(
    snapshot: dict, *, prose: str, player_input: dict, scene_location: str,
) -> dict | None:
    """Calls the NPC-mind tick for one NPC. Returns the raw emit_npc_mind, or None on failure
    (best-effort: a failed mind tick just skips that NPC's subjective update this turn)."""
    inp = _mind_input(snapshot, prose=prose, player_input=player_input, scene_location=scene_location)
    name = snapshot.get("name") or ""
    try:
        out = await client.call_tool(
            model=config.AGENT_MODEL,
            instructions=_instructions(),
            tag="npc_mind",
            sections=[("input — a cena que você acabou de viver", inp)],
            volatile_instructions=language.output_directive(),
            tool=EMIT_TOOL,
            tool_name="emit_npc_mind",
            temperature=config.AGENT_TEMPERATURE,
            max_tokens=MAX_TOKENS,
            trace_label=f"NPC-mind · {name}" if name else "NPC-mind",
        )
    except Exception:  # noqa: BLE001 best-effort subjective update
        return None
    if isinstance(out, dict):
        out.pop("pre_emit_audit", None)
    return out


def apply_npc_mind_output(data: dict, output: dict, *, turn_index: int, scene_location: str) -> dict:
    """Applies an emit_npc_mind to NPC state (copy): memory log entry, relationship_delta,
    mood from emotion, last_seen/last_tick, wakes a dormant catalog NPC. On-scene scene_mode."""
    memory = (output.get("memory_note") or "").strip()
    data = agent_state.append_log_entry(data, agent_state.make_log_entry(
        turn_index=turn_index,
        action_summary=memory,
        location=scene_location,
        scene_mode="on_scene",
        important=bool(output.get("important")),
        source="self",
    ))
    data = agent_state.apply_relationship_deltas(
        data, output.get("relationship_delta"), turn_index=turn_index,
        bond_tier_changes=output.get("bond_tier_change"),
    )
    emotion = (output.get("emotion") or "").strip()
    if emotion:
        data["mood"] = emotion
    progress = (output.get("goal_progress") or "").strip()
    if progress:
        data["goal_progress_note"] = progress
    data["last_tick_index"] = turn_index
    data["last_seen_by_player_index"] = turn_index
    data.pop("dormant", None)
    return data


async def run_post_ticks(
    snapshots_with_ids: list[tuple[str, dict]], *, prose: str, player_input: dict,
    scene_location: str, concurrency: int = POST_TICK_CONCURRENCY,
) -> list[tuple[str, dict]]:
    """Runs the mind tick concurrently for each (agent_id, snapshot). Returns (agent_id, output)
    for those that resolved. Best-effort: failures are dropped."""
    if not snapshots_with_ids:
        return []
    sem = asyncio.Semaphore(concurrency)

    async def _one(aid: str, snap: dict) -> tuple[str, dict | None]:
        async with sem:
            out = await run_npc_mind(
                snap, prose=prose, player_input=player_input, scene_location=scene_location
            )
        return aid, out

    raw = await asyncio.gather(*[_one(aid, snap) for aid, snap in snapshots_with_ids])
    return [(aid, out) for aid, out in raw if isinstance(out, dict)]
