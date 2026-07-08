"""FASE 33 return reconciler (Sonnet). When a frozen NPC re-enters the player's scene, this one
call redraws its volatile state against the current canon (crystals + world state) plus the elapsed
time since it left. It replaces the off-scene tick's parallel simulation: instead of the NPC acting
off-frame and inventing conflicting truths, it is pulled back to canon on return. Immutable identity
(name/tier/status/origin/central bond/affiliation) is never rewritten — only where it is, what it
wants, its mood, and what it plausibly learned about the world and the player while away.

Mirrors the auditor: run_reconcile makes the LLM call (cache-disciplined, returns the raw dict) and
apply_reconciliation is a pure DB-free merge over the card dict."""
from __future__ import annotations

from .. import config
from ..proxy import client
from . import language

_PROMPT_FILE = "return_reconciler.pt-br.md"
MAX_TOKENS = 2048

EMIT_TOOL = {
    "name": "emit_reconciliation",
    "description": (
        "Você É este NPC, reencontrando o jogador depois de um tempo fora do quadro. Atualize o seu "
        "estado pro agora: onde você está, o que quer, o seu humor, e o que soube do mundo e do "
        "jogador enquanto esteve fora — sempre ancorado no que a memória do mundo e o estado atual "
        "justificam, nunca inventado. Identidade sua (nome, origem, vínculo central) não muda. "
        "Preencha pre_emit_audit PRIMEIRO."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pre_emit_audit": {
                "type": "object",
                "description": (
                    "Compromisso de estilo dos campos de texto (current_situation, updated_goal, "
                    "updated_mood, world_awareness, player_knowledge_note). Emita cada gate e honre-o."
                ),
                "properties": {
                    "diegese": {
                        "type": "string",
                        "enum": ["penso_em_termos_do_mundo_sem_rotulos_do_sistema"],
                        "description": (
                            "Não conheço turn, tick, card, cristal, campanha. Penso onde estou e o "
                            "que sei, em palavra do mundo."
                        ),
                    },
                    "ancoragem": {
                        "type": "string",
                        "enum": ["so_sei_do_mundo_o_que_a_memoria_e_o_estado_atual_permitem"],
                        "description": (
                            "O que digo saber do mundo e do jogador vem da memória do mundo e do "
                            "estado atual, ou do que o tempo decorrido plausivelmente me traria. "
                            "Não fabrico um acontecimento paralelo que a verdade da história não tem."
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
                "required": ["diegese", "ancoragem", "afirmacao_direta", "pontuacao", "sem_aforismo"],
            },
            "current_situation": {
                "type": "string",
                "description": (
                    "1-3 frases: onde você está agora e como chegou aqui desde que sumiu de cena. "
                    "Coerente com o tempo decorrido. Se você ficou parado e nada notável passou, "
                    "diga isso — não invente uma jornada."
                ),
            },
            "updated_location": {
                "type": "string",
                "description": "Onde você está agora, no formato do mundo. Vazio se segue onde te deixaram.",
            },
            "updated_goal": {
                "type": "string",
                "description": "O seu objetivo agora. Pode ser o mesmo. Vazio se não mudou.",
            },
            "updated_mood": {
                "type": "string",
                "description": "Uma palavra ou frase curta: o humor em que você reencontra o jogador. Vazio se igual.",
            },
            "world_awareness": {
                "type": "string",
                "description": (
                    "1 frase do que você soube do mundo enquanto esteve fora (um marco, uma notícia "
                    "que te alcançaria), ancorado na memória do mundo. Vazio se você esteve isolado."
                ),
            },
            "player_knowledge_note": {
                "type": "string",
                "description": (
                    "1 frase do que você agora sabe ou pensa do jogador (uma fama que te chegou, uma "
                    "conclusão do último encontro). Vazio se nada novo."
                ),
            },
            "reasoning": {
                "type": "string",
                "description": "Nota curta de por que você reconciliou assim (trilha de auditoria, não vai pro mundo).",
            },
        },
        "required": ["current_situation", "updated_location", "updated_goal", "updated_mood"],
    },
}


def _instructions() -> str:
    return (config.PROMPTS_DIR / _PROMPT_FILE).read_text(encoding="utf-8")


def card_view(data: dict) -> dict:
    """The returning NPC's self-view: immutable identity (so the model knows who it is and does not
    rewrite it) + the volatile state it may redraw."""
    hist = data.get("history") or {}
    rel = (data.get("relationships") or {}).get("player") or {}
    return {
        "name": data.get("name", ""),
        "tier": data.get("tier", ""),
        "affiliation": data.get("affiliation", ""),
        "status": data.get("status", "alive"),
        "base_backstory": data.get("base_backstory", ""),
        "origin": hist.get("origin", ""),
        "central_bond": hist.get("central_bond", ""),
        "long_term_dream": data.get("long_term_dream", ""),
        "voice_notes": data.get("voice_notes", ""),
        "current_goal": data.get("current_goal", ""),
        "mood": data.get("mood", ""),
        "current_location": data.get("current_location", ""),
        "appearance": data.get("appearance") or {},
        "personality_shows_as": (data.get("personality") or {}).get("shows_as", ""),
        "relationship_to_player": {
            "affinity": rel.get("affinity", 0.0),
            "bond_tier": rel.get("bond_tier", 0),
            "what_they_know": rel.get("what_they_know_about_other") or [],
        },
    }


def elapsed_since(snapshot: dict, *, current_turn: int, current_day: int) -> dict:
    """Elapsed off-frame window: turns (monotonic index) + in-world days (game_clock)."""
    left_turn = int(snapshot.get("left_at_turn") or current_turn)
    left_day = int(snapshot.get("campaign_day") or current_day)
    return {"turns": max(0, current_turn - left_turn), "days": max(0, current_day - left_day)}


def reconciliation_changed(output: dict) -> bool:
    """True when the reconciler actually redrew something (any volatile field written). Decides
    whether to stage a reunion note for the Narrator; an all-empty output is a no-change thaw."""
    return any(
        (output.get(k) or "").strip()
        for k in (
            "current_situation", "updated_location", "updated_goal", "updated_mood",
            "world_awareness", "player_knowledge_note",
        )
    )


def apply_reconciliation(data: dict, output: dict, *, turn_index: int) -> dict:
    """Merges the reconciliation over the card (copy) and wakes it: rewrites volatile descriptive
    fields, appends player knowledge, clears dormant + departure_snapshot. Immutable identity
    (name/tier/status/origin/central_bond/affiliation) is untouched."""
    out = dict(data)
    goal = (output.get("updated_goal") or "").strip()
    if goal:
        out["current_goal"] = goal
    mood = (output.get("updated_mood") or "").strip()
    if mood:
        out["mood"] = mood
    loc = (output.get("updated_location") or "").strip()
    if loc:
        out["current_location"] = loc
    situ = (output.get("current_situation") or "").strip()
    if situ:
        out["current_situation"] = situ
    world_aw = (output.get("world_awareness") or "").strip()
    if world_aw:
        out["world_awareness"] = world_aw
    pk = (output.get("player_knowledge_note") or "").strip()
    if pk:
        rels = {k: dict(v) for k, v in (data.get("relationships") or {}).items() if isinstance(v, dict)}
        prec = rels.get("player") or {
            "affinity": 0.0, "bond_tier": 0, "last_interaction_turn_index": None,
            "what_they_know_about_other": [],
        }
        known = list(prec.get("what_they_know_about_other") or [])
        if pk not in known:
            known.append(pk)
        prec["what_they_know_about_other"] = known
        rels["player"] = prec
        out["relationships"] = rels
    out["last_reconciled_turn"] = turn_index
    out.pop("dormant", None)
    out.pop("departure_snapshot", None)
    return out


def returning_context(name: str, snapshot: dict, output: dict, *, elapsed: dict) -> dict:
    """The Narrator-facing note so the return reads as a reunion after a gap, not a mechanical recap.
    Built from the departure snapshot + the fresh reconciliation."""
    return {
        "name": name,
        "gone_for_turns": int(elapsed.get("turns") or 0),
        "gone_for_days": int(elapsed.get("days") or 0),
        "last_seen_doing": (snapshot.get("executive_summary") or snapshot.get("in_progress_goal") or "").strip(),
        "player_left_pending": (snapshot.get("last_directive_from_player") or "").strip(),
        "now": (output.get("current_situation") or "").strip(),
    }


async def run_reconcile(
    *,
    npc_view: dict,
    departure_snapshot: dict,
    elapsed: dict,
    crystals: list[dict],
    cards_catalog: list[dict],
    agents_catalog: list[dict],
    world_now: dict,
) -> dict | None:
    """Calls the reconciler for one returning NPC. Cache-disciplined: the stable canon catalogs +
    world memory ride cached_sections (byte-identical across NPCs returning the same turn); the
    volatile returning card + snapshot + elapsed window ride sections. Returns the raw dict, or None
    on failure (best-effort: the NPC wakes with its existing card)."""
    cached_sections: list[tuple[str, object]] = [
        ("WORLD-CARDS-CATALOG (identidade de todo NPC/ITEM/FACÇÃO)", cards_catalog or []),
        ("AGENTS-KNOWN-CATALOG (elenco: id, nome, status, voz, tier)", agents_catalog or []),
        ("MEMÓRIA-DO-MUNDO (fatos cristalizados — a verdade do que se passou)", crystals or []),
    ]
    sections: list[tuple[str, object]] = [
        ("você — o NPC que reencontra o jogador agora (identidade imutável + estado a redesenhar)", npc_view),
        ("sua_saída — a fotografia de quando você congelou (onde ficou, o que perseguia, o que o jogador deixou)", departure_snapshot),
        ("tempo_decorrido — quanto você ficou fora", elapsed),
        ("mundo_agora — onde a história está (posição do jogador, arco, dia)", world_now),
    ]
    name = npc_view.get("name") or ""
    try:
        out = await client.call_tool(
            model=config.RECONCILE_MODEL,
            instructions=_instructions(),
            tag="reconcile",
            cached_sections=cached_sections,
            sections=sections,
            volatile_instructions=language.output_directive(),
            tool=EMIT_TOOL,
            tool_name="emit_reconciliation",
            temperature=config.AGENT_TEMPERATURE,
            max_tokens=MAX_TOKENS,
            trace_label=f"Reconciler · {name}" if name else "Reconciler",
        )
    except Exception:  # noqa: BLE001 best-effort: on failure the NPC wakes with its existing card
        return None
    if isinstance(out, dict):
        out.pop("pre_emit_audit", None)
    return out
