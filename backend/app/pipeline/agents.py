"""Production NPC agent (Sonnet 4.6) via tool emit_agent_turn. Consumes the full
NamedNPCAgent and emits the turn resolution; to_narrator_briefing maps the output
to the narrator's npcs_in_scene[] contract."""
from __future__ import annotations

from .. import config
from . import agent_state
from . import language
from ..proxy import client

# master + fixed addenda. Tactical and mushi cover generic repertoire for any NPC, loaded
# always; their gates are absolute so loading is inert when unavailable. The remaining
# addenda stay silent (§0) when their briefing field is absent.
_PROMPT_FILES = [
    "agent_system_prompt.pt-br.md",
    "agent_tactical_actions_addendum.pt-br.md",
    "agent_mushi_addendum.pt-br.md",
    "agent_faction_reputation_addendum.pt-br.md",
    "agent_alliance_addendum.pt-br.md",
    # recruitment: engine rolls the outcome before the agent; the target voices accept/decline.
    "agent_recruitment_decision_addendum.pt-br.md",
]

_ACTION_TYPES = [
    "idle", "move", "socialize", "conflict", "train", "pursue",
    "invite_to_crew", "call_player", "give_vivre_card", "offer_training",
    "surrender", "take_hostage", "regroup",
]

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
    "name": "emit_agent_turn",
    "description": (
        "Emite a resolução deste NPC pro turn (decisão mecânica, emoção, action_type, "
        "intenção de fala, ação física, fatos a revelar, relationship_delta). "
        "Você É o NPC; sem prosa, sem decidir pelo player nem pelo narrador. "
        "Preencha pre_emit_audit PRIMEIRO: cada gate é um compromisso de estilo que os "
        "campos de texto escritos depois dele honram."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            # Reflexive forcing function: gate-required string-enum filled before the text
            # fields; re-asserting the rule reduces style drift. Engine discards on parse.
            "pre_emit_audit": {
                "type": "object",
                "description": (
                    "Compromissos de estilo dos campos de texto (reasoning_chain, "
                    "action_summary, speech_intent, physical_action, action_details, "
                    "relationship_delta.reason, bond_tier_change.reason). "
                    "Emita cada gate com seu valor literal e escreva os campos honrando-o."
                ),
                "properties": {
                    "diegese": {
                        "type": "string",
                        "enum": ["penso_em_termos_do_mundo_sem_rotulos_do_sistema"],
                        "description": (
                            "O personagem não conhece log, slice, tick, turn, gatilho, "
                            "incoming, campanha, arco. Ausência de estímulo vira fato "
                            "vivido (manhã comum), nunca menção ao registro."
                        ),
                    },
                    "primeira_pessoa": {
                        "type": "string",
                        "enum": ["pensamento_concreto_deste_momento_sem_maxima_sobre_mim"],
                        "description": (
                            "Nada de me comentar em terceira pessoa nem formular ditado "
                            "sobre o meu próprio jeito."
                        ),
                    },
                    "afirmacao_direta": {
                        "type": "string",
                        "enum": ["afirmo_o_que_e_sem_negar_uma_alternativa_antes"],
                        "description": (
                            "Frase que nega uma hipótese para revelar a verdadeira, que afirma "
                            "e nega o oposto em seguida, ou que enfileira negações é proibida em "
                            "qualquer campo de texto. Em inglês o mesmo vício entra pelo aposto "
                            "de negação pendurado na afirmação (o \"not/no ...\" curto que "
                            "descarta a alternativa) e pela estrutura not-X-but-Y. Diga direto "
                            "o que é."
                        ),
                    },
                    "pontuacao": {
                        "type": "string",
                        "enum": ["sem_travessao_separo_com_virgula_ou_ponto"],
                        "description": (
                            "Campos são nota factual ou pensamento, não prosa; travessão "
                            "é recurso do Narrador."
                        ),
                    },
                    "voz_expressiva_completa": {
                        "type": "string",
                        "enum": ["npc_contido_fala_pouco_mas_em_frase_completa_e_viva_nunca_picada_ou_monossilabica"],
                        "description": (
                            "speech_intent de NPC contido é pouco, mas em frase inteira e viva. "
                            "A economia vale porque a fala é rara, não porque é picada ou "
                            "monossilábica. Não empurra NPC para expansivo."
                        ),
                    },
                },
                "required": [
                    "diegese", "primeira_pessoa", "afirmacao_direta", "pontuacao",
                    "voz_expressiva_completa",
                ],
            },
            "reasoning_chain": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": 4,
                "description": (
                    "2 a 4 passos telegráficos, 3 a 6 palavras cada, em primeira pessoa: "
                    "inferência, impulso, escolha. O cenário já está no input; parta da "
                    "sua leitura dele. A ação escolhida pertence a decision."
                ),
            },
            "decision": {
                "type": "string",
                "description": (
                    "O ato em uma oração: o quê e o alvo, sem a fala (a fala vai em "
                    "speech_intent). A encenação pertence a physical_action."
                ),
            },
            "emotion": {"type": "string"},
            "action_type": {"type": "string", "enum": _ACTION_TYPES},
            "action_details": {"type": "object"},
            "action_summary": {"type": "string"},
            "important": {"type": "boolean"},
            "emotion_intensity": {"type": "string", "enum": ["low", "medium", "high"]},
            "speech_intent": {"type": "string"},
            "physical_action": {"type": "string"},
            "key_information": {"type": "array", "items": {"type": "string"}},
            "relationship_delta": {"type": "array", "items": _REL_DELTA},
            "bond_tier_change": {
                "type": "array",
                "items": _BOND_TIER_CHANGE,
                "description": (
                    "Só quando você SENTE que a relação com alguém mudou de patamar agora "
                    "(de conhecido para próximo, ou o rompimento de um laço): bond_tier 0, 1 "
                    "ou 2. [] ou omitido na esmagadora maioria dos turns. Afinidade acumulada "
                    "não promove sozinha; quem decide o salto é você."
                ),
            },
        },
        "required": [
            "pre_emit_audit",
            "reasoning_chain", "decision", "emotion", "action_type",
            "action_details", "action_summary", "important", "emotion_intensity",
        ],
    },
}


