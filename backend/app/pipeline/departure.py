"""FASE 33 departure snapshot (Sonnet). When a scene closes, every NPC that shared it with the
player FREEZES: this one call writes where the NPC stands as it leaves the frame, so the reconciler
can redraw it against canon when it returns. The engine fills the mechanical fields (left_at_turn,
campaign_day, location, last proses); the model writes only the summary + goal + player directive."""
from __future__ import annotations

import asyncio

from .. import config
from ..proxy import client
from . import language

_PROMPT_FILE = "departure_snapshot_generator.pt-br.md"
MAX_TOKENS = 1024
CONCURRENCY = 8

EMIT_TOOL = {
    "name": "emit_departure_snapshot",
    "description": (
        "Você É este NPC, e a cena com o jogador acabou de fechar — você segue a sua vida fora do "
        "quadro. Registre onde você fica ao sair: um resumo do seu estado, o que estava perseguindo, "
        "e qualquer coisa que o jogador te pediu ou deixou pendente. Nota factual em termos do mundo, "
        "sem prosa. Preencha pre_emit_audit PRIMEIRO."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pre_emit_audit": {
                "type": "object",
                "description": (
                    "Compromisso de estilo dos campos de texto (executive_summary, "
                    "in_progress_goal, last_directive_from_player). Emita cada gate e honre-o."
                ),
                "properties": {
                    "diegese": {
                        "type": "string",
                        "enum": ["penso_em_termos_do_mundo_sem_rotulos_do_sistema"],
                        "description": (
                            "Não conheço log, tick, turn, card, cristal, campanha. O resumo é do que "
                            "vivi e do que quero, em palavra do mundo."
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
                "required": ["diegese", "afirmacao_direta", "pontuacao", "sem_aforismo"],
            },
            "executive_summary": {
                "type": "string",
                "description": (
                    "1-3 frases factuais: onde você fica ao sair de cena — situação, humor, o que "
                    "mudou pra você nesta cena. É a fotografia do seu estado ao congelar."
                ),
            },
            "in_progress_goal": {
                "type": "string",
                "description": "1 frase: o que você estava perseguindo quando a cena fechou. Vazio se nada em aberto.",
            },
            "last_directive_from_player": {
                "type": "string",
                "description": (
                    "1 frase: a última coisa que o jogador te pediu, prometeu ou deixou pendente com "
                    "você. Vazio se o jogador não deixou nada seu a resolver."
                ),
            },
        },
        "required": ["executive_summary", "in_progress_goal", "last_directive_from_player"],
    },
}


def _instructions() -> str:
    return (config.PROMPTS_DIR / _PROMPT_FILE).read_text(encoding="utf-8")


def card_view(data: dict) -> dict:
    """Compact self-view fed to the departure call: who the NPC is + where it stood this scene."""
    rel = (data.get("relationships") or {}).get("player") or {}
    return {
        "name": data.get("name", ""),
        "tier": data.get("tier", ""),
        "affiliation": data.get("affiliation", ""),
        "current_goal": data.get("current_goal", ""),
        "long_term_dream": data.get("long_term_dream", ""),
        "personality_shows_as": (data.get("personality") or {}).get("shows_as", ""),
        "mood": data.get("mood", ""),
        "goal_progress_note": data.get("goal_progress_note", ""),
        "relationship_to_player": {
            "affinity": rel.get("affinity", 0.0),
            "bond_tier": rel.get("bond_tier", 0),
            "what_they_know": rel.get("what_they_know_about_other") or [],
        },
    }


def build_snapshot(
    output: dict, *, left_at_turn: int, campaign_day: int, location: str, last_prose_excerpt: list[str],
) -> dict:
    """Assembles the durable departure_snapshot: model fields + engine-provided mechanical fields.
    Called with output=None (degraded) when the LLM failed — the snapshot still freezes the NPC."""
    out = output or {}
    return {
        "left_at_turn": int(left_at_turn),
        "campaign_day": int(campaign_day),
        "location": location or "",
        "last_prose_excerpt": list(last_prose_excerpt or []),
        "executive_summary": (out.get("executive_summary") or "").strip(),
        "in_progress_goal": (out.get("in_progress_goal") or "").strip(),
        "last_directive_from_player": (out.get("last_directive_from_player") or "").strip(),
    }


def apply_departure(data: dict, snapshot: dict) -> dict:
    """Freezes the NPC (copy): dormant=True + the departure_snapshot. The snapshot is immutable to
    the rolling log so it survives a long absence."""
    out = dict(data)
    out["dormant"] = True
    out["departure_snapshot"] = snapshot
    return out


async def run_departure_snapshot(
    npc_view: dict, *, scene_prose: str, location: str,
) -> dict | None:
    """Calls the departure snapshot for one NPC. Returns the raw emit_departure_snapshot, or None on
    failure (best-effort: a failed call still freezes the NPC with a degraded snapshot)."""
    cached_sections: list[tuple[str, object]] = [
        ("cena_que_fechou (últimos beats — contexto compartilhado da cena)", scene_prose or "(sem prosa)"),
        ("onde_a_cena_se_passou", location or ""),
    ]
    sections: list[tuple[str, object]] = [
        ("você — o NPC que está saindo de cena", npc_view),
    ]
    name = npc_view.get("name") or ""
    try:
        out = await client.call_tool(
            model=config.DEPARTURE_MODEL,
            instructions=_instructions(),
            tag="departure",
            cached_sections=cached_sections,
            sections=sections,
            volatile_instructions=language.output_directive(),
            tool=EMIT_TOOL,
            tool_name="emit_departure_snapshot",
            temperature=config.AGENT_TEMPERATURE,
            max_tokens=MAX_TOKENS,
            trace_label=f"Departure · {name}" if name else "Departure",
        )
    except Exception:  # noqa: BLE001 best-effort: the freeze still happens with a degraded snapshot
        return None
    if isinstance(out, dict):
        out.pop("pre_emit_audit", None)
    return out


async def run_departures(
    npc_views_with_ids: list[tuple[str, dict]], *, scene_prose: str, location: str,
    concurrency: int = CONCURRENCY,
) -> list[tuple[str, dict | None]]:
    """Runs the departure snapshot concurrently for each (agent_id, npc_view). Returns
    (agent_id, output|None) for all — a None output still freezes the NPC (degraded snapshot)."""
    if not npc_views_with_ids:
        return []
    sem = asyncio.Semaphore(concurrency)

    async def _one(aid: str, view: dict) -> tuple[str, dict | None]:
        async with sem:
            out = await run_departure_snapshot(view, scene_prose=scene_prose, location=location)
        return aid, out

    # Prime the shared cached prefix (scene_prose + location) with the first call, then fan out the
    # rest so they read the warm prefix instead of each racing a cold cache.
    first_id, first_view = npc_views_with_ids[0]
    first = await _one(first_id, first_view)
    rest = await asyncio.gather(*[_one(aid, view) for aid, view in npc_views_with_ids[1:]])
    return [first, *rest]