def _instructions() -> str:
    """master + fixed addenda. Stable across calls so it is a cacheable static prefix."""
    parts = [(config.PROMPTS_DIR / f).read_text(encoding="utf-8") for f in _PROMPT_FILES]
    return "\n\n---\n\n".join(parts)


def build_agent_input(
    agent_self: dict,
    *,
    scene_mode: str,
    scene_context: dict | None = None,
    orchestration_mode: str | None = None,
    perception: dict | None = None,
    log_slice: list | None = None,
    incoming_socialize: dict | None = None,
    incoming_player_mushi_call: dict | None = None,
    has_paired_mushi: bool = False,
    game_clock: dict | None = None,
    institutional_standing: dict | None = None,
    alliance_with_player_crew: dict | None = None,
    recruitment_decision: dict | None = None,
) -> dict:
    """Builds the agent's §1 input contract. scene_context/orchestration_mode only on-scene;
    off-scene carries perception + log slice. Each optional top-level field is added only
    when present, keeping its addendum silent (§0) otherwise."""
    self_with_mushi = {**agent_self, "has_paired_mushi_with_player": bool(has_paired_mushi)}
    inp: dict = {
        "agent_self": self_with_mushi,
        "scene_mode": scene_mode,
        "agent_perception": perception or {"same_location_events": []},
        "personal_event_log_slice": log_slice or [],
        "incoming_socialize": incoming_socialize,
        "incoming_player_mushi_call": incoming_player_mushi_call,
        "game_clock": game_clock,
    }
    if institutional_standing:
        inp["institutional_standing"] = institutional_standing
    if alliance_with_player_crew:
        inp["alliance_with_player_crew"] = alliance_with_player_crew
    if recruitment_decision:
        inp["recruitment_decision"] = recruitment_decision
    if scene_mode == "on_scene":
        inp["orchestration_mode"] = orchestration_mode or "A"
        inp["scene_context"] = scene_context or {}
    return inp


async def call_npc_agent(agent_input: dict) -> dict:
    """agent_input follows the §1 contract. Returns the raw emit_agent_turn."""
    name = (agent_input.get("agent_self") or {}).get("name") or ""
    label = f"Agente · {name}" if name else "Agente"
    if agent_input.get("scene_mode") == "off_scene":
        label += " (off-scene)"
    turn = await client.call_tool(
        model=config.AGENT_MODEL,
        instructions=_instructions(),
        tag="agent",
        sections=[("input (contrato de entrada §1)", agent_input)],
        volatile_instructions=language.output_directive(),
        tool=EMIT_TOOL,
        tool_name="emit_agent_turn",
        temperature=config.AGENT_TEMPERATURE,
        max_tokens=2048,
        trace_label=label,
    )
    # Style scratchpad: forcing function / dev-only; engine discards. reasoning_chain stays.
    if isinstance(turn, dict):
        turn.pop("pre_emit_audit", None)
    return turn


def to_narrator_briefing(agent_self: dict, agent_turn: dict, *, recent_event_log: list | None = None) -> dict:
    """Adapts emit_agent_turn to the narrator's npcs_in_scene[] contract. recent_event_log
    triggers the narrator_event_log_discretion_addendum."""
    briefing = {
        "name": agent_self.get("name", ""),
        "tier": agent_self.get("tier", ""),
        "knowledge_tier": agent_self.get("knowledge_clearance", ""),
        "decision": agent_turn.get("decision", ""),
        "speech_intent": agent_turn.get("speech_intent", ""),
        "key_information": agent_turn.get("key_information", []),
        "physical_action": agent_turn.get("physical_action", ""),
        "emotion": agent_turn.get("emotion", ""),
        "voice_notes": agent_self.get("voice_notes", ""),
        "appearance": agent_self.get("appearance") or {},
        "secret_intent": None,
    }
    # Marine moral_code feeds the briefing for narrator_marine_moral_code_addendum; absent = omitted.
    moral_code = agent_self.get("moral_code")
    if moral_code:
        briefing["moral_code"] = moral_code
    if recent_event_log:
        briefing["recent_event_log"] = recent_event_log
    return briefing


def to_narrator_mind_snapshot(data: dict, *, memory_window: int = 6) -> dict:
    """FASE 27. Narrator-author contract: the NPC's mind straight from the card, no agent call.
    The Narrator DECIDES this NPC's tactic, speech, gesture and emotion from it (parallel to
    to_narrator_briefing, which carries an agent's pre-decided turn). No `decision`/`speech_intent`
    here is the discriminator: their absence tells the Narrator to author this NPC."""
    rel = (data.get("relationships") or {}).get("player") or {}
    log = agent_state.log_slice(data.get("personal_event_log"))[-memory_window:]
    memory_slice = [
        {"summary": e.get("action_summary", ""), "off_scene": e.get("scene_mode") == "off_scene"}
        for e in log if e.get("action_summary")
    ]
    snap = {
        "name": data.get("name", ""),
        "tier": data.get("tier", ""),
        "knowledge_tier": data.get("knowledge_clearance", ""),
        "voice_notes": data.get("voice_notes", ""),
        "current_goal": data.get("current_goal", ""),
        "long_term_dream": data.get("long_term_dream", ""),
        "relationship_to_player": {
            "affinity": rel.get("affinity", 0.0),
            "bond_tier": rel.get("bond_tier", 0),
            "what_they_know": rel.get("what_they_know_about_other") or [],
        },
        "memory_slice": memory_slice,
        "emotion_baseline": data.get("mood", ""),
        "expressiveness": data.get("expressiveness") or "",
        "appearance": data.get("appearance") or {},
        "personality_shows_as": (data.get("personality") or {}).get("shows_as", ""),
        "secret_intent": None,
    }
    last = data.get("last_act")
    if isinstance(last, dict) and last.get("action_type"):
        snap["last_act"] = {"action_type": last.get("action_type", "")}
    if data.get("moral_code"):
        snap["moral_code"] = data["moral_code"]
    return snap
