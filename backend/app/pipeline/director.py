"""Scene Director PRE-TURN pass via emit_pre_turn_decisions tool.

Director reads world state + player input + recent prose and decides the scene,
who enters the frame, present crewmates, active cards and the qualitative pre-flags.
pre_emit_audit is a required scratchpad in the schema; the engine ignores it on parse.
Defensive parse handles npcs_in_scene string-of-JSON via brace-matching, defaults
missing top-level fields, and retries once on invalid/truncated output.
"""
from __future__ import annotations

import json

from .. import config
from ..proxy import client
from . import alliances
from . import economy
from . import language
from . import faction
from . import legend
from . import mushi
from . import news_coo
from . import plots
from . import ship
from . import world_map
from . import world_state as ws

# PRE prompt stack, same concatenation order as the validated harness.
_PROMPT_FILES = [
    "director_system_prompt.pt-br.md",
    "director_combat_addendum.pt-br.md",
    "director_mushi_addendum.pt-br.md",
    "director_offer_training_addendum.pt-br.md",
    "director_tactical_actions_addendum.pt-br.md",
    "director_ship_addendum.pt-br.md",
    "director_crew_recruitment_addendum.pt-br.md",
    "director_threads_addendum.pt-br.md",
    "director_legend_addendum.pt-br.md",
]

# POST prompt stack, same concatenation order as the validated harness. Alliances,
# hunters and crew addenda sit last so they read the rest of the assembled state.
_POST_PROMPT_FILES = [
    "director_system_prompt.pt-br.md",
    "director_alignment_addendum.pt-br.md",
    "director_chaos_meter_addendum.pt-br.md",
    "director_bounty_addendum.pt-br.md",
    "director_legend_addendum.pt-br.md",
    "director_faction_reputation_addendum.pt-br.md",
    "director_combat_addendum.pt-br.md",
    "director_marine_generation_addendum.pt-br.md",
    "director_world_events_addendum.pt-br.md",
    "director_mushi_addendum.pt-br.md",
    "director_tactical_actions_addendum.pt-br.md",
    "director_economy_inventory_addendum.pt-br.md",
    "director_ship_addendum.pt-br.md",
    "director_crew_alliances_addendum.pt-br.md",
    "director_bounty_hunters_addendum.pt-br.md",
    "director_crew_addendum.pt-br.md",
    # Always present in the post-turn pass; part of the static (cached) prefix, not a volatile
    # addendum. Only the conditional nemesis addenda ride volatile_instructions.
    "director_navigation_addendum.pt-br.md",
]

# Top-level field defaults mirroring the schema contract.
_PRE_TURN_DEFAULTS: dict = {
    "scene": {"location": "", "ambient": "", "tension_level": "calm", "mode": "A"},
    "npcs_in_scene": [],
    # Director-decided off-frame cast movement; corrects the card's registered location.
    "npc_location_updates": [],
    # Director-decided scene transition this turn: place-hook (closes on a hook, next turn moves)
    # or time-ellipsis (jump mid-prose into the new scene). None = the scene continues.
    "scene_transition": None,
    "crew_present_in_scene": [],
    "active_cards": [],
    "world_memory_relevant": "",
    "plot_armor_engaged": False,
    "surprise_actions": [],
    "breakthrough_imminent": None,
    "incoming_mushi_call": None,
    "outgoing_mushi_call": None,
    "mushi_call_active": None,
    "vivre_card_state_change": None,
    "intercepted_transmission": None,
    "surveillance_alert": None,
    "offer_training": None,
    "offer_training_rejected": None,
    # Director withdraws a stale pending training offer (mentor left/died, arc moved on).
    "withdraw_pending_offer": False,
    "player_recruitment_intent": None,
    "player_offer_response": None,
    # Gates the Narrator economy / ship addenda for the turn (relevance is the Director's call).
    "economy_relevant": False,
    "ship_relevant": False,
    # Player engagement with a training/timeskip this turn (the trigger the engine reads to fire
    # the timeskip). "none" = the input does not engage training, the norm.
    "timeskip_intent": "none",
    # Organic News Coo arrival decided by context (None = no paper this turn, the norm).
    "news_coo_arrival": None,
    "arrival_triggers": {"research_pipeline": None, "island_designer": None},
    # Director-chosen real sea destination when the player heads out by CRITERION (not a named
    # island): {island_id, display_name} from the WORLD-MAP, fed to the Narrator so the prose names
    # a real island instead of inventing one. None when the player named the island or no sea choice.
    "sea_destination_choice": None,
    # Opening turn only: island_ids this character plausibly already knows (None = region fallback).
    "opening_known_island_ids": None,
    # Opt-in continuity thread the Director plants this turn (None = no thread, the norm).
    "plant_thread": None,
    # Preserved (not popped) for the devtools panel + trace.
    "thread_reasoning": None,
}

# Why behind planting a thread: preserved (not popped), feeds the devtools "what the LLM thought"
# panel. Filled only when plant_thread is emitted; null otherwise. Bookkeeping of intent + a
# reflexive forcing function (re-reading the reason before committing the decision).
_THREAD_REASONING = {
    "type": ["string", "null"],
    "description": (
        "GUARDADO (a engine preserva, nao descarta). Quando voce emite plant_thread neste turn, "
        "preencha com 1-2 frases factuais do PORQUE plantar um fio agora ('a fala do taverneiro "
        "sobre o irmao desaparecido pede continuidade'; 'o player ignorou o navio ancorado, vale "
        "deixar o fio aberto'). null quando nao planta fio. E o registro da sua intencao, releia "
        "antes de decidir."
    ),
}

# Opt-in continuity thread (FASE 30). The Director plants ONE only when a moment in the scene
# genuinely asks for a later payoff; the island is born neutral, so most turns plant nothing.
# Prefer pulling an open thread from foreshadow_pool over minting a new one. Qualitative, never
# forced. null = no thread this turn.
_PLANT_THREAD = {
    "type": ["object", "null"],
    "description": (
        "Fio de continuidade OPCIONAL plantado neste turn. A ilha nasce neutra: na MAIORIA dos "
        "turns isto e null. So preencha quando a cena de fato pede um desdobramento futuro e o "
        "player nao o fechou. Antes de criar, prefira deixar o Narrador PUXAR um fio ja aberto do "
        "foreshadow_pool. Nunca plante por rotina."
    ),
    "properties": {
        "hook_summary": {
            "type": "string",
            "description": (
                "1 frase factual do fio que fica em aberto (o que ficou pendente, sem decretar "
                "como resolve). Ex.: 'o taverneiro mencionou um irmao levado pela Marinha e nao "
                "voltou ao assunto'."
            ),
        },
        "theme_tag": {
            "type": "string",
            "description": "Etiqueta curta em snake_case do tema do fio (ex.: 'marine_grudge', 'missing_kin', 'cursed_relic'). Ajuda o Narrador a reconhecer quando o player toca o tema.",
        },
        "where_hint": {
            "type": "string",
            "description": "Opcional. Pista solta de onde/quando o fio pode reaparecer (sem fixar nada; e textura, nao agendamento). Vazio se nao ha pista.",
        },
    },
    "required": ["hook_summary"],
}

# Reflexive scratchpad of the PRE tool: literal input citations that gate the pre-turn
# flags. First property of the schema so the model emits it BEFORE deciding the flags
# (schema order = emission order). Engine discards on parse.
_PRE_EMIT_AUDIT = {
    "type": "object",
    "description": (
        "Scratchpad OBRIGATORIO. Trace de auditoria: cite LITERAL os valores "
        "do input que travam gates ANTES de decidir flags abaixo. Engine "
        "ignora este campo; objetivo e forcar comparacao literal em vez de "
        "inferir do contexto. Preencher TODOS os campos required mesmo "
        "quando arrays sao vazios — escreva '[]' explicito."
    ),
    "properties": {
        "paired_mushis_literal": {
            "type": "string",
            "description": (
                "Copia textual de player.paired_mushis. Vazio = '[]' literal. "
                "NAO interprete; copie."
            ),
        },
        "player_position_cluster_literal": {
            "type": "string",
            "description": "Copia textual de player.position_cluster. Ausente = 'AUSENTE'.",
        },
        "incoming_callers_evaluation": {
            "type": "array",
            "description": (
                "Pra CADA agent_tick_outputs[] com action_type=call_player, "
                "uma row. Vazio se nenhum tentou."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string"},
                    "in_paired_mushis": {
                        "type": "boolean",
                        "description": "true SO se agent_id em paired_mushis_literal literal. '[]' = sempre false.",
                    },
                    "agent_status_literal": {"type": "string"},
                    "agent_cluster_literal": {"type": "string"},
                    "passes_all_three_gates": {
                        "type": "boolean",
                        "description": (
                            "TRUE so se in_paired_mushis=true E status in "
                            "{alive,injured} E (baby => cluster string-igual)."
                        ),
                    },
                    "blocked_reason": {
                        "type": ["string", "null"],
                        "description": "Se false: pairing_missing/status_dead/status_missing/cluster_mismatch/status_captured_no_evidence. Se true, null.",
                    },
                },
                "required": [
                    "agent_id", "in_paired_mushis", "agent_status_literal",
                    "agent_cluster_literal", "passes_all_three_gates", "blocked_reason",
                ],
            },
        },
        "crew_in_combat_scene_literal": {
            "type": "array",
            "description": (
                "agent_ids de crew[] cuja current_location bate com a cena "
                "de combate atual. Vazio fora de combate. TODA entrada aqui "
                "DEVE aparecer em npcs_in_scene[] com skip_agent_call=true E em "
                "crew_present_in_scene[]."
            ),
            "items": {"type": "string"},
        },
        "npcs_in_scene_planned_ids": {
            "type": "array",
            "description": (
                "TODOS os agent_ids que vao em npcs_in_scene[]. Inclui: cada "
                "inimigo on-scene + cada id em crew_in_combat_scene_literal. "
                "Omitir id de crew_in_combat_scene_literal = output errado."
            ),
            "items": {"type": "string"},
        },
        "scene_cast_audit": {
            "type": "array",
            "description": (
                "Planta de posicao da cena. Uma row por CANDIDATO a estar no "
                "quadro: cada NPC presente no turn anterior MAIS cada NPC que "
                "voce traz agora. Confronta a posicao REGISTRADA com onde o NPC "
                "fica ao fim deste turn, NPC a NPC, ANTES de montar npcs_in_scene "
                "e npc_location_updates. Regra de saida: todo agent_id com "
                "moves_this_turn=true E location_now != registered_location_literal "
                "DEVE ter entry correspondente em npc_location_updates (mesmo "
                "new_location). Quem fica (moves_this_turn=false) nao precisa de "
                "update nem de aparecer em npcs_in_scene se nao esta no setor da "
                "cena. Vazio so no 1o turn de uma cena sem elenco anterior."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string"},
                    "registered_location_literal": {
                        "type": "string",
                        "description": (
                            "Copia literal da current_location deste NPC em "
                            "AGENTS-LOCATIONS (formato 'ilha/sub-area')."
                        ),
                    },
                    "moves_this_turn": {
                        "type": "boolean",
                        "description": (
                            "A cena ou uma acao desloca este NPC neste turn — "
                            "ele entra no setor da cena, sai dele, ou vai embora? "
                            "false = permanece exatamente onde o registro aponta."
                        ),
                    },
                    "location_now": {
                        "type": "string",
                        "description": (
                            "Sub-area 'ilha/sub-area' onde o NPC esta ao FIM do "
                            "turn. Igual a registered_location_literal se "
                            "moves_this_turn=false. Se a cena o trouxe, "
                            "'ilha/<scene.area_slug>'. Se ele saiu, o setor de "
                            "destino."
                        ),
                    },
                },
                "required": [
                    "agent_id", "registered_location_literal",
                    "moves_this_turn", "location_now",
                ],
            },
        },
        "hostage_grab_evaluation": {
            "type": "array",
            "description": (
                "FASE 12 §A: pra CADA NPC que voce considerou pra hostage_grab "
                "(antagonista on-scene sem escrupulos perdendo posicao), uma row "
                "citando persona+tiers literais. Vazio ('[]') se nenhum "
                "hostage_grab no turn. Forca a comparacao literal antes de decidir."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "actor_npc_id": {"type": "string"},
                    "actor_alignment_literal": {"type": "string"},
                    "actor_voice_notes_literal": {"type": "string"},
                    "actor_tier_literal": {"type": "string"},
                    "candidate_hostage_id": {"type": "string"},
                    "candidate_hostage_tier_literal": {"type": "string"},
                    "persona_permits_hostage": {
                        "type": "boolean",
                        "description": (
                            "false se actor alignment >= +0.5 OU voice_notes traz "
                            "codigo de honra/aversao a refem. true so se persona "
                            "sem escrupulos."
                        ),
                    },
                    "hostage_dominable": {
                        "type": "boolean",
                        "description": "true so se tier(refem) <= tier(ator).",
                    },
                    "emits_hostage_grab": {
                        "type": "boolean",
                        "description": (
                            "TRUE so se persona_permits_hostage E hostage_dominable. "
                            "Se TRUE, surprise_actions DEVE ter 1 entry hostage_grab "
                            "com esse actor."
                        ),
                    },
                },
                "required": [
                    "actor_npc_id", "actor_alignment_literal",
                    "actor_voice_notes_literal", "actor_tier_literal",
                    "candidate_hostage_id", "candidate_hostage_tier_literal",
                    "persona_permits_hostage", "hostage_dominable",
                    "emits_hostage_grab",
                ],
            },
        },
        "recruitment_intent_audit": {
            "type": "object",
            "description": (
                "FASE 13 — scratchpad de classificacao do intent de crew no input do "
                "player. Preencha ANTES de player_recruitment_intent e "
                "player_offer_response. Forca a distinguir convite REAL (o player "
                "oferece a um NPC presente entrar no bando dele) de elogio, pergunta, "
                "mera mencao do bando, recusa ou hipotese. Engine ignora este campo."
            ),
            "properties": {
                "player_input_literal": {
                    "type": "string",
                    "description": "Copia textual de player_input.raw.",
                },
                "is_directed_crew_invite": {
                    "type": "boolean",
                    "description": (
                        "TRUE so se o player, neste input, OFERECE a um NPC presente "
                        "entrar no bando dele (qualquer redacao). false pra elogio, "
                        "pergunta, mencao do bando, recusa ou hipotese."
                    ),
                },
                "invite_target_npc_id": {
                    "type": ["string", "null"],
                    "description": (
                        "Se is_directed_crew_invite=true, o agent_id (de "
                        "npcs_in_scene) do alvo; senao null. DEVE bater com "
                        "player_recruitment_intent.target_npc_id."
                    ),
                },
                "pending_offers_literal": {
                    "type": "string",
                    "description": (
                        "Copia textual de world_state.pending_crew_offers (ids+nomes). "
                        "'[]' literal se vazio."
                    ),
                },
                "is_response_to_pending_offer": {
                    "type": "boolean",
                    "description": (
                        "TRUE so se ha oferta pendente E o player, neste input, aceita "
                        "ou recusa entrar. '[]' em pending_offers => sempre false."
                    ),
                },
                "offer_response_target_npc_id": {
                    "type": ["string", "null"],
                    "description": (
                        "Se is_response_to_pending_offer=true, o npc_id da oferta "
                        "respondida; senao null. DEVE bater com "
                        "player_offer_response.target_npc_id."
                    ),
                },
            },
            "required": [
                "player_input_literal",
                "is_directed_crew_invite",
                "invite_target_npc_id",
                "pending_offers_literal",
                "is_response_to_pending_offer",
                "offer_response_target_npc_id",
            ],
        },
        "timeskip_intent_audit": {
            "type": "object",
            "description": (
                "Scratchpad de classificacao do engajamento de treino/timeskip no "
                "input do player. Preencha ANTES de timeskip_intent. Forca a distinguir "
                "pedido/aceite REAL de mera mencao, pergunta ou recusa. Engine ignora."
            ),
            "properties": {
                "player_input_literal": {
                    "type": "string",
                    "description": "Copia textual de player_input.raw.",
                },
                "pending_training_offer_literal": {
                    "type": "string",
                    "description": (
                        "Copia textual de world_state.pending_training_offer "
                        "(mentor + foco). 'null' literal se nao ha oferta pendente."
                    ),
                },
                "classification": {
                    "type": "string",
                    "enum": ["accepted", "requested", "none"],
                    "description": (
                        "DEVE bater com timeskip_intent. 'accepted' exige "
                        "pending_training_offer_literal != 'null' E o input respondendo "
                        "a ela."
                    ),
                },
            },
            "required": [
                "player_input_literal",
                "pending_training_offer_literal",
                "classification",
            ],
        },
        "player_engaged_cast_audit": {
            "type": "array",
            "description": (
                "Uma row por personagem que o player_input DESTE turn engaja "
                "diretamente (dirige fala, ajuda, toca, carrega, ataca, protege, "
                "age sobre). Forca a promover ao elenco quem o player interage, "
                "em vez de deixar so no ambient/world_memory_relevant (master "
                "§2.1). Vazio ('[]') so se o player nao engaja personagem nenhum "
                "(age sobre objeto/ambiente ou so se desloca)."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "engaged_descriptor": {
                        "type": "string",
                        "description": (
                            "Como o input ou a cena se refere a quem o player "
                            "engaja, na linguagem da cena."
                        ),
                    },
                    "matched_card_id": {
                        "type": ["string", "null"],
                        "description": (
                            "id de agents-known/active_cards que corresponde a "
                            "esse personagem (copy-paste), ou null se figurante "
                            "anonimo sem card."
                        ),
                    },
                    "has_card": {"type": "boolean"},
                    "physically_in_scene": {
                        "type": "boolean",
                        "description": (
                            "true se esta no setor da cena atual (mesmo que "
                            "tenha chegado ou saido neste turn)."
                        ),
                    },
                    "in_npcs_in_scene": {
                        "type": "boolean",
                        "description": (
                            "TRUE obrigatorio se has_card=true E "
                            "physically_in_scene=true: ai o matched_card_id DEVE "
                            "aparecer em npcs_in_scene_planned_ids (e em "
                            "npcs_in_scene[]). Personagem com card que o player "
                            "engaja nao pode ficar so em world_memory_relevant "
                            "ou no ambient."
                        ),
                    },
                },
                "required": [
                    "engaged_descriptor", "matched_card_id", "has_card",
                    "physically_in_scene", "in_npcs_in_scene",
                ],
            },
        },
        "npcs_in_scene_reference_only": {
            "type": "string",
            "enum": ["aponto_agent_id_de_card_real_a_mente_e_do_narrador"],
            "description": (
                "Releia cada entry de npcs_in_scene[] antes de emitir. Cada uma e so "
                "REFERENCIA: agent_id (copy-paste de agents-known/active_cards) + "
                "skip_agent_call. A ficha, a persona, a mente e a fala do NPC sao do "
                "Narrador (mind-snapshot montado pela engine), nao entram na entry. "
                "Personagem sem card nao entra em npcs_in_scene."
            ),
        },
        "arrival_scene_audit": {
            "type": ["object", "null"],
            "description": (
                "Preencha SO quando QUALQUER campo de arrival_triggers != null (o "
                "player CHEGA a uma ilha neste turn, por mar/deriva/elipse). null "
                "quando nao ha chegada. Forca a cena a nascer NA ilha de chegada, "
                "nao no porto/ilha de partida nem no mar."
            ),
            "properties": {
                "arriving_island_slug": {
                    "type": "string",
                    "description": "Slug de arrival_triggers (research_pipeline ou island_designer).",
                },
                "scene_location_literal": {
                    "type": "string",
                    "description": "Copia textual de scene.location que voce vai emitir.",
                },
                "scene_is_at_arriving_island": {
                    "type": "boolean",
                    "description": (
                        "TRUE so se scene.location descreve a ILHA DE CHEGADA (terra "
                        "nova), nao a ilha/porto de partida nem o mar. Se voce salta "
                        "tempo/mar pra chegar (elipse_de_tempo), monte JA a cena na "
                        "ilha nova: scene.location, area_slug e npcs_in_scene do "
                        "lugar novo."
                    ),
                },
            },
            "required": [
                "arriving_island_slug", "scene_location_literal",
                "scene_is_at_arriving_island",
            ],
        },
        "scene_location_audit": {
            "type": "object",
            "description": (
                "Releia a string scene.location que vai emitir e ateste que ela nomeia "
                "SO o lugar — sem acao, sem NPC, sem verbo de movimento/combate. A acao "
                "da cena e do Narrador, nao do rotulo de lugar."
            ),
            "properties": {
                "scene_location_literal": {
                    "type": "string",
                    "description": "Copia textual de scene.location que voce vai emitir.",
                },
                "names_place_only": {
                    "type": "string",
                    "enum": ["nomeio_so_o_lugar_sem_acao_nem_npc"],
                },
            },
            "required": ["scene_location_literal", "names_place_only"],
        },
        "news_coo_decision": {
            "type": "object",
            "description": (
                "Releia world_state.news_signals ANTES de decidir news_coo_arrival. "
                "Ateste o que ha de peso e a decisao. Sem peso, news_coo_arrival e null."
            ),
            "properties": {
                "peso_atestado": {
                    "type": "string",
                    "description": "O que ha de noticia de peso agora (bounty/marco/evento/NPC), ou 'nada'.",
                },
                "decision": {
                    "type": "string",
                    "enum": [
                        "emito_jornal_com_noticia_de_peso",
                        "sem_peso_deixo_null",
                    ],
                },
            },
            "required": ["peso_atestado", "decision"],
        },
    },
    "required": [
        "paired_mushis_literal",
        "player_position_cluster_literal",
        "incoming_callers_evaluation",
        "crew_in_combat_scene_literal",
        "npcs_in_scene_planned_ids",
        "scene_cast_audit",
        "hostage_grab_evaluation",
        "recruitment_intent_audit",
        "timeskip_intent_audit",
        "player_engaged_cast_audit",
        "npcs_in_scene_reference_only",
        "arrival_scene_audit",
        "scene_location_audit",
        "news_coo_decision",
    ],
}

EMIT_PRE_TURN_TOOL = {
    "name": "emit_pre_turn_decisions",
    "description": (
        "Emite TODAS as decisoes pre-turn do Diretor numa unica chamada. "
        "Preencha pre_emit_audit PRIMEIRO (citacao literal dos campos do input "
        "que travam gates de pareamento/cluster/crew-skip) — isso e scratchpad "
        "obrigatorio que voce usa pra DECIDIR as flags abaixo; nao e cosmetico. "
        "Depois preencha scene (location/area_slug/tension_level/mode A|B|C; sem ambient), "
        "npcs_in_scene[] (com skip_agent_call coerente com pre_emit_audit), "
        "npc_location_updates[] (uma entry por agent_id que scene_cast_audit "
        "marcou moves_this_turn=true — quem entra no setor da cena E quem sai), "
        "scene_transition (elipse_de_tempo | null — §2.1.1), "
        "crew_present_in_scene[], active_cards[], world_memory_relevant, "
        "plot_armor_engaged, pre-flags (surprise_actions, breakthrough_imminent, "
        "incoming_mushi_call coerente com pre_emit_audit.incoming_callers_evaluation, "
        "outgoing_mushi_call, mushi_call_active, vivre_card_state_change), "
        "arrival_triggers, sea_destination_choice (destino de mar real quando o player "
        "zarpa/desvia sem nomear a ilha), offer_training, offer_training_rejected, "
        "player_recruitment_intent (convite de crew do player a NPC presente), "
        "player_offer_response (resposta a oferta de crew pendente), "
        "timeskip_intent (o input engaja treino/timeskip: accepted|requested|none), "
        "plant_thread (fio de continuidade OPCIONAL — null na maioria dos turns). "
        "Chame UMA vez por turn."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pre_emit_audit": _PRE_EMIT_AUDIT,
            "thread_reasoning": _THREAD_REASONING,
            "plant_thread": _PLANT_THREAD,
            "scene": {
                "type": "object",
                "description": (
                    "Cena atual: location (prosa curta SO do lugar) + area_slug (sub-area da "
                    "ilha, slug estavel, chave mecanica de presenca, §2.1) + tension_level + "
                    "modo de orquestracao A|B|C (master §2.2). FASE 27: voce NAO compoe ambient; "
                    "quem pinta o cenario e o Narrador (master §2.9)."
                ),
                "properties": {
                    "location": {
                        "type": "string",
                        "description": (
                            "Prosa curta que nomeia SO o lugar da cena (regiao/ilha + sub-area). "
                            "Nao narra acao, nao cita NPC, nao usa verbo de movimento/combate — a "
                            "acao e do Narrador. So onde a cena acontece."
                        ),
                    },
                    "area_slug": {
                        "type": "string",
                        "description": (
                            "Slug curto e ESTAVEL da sub-area dentro da ilha (ex.: 'bar', "
                            "'cais', 'praca'): minusculas, sem espaco. MESMO lugar = MESMO "
                            "slug turn a turn — reuse o que ja aparece em AGENTS-LOCATIONS pra "
                            "aquele setor. A engine ancora os npcs_in_scene em ilha/area_slug; "
                            "quem fica noutro slug e off-scene perto. Vazio so sem sub-area "
                            "resolvivel (mar aberto, viagem)."
                        ),
                    },
                    "island_slug": {
                        "type": "string",
                        "description": (
                            "id LITERAL da ilha catalogada onde a cena acontece — copie o id= de "
                            "um <circle> do WORLD-MAP. Preencha SO quando o player chega a "
                            "PE a outra ilha da mesma massa de terra (mesmo cluster/regiao, sem "
                            "travessia de mar); a engine sincroniza a posicao de mundo e o mapa. "
                            "Vazio mantem a ilha atual — use vazio pra um lugar novo que e apenas "
                            "sub-area (vai em area_slug) e pra travessia de mar (vai em "
                            "world_movement no POST)."
                        ),
                    },
                    "tension_level": {
                        "type": "string",
                        "enum": ["calm", "alert", "hostile", "combat", "aftermath"],
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["A", "B", "C"],
                        "description": (
                            "A=sequencial reativo (default em duvida); "
                            "B=paralelo independente (mesmo gatilho); "
                            "C=hibrido (paralelo + sequencial depois). "
                            "Usado so no caminho de combate (cena social: o Narrador orquestra)."
                        ),
                    },
                },
                "required": ["location", "tension_level", "mode"],
            },
            "npcs_in_scene": {
                "type": "array",
                "description": (
                    "Array NATIVO de objetos-REFERENCIA (NAO string, NAO a ficha do NPC). Cada "
                    "entry so APONTA um card existente: agent_id (copy-paste de agents-known/"
                    "active_cards) + skip_agent_call + briefing_note opcional. A persona, a mente "
                    "e a fala do NPC ficam FORA daqui — sao do Narrador, via mind-snapshot que a "
                    "engine monta do card. NPC sem card nao entra por aqui; figurante anonimo o "
                    "Narrador improvisa via active_cards. skip_agent_call=true SO em crewmate "
                    "on-scene em combate (combat addendum §4). Inclua TODOS os ids de "
                    "pre_emit_audit.npcs_in_scene_planned_ids — sem omitir crewmates."
                ),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "agent_id": {
                            "type": "string",
                            "description": "id de um card real (agents-known/active_cards), copy-paste.",
                        },
                        "skip_agent_call": {"type": "boolean"},
                        "briefing_note": {
                            "type": "string",
                            "description": "Opcional. 1 frase contextual pro agente.",
                        },
                    },
                    "required": ["agent_id", "skip_agent_call"],
                },
            },
            "npc_location_updates": {
                "type": "array",
                "description": (
                    "Canal UNICO de movimento de NPC neste turn — quem ENTRA no setor da "
                    "cena E quem SAI dele. Para CADA agent_id que o scene_cast_audit marcou "
                    "moves_this_turn=true (location_now != registered), emita uma entry com "
                    "esse new_location. A engine aplica ANTES de montar a cena, entao a "
                    "posicao ja esta certa quando ela decide quem esta em quadro: quem voce "
                    "trouxe pro setor da cena casa e fica; quem nao moveu permanece onde "
                    "estava (off-scene) sem voce precisar lista-lo. new_location e "
                    "'ilha/sub-area' — pode nomear um lugar que a historia acabou de criar. "
                    "Vazio so quando ninguem se desloca."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "agent_id": {"type": "string"},
                        "new_location": {
                            "type": "string",
                            "description": "Onde o NPC esta agora, formato 'ilha/sub-area'.",
                        },
                        "reason": {
                            "type": "string",
                            "description": "1 frase: o fato estabelecido que poe o NPC la.",
                        },
                    },
                    "required": ["agent_id", "new_location", "reason"],
                },
            },
            "scene_transition": {
                "type": ["object", "null"],
                "description": (
                    "Transicao por SALTO DE TEMPO deste turn (§2.1.1). null/omitido = a cena segue no "
                    "mesmo momento — INCLUSIVE quando o player se desloca pra outro lugar AGORA: isso o "
                    "Narrador encena dentro do turn e o lugar final volta no pos-turn via scene_end; NAO "
                    "sinalize aqui nem pre-monte o destino. Use SO quando o proximo beat exige um salto "
                    "de tempo (horas/dias/anos) que o player nao atravessa agindo: monte JA a cena "
                    "pos-salto (scene/area_slug e npcs_in_scene da cena NOVA, e mova quem saiu via "
                    "npc_location_updates) e ponha em note quanto saltou + o que mudou. O Narrador fecha "
                    "o beat anterior, salta o tempo por volta da metade da prosa e abre a cena nova na "
                    "segunda metade. Mover alguem pra um destino-de-tempo (mar, outra ilha) E a propria "
                    "elipse — sinalize junto; sem o sinal o Narrador nao da o salto e o NPC some do "
                    "quadro sem partida."
                ),
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["elipse_de_tempo"],
                    },
                    "note": {
                        "type": "string",
                        "description": "quanto tempo saltou + o que mudou na cena nova.",
                    },
                },
                "required": ["kind", "note"],
            },
            "crew_present_in_scene": {
                "type": "array",
                "description": (
                    "agent_ids de crewmates fisicamente presentes na cena atual. "
                    "Vazio se nenhum crewmate on-scene."
                ),
                "items": {"type": "string"},
            },
            "active_cards": {
                "type": "array",
                "description": (
                    "Cards ativos pro Opus consultar: NPCs in-scene + crewmates + "
                    "location + faction dominante + mencionados nos ultimos 30 turns "
                    "+ canon-near do arco da ilha. Master §2.3."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "aliases": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["id", "name"],
                },
            },
            "world_memory_relevant": {
                "type": "string",
                "description": (
                    "Resumo curto pro Opus orientar coerencia (master §2.4). "
                    "Pode ser vazio se nada relevante."
                ),
            },
            "plot_armor_engaged": {
                "type": "boolean",
                "description": (
                    "True quando combate em near-death contra tier muito superior "
                    "(combat addendum §6) ja foi engajado neste turn."
                ),
            },
            "surprise_actions": {
                "type": "array",
                "description": (
                    "NPCs tentando ataque sorrateiro / ambush / aggressive_reaction "
                    "/ betrayal / hostage_grab neste turn (combat addendum §2.4 + "
                    "tactical addendum §A). Vazio se ninguem tenta surpresa. type "
                    "'hostage_grab' = um NPC sem escrupulos agarra um terceiro ao "
                    "alcance de repente (exige hostage_npc_id dominavel e persona "
                    "compativel — good/codigo de honra NAO faz hostage_grab)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "actor_npc_id": {"type": "string"},
                        "type": {
                            "type": "string",
                            "enum": [
                                "attack", "ambush", "aggressive_reaction",
                                "betrayal", "hostage_grab",
                            ],
                        },
                        "hostage_npc_id": {
                            "type": "string",
                            "description": (
                                "Obrigatorio quando type == 'hostage_grab'. Id do "
                                "terceiro agarrado — NPC ao alcance do ator e dominavel "
                                "por ele (tier(refem) <= tier(ator))."
                            ),
                        },
                        "player_perception_outcome": {
                            "type": "string",
                            "enum": ["connect", "in_extremis", "anticipated"],
                        },
                        "rationale": {
                            "type": "string",
                            "description": "1 linha PT-BR explicando calibracao da perception.",
                        },
                    },
                    "required": ["actor_npc_id", "type", "player_perception_outcome", "rationale"],
                },
            },
            "breakthrough_imminent": {
                "type": ["object", "null"],
                "description": (
                    "Flag pre-turn pra primar Opus a narrar com nuance climatica "
                    "(combat addendum §5). null quando nenhum breakthrough qualifica "
                    "(gating canon por kind)."
                ),
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": [
                            "fruit_awakening",
                            "black_blade",
                            "haoshoku_imbuing",
                            "voice_of_all_things",
                            "advanced_armament",
                            "advanced_observation",
                        ],
                    },
                    "target_card_id": {
                        "type": "string",
                        "description": (
                            "FRUIT id (fruit_awakening) ou ITEM id (black_blade). "
                            "Ausente nos 4 player-only."
                        ),
                    },
                    "context": {
                        "type": "string",
                        "description": "1-2 frases PT-BR: por que agora + tipo de climax.",
                    },
                },
                "required": ["kind", "context"],
            },
            "incoming_mushi_call": {
                "type": ["object", "null"],
                "description": (
                    "Chamada de NPC pro player (mushi addendum §1.3). null se nenhum "
                    "agente passou os checks de pareamento + status + alcance."
                ),
                "properties": {
                    "caller_npc_id": {"type": "string"},
                    "mushi_kind": {"type": "string", "enum": ["baby", "standard", "visual"]},
                    "caller_motive_hint": {
                        "type": "string",
                        "description": "1 frase do output JSON do agente.",
                    },
                },
                "required": ["caller_npc_id", "mushi_kind", "caller_motive_hint"],
            },
            "outgoing_mushi_call": {
                "type": ["object", "null"],
                "description": (
                    "Chamada do player pra NPC (mushi addendum §2.2). null se nao "
                    "houve intent de ligar OU se alvo nao identificado / sem pairing "
                    "(pode tambem ser preenchido com target_unavailable=true pra Opus "
                    "narrar tentativa frustrada)."
                ),
                "properties": {
                    "target_npc_id": {"type": "string"},
                    "mushi_kind": {"type": "string", "enum": ["baby", "standard", "visual"]},
                    "target_unavailable": {
                        "type": "boolean",
                        "description": "true quando alvo nao alcancavel / nao paired.",
                    },
                },
                "required": ["target_npc_id", "mushi_kind", "target_unavailable"],
            },
            "mushi_call_active": {
                "type": ["object", "null"],
                "description": (
                    "Chamada em curso entre turns (mushi addendum §1.4). null se "
                    "nenhuma chamada ativa."
                ),
                "properties": {
                    "caller_npc_id": {"type": "string"},
                    "kind": {"type": "string", "enum": ["incoming", "outgoing"]},
                    "mushi_kind": {"type": "string", "enum": ["baby", "standard", "visual"]},
                    "started_at_turn_index": {"type": "integer"},
                },
                "required": ["caller_npc_id", "kind", "mushi_kind", "started_at_turn_index"],
            },
            "vivre_card_state_change": {
                "type": ["object", "null"],
                "description": (
                    "Mudanca de visual state em vivre card que player possui "
                    "(mushi addendum §3.3). SO emite se player tem card desse NPC. "
                    "null se sem mudanca aplicavel."
                ),
                "properties": {
                    "npc_id": {"type": "string"},
                    "old_visual_state": {
                        "type": ["string", "null"],
                        "enum": ["white", "burning", "errant", "ashes", None],
                    },
                    "new_visual_state": {
                        "type": "string",
                        "enum": ["white", "burning", "errant", "ashes"],
                    },
                    "cause_hint": {
                        "type": "string",
                        "description": "1 frase: por que mudou, pro Opus narrar.",
                    },
                },
                "required": ["npc_id", "new_visual_state", "cause_hint"],
            },
            "intercepted_transmission": {
                "type": ["object", "null"],
                "description": (
                    "Black Den Den Mushi (mushi addendum §7.2): transmissao que o player "
                    "INTERCEPTA neste turn. So preenche se o player tem grampo no alvo "
                    "(tapped_npc_id in player.black_mushi_taps[]) E o alvo esta se comunicando "
                    "off-scene neste turn. null caso contrario."
                ),
                "properties": {
                    "tapped_npc_id": {"type": "string", "description": "NPC grampeado cuja linha o player ouve."},
                    "other_party_hint": {
                        "type": ["string", "null"],
                        "description": "Com quem o alvo fala (id ou descricao), se sabido. null se voz unica.",
                    },
                    "gist": {"type": "string", "description": "1-2 frases PT-BR: o que o player ouve pelo grampo."},
                },
                "required": ["tapped_npc_id", "gist"],
            },
            "surveillance_alert": {
                "type": ["object", "null"],
                "description": (
                    "White Den Den Mushi (mushi addendum §7.3): o contra-grampo do player "
                    "DETECTOU que alguem o escuta. So preenche se player.white_mushi_active E "
                    "ha grampo nele (metadata.taps_on_player nao vazio). null caso contrario."
                ),
                "properties": {
                    "watcher_hint": {
                        "type": ["string", "null"],
                        "description": "Quem grampeia (faccao/NPC), se inferivel. null se so 'alguem'.",
                    },
                    "detail": {"type": "string", "description": "1 frase PT-BR: o que o white mushi acusa."},
                },
                "required": ["detail"],
            },
            "arrival_triggers": {
                "type": "object",
                "description": (
                    "Disparos de research na primeira chegada em ilha (master §2.7). "
                    "Ilha canonica primeira vez -> research_pipeline preenchido, island_designer "
                    "null. Ilha inventada primeira vez -> island_designer preenchido, "
                    "research_pipeline null. Ilha ja visitada / sem chegada -> ambos null. "
                    "A ilha nasce neutra: research e contexto de fundo, nao trama imposta."
                ),
                "properties": {
                    "research_pipeline": {"type": ["string", "null"], "description": "island_slug ou null."},
                    "island_designer": {"type": ["string", "null"], "description": "island_slug ou null."},
                },
                "required": ["research_pipeline", "island_designer"],
            },
            "sea_destination_choice": {
                "type": ["object", "null"],
                "description": (
                    "Destino de mar que VOCE escolhe quando o player zarpa/desvia rumo a um lugar "
                    "que NAO nomeou — pediu por CRITERIO ('uma ilha a oeste', 'o proximo porto', "
                    "'terra pra se esconder') ou perguntou o nome do destino a um NPC. Escolha no "
                    "WORLD-MAP uma ilha REAL plausivel pela posicao (descoberta ou nao; varie, nao a "
                    "mais famosa) e devolva {island_id, display_name} — o Narrador diz esse nome na "
                    "prosa em vez de inventar um. null quando o player JA nomeou a ilha, ou nao ha "
                    "navegacao a decidir neste turn. NUNCA cunhe ilha fora do catalogo em mar canon."
                ),
                "properties": {
                    "island_id": {"type": "string", "description": "id LITERAL de um <circle> do WORLD-MAP."},
                    "display_name": {"type": "string", "description": "data-name da ilha escolhida (nome pra prosa)."},
                },
                "required": ["island_id", "display_name"],
            },
            "opening_known_island_ids": {
                "type": ["array", "null"],
                "items": {"type": "string"},
                "description": (
                    "SO no turno de abertura: island_ids (do WORLD-MAP) que ESTE personagem "
                    "plausivelmente ja conhece pela origem/historia/era. A engine acende o fog "
                    "dessas ilhas uma vez. null/omitido deixa a engine usar a vizinhanca de regiao "
                    "como padrao. Ignorado fora da abertura."
                ),
            },
            "offer_training": {
                "type": ["object", "null"],
                "description": (
                    "Oferta valida de timeskip (offer_training addendum §2.1/§2.2). "
                    "null se a oferta nao passa nos 4 eixos (mentor + rota + mundo + "
                    "expertise) OU se nao ha trigger de oferta neste turn."
                ),
                "properties": {
                    "mentor_npc_id": {"type": "string"},
                    "duration_hint": {"type": ["string", "null"], "description": "Texto livre da duracao pra prosa ('2 anos', 'alguns meses'), ou null."},
                    "duration_days": {
                        "type": "integer",
                        "description": (
                            "Duracao do treino em DIAS (inteiro) — voce converte o duration_hint: "
                            "'2 anos'=730, '1 ano'=365, '6 meses'=180, 'alguns meses'~150, 'longo/aberto'~540. "
                            "E o numero que avanca o relogio; sem ele o tempo nao passa."
                        ),
                    },
                    "focus_hint": {"type": ["string", "null"]},
                    "location_hint": {"type": ["string", "null"]},
                    "mentor_motive": {"type": "string"},
                    "friction_hint": {
                        "type": "string",
                        "description": "Opcional. 1-2 frases pra pass_with_friction.",
                    },
                },
                "required": ["mentor_npc_id", "mentor_motive", "duration_days"],
            },
            "offer_training_rejected": {
                "type": ["object", "null"],
                "description": (
                    "Recusa narrada via fricção (offer_training addendum §2.3). "
                    "null se nao houve trigger de recusa."
                ),
                "properties": {
                    "mentor_npc_id": {"type": "string"},
                    "rejection_reason_narrative": {
                        "type": "string",
                        "description": "1-2 frases PT-BR: que obstaculo o player percebe.",
                    },
                },
                "required": ["mentor_npc_id", "rejection_reason_narrative"],
            },
            "player_recruitment_intent": {
                "type": ["object", "null"],
                "description": (
                    "FASE 13. Convite de recrutamento do player a um NPC PRESENTE neste turn "
                    "(crew recruitment addendum). Preencha quando o player, no input, oferece a "
                    "um NPC da cena entrar no bando dele — INDEPENDENTE da redacao (parafrase "
                    "vale). null pra elogio, pergunta, mencao do bando sem convite, recusa, ou "
                    "hipotese. Coerente com pre_emit_audit.recruitment_intent_audit. A engine "
                    "rola a aceitacao (sigmoid); aqui voce so identifica o alvo."
                ),
                "properties": {
                    "target_npc_id": {
                        "type": "string",
                        "description": "agent_id do NPC presente (de npcs_in_scene) que o player convida.",
                    },
                    "evidence_quote": {
                        "type": "string",
                        "description": "Trecho literal do input do player que expressa o convite.",
                    },
                },
                "required": ["target_npc_id", "evidence_quote"],
            },
            "player_offer_response": {
                "type": ["object", "null"],
                "description": (
                    "FASE 13. Resposta do player a uma oferta de crew NPC-iniciada PENDENTE (um "
                    "NPC pediu pra entrar no bando em turn anterior; lista em "
                    "world_state.pending_crew_offers). Preencha quando o player aceita ou recusa "
                    "essa oferta — INDEPENDENTE da redacao. null se nao ha oferta pendente OU o "
                    "input nao responde a ela. Coerente com pre_emit_audit.recruitment_intent_audit."
                ),
                "properties": {
                    "target_npc_id": {
                        "type": "string",
                        "description": "npc_id da oferta pendente (de pending_crew_offers) que o player responde.",
                    },
                    "response": {"type": "string", "enum": ["accept", "reject"]},
                    "evidence_quote": {
                        "type": "string",
                        "description": "Trecho literal do input do player que expressa o aceite/recusa.",
                    },
                },
                "required": ["target_npc_id", "response", "evidence_quote"],
            },
            "timeskip_intent": {
                "type": "string",
                "enum": ["accepted", "requested", "none"],
                "description": (
                    "Leitura do input do player quanto a ENGAJAR um treino/timeskip neste turn "
                    "(offer_training addendum §2.4). 'requested': o player, no proprio input, PEDE "
                    "treino/timeskip (qualquer redacao — parafrase vale). 'accepted': o player "
                    "ACEITA a oferta de treino pendente em world_state.pending_training_offer (um "
                    "mentor ofereceu antes). 'none': o input nao engaja treino agora. So 'accepted' "
                    "quando ha pending_training_offer real E o input responde a ela; so 'requested' "
                    "quando o player de fato pede treino. Elogio ao mentor, pergunta, mencao do "
                    "assunto sem querer treinar agora, ou recusa => 'none'. Coerente com "
                    "pre_emit_audit.timeskip_intent_audit."
                ),
            },
            "withdraw_pending_offer": {
                "type": "boolean",
                "description": (
                    "true SO quando ha uma pending_training_offer viva em world_state E o player "
                    "mudou de rumo de modo que a oferta perdeu sentido (partiu da ilha do mentor, "
                    "recusou de vez, o mentor sumiu/morreu, o arco virou outra coisa). Retira a "
                    "oferta pendente. false por padrao: uma oferta viva permanece ate ser aceita "
                    "ou retirada aqui."
                ),
            },
            "economy_relevant": {
                "type": "boolean",
                "description": (
                    "A cena toca dinheiro de forma ATIVA neste turn (compra, venda, suborno, "
                    "recompensa, saque, preco, contrato, taverna/loja). false quando economia nao "
                    "entra na acao; o Narrador cobre o resto pela regra base."
                ),
            },
            "ship_relevant": {
                "type": "boolean",
                "description": (
                    "A cena toca navio/navegacao neste turn (casco, estaleiro, zarpar, ancorar, "
                    "rumo, bandeira/Jolly Roger, frota, naufragio, mar adentro). false quando navio "
                    "nao entra na acao."
                ),
            },
            "news_coo_arrival": {
                "type": ["object", "null"],
                "description": (
                    "Sinal OPCIONAL: a News Coo (ave-jornaleira) chega na cena neste turn. Decida "
                    "pelo CONTEXTO, nunca por agendamento. So emita quando houver noticia de PESO "
                    "REAL em world_state.news_signals: salto do bounty do jogador "
                    "(player_bounty_updates: old_amount->new_amount), evento grande do mundo "
                    "(major_unpublished_events), ou mudanca importante de NPC ligado ao jogador. "
                    "Voce julga o peso; nao ha flag que decida por voce. O jornal NUNCA chega "
                    "vazio: sem peso, deixe null (a maioria dos turns e null). Prefira um momento em "
                    "que a entrega cabe na cena; nao force se o turn pede outra coisa. O Narrador "
                    "encena a chegada e a repercussao; aqui voce so decide que chega e o foco da capa."
                ),
                "properties": {
                    "trigger_reason": {
                        "type": "string",
                        "enum": [
                            "bounty_milestone", "bounty_jump", "major_world_event",
                            "npc_death_or_capture", "crew_change", "other",
                        ],
                    },
                    "cover_focus": {
                        "type": "string",
                        "enum": ["player", "world", "other_character"],
                        "description": "Sobre quem/o que e a capa.",
                    },
                    "headline_seed": {
                        "type": "string",
                        "description": "Pista curta (poucas palavras) e factual do que esta na capa.",
                    },
                    "context_memo": {
                        "type": "string",
                        "description": "1 frase factual: por que esta noticia chega agora.",
                    },
                },
                "required": ["trigger_reason", "cover_focus", "headline_seed"],
            },
        },
        "required": [
            "pre_emit_audit",
            "scene",
            "npcs_in_scene",
            "npc_location_updates",
            "crew_present_in_scene",
            "active_cards",
            "world_memory_relevant",
            "plot_armor_engaged",
            "surprise_actions",
            "breakthrough_imminent",
            "incoming_mushi_call",
            "outgoing_mushi_call",
            "mushi_call_active",
            "vivre_card_state_change",
            "intercepted_transmission",
            "surveillance_alert",
            "arrival_triggers",
            "offer_training",
            "offer_training_rejected",
            "player_recruitment_intent",
            "player_offer_response",
            "withdraw_pending_offer",
            "economy_relevant",
            "ship_relevant",
            "timeskip_intent",
            "news_coo_arrival",
        ],
    },
}


def _instructions(extra_addenda: list[str] | None = None) -> str:
    """Concatenate master + addenda; extra_addenda appends conditional addenda."""
    files = _PROMPT_FILES + list(extra_addenda or [])
    parts = [(config.PROMPTS_DIR / f).read_text(encoding="utf-8") for f in files]
    return "\n\n---\n\n".join(parts)


def _addenda_text(extra_addenda: list[str] | None) -> str | None:
    """Conditional addenda as a separate volatile block, kept OUT of the cached instructions
    prefix. A nemesis entering/leaving toggles these; concatenating them into the static prefix
    would bust the 1h cache breakpoint every time (the Narrator routes addenda the same way)."""
    if not extra_addenda:
        return None
    parts = [(config.PROMPTS_DIR / f).read_text(encoding="utf-8") for f in extra_addenda]
    return "\n\n---\n\n".join(parts)


def _coerce_to_list(value) -> list:
    """Coerce npcs_in_scene to a list: json.loads, falling back to brace-matching."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        s = value.strip()
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
        i, j = s.find("["), s.rfind("]")
        if 0 <= i < j:
            try:
                parsed = json.loads(s[i : j + 1])
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                pass
    return []


def _sanitize_npcs_in_scene(raw: list) -> tuple[list[dict], list[dict]]:
    """Keep only reference entries {agent_id, skip_agent_call, briefing_note}; agent_id required.
    Returns (kept, dropped). Dropped = entries with no usable agent_id (the model dumped a rich
    mind-snapshot in place of a reference); a light summary is kept for diagnostics, not the ficha."""
    kept: list[dict] = []
    dropped: list[dict] = []
    for e in raw:
        if isinstance(e, dict) and str(e.get("agent_id") or "").strip():
            kept.append({
                "agent_id": str(e["agent_id"]).strip(),
                "skip_agent_call": bool(e.get("skip_agent_call")),
                "briefing_note": str(e.get("briefing_note") or "").strip(),
            })
        else:
            dropped.append(
                {"name": e.get("name"), "keys": sorted(e.keys())}
                if isinstance(e, dict) else {"type": type(e).__name__}
            )
    return kept, dropped


def parse_pre_turn(emitted: dict | None) -> dict:
    """Normalize Director output: drop pre_emit_audit, default all top-level fields,
    coerce npcs_in_scene string-of-JSON to a list."""
    emitted = dict(emitted or {})
    emitted.pop("pre_emit_audit", None)

    out: dict = {k: (v.copy() if isinstance(v, (dict, list)) else v) for k, v in _PRE_TURN_DEFAULTS.items()}
    for k, v in emitted.items():
        if k in _PRE_TURN_DEFAULTS:
            out[k] = v

    # npcs_in_scene is a reference list ({agent_id, skip_agent_call}); strip any rich mind-snapshot
    # the model dumped in place of a reference. dropped entries (no agent_id) drive one retry via
    # _is_valid and surface as a diagnostic for the runner.
    _kept_nis, _dropped_nis = _sanitize_npcs_in_scene(_coerce_to_list(out.get("npcs_in_scene")))
    out["npcs_in_scene"] = _kept_nis
    out["malformed_npcs_in_scene"] = _dropped_nis
    out["npc_location_updates"] = [
        u for u in _coerce_to_list(out.get("npc_location_updates")) if isinstance(u, dict)
    ]
    st = out.get("scene_transition")
    if isinstance(st, dict) and st.get("kind") == "elipse_de_tempo" and str(st.get("note") or "").strip():
        out["scene_transition"] = {"kind": st["kind"], "note": str(st["note"]).strip()}
    else:
        out["scene_transition"] = None
    # Opt-in continuity thread (FASE 30): keep only a dict with a real hook_summary; null otherwise.
    pt = out.get("plant_thread")
    if isinstance(pt, dict) and str(pt.get("hook_summary") or "").strip():
        out["plant_thread"] = {
            "hook_summary": str(pt["hook_summary"]).strip(),
            "theme_tag": str(pt.get("theme_tag") or "").strip(),
            "where_hint": str(pt.get("where_hint") or "").strip(),
        }
    else:
        out["plant_thread"] = None
    if not isinstance(out.get("crew_present_in_scene"), list):
        out["crew_present_in_scene"] = []
    if not isinstance(out.get("active_cards"), list):
        out["active_cards"] = []
    oki = out.get("opening_known_island_ids")
    out["opening_known_island_ids"] = (
        [str(i).strip() for i in oki if str(i).strip()] if isinstance(oki, list) else None
    )
    sdc = out.get("sea_destination_choice")
    if isinstance(sdc, dict) and str(sdc.get("island_id") or "").strip():
        out["sea_destination_choice"] = {
            "island_id": str(sdc["island_id"]).strip(),
            "display_name": str(sdc.get("display_name") or "").strip(),
        }
    else:
        out["sea_destination_choice"] = None

    scene = out.get("scene") or {}
    if not isinstance(scene, dict):
        scene = {}
    out["scene"] = {
        "location": scene.get("location", ""),
        # Normalize the sub-area slug so persisted scene.area_slug matches agents_locations byte-for-byte.
        "area_slug": world_map.normalize_area_slug(scene.get("area_slug", "")),
        # Catalogued island id (exact match against world.islands); engine validates, blank = no move.
        "island_slug": str(scene.get("island_slug") or "").strip(),
        "ambient": scene.get("ambient", ""),
        # Keep the raw emitted values so _is_valid can reject an omitted/invalid gate and drive the retry.
        "tension_level": scene.get("tension_level", ""),
        "mode": scene.get("mode", ""),
    }
    if out.get("timeskip_intent") not in ("accepted", "requested", "none"):
        out["timeskip_intent"] = "none"
    out["withdraw_pending_offer"] = bool(out.get("withdraw_pending_offer"))
    out["economy_relevant"] = bool(out.get("economy_relevant"))
    out["ship_relevant"] = bool(out.get("ship_relevant"))
    # offer_training only fires a timeskip with a mentor + a positive-int duration_days (the clock
    # advance). A malformed offer is nulled here so it never fires a 0-day skip.
    ot = out.get("offer_training")
    if isinstance(ot, dict) and (ot.get("mentor_npc_id") or "").strip():
        dd = ot.get("duration_days")
        ot["duration_days"] = int(dd) if isinstance(dd, (int, float)) and int(dd) > 0 else None
        out["offer_training"] = ot if ot["duration_days"] else None
    else:
        out["offer_training"] = None
    return out


def _is_valid(parsed: dict) -> bool:
    sc = parsed.get("scene") or {}
    return (
        bool(sc.get("location"))
        and sc.get("tension_level") in ("calm", "alert", "hostile", "combat", "aftermath")
        and sc.get("mode") in ("A", "B", "C")
        and isinstance(parsed.get("npcs_in_scene"), list)
        # A dropped entry (rich ficha with no agent_id) drives a retry to get the reference right.
        and not parsed.get("malformed_npcs_in_scene")
    )


def validate_npc_location_updates(updates: list, npcs: dict, *, warnings: list | None = None) -> list[dict]:
    """Engine-side gate for npc_location_updates: any NPC with a real card, alive, with a
    non-empty new_location differing from the registered one. Covers BOTH cast pulled INTO the
    scene's sub-area and cast leaving it off-scene — the move lands before the presence gate so
    the slug the gate matches on is already current. Returns ready entries."""
    out: list[dict] = []
    for u in updates or []:
        if not isinstance(u, dict):
            continue
        aid = (u.get("agent_id") or "").strip()
        loc = (u.get("new_location") or "").strip()
        data = npcs.get(aid)
        if not data or not loc:
            continue
        # No-op (already there) is a legit drop. Moving a dead NPC is an incoherence: surface it as
        # a warning for the Auditor to reconcile (status change first), don't move.
        if data.get("current_location") == loc:
            continue
        if data.get("status") == "dead":
            if warnings is not None:
                warnings.append({
                    "kind": "moved_dead_npc", "agent_id": aid, "new_location": loc,
                    "note": "npc_location_update para NPC status=dead; move ignorado (reconcilie status antes de mover)",
                })
            continue
        out.append({"agent_id": aid, "new_location": loc, "reason": u.get("reason", "")})
    return out


async def call_pre_turn(
    pre_turn_state: dict, *, retries: int = 1, extra_addenda: list[str] | None = None,
    cached_sections: list[tuple[str, object]] | None = None,
) -> dict:
    """Run the Director pre-turn pass and return the parsed output (without pre_emit_audit).

    cached_sections (near-static cast/card catalog) gets its own cache breakpoint block
    before the dynamic state. Retries (up to `retries`) on invalid/truncated output or
    parse exception. extra_addenda appends conditional addenda.
    """
    parsed: dict | None = None
    last_exc: Exception | None = None
    for _attempt in range(retries + 1):
        try:
            emitted = await client.call_tool(
                model=config.DIRECTOR_MODEL,
                instructions=_instructions(),
                volatile_instructions=language.with_directive(_addenda_text(extra_addenda)),
                tag="director",
                sections=[("PRE-TURN-STATE", pre_turn_state)],
                cached_sections=cached_sections,
                tool=EMIT_PRE_TURN_TOOL,
                tool_name="emit_pre_turn_decisions",
                temperature=config.DIRECTOR_TEMPERATURE,
                max_tokens=4096,
                trace_label="Diretor · pré-turn",
            )
            parsed = parse_pre_turn(emitted)
            if _is_valid(parsed):
                return parsed
        except Exception as e:  # noqa: BLE001 retry covers truncation/parse
            last_exc = e
    if parsed is not None:
        sc = parsed.get("scene") or {}
        # Last-resort floor: retries exhausted on an invalid gate. Crave the safe default ONCE here,
        # not inside parse, so an omitted/invalid tension/mode drives the retry first.
        if sc.get("tension_level") not in ("calm", "alert", "hostile", "combat", "aftermath"):
            sc["tension_level"] = "calm"
        if sc.get("mode") not in ("A", "B", "C"):
            sc["mode"] = "A"
        parsed["scene"] = sc
        return parsed
    raise last_exc if last_exc is not None else RuntimeError("pre-turn sem output utilizável")


# Input assembly (engine state -> pre-turn contract).
def _agent_known_entry(data: dict, override_location: str | None = None) -> dict:
    """Project an NPC card into the matchmaking agents_known[] candidate. current_cluster
    feeds the baby mushi range gate."""
    loc = override_location or data.get("current_location", "")
    return {
        "agent_id": data.get("id", ""),
        "name": data.get("name", ""),
        "status": data.get("status", "alive"),
        "current_location": loc,
        "current_cluster": mushi.cluster_of(loc),
        "voice_notes": data.get("voice_notes", ""),
        "tier": data.get("tier", ""),
        "alignment_baseline": data.get("alignment_baseline", 0.0),
    }


def _bounty_amount(ps: dict) -> int:
    """player_snapshot.bounty is structured {current_amount,...}; accepts legacy int."""
    b = ps.get("bounty", 0)
    if isinstance(b, dict):
        return int(b.get("current_amount", 0) or 0)
    return int(b or 0)


# Near-static catalogs (own cache-breakpoint block). Rendering MUST be byte-identical turn
# to turn for cache hits. Ordering is append-only (created_at_turn_index, id): a card minted
# this campaign sorts to the END, so it never inserts mid-prefix and only its own delta
# re-caches (vs ordering by random uuid, which busts ~half the prefix on every new card).
def _catalog_sort_key(d: dict, ident: str) -> tuple:
    return (int(d.get("created_at_turn_index", 0) or 0), ident)


def build_card_catalog(state: dict) -> list[dict]:
    """Stable part of world_state.active_cards[]: id+name+aliases+type of every NPC/ITEM/FACTION.
    SHIPs excluded: role/hull_condition are volatile and travel in the dynamic active_cards."""
    rows: list[tuple] = []
    for d in (state.get("npcs") or {}).values():
        e = {"id": d.get("id", ""), "name": d.get("name", ""), "type": "NPC"}
        if d.get("aliases"):
            e["aliases"] = d["aliases"]
        rows.append((_catalog_sort_key(d, e["id"]), e))
    for d in (state.get("item_cards") or {}).values():
        e = {"id": d.get("id", ""), "name": d.get("name", ""), "type": d.get("type", "ITEM")}
        if d.get("aliases"):
            e["aliases"] = d["aliases"]
        rows.append((_catalog_sort_key(d, e["id"]), e))
    for d in (state.get("faction_cards") or {}).values():
        e = {"id": d.get("id", ""), "name": d.get("name", ""), "type": "FACTION"}
        if d.get("aliases"):
            e["aliases"] = d["aliases"]
        rows.append((_catalog_sort_key(d, e["id"]), e))
    return [e for _, e in sorted(rows, key=lambda r: r[0])]


def build_agents_catalog(state: dict) -> list[dict]:
    """Stable part of agents_known[] (PRE cached block): matchmaking identity of every NPC.
    No current_location/current_cluster (positions travel in dynamic agents_locations so
    frequent moves don't break the cache); present NPCs arrive re-projected in the dynamic
    agents_known[], which prevails."""
    rows: list[tuple] = []
    for d in (state.get("npcs") or {}).values():
        e = {
            "agent_id": d.get("id", ""),
            "name": d.get("name", ""),
            "status": d.get("status", "alive"),
            "voice_notes": d.get("voice_notes", ""),
            "tier": d.get("tier", ""),
            "alignment_baseline": d.get("alignment_baseline", 0.0),
        }
        rows.append((_catalog_sort_key(d, e["agent_id"]), e))
    return [e for _, e in sorted(rows, key=lambda r: r[0])]


def build_agents_locations(state: dict) -> dict:
    """Current positions of every NPC (volatile cast part, dynamic input):
    {agent_id: {"location", "cluster"}}. Complements the cached catalog; feeds location-match
    and the baby mushi range gate."""
    out = {}
    for d in (state.get("npcs") or {}).values():
        loc = d.get("current_location", "")
        out[d.get("id", "")] = {"location": loc, "cluster": mushi.cluster_of(loc)}
    return dict(sorted(out.items()))


def _islands_catalog_section(state: dict) -> tuple[str, object]:
    """Cached navigable-world map (SVG): every place island positioned + the fixed Grand Line Log
    Pose route. Volatile hints/fog/position stay dynamic in nav_summary."""
    metadata = (state.get("campaign") or {}).get("metadata") or {}
    return (
        "WORLD-MAP — mapa navegável do mundo (SVG legível: ilha = <circle id=destino>, rota do "
        "Log Pose em Paradise = <polyline>; distância em dias vem em world_state.navigable_hints)",
        world_map.world_map_svg(metadata),
    )


def pre_turn_cached_sections(state: dict) -> list[tuple[str, object]]:
    """cached_sections for the PRE pass (cast catalog + card catalog + island catalog)."""
    return [
        ("AGENTS-KNOWN-CATALOG (parte estável de agents_known[]: todos os NPCs, location de registro)",
         build_agents_catalog(state)),
        ("WORLD-CARDS-CATALOG (parte estável de world_state.active_cards[]: NPC/ITEM/FACTION)",
         build_card_catalog(state)),
        _islands_catalog_section(state),
    ]


def post_turn_cached_sections(state: dict) -> list[tuple[str, object]]:
    """cached_sections for the POST pass (card catalog + island catalog)."""
    return [
        ("WORLD-CARDS-CATALOG (parte estável de world_state.active_cards[]: NPC/ITEM/FACTION)",
         build_card_catalog(state)),
        _islands_catalog_section(state),
    ]


def _pending_training_offer(metadata: dict, npcs: dict, current_turn_index: int = 0) -> dict | None:
    """Pending mentor training offer surfaced to the PRE Director so it reads the player's input
    against it (timeskip_intent=accepted, or withdraw_pending_offer when it went stale). None when
    there is no offer or the mentor is gone."""
    pt = metadata.get("pending_offer_training")
    if not isinstance(pt, dict):
        return None
    mid = pt.get("mentor_npc_id")
    mentor = npcs.get(mid) if mid else None
    if not mentor or mentor.get("status", "alive") in ("dead", "missing"):
        return None
    return {
        "mentor_npc_id": mid,
        "mentor_name": mentor.get("name", ""),
        "focus_hint": pt.get("focus_hint"),
        "duration_hint": pt.get("duration_hint"),
        "duration_days": pt.get("duration_days"),
    }


def _world_state(
    player_card: dict, npcs: dict, metadata: dict, scene_location: str = "",
    ship_cards: dict | None = None, current_turn_index: int = 0,
) -> dict:
    pc = player_card.get("player_character") or {}
    ps = player_card.get("player_snapshot") or {}
    crew = [
        {
            "id": d.get("id", ""),
            "name": d.get("name", ""),
            "tier": d.get("tier", ""),
            "role": d.get("class", ""),
            "current_location": d.get("current_location", ""),
        }
        for d in npcs.values()
        if d.get("affiliation") == "player_crew"
    ]
    # The card catalog lives in the cached WORLD-CARDS-CATALOG block, out of the dynamic input.
    return {
        "player": {
            "id": player_card.get("id", "player"),
            "name": pc.get("name", ""),
            # The dream the player typed at creation; scene material for bonded NPCs
            # (charge/provoke/test it), never a quest tracker.
            "dream": pc.get("dream") or (player_card.get("character_creation") or {}).get("dream") or "",
            "tier": ps.get("tier") or pc.get("tier", ""),
            "fruit": ps.get("fruit") or pc.get("fruit"),
            "haki": ps.get("haki") or pc.get("haki", []),
            "bounty": {"current_amount": _bounty_amount(ps)},
            "alignment": ps.get("alignment"),
            "breakthroughs": [],
            # Raw belly as the plausibility lens for scene building; the Director characterizes
            # the financial situation from the number (no mechanical cap, no bucket quantization).
            "belly": economy.belly_amount(ps),
            # Communication state; Director validates pairing + range before injecting mushi calls
            # and detects vital transitions for vivre_card_state_change.
            "position_cluster": mushi.cluster_of(scene_location),
            "paired_mushis": mushi.director_paired_mushis(ps, npcs),
            "vivre_cards": mushi.director_vivre_cards(ps, npcs),
            # Player taps (black) + counter-tap (white) + who taps the player; gate intercepted/surveillance.
            "black_mushi_taps": mushi.director_black_taps(ps, npcs),
            "white_mushi_active": mushi.white_mushi_active(ps),
            "taps_on_player": mushi.taps_on_player(metadata),
            "fruit_usage_log": [],
            # Consolidated fighting style (null before the first tier-up).
            "fighting_style": ps.get("fighting_style"),
        },
        "crew": crew,
        # Pending NPC-initiated crew offers; Director crosses with input to classify player_offer_response.
        # Orphaned offers (missing/dead target) are omitted from the briefing.
        "pending_crew_offers": [
            {"npc_id": o.get("npc_id", ""), "npc_name": o.get("npc_name", "")}
            for o in (metadata.get("crew_offers") or [])
            if isinstance(o, dict) and o.get("npc_id")
            and o["npc_id"] in npcs
            and (npcs[o["npc_id"]].get("status", "alive") not in ("dead", "missing"))
        ],
        # Pending mentor training offer; Director crosses with input to classify timeskip_intent.
        "pending_training_offer": _pending_training_offer(metadata, npcs, current_turn_index),
        "chaos_meter": metadata.get("chaos_meter") or {"value": 0.0, "bucket": "calm"},
        # Fleet summary for staging Reverse Mountain / broken-hull-at-sea friction.
        "crew_fleet": ship.fleet_summary(ship.get_crew(metadata), ship_cards or {}),
        # Open continuity threads (age_in_turns crus, sem buckets); o Diretor pesa qualitativamente.
        "foreshadow_pool": plots.build_foreshadow_pool(metadata, current_turn_index),
        # Themes of threads already paid off (resolved leaves the pool projection); informational,
        # so a new thread does not replant a closed theme.
        "resolved_thread_themes_recent": plots.recent_resolved_theme_tags(metadata),
        "events_background_recent": metadata.get("events_background_recent") or [],
        "visited_islands": metadata.get("visited_islands") or [],
        # Active alliances for matchmaking + allied-faction hunter spawn-blocking.
        "crew_alliances": alliances.crew_alliances_of(metadata),
        # Organic News Coo: raw pending newsworthy material; the Director judges the weight.
        "news_signals": news_coo.build_news_signals(metadata, current_turn_index),
        # Public myth per target (player/crewmates) + germinable reactions from past editions.
        "legend_state": legend.legend_brief(metadata),
        "legend_repercussions": legend.reaction_seeds(metadata),
        # Position + navigable islands + pending sea hooks. Geography/routes live in the cached
        # WORLD-MAP (SVG); the Director reads it and chooses (no engine-side destination sampling).
        **world_map.nav_summary(metadata),
    }


def build_pre_turn_state(
    player_action: dict,
    state: dict,
    recent_prose: list[dict],
    *,
    agent_tick_outputs: list | None = None,
    previous_turn_state: dict | None = None,
    active_directives: list[str] | None = None,
    current_turn_index: int = 0,
) -> dict:
    """Build the pre-turn input contract from engine state.

    state is the runner._load_state dict. active_directives[] (active META directive text)
    is injected so the Director honors player authority when building the briefing.
    """
    scene = state.get("scene") or {}
    npcs: dict = state.get("npcs") or {}
    metadata = (state.get("campaign") or {}).get("metadata") or {}
    present_ids = set(metadata.get("present_npc_ids") or [])
    scene_location = scene.get("location", "")

    # Dynamic part of agents_known[]: only NPCs present at the end of the previous turn, with the
    # card's real current_location. Matches agents_locations and off-scene slugs; scene prose
    # arrives separately in scene_current.location. The dynamic entry prevails over the catalog one.
    agents_known = [
        _agent_known_entry(data)
        for cid, data in npcs.items()
        if cid in present_ids
    ]
    if previous_turn_state is None:
        previous_turn_state = {"mushi_call_active": metadata.get("mushi_call_active")}

    player_input: dict = {
        "type": player_action.get("type", "DO"),
        "raw": player_action.get("raw", ""),
    }
    # Turn regeneration: player OOC instruction for re-running the same action.
    if player_action.get("ooc_note"):
        player_input["ooc_note"] = player_action["ooc_note"]
    out = {
        "player_input": player_input,
        "recent_turns_prose": recent_prose,
        "world_state": {
            **_world_state(
                state["player_card"], npcs, metadata, scene_location,
                ship_cards=state.get("ship_cards") or {}, current_turn_index=current_turn_index,
            ),
            # Open promise crystals (with participants); scene material when the Director
            # composes with those NPCs. Truncated by recency only.
            "open_promises": (state.get("promise_crystals") or [])[-12:],
        },
        "scene_current": {
            "location": scene_location,
            "ambient": scene.get("ambient", ""),
        },
        "agents_known": agents_known,
        "agents_locations": build_agents_locations(state),
        "agent_tick_outputs": agent_tick_outputs or [],
        "previous_turn_state": previous_turn_state,
        "active_directives": active_directives or [],
    }
    return out


# POST-TURN — emit_post_turn_decisions. The *_pre_audit scratchpads are reflexive forcing
# functions the engine ignores on parse. Calibration lives in the addenda; here is wiring +
# routing by kind.

# pre_audit scratchpads (engine discards on parse).
_ALIGNMENT_PRE_AUDIT = {
    "type": "object",
    "description": (
        "Pre-audit OBRIGATORIO antes de decidir alignment_delta e crew_alignment_delta. "
        "Preencha PRIMEIRO e use as conclusoes pra decidir os deltas. Coerencia "
        "auditada (alignment_addendum §2). Engine descarta este campo."
    ),
    "properties": {
        "ato_moral_central": {"type": "string"},
        "verbo_extraido_de_ato": {"type": "string"},
        "is_entrega_protecao_intervencao": {"type": "string", "enum": ["sim", "nao"]},
        "categoria_omissao_aplicavel": {
            "type": "string",
            "enum": [
                "combate_funcional", "tatica_neutra", "trait_colorante",
                "crewmate_solo_player_inerte", "dialogo_informativo_neutro",
                "presenca_empatica_sem_intervencao", "nenhuma",
            ],
        },
        "source_eleita": {"type": "string", "enum": ["action", "dialog", "meta", "omitir"]},
        "coacao_seria": {"type": "string"},
        "atos_distintos_count": {"type": "integer"},
        "alignment_value_choice": {
            "type": "string",
            "enum": ["omitir", "+0.2", "+0.5", "+1.0", "+1.5", "-0.2", "-0.5", "-1.0", "-1.5"],
        },
        "crew_participacao_ativa": {"type": "string"},
        "crew_alignment_value_choice": {
            "type": "string",
            "enum": ["omitir", "+0.2", "+0.5", "+1.0", "+1.5", "-0.2", "-0.5", "-1.0", "-1.5"],
        },
    },
    "required": [
        "ato_moral_central", "verbo_extraido_de_ato", "is_entrega_protecao_intervencao",
        "categoria_omissao_aplicavel", "source_eleita", "coacao_seria",
        "atos_distintos_count", "alignment_value_choice", "crew_participacao_ativa",
        "crew_alignment_value_choice",
    ],
}

_BOUNTY_PRE_AUDIT = {
    "type": "object",
    "description": (
        "Pre-audit OBRIGATORIO antes de decidir bounty_delta. Preencha PRIMEIRO e use "
        "as conclusoes pra decidir o delta. Coerencia auditada (bounty_addendum §7). "
        "Cite LITERAL os campos chave do input. Engine descarta este campo."
    ),
    "properties": {
        "ato_publico_processavel_pelo_wg": {"type": "string"},
        "componente_anti_wg": {
            "type": "string",
            "enum": [
                "violencia_marine", "dano_patrimonio_wg", "desafio_autoridade_wg",
                "sabotagem_operacao_wg", "libertacao_preso_wg",
                "ataque_tenryuubito_ou_estrutura_global", "heroismo_civico_puro",
                "ato_privado_ou_isolado", "filler_neutro_sem_ato", "nao_aplicavel",
            ],
        },
        "testemunhas_alcance": {"type": "string"},
        "escala_repercussao_eleita": {
            "type": "string",
            "enum": ["small", "medium", "large", "massive", "absurd", "omitir"],
        },
        "target_eleito": {
            "type": "string",
            "description": (
                "'player' | '<crewmate_char_id>' | 'nenhum'. 'nenhum' SE E SO SE "
                "escala_repercussao_eleita == 'omitir'. Escolhida uma escala real, DEVE nomear "
                "player ou um crewmate; tier real + target 'nenhum' e incoerente (a engine "
                "descarta a reconstrucao e avisa, nao adivinha o alvo)."
            ),
        },
        "crewmate_proprio_ato_identificavel": {"type": "string"},
        "lenda_e_cartaz": {
            "type": "string",
            "description": (
                "GATE do MITO publico (legend_addendum). Releia world_state.legend_state e o "
                "turn: o mito sobre o player ou um tripulante MUDOU (epiteto nascendo encenado, "
                "imagem publica divergindo dos fatos, cartaz novo/reimpresso, diretriz "
                "vivo-ou-morto)? Formato: 'atualizo: target=<player|npc_id>; <o que muda no "
                "mito>' -> DEVE existir legend_update coerente em edit_primitives[]; OU "
                "'seguro: <motivo>' -> nenhum legend_update. O cartaz NAO imprime a cada salto "
                "de bounty: a decisao e sobre o MITO, nao sobre o numero."
            ),
        },
    },
    "required": [
        "ato_publico_processavel_pelo_wg", "componente_anti_wg", "testemunhas_alcance",
        "escala_repercussao_eleita", "target_eleito", "crewmate_proprio_ato_identificavel",
        "lenda_e_cartaz",
    ],
}

_AGENT_MEMORY_WRITEBACK_PRE_AUDIT = {
    "type": "object",
    "description": (
        "Pre-audit OBRIGATORIO antes de decidir os append_agent_log_entry de "
        "edit_primitives[] (master §3.9). A memoria de um NPC (o log que alimenta o "
        "agente dele off-scene) so registra a historia quando VOCE a escreve; o "
        "agente off-scene roda so sobre o card e o proprio log, nao ve a prosa nem o "
        "que o player fez. Sem write-back ele inventa uma versao que contradiz a "
        "cena. Liste cada NPC com card materialmente afetado e force o write-back. "
        "Engine descarta este campo."
    ),
    "properties": {
        "materially_involved_npcs": {
            "type": "array",
            "description": (
                "Uma row por NPC COM card que a prosa deste turn mostra "
                "materialmente envolvido ou afetado (o player agiu sobre ele, ele "
                "ganhou ou perdeu algo, sua situacao mudou). Ignore NPC so "
                "mencionado ou de fundo. Vazio ('[]') se nenhum."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "npc_id": {
                        "type": "string",
                        "description": "id LITERAL (copy-paste) de active_cards[]/agents-known.",
                    },
                    "involved_how": {
                        "type": "string",
                        "description": "1 frase: o que a prosa mostra acontecendo com ele ou ao redor dele.",
                    },
                    "ran_own_agent_this_turn": {
                        "type": "boolean",
                        "description": (
                            "true se este NPC aparece nos outputs de agente in-scene "
                            "deste turn (ja se auto-registrou; a engine deduplica)."
                        ),
                    },
                    "needs_writeback": {
                        "type": "boolean",
                        "description": (
                            "TRUE so se ran_own_agent_this_turn=false. Se TRUE, "
                            "edit_primitives[] DEVE ter um append_agent_log_entry com "
                            "este agent_id e um action_summary factual do desfecho no "
                            "POV do NPC, source 'self'."
                        ),
                    },
                },
                "required": [
                    "npc_id", "involved_how", "ran_own_agent_this_turn", "needs_writeback",
                ],
            },
        },
    },
    "required": ["materially_involved_npcs"],
}

# economy_pre_audit: belly_choice gate + inventory checks. Engine discards on parse but reads
# belly_choice first for runtime reconstruction.
_BELLY_CHOICE_ENUM = ["omitir"] + [
    f"{d}:{t}" for d in ("gain", "loss")
    for t in ("small", "medium", "large", "massive", "absurd")
]
_ECONOMY_PRE_AUDIT = {
    "type": "object",
    "description": (
        "Pre-audit OBRIGATORIO antes de decidir belly_delta e inventory_events. Voce DEVE "
        "preencher esse bloco PRIMEIRO e USAR as conclusoes dele. Coerencia auditada: se "
        "transacao_monetaria_na_cena starts with 'false' OU belly_choice == 'omitir', "
        "belly_delta DEVE estar ausente; belly_choice 'direction:tier' DEVE bater com o "
        "belly_delta emitido. Se itens_movidos_na_cena == 'nenhum', inventory_events DEVE estar "
        "vazio. Se item_novo_adquirido_sinalizado starts with 'true', dispatched_jobs DEVE conter "
        "item_generator E voce NAO emite inventory_event 'acquired' pra esse item. Se "
        "item_na_prosa_sem_card_nem_sinal starts with 'true', inspector_warnings DEVE conter "
        "unsignaled_item. Cite LITERAL os campos do input. Engine descarta este campo."
    ),
    "properties": {
        "transacao_monetaria_na_cena": {
            "type": "string",
            "description": (
                "Houve transacao com valor monetario VISIVEL no turn? Formato: 'true: <ato "
                "factual + escala monetaria + cite literal world_state.player.belly>' OR "
                "'false: <motivo — viagem/descanso/treino/conversa sem dinheiro, combate SEM "
                "saque, ato privado>'. Se 'false', belly_delta DEVE ser omitido (sem drain passivo)."
            ),
        },
        "belly_choice": {
            "type": "string",
            "enum": _BELLY_CHOICE_ENUM,
            "description": (
                "GATE — escolha aqui direction:tier EXATO do belly_delta ANTES de montar "
                "deltas[]. 'omitir' = sem belly_delta. Se vai emitir, escolha LITERAL do set "
                "{gain|loss}:{small|medium|large|massive|absurd}. 'absurd' SO pra escala "
                "canon-massiva. Em multi-transacao, este campo indica a PRINCIPAL."
            ),
        },
        "belly_source_eleita": {
            "type": "string",
            "enum": ["action", "dialog", "meta", "omitir"],
            "description": "Fonte do belly_delta (DEVE bater com o source emitido). 'omitir' quando belly_choice=='omitir'.",
        },
        "escala_justificativa": {
            "type": "string",
            "description": "1-2 frases: POR QUE essa faixa — pela ESCALA MONETARIA do ato, NAO pelo peso da prosa.",
        },
        "itens_movidos_na_cena": {
            "type": "string",
            "description": (
                "Itens com card EXISTENTE que entraram/sairam/usados/dados. Formato: lista "
                "'kind:item_card_id' (ex: 'acquired:fruit_gomu_gomu, lost:item_katana_reno') — "
                "cada id LITERAL de world_state.active_cards[].id (e, pra lost/consumed/given_away, "
                "em player.inventory). OR 'nenhum'. NAO inclua aqui item novo a gerar."
            ),
        },
        "item_novo_adquirido_sinalizado": {
            "type": "string",
            "description": (
                "Player adquiriu item nomeado NOVO (sem card) que o Opus sinalizou? Formato: "
                "'true: <nome + cite literal turn_meta.items_to_generate[<idx>]>' OR 'false: "
                "<motivo>'. Se 'true', dispatched_jobs DEVE conter item_generator e voce NAO emite "
                "inventory_event 'acquired' pra ele (o engine inventaria; o id ainda nao existe)."
            ),
        },
        "item_na_prosa_sem_card_nem_sinal": {
            "type": "string",
            "description": (
                "Algum item nomeado aparece na prosa SEM card em active_cards[] E SEM entry em "
                "turn_meta.items_to_generate[]? Formato: 'true: <qual item>' OR 'false: <motivo>'. "
                "Se 'true', emita inspector_warnings{ kind: 'unsignaled_item' } — NUNCA id forjado."
            ),
        },
    },
    "required": [
        "transacao_monetaria_na_cena", "belly_choice", "belly_source_eleita",
        "escala_justificativa", "itens_movidos_na_cena",
        "item_novo_adquirido_sinalizado", "item_na_prosa_sem_card_nem_sinal",
    ],
}

# ship_pre_audit: hull gate + 4-way swap_path gate + sinking gate. Engine discards on parse.
_HULL_CONDITIONS_ENUM = list(ship.HULL_CONDITIONS)
_HULL_CHOICE_ENUM = ["omitir"] + _HULL_CONDITIONS_ENUM
_SWAP_KINDS_ENUM = list(ship.SWAP_KINDS)
_SWAP_KIND_CHOICE_ENUM = ["omitir"] + _SWAP_KINDS_ENUM
_SWAP_PATH_ENUM = [
    "omitir", "swap_event_card_existente", "ship_generator_navio_novo", "unsignaled_ship",
]
_DISPOSITIONS_ENUM = list(ship.DISPOSITIONS)
_SHIP_PRE_AUDIT = {
    "type": "object",
    "description": (
        "Pre-audit OBRIGATORIO antes de decidir eventos de navio. Voce DEVE preencher esse "
        "bloco PRIMEIRO e USAR as conclusoes dele. Coerencia auditada: se "
        "hull_dano_ou_conserto_na_cena starts with 'false' OU hull_change_choice == 'omitir', "
        "hull_condition_change_events DEVE estar vazio; hull_change_choice '<estado>' DEVE bater "
        "com o new_condition emitido. swap_path_choice decide o CAMINHO: 'omitir' (sem troca) -> "
        "sem ship_swap_event/ship_generator/unsignaled_ship; 'swap_event_card_existente' -> "
        "ship_swap_events com ids de active_cards; 'ship_generator_navio_novo' -> "
        "dispatched_jobs[ship_generator] E SEM ship_swap_event (id do navio novo nao existe); "
        "'unsignaled_ship' -> inspector_warnings[unsignaled_ship]: se o player ASSUMIU o navio, "
        "preencha os campos de posse do warning (o engine gera o card + aplica a troca), senao so "
        "diagnostico; nunca id forjado. Se "
        "navio_afundou_na_cena starts with 'true', e TROCA (wrecked_replacement), NUNCA "
        "hull_condition_change_event{broken} pro afundado. Cite LITERAL os campos do input. "
        "Engine descarta este campo."
    ),
    "properties": {
        "hull_dano_ou_conserto_na_cena": {
            "type": "string",
            "description": (
                "Houve BEAT CONCRETO que castigou ou consertou o casco neste turn? Formato: "
                "'true: <beat factual — canhonaco/encalhe/tempestade-que-estilhaca/abalroamento/"
                "Sea-King + grau fisico, OU reparo MOSTRADO: carpinteiro/estaleiro/doca-seca/"
                "mutirao> + cite literal o navio active e seu hull_condition do input' OR 'false: "
                "<motivo — travessia rotineira, maresia, manutencao comum, descanso, sem beat>'. "
                "Se 'false', hull_condition_change_events DEVE ser omitido (SEM drain passivo "
                "§A.3). Densidade de prosa != gravidade do dano §A.2/§E."
            ),
        },
        "hull_change_choice": {
            "type": "string",
            "enum": _HULL_CHOICE_ENUM,
            "description": (
                "GATE — escolha aqui o new_condition EXATO do casco ANTES de montar "
                "hull_condition_change_events[]. 'omitir' = casco nao mudou neste turn. Se vai "
                "emitir, escolha LITERAL do set {pristine|scarred|damaged|broken}. Calibre pela "
                "GRAVIDADE FISICA: piora em geral UM degrau por beat; salto de dois degraus so "
                "com catastrofe unica inequivoca. O new_condition emitido DEVE bater com esta "
                "escolha (caso de UM navio; em raro multi-navio, este indica o PRINCIPAL)."
            ),
        },
        "navio_trocado_na_cena": {
            "type": "string",
            "description": (
                "O player passou a navegar num CASCO DIFERENTE nesta cena? Formato: 'true: <como "
                "— primeiro navio pos-jangada / trocou por melhor / casco afundou e repos / "
                "perdeu e reaveu> + cite o navio novo e se ele JA TEM card em active_cards ou e "
                "novo sem card' OR 'false: <motivo>'. Jangada inicial NAO conta como navio "
                "anterior (fora do fleet, §B / §E)."
            ),
        },
        "swap_path_choice": {
            "type": "string",
            "enum": _SWAP_PATH_ENUM,
            "description": (
                "GATE 4-VIAS — decida o CAMINHO da troca ANTES de emitir. 'omitir' = nenhuma "
                "troca. 'swap_event_card_existente' = navio novo JA TEM card em active_cards "
                "(plot/reserva promovido/saqueado cardificado) -> ship_swap_events com "
                "new_ship_card_id REAL (copy-paste). 'ship_generator_navio_novo' = navio NOVO sem "
                "card E COM entry em turn_meta.ships_to_generate[] -> dispatched_jobs[ship_"
                "generator] E SEM ship_swap_event (o id nao existe). SO escolha este se a entry "
                "existe em ships_to_generate[] — sem card NAO implica generator. 'unsignaled_ship' "
                "= navio nomeado na prosa SEM card E SEM entry -> inspector_warnings{unsignaled_"
                "ship}. Se o player ASSUMIU o navio na cena (passou a navega-lo), preencha os "
                "campos de posse do warning (acquired_by_player:'true', tentative_name, subtype_"
                "hint, initial_hull_condition, previous_ship_card_id/disposition, swap_kind): o "
                "ENGINE gera o card e aplica a troca. Voce NUNCA forja id nem emite ship_generator. "
                "Navio de passagem (nao assumido) = so o warning diagnostico."
            ),
        },
        "swap_kind_eleito": {
            "type": "string",
            "enum": _SWAP_KIND_CHOICE_ENUM,
            "description": (
                "GATE — swap_kind comprometido (vale pro ship_swap_event OU pros campos do lado "
                "antigo no job ship_generator). 'omitir' quando swap_path_choice == 'omitir' ou "
                "'unsignaled_ship'. 'acquired' = primeiro navio proprio pos-jangada (previous "
                "null). 'upgraded' = trocou por melhor. 'wrecked_replacement' = casco anterior "
                "afundou e repos (previous_ship_disposition=sunken). 'lost_and_recovered' = raro."
            ),
        },
        "navio_afundou_na_cena": {
            "type": "string",
            "description": (
                "Algum navio AFUNDOU de vez nesta cena? Formato: 'true: <qual navio + cite o id "
                "se tem card>' OR 'false: <motivo>'. Se 'true': afundamento e TROCA "
                "(swap_kind=wrecked_replacement, previous_ship_disposition=sunken). NUNCA emita "
                "hull_condition_change_event{broken} pro navio que afundou (§A.4)."
            ),
        },
        "ids_de_navio_citados": {
            "type": "string",
            "description": (
                "Restatement do gate de existencia: liste os SHIP card ids referenciados neste "
                "turn (ship_card_id de hull change, new/previous_ship_card_id de swap), cada um "
                "copy-paste de world_state.active_cards[].id (type SHIP). 'nenhum id existente — "
                "navio novo via ship_generator' OR 'nenhum navio movido'."
            ),
        },
    },
    "required": [
        "hull_dano_ou_conserto_na_cena", "hull_change_choice", "navio_trocado_na_cena",
        "swap_path_choice", "swap_kind_eleito", "navio_afundou_na_cena", "ids_de_navio_citados",
    ],
}

# faction_reputation_pre_audit: required gate preventing array drop. Engine discards on parse.
_FACTION_TIER_CHOICE_ENUM = ["omitir", "small", "medium", "large", "top"]
_FACTION_PRE_AUDIT = {
    "type": "object",
    "description": (
        "Pre-audit OBRIGATORIO antes de decidir faction_reputation_delta. Voce DEVE preencher "
        "esse bloco PRIMEIRO (na ordem em que os campos sao listados) e USAR as conclusoes dele "
        "pra decidir os deltas — nao apenas preencher mecanicamente. Coerencia auditada: "
        "(1) tier_principal == 'omitir' SE E SO SE source_eleita == 'omitir' SE E SO SE NENHUM "
        "faction_reputation_delta em deltas[]; (2) se tier_principal != 'omitir', deltas[] DEVE "
        "conter >=1 faction_reputation_delta com faction_id == faction_id_principal, target == "
        "target_eleito, sinal de value == sinal_principal, e value no range do tier (small ~±0.1, "
        "medium ~±0.3, large ~±0.7, top ~±1.5); (3) faction_id_principal DEVE constar em "
        "faction_cards_disponiveis — NUNCA invente faction_id sem card FACTION no estado; (4) se "
        "facoes_adicionais_count >= 1, o total de faction_reputation_delta DEVE ser >= 1 + "
        "facoes_adicionais_count (um delta por faccao, sem consolidar); (5) source de cada "
        "faction_reputation_delta DEVE bater com source_eleita. Engine descarta este campo."
    ),
    "properties": {
        "ato_institucional_central": {
            "type": "string",
            "description": (
                "Descricao factual neutra em 1 frase do ato com LEITURA INSTITUCIONAL do turn (o "
                "ato + qual faccao o arquivaria como dela), OU 'nenhum' se o turn nao tem ato que "
                "alguma faccao leria institucionalmente. NAO use prosa atmosferica do Opus — "
                "extraia a acao em forma neutra: 'player/<npc> [fez Y] contra/perante [faccao Z] "
                "em [situacao W]'."
            ),
        },
        "faction_cards_disponiveis": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "RESTATEMENT obrigatorio: liste os faction_id de TODOS os cards FACTION presentes "
                "no estado (world_state.active_cards com type=='FACTION'). Cite os ids LITERAIS. "
                "Voce SO pode emitir faction_reputation_delta pra um id desta lista. Se a lista "
                "esta vazia, NAO ha faccao rastreavel — omita (vila/gangue anonima sem card "
                "FACTION nao entra; vai pra relationship/summary)."
            ),
        },
        "target_eleito": {
            "type": "string",
            "description": (
                "'player' | '<npc_id>' | 'nenhum'. NPC nomeado em cena que agiu institucionalmente, "
                "OU NPC off-screen CUJO personal_event_log registra ato com leitura institucional. "
                "NUNCA 'crew' (a crew.faction_reputations eh derivada pela engine). NPC off-screen "
                "idle / que viajou / agiu sem friccao institucional => 'nenhum' (sem delta "
                "artificial pra 'manter o NPC vivo')."
            ),
        },
        "faction_id_principal": {
            "type": "string",
            "description": (
                "faction_id do ato PRINCIPAL (maior magnitude institucional), ou 'nenhum'. DEVE "
                "constar em faction_cards_disponiveis."
            ),
        },
        "tier_principal": {
            "type": "string",
            "enum": _FACTION_TIER_CHOICE_ENUM,
            "description": (
                "GATE — tier institucional do ato principal, ANTES de emitir. 'omitir' OBRIGATORIO "
                "quando QUALQUER: (a) sem ato com leitura institucional; (b) ato contra vila/gangue/"
                "grupo SEM card FACTION; (c) combate funcional neutro contra alvo sem vinculo de "
                "faccao; (d) sem processador institucional — ilha isolada, sem testemunha da faccao, "
                "sem reporte/registro (a instituicao nao soube); (e) agente off-screen idle. Senao "
                "escolha o tier ancorado na ESCALA INSTITUCIONAL (quem processa + alvo + simbolismo "
                "+ publicidade), NAO no drama narrado: small = atrito/cortesia de superficie; medium "
                "= ato institucional local (derrotar oficial corrupto raso, libertar 1 capturado, "
                "recusar ordem em publico); large = escala de mar (derrotar capitao serio, queimar "
                "bandeira do WG em publico, libertar prisioneiro famoso); top = sismico canon-tier "
                "(agressao a Tenryuubito, invasao Marineford-tier, sabotagem ao Reverie/Mariejois). "
                "Em duvida entre large e top, escolha large."
            ),
        },
        "sinal_principal": {
            "type": "string",
            "enum": ["+", "-", "n/a"],
            "description": (
                "'+' = respeito/deferencia conquistada perante a faccao; '-' = hostilidade/afronta "
                "conquistada; 'n/a' se tier_principal == 'omitir'."
            ),
        },
        "source_eleita": {
            "type": "string",
            "enum": ["action", "dialog", "meta", "omitir"],
            "description": (
                "action: ato fisico na cena. dialog: sem ato fisico, postura por fala publica/"
                "calculada (declaracao que sela inimizade, denuncia que a faccao arquiva). meta: "
                "player_input.type == 'META' com postura institucional declarada. omitir: sem "
                "faction_reputation_delta (obrigatorio quando tier_principal == 'omitir'). Se "
                "escolheu action/dialog/meta, voce SE COMPROMETEU a emitir >=1 faction_reputation_delta."
            ),
        },
        "facoes_adicionais_count": {
            "type": "integer",
            "description": (
                "Quantas faccoes ALEM da principal o MESMO ato move neste turn (multi-faccao: ex. "
                "defender vila contra Marines move -marinha E +revolution => count=1). Cada faccao "
                "adicional vira um faction_reputation_delta proprio em deltas[], sem consolidar. 0 "
                "se so a principal (ou nenhuma)."
            ),
        },
    },
    "required": [
        "ato_institucional_central", "faction_cards_disponiveis", "target_eleito",
        "faction_id_principal", "tier_principal", "sinal_principal", "source_eleita",
        "facoes_adicionais_count",
    ],
}

# alliances_hunters_pre_audit: alliance/hunter gates only. LOOT fields are intentionally dropped
# (loot belly is gated by economy_pre_audit.belly_choice; avoids a double source). Engine discards.
_ALLIANCE_EVENT_CHOICE_ENUM = ["omitir", "alliance_formed", "alliance_broken"]
_HUNTER_EVENT_CHOICE_ENUM = ["omitir", "appearance", "nemesis_paralelo_promoted"]
_ALLIANCE_HUNTER_PRE_AUDIT = {
    "type": "object",
    "description": (
        "Pre-audit OBRIGATORIO antes de decidir eventos de alianca/cacador. Voce DEVE preencher "
        "esse bloco PRIMEIRO e USAR as conclusoes dele — nao apenas preencher mecanicamente. "
        "Coerencia auditada: alliance_event_choice 'omitir' -> crew_alliance_events vazio; "
        "'alliance_formed'/'alliance_broken' -> crew_alliance_events contem o kind. hunter_event_"
        "choice 'omitir' -> bounty_hunter_events vazio; 'appearance' -> bounty_hunter_events"
        "[appearance] E npc_generator companion por id; 'nemesis_paralelo_promoted' -> "
        "bounty_hunter_events[promoted]. Cite LITERAL os campos do input — sem reformular."
    ),
    "properties": {
        "selagem_ou_ruptura_narrada": {
            "type": "string",
            "description": (
                "Houve cena EXPLICITA de selagem de alianca (sake ritual / handshake / declaracao "
                "publica / juramento verbal / troca formal de mensageiros) OU de ruptura (traicao "
                "encenada / conflito irreconciliavel declarado / morte do capitao aliado / renuncia "
                "explicita)? Formato: 'selagem: <gesto literal citado da prosa>' OR 'ruptura: <ato "
                "literal + trigger>' OR 'nenhuma: <motivo — so cooperacao tatica circunstancial / "
                "so divergencia de alignment / so passagem de tempo>'. Cooperacao tatica sem gesto "
                "e divergencia de alignment NAO sao evento de alianca."
            ),
        },
        "crew_b_existe_no_mundo": {
            "type": "string",
            "description": (
                "Se vai emitir alliance event, cite o crew_b: id de card FACTION em active_cards "
                "(copy-paste) OU nome do agrupamento de NamedNPCAgent com affiliation comum presente "
                "no mundo. Formato: 'faction_xxx (card)' OR 'agrupamento <affiliation> (npcs "
                "presentes)' OR 'NAO existe — crew sugerida sem card nem agrupamento, NAO emitir' OR "
                "'nao se aplica (sem evento de alianca)'. NUNCA invente crew na hora da alianca."
            ),
        },
        "alliance_event_choice": {
            "type": "string",
            "enum": _ALLIANCE_EVENT_CHOICE_ENUM,
            "description": (
                "GATE — comprometa o evento de alianca ANTES de montar crew_alliance_events[]. "
                "'omitir' = nenhum evento (OBRIGATORIO sem cena de selagem/ruptura, em cooperacao "
                "tatica, em divergencia de alignment, ou quando crew_b nao existe). 'alliance_formed' "
                "= selagem narrada + crew_b existe. 'alliance_broken' = ruptura narrada com trigger "
                "canon. O kind emitido em crew_alliance_events[] DEVE bater com esta escolha."
            ),
        },
        "alliance_formality_hierarchy": {
            "type": "string",
            "description": (
                "Se alliance_formed: 'formality: <informal|formal> pelo gesto (sake/declaracao/"
                "juramento=formal; handshake/verbal=informal; default informal); hierarchy: <peer|"
                "subordinate|sovereign> pelo tom (iguais=peer; subordinacao gesticulada=subordinate; "
                "player jurou a crew maior=sovereign; default peer)'. 'nao se aplica' caso contrario."
            ),
        },
        "spawn_signals": {
            "type": "string",
            "description": (
                "Sinais pro/contra spawn de cacador (pondere, sem formula): 'bounty=<valor>, "
                "chaos=<bucket>, localizacao=<porto/ilha-pirata/mar/ilha-pacifica-isolada>, "
                "encontros_bounty_hunter_recentes=<N de world_state.recent_bounty_hunter_encounters>'. "
                "Bounty alto + chaos volatile/apocalyptic + porto pesam PRO; ilha pacifica + bounty "
                "baixo + 3+ encontros recentes pesam CONTRA (anti-saturacao)."
            ),
        },
        "active_alliances_consultadas": {
            "type": "string",
            "description": (
                "Liste as facoes/crews aliadas VIGENTES (de world_state.crew_alliances). 'nenhuma' "
                "se vazio. Spawn-blocking: um cacador afiliado a facao aliada vigente e BLOQUEADO — "
                "substitua por outra afiliacao ou cancele o spawn. Formato: 'aliadas: <lista de "
                "crew_b_id>; cacador planejado seria de <affiliation> -> <liberado / BLOQUEADO por "
                "ser aliada>'."
            ),
        },
        "hunter_event_choice": {
            "type": "string",
            "enum": _HUNTER_EVENT_CHOICE_ENUM,
            "description": (
                "GATE — comprometa o evento de cacador ANTES de montar bounty_hunter_events[]. Cobre "
                "AMBOS os kinds. 'omitir' = NENHUM evento de cacador (nem appearance NEM promocao) -> "
                "bounty_hunter_events VAZIO (OBRIGATORIO quando sinais fracos, anti-saturacao ativa, "
                "ou o unico cacador plausivel seria de facao aliada sem substituto). 'appearance' = "
                "um cacador novo aparece -> EXIGE npc_generator companion em dispatched_jobs[] pra "
                "CADA id novo em hunter_npc_ids[]. 'nemesis_paralelo_promoted' = decisao RARA de "
                "promover um cacador JA EXISTENTE com peso recorrente forte. O kind emitido em "
                "bounty_hunter_events[] DEVE bater exatamente com esta escolha."
            ),
        },
    },
    "required": [
        "selagem_ou_ruptura_narrada", "crew_b_existe_no_mundo", "alliance_event_choice",
        "alliance_formality_hierarchy", "spawn_signals", "active_alliances_consultadas",
        "hunter_event_choice",
    ],
}


_WORLD_EVENT_SCHEMA = {
    "type": "object",
    "description": "append_world_event: payload do evento background (world_events_addendum §7).",
    "properties": {
        "kind": {"type": "string"},
        "summary": {"type": "string"},
        "status": {"type": "string", "enum": ["brewing", "active"]},
        "wenp_version": {"type": ["string", "null"]},
        "true_version": {"type": ["string", "null"]},
        "expected_discovery_channels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "channel": {
                        "type": "string",
                        "enum": ["wenp", "rumor", "den_den_mushi", "first_hand"],
                    },
                    "latency_hint": {"type": "string"},
                },
                "required": ["channel", "latency_hint"],
            },
        },
        "expected_resolution_hint": {"type": "string"},
        "player_insertion_plausibility": {
            "type": "string",
            "enum": ["plausible", "implausible_for_now", "implausible_full"],
        },
    },
    "required": [
        "kind", "summary", "status", "expected_discovery_channels",
        "expected_resolution_hint", "player_insertion_plausibility",
    ],
}

# Crew dissatisfaction gate, per member: bond_tier restate + what the turn touched + delta choice
# + departs flag. Gate-array coherence is audited/reconstructed. Engine discards on parse.
_CREW_PRE_AUDIT = {
    "type": "object",
    "description": (
        "Gate OBRIGATORIO antes de decidir insatisfacao/saida de tripulante. Preencha PRIMEIRO e "
        "USE pra montar crew_dissatisfaction_delta + crew_departure_event. Coerencia auditada: "
        "(1) per_member.dissatisfaction_choice == 'omitir' SE E SO SE NENHUM crew_dissatisfaction_"
        "delta pra aquele npc; senao deltas[] DEVE conter 1 com value == a escolha; (2) so membros "
        "do bando (world_state.crew, affiliation player_crew) entram em per_member; (3) departure_"
        "decision == '<npc_id>' SE E SO SE crew_departure_event nao-null com esse npc; 'nenhum' "
        "caso contrario. Engine descarta este campo."
    ),
    "properties": {
        "crew_members_in_play": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "RESTATEMENT: npc_id LITERAIS dos membros do bando (world_state.crew) que estao em "
                "cena OU que o turn tocou. NPC que nao e membro do bando NAO entra."
            ),
        },
        "per_member": {
            "type": "array",
            "description": "Uma entry por membro em crew_members_in_play. Decida ANTES de emitir deltas.",
            "items": {
                "type": "object",
                "properties": {
                    "npc_id": {"type": "string"},
                    "bond_tier_literal": {
                        "type": "string",
                        "enum": ["0", "1", "2"],
                        "description": (
                            "Cite LITERAL o bond_tier do membro (world_state.crew[].bond_tier). "
                            "bond_tier 2 (irmandade) e imune a atrito ROTINEIRO — so traicao grave "
                            "o move pra cima."
                        ),
                    },
                    "touched_this_turn": {
                        "type": "string",
                        "description": (
                            "1 frase factual: o que NESTE turn tocou o membro (ignorado, contrariado "
                            "no trait, pedido recusado, sonho/valor violado; OU atencao direta, goal "
                            "favorecido, protegido na vida). 'nada' se o turn nao o tocou."
                        ),
                    },
                    "dissatisfaction_choice": {
                        "type": "string",
                        "enum": ["+0.5", "+0.3", "+0.1", "omitir", "-0.1", "-0.3", "-0.5"],
                        "description": (
                            "GATE — value EXATO do delta deste membro ANTES de emitir deltas[]. "
                            "'omitir' OBRIGATORIO quando: o turn nao tocou o membro; OU bond_tier 2 "
                            "sob atrito rotineiro (nao traicao grave). Sobe (+) por frustracao, desce "
                            "(-) por acolhimento. ±0.1 superficie, ±0.3 trait/atencao real, ±0.5 "
                            "sonho/valor violado ou protecao na vida. O value em deltas[] DEVE bater."
                        ),
                    },
                    "departs": {
                        "type": "boolean",
                        "description": (
                            "true SO se os TRES se reunem: insatisfacao ACUMULADA alta (world_state."
                            "crew[].dissatisfaction) + gatilho concreto neste turn + valor de fundo "
                            "violado. Pico isolado / turno calmo / so insatisfacao alta sem gatilho = "
                            "false. bond_tier 2 so parte por traicao grave."
                        ),
                    },
                },
                "required": [
                    "npc_id", "bond_tier_literal", "touched_this_turn",
                    "dissatisfaction_choice", "departs",
                ],
            },
        },
        "departure_decision": {
            "type": "string",
            "description": "'<npc_id>' do membro que parte, ou 'nenhum'. DEVE bater com crew_departure_event.",
        },
    },
    "required": ["crew_members_in_play", "per_member", "departure_decision"],
}

# navigation_pre_audit: forces a re-read of where the prose left the player on the MAP and whether
# time jumped, so world_movement/time_advancement stop being neglected among the other channels.
# Engine discards on parse.
_NAVIGATION_PRE_AUDIT = {
    "type": "object",
    "description": (
        "Pre-audit OBRIGATORIO antes de decidir world_movement e time_advancement "
        "(navigation_addendum §1-2). Preencha PRIMEIRO e USE as conclusoes. Coerencia auditada: se "
        "deslocamento_no_mapa starts with 'false', world_movement DEVE estar ausente; se starts with "
        "'true', world_movement DEVE existir com kind/destination_id coerentes com o que voce atestou. "
        "Se tempo_decorrido starts with 'false', time_advancement DEVE estar ausente; se 'true', "
        "time_advancement.advance_days DEVE bater com os dias atestados. Cite LITERAL "
        "world_state.position e os ids do catalogo. Engine descarta este campo."
    ),
    "properties": {
        "posicao_no_input": {
            "type": "string",
            "description": (
                "Cite LITERAL world_state.position do input (kind + island_id, OU sea + origin/dest). "
                "E o ponto de partida deste turn no MAPA — distinto da sub-area da cena."
            ),
        },
        "lugar_final_na_prosa": {
            "type": "string",
            "description": (
                "Releia o FIM de prose_do_opus (e scene_end, se houver): onde o player esta no "
                "encerramento — em terra (qual ilha) ou no mar (rumo a que)? 1 frase factual."
            ),
        },
        "deslocamento_no_mapa": {
            "type": "string",
            "description": (
                "Comparando posicao_no_input com lugar_final_na_prosa: o player embarcou, navegou OU "
                "desembarcou ENTRE pontos do mapa neste turn? Formato: 'true: "
                "zarpou_rumo_a|zarpou_a_deriva|chegou; origin_id=<id catalogo>; destination_id=<id "
                "catalogo OU none>' OR 'false: <motivo — segue na mesma ilha/sub-area, OU segue a mesma "
                "travessia sem por o pe em terra>'. Zarpou rumo a um destino NOMEADO ('vamos a Loguetown') "
                "OU apontado por CRITERIO ('uma ilha a oeste', 'o proximo porto', 'terra pra se esconder', "
                "'deixa o mar levar ate a proxima ilha') -> set_sea: no criterio VOCE escolhe no WORLD-MAP "
                "uma ilha real que satisfaca (descoberta OU nao — o fog nao filtra rota; varie pela "
                "geografia, plausivel pela posicao) e emite destination_id. So set_adrift (SEM "
                "destination_id) quando ele se entrega ao mar SEM rumo nenhum nem criterio ('so ficar no "
                "mar', naufragio/correnteza sem controle) — nunca cunhe ilha fora do catalogo em mar canon. "
                "Chegou em terra -> arrive_island. Trocar de sub-area na MESMA ilha NAO conta (isso e "
                "scene_end, nao world_movement)."
            ),
        },
        "tempo_decorrido": {
            "type": "string",
            "description": (
                "A prosa saltou tempo de fato (dormir, 'no dia seguinte', montagem, dias consumidos a "
                "bordo de uma travessia, skip pedido pelo player)? Formato: 'true: <N dias + trecho da "
                "prosa que prova>' OR 'false: <motivo — acao continua no mesmo dia>'. Se 'true', emita "
                "time_advancement.advance_days=N. Uma travessia entre ilhas consome dias mesmo quando a "
                "prosa nao crava o numero."
            ),
        },
        "origem_do_nome_do_destino": {
            "type": "string",
            "description": (
                "So quando ha deslocamento com destino (set_sea/arrive_island): de onde saiu o "
                "destination_id que voce vai emitir? Formato: 'catalogo: <id do WORLD-MAP>' quando e "
                "ilha do mapa; OU 'carta/rumo: <slug>' quando e ilha inventada sem nome — o slug vem da "
                "carta/rota que mandou o player, e o nome de exibicao nasce na chegada pelo Island "
                "Designer. O slug NUNCA carrega o nome de uma pessoa da cena (um civil, um NPC citado "
                "neste turn). 'n/a' quando nao ha deslocamento ou e set_adrift."
            ),
        },
    },
    "required": [
        "posicao_no_input", "lugar_final_na_prosa", "deslocamento_no_mapa", "tempo_decorrido",
        "origem_do_nome_do_destino",
    ],
}

# world_pulse_pre_audit: forces a re-read of the background-world axis every turn. append_world_event
# was the only proactive Director channel without a required gate, so it never fired and the world
# stagnated (reactive-only). This makes the Director commit generate-or-hold each turn. NOT a tick:
# 'segurar' is a legitimate, frequent answer and nothing is auto-materialized (anti-determinism).
# Engine discards on parse.
_WORLD_PULSE_PRE_AUDIT = {
    "type": "object",
    "description": (
        "Pre-audit OBRIGATORIO antes de decidir se o mundo PULSA por conta propria neste turn "
        "(world_events_addendum: Cross Guild, Revolucionarios, Yonko, WG/Marinha, Mother Flame, "
        "God's Knights se movem SEM o player pedir). Preencha PRIMEIRO e USE a conclusao pra montar "
        "(ou nao) o append_world_event em edit_primitives. Voce SUSTENTA o par: pulso_escolhido "
        "'gerar' -> 1 append_world_event coerente com o kind + chaos_delta companion "
        "source=world_event na MESMA call (addendum §7.1); 'segurar' -> nenhum append_world_event "
        "novo. SEGURAR e resposta legitima e FREQUENTE: o mundo nao vira todo turn, bucket calm "
        "passa trecho inteiro sem evento. O gate forca a DECISAO consciente do eixo, NAO a geracao "
        "— nao e cota, relogio nem tick. Engine descarta este campo."
    ),
    "properties": {
        "ultimo_pulso": {
            "type": "string",
            "description": (
                "Cite LITERAL o world event de fundo mais recente de world_state.events_background_"
                "recent (kind + status brewing/active + ha quantos turns/dias), ou 'nenhum vivo' se "
                "vazio. E a leitura de SATURACAO: evento fresco ainda brewing/active nao pede outro "
                "por cima; gap longo desde o ultimo abre espaco."
            ),
        },
        "estado_do_mundo": {
            "type": "string",
            "description": (
                "1 frase factual do clima macro AGORA: chaos bucket (world_state.chaos_meter.bucket), "
                "regiao/cluster do player, tier + bounty do player (escala plausivel), e que forcas "
                "estao em jogo perto (Marinha, Cross Guild, Revolucionarios, Yonko, faccao local). O "
                "que no mundo MAIOR estaria se mexendo enquanto o player age, independente de ele ter "
                "pedido algo."
            ),
        },
        "pulso_escolhido": {
            "type": "string",
            "description": (
                "GATE — comprometa ANTES de montar edit_primitives. Formato: 'gerar: kind=<tipo do "
                "catalogo §2 ou emergente snake_case> porque <fio concreto do estado_do_mundo/cascata "
                "que o justifica>; toca_caos=<sim/nao>' OR 'segurar: <motivo — ultimo pulso ainda "
                "brewing / chaos calm sem gatilho / clímax de arc local que um evento de fundo "
                "abafaria / cadencia (pulso ha poucos turns)>'. Gere quando um fio real do mundo maior "
                "avancou (calibre a escala pelo tier do player, addendum §1); segure quando forcar "
                "seria ruido. Nem todo turn tem pulso; o mundo respira sozinho."
            ),
        },
    },
    "required": ["ultimo_pulso", "estado_do_mundo", "pulso_escolhido"],
}

EMIT_POST_TURN_TOOL = {
    "name": "emit_post_turn_decisions",
    "description": (
        "Emite TODAS as decisoes pos-turn do Diretor: deltas (alignment / bounty / "
        "chaos / crew_alignment / belly), inventory_events (acquired / lost / consumed / "
        "given_away), hull_condition_change_events (estado do casco mudou), ship_swap_events "
        "(player trocou de navio com card existente), tier_change_event, breakthrough_event, "
        "edit_primitives (dedup append_alias, legend_update lenda/cartaz, mushi/vivre, "
        "world events, agent log), "
        "inspector_warnings (unsignaled_npc / unsignaled_item / unsignaled_ship / "
        "schema_mismatch), dispatched_jobs (geradores e detectores — inclui ship_generator "
        "pra navio novo sem card). Preencha alignment_pre_audit, bounty_pre_audit, "
        "economy_pre_audit e ship_pre_audit PRIMEIRO (scratchpad "
        "obrigatorio; engine ignora). ORDEM: edit_primitives ANTES de deltas; voce sustenta o "
        "par world_event<->chaos_delta companion source=world_event (engine nao cruza a contagem). "
        "Chame UMA vez por turn."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "alignment_pre_audit": _ALIGNMENT_PRE_AUDIT,
            "bounty_pre_audit": _BOUNTY_PRE_AUDIT,
            "economy_pre_audit": _ECONOMY_PRE_AUDIT,
            "ship_pre_audit": _SHIP_PRE_AUDIT,
            "faction_reputation_pre_audit": _FACTION_PRE_AUDIT,
            "alliances_hunters_pre_audit": _ALLIANCE_HUNTER_PRE_AUDIT,
            "crew_pre_audit": _CREW_PRE_AUDIT,
            "agent_memory_writeback_pre_audit": _AGENT_MEMORY_WRITEBACK_PRE_AUDIT,
            "navigation_pre_audit": _NAVIGATION_PRE_AUDIT,
            "world_pulse_pre_audit": _WORLD_PULSE_PRE_AUDIT,
            "scene_end": {
                "type": ["object", "null"],
                "description": (
                    "Lugar onde a cena TERMINOU de fato na prose_do_opus. Leia o fim da prosa: o player "
                    "ficou onde a cena abriu, ou o Narrador o levou a outro lugar (mesmo momento, mesma "
                    "ilha)? Reporte o lugar final — e o que abre o PROXIMO turn. null/omitido = mesmo "
                    "lugar do scene de abertura. Nota factual, nao prosa. Movimento entre ILHAS vai por "
                    "world_movement, nao aqui."
                ),
                "properties": {
                    "area_slug": {
                        "type": "string",
                        "description": "slug curto estavel do lugar final (reuse o de scene se nao mudou).",
                    },
                    "location": {
                        "type": "string",
                        "description": "1 frase do lugar final, no formato de scene.location.",
                    },
                },
                "required": ["area_slug", "location"],
            },
            "edit_primitives": {
                "type": "array",
                "description": (
                    "Mutacoes do estado do mundo pos-turn. ORDEM: emita ANTES de deltas. "
                    "Cobre dedup (append_alias), lenda/cartaz (legend_update — legend "
                    "addendum), mushi/vivre (pair_mushi, unpair_mushi, "
                    "receive_vivre_card, remove_vivre_card), mushi exotico (plant_black_mushi, "
                    "remove_black_mushi, set_white_mushi — mushi addendum §7), world events "
                    "(append_world_event, update_world_event), e log de agente "
                    "(append_agent_log_entry). Vazio se nada."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": [
                                "append_alias", "legend_update", "pair_mushi", "unpair_mushi",
                                "receive_vivre_card", "remove_vivre_card",
                                "plant_black_mushi", "remove_black_mushi", "set_white_mushi",
                                "plant_tap_on_player", "remove_tap_on_player",
                                "append_world_event", "update_world_event",
                                "append_agent_log_entry",
                            ],
                        },
                        "card_id": {"type": "string", "description": "append_alias/legend_update: id de card existente em active_cards[] (legend_update: player ou tripulante)."},
                        "alias": {"type": "string", "description": "append_alias: epiteto/variacao a adicionar."},
                        "epithet": {"type": "string", "description": "legend_update: epiteto publico novo, nascido ENCENADO na prosa/jornal (vira alias do card). Omita se nao nasceu epiteto."},
                        "public_image": {"type": "string", "description": "legend_update: 1-2 frases do MITO que circula sobre o alvo — o que estranhos acreditam, que pode divergir dos fatos."},
                        "divergence_note": {"type": "string", "description": "legend_update: no que o mito diverge da verdade (exagero de tabloide, feito mal-atribuido, subestimacao). Omita se mito e fatos batem."},
                        "poster_note": {"type": "string", "description": "legend_update: retrato qualitativo do cartaz de procurado (esboco borrado -> foto nitida, pose, selo). Omita se o cartaz fisico nao mudou."},
                        "wanted_status": {"type": "string", "enum": ["none", "alive_only", "dead_or_alive"], "description": "legend_update: diretriz do cartaz atual."},
                        "npc_id": {"type": "string", "description": "pair_mushi/unpair_mushi/remove_vivre_card: id do NPC."},
                        "from_npc_id": {"type": "string", "description": "receive_vivre_card: id do NPC dono."},
                        "target_npc_id": {"type": "string", "description": "plant_black_mushi/remove_black_mushi: NPC grampeado."},
                        "white_active": {"type": "boolean", "description": "set_white_mushi: liga (true) / desliga (false) o contra-grampo do player."},
                        "watcher_npc_id": {"type": "string", "description": "plant_tap_on_player/remove_tap_on_player: NPC que grampeia o PLAYER."},
                        "note": {"type": "string", "description": "plant_tap_on_player: nota curta (como/por que)."},
                        "mushi_kind": {"type": "string", "enum": ["baby", "standard", "visual"]},
                        "location": {"type": "string", "description": "pair_mushi: location atual."},
                        "received_at_location": {"type": "string"},
                        "origin_note": {"type": "string"},
                        "reason": {"type": "string", "description": "unpair_mushi/remove_vivre_card/legend_update: motivo curto."},
                        "world_event": _WORLD_EVENT_SCHEMA,
                        "event_id": {"type": "string", "description": "update_world_event: id do evento existente."},
                        "patch": {
                            "type": "object",
                            "description": "update_world_event: campos a atualizar (status, summary_addition, new_discovery_channel).",
                        },
                        "agent_id": {"type": "string", "description": "append_agent_log_entry: id do agente."},
                        "entry": {
                            "type": "object",
                            "description": "append_agent_log_entry: payload do log do NPC (master §3.9; mushi addendum §1.5).",
                            "properties": {
                                "action_summary": {"type": "string"},
                                "source": {"type": "string"},
                                "important": {"type": "boolean"},
                                "subject_npc_id": {"type": "string"},
                            },
                            "required": ["action_summary", "source"],
                        },
                    },
                    "required": ["kind"],
                },
            },
            "deltas": {
                "type": "array",
                "description": (
                    "Deltas pos-turn. Cada entry tem `kind` discriminando o eixo. Vazio se o "
                    "turn nao pediu delta — omitir e preferido a inflar. "
                    "belly_delta: { kind, direction (gain|loss), tier, source, reason, exact_amount } "
                    "— SEM target (pote unico do capitao). tier pela escala MONETARIA da transacao "
                    "(nao pelo peso da prosa); VOCE emite exact_amount (cifra exata em Berries). "
                    "bounty_delta: { kind, target, tier, source, reason, exact_amount, news_delay_days }."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": [
                                "alignment_delta", "bounty_delta",
                                "chaos_delta", "crew_alignment_delta", "belly_delta",
                                "faction_reputation_delta", "crew_dissatisfaction_delta",
                            ],
                        },
                        "value": {
                            "type": "number",
                            "description": (
                                "alignment/crew_alignment: {-1.5,-1.0,-0.5,-0.2,0.2,0.5,1.0,1.5}; "
                                "chaos: {-0.5,-0.3,-0.15,-0.05,0.05,0.15,0.3,0.5}. "
                                "faction_reputation: FLOAT GUIDELINE ancorado em ±0.1 (small) / "
                                "±0.3 (medium) / ±0.7 (large) / ±1.5 (top), ajuste fino dentro de "
                                "[-2.0,+2.0]; sinal pela direcao (respeito + / hostilidade -). "
                                "crew_dissatisfaction: float assinado ancorado em ±0.1/±0.3/±0.5 "
                                "(igual a crew_pre_audit.per_member.dissatisfaction_choice); + sobe a "
                                "insatisfacao, - alivia. "
                                "Bounty e belly usam tier."
                            ),
                        },
                        "faction_id": {
                            "type": "string",
                            "description": (
                                "faction_reputation_delta ONLY: id de um card FACTION existente no "
                                "estado (marinha, world_government, cipher_pol, revolution, "
                                "cross_guild, crew Yonko, ou emergente com card). NUNCA inventar "
                                "id sem card FACTION."
                            ),
                        },
                        "direction": {
                            "type": "string",
                            "enum": ["gain", "loss"],
                            "description": (
                                "belly_delta only. 'gain' = belly entrou (recompensa, venda, saque, "
                                "butim, presente). 'loss' = belly saiu (compra, suborno, taxa, doacao, "
                                "conserto, roubo sofrido)."
                            ),
                        },
                        "tier": {
                            "type": "string",
                            "enum": ["small", "medium", "large", "massive", "absurd"],
                            "description": (
                                "bounty_delta e belly_delta: faixa qualitativa de grandeza pra voce "
                                "ancorar exact_amount. Pra belly: pela escala MONETARIA, NAO pelo "
                                "peso da prosa."
                            ),
                        },
                        "target": {
                            "type": "string",
                            "description": (
                                "bounty_delta: 'player' ou char_id de crewmate. faction_reputation_"
                                "delta: 'player' ou <npc_id> (NUNCA 'crew' — engine deriva). "
                                "crew_dissatisfaction_delta: o <npc_id> do membro do bando "
                                "(affiliation player_crew) cuja satisfacao o turn moveu. "
                                "belly_delta NAO usa target (pote unico do capitao)."
                            ),
                        },
                        "source": {
                            "type": "string",
                            "enum": ["action", "dialog", "meta", "world_event", "elapsed"],
                            "description": (
                                "'elapsed': drift causado pela passagem de tempo numa elipse "
                                "(chaos_delta esfriando/fermentando o mundo quando o intervalo "
                                "avanca dias). Use so com time_advancement no mesmo passe."
                            ),
                        },
                        "reason": {"type": "string", "description": "1-2 frases PT-BR factuais."},
                        "exact_amount": {
                            "type": ["integer", "null"],
                            "description": (
                                "bounty_delta e belly_delta: a CIFRA EXATA em Berries (>0) — sua "
                                "decisao dramatica dentro da faixa do tier, nao sorteio da engine. "
                                "Omita e a engine sorteia no range do tier."
                            ),
                        },
                        "news_delay_days": {
                            "type": ["integer", "null"],
                            "description": (
                                "bounty_delta only: dias ate a manchete chegar a um cartaz que o "
                                "player possa ver (0 = mesmo dia, num porto/base marinha; mais em mar "
                                "isolado), pesando distancia/isolamento da posicao atual. Omita e a "
                                "engine sorteia 1-3."
                            ),
                        },
                        "consolidated_reason": {
                            "type": ["string", "null"],
                            "description": (
                                "bounty_delta only: quando este ato dobra num cartaz pendente ainda "
                                "nao publicado do MESMO alvo, o motivo-manchete unico que o cartaz "
                                "consolidado carrega (a serie toda numa linha). Omita no 1o ato."
                            ),
                        },
                    },
                    "required": ["kind", "reason"],
                },
            },
            "inventory_events": {
                "type": "array",
                "description": (
                    "Itens materiais que entraram/sairam/foram usados/dados na cena (economy_"
                    "inventory_addendum §B). Um event por item movido. Vazio quando nenhum item se "
                    "moveu — inventario eh ILIMITADO, nao registre desgaste rotineiro nem cada bala/"
                    "refeicao, so o beat que a cena marca. ITEM NOVO adquirido NAO vai aqui: vai via "
                    "dispatched_jobs[item_generator] (o engine inventaria; o item_card_id ainda nao existe)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": ["acquired", "lost", "consumed", "given_away"],
                            "description": (
                                "acquired: player ganhou item com card EXISTENTE. lost: saiu sem ser "
                                "dado (roubado/confiscado/destruido/perdido). consumed: gasto no uso "
                                "(fruta comida, antidoto bebido, stack decai). given_away: entregue de "
                                "proposito a um NPC/aliado."
                            ),
                        },
                        "item_card_id": {
                            "type": "string",
                            "description": (
                                "id de ITEM/FRUIT card que EXISTE — copy-paste de world_state."
                                "active_cards[].id. Pra lost/consumed/given_away, tambem em world_state."
                                "player.inventory[].item_card_id. NUNCA id forjado. Fruta encontrada/"
                                "comida/dada referencia o FRUIT card original."
                            ),
                        },
                        "reason": {
                            "type": "string",
                            "description": "Prosa curta PT-BR factual: como o item entrou, saiu, foi usado ou dado.",
                        },
                        "quantity": {
                            "type": ["integer", "null"],
                            "description": (
                                "Stack-semantics (provisoes, balas, antidotos genericos): int com a "
                                "variacao (positivo em acquired, negativo em consumed/lost). Item unico "
                                "(Log Pose, Eternal Pose especifica, espada nomeada, fruta): null."
                            ),
                        },
                    },
                    "required": ["kind", "item_card_id", "reason"],
                },
            },
            "hull_condition_change_events": {
                "type": "array",
                "description": (
                    "FASE 18. Mudancas de estado do casco (ship addendum §A). Um event por navio "
                    "afetado, SO por beat concreto na cena (dano fisico visivel OU reparo "
                    "mostrado). Vazio quando nenhum casco mudou — SEM drain passivo de viagem/"
                    "maresia/manutencao (§A.3). Navio que AFUNDOU nao entra aqui: afundamento e "
                    "ship_swap_event/ship_generator (§A.4). new_condition calibrado pela GRAVIDADE "
                    "FISICA, nao pela densidade da prosa (§E)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["hull_condition_change_event"]},
                        "ship_card_id": {
                            "type": "string",
                            "description": (
                                "id de SHIP card que EXISTE — copy-paste de world_state."
                                "active_cards[].id (type SHIP). NUNCA id forjado."
                            ),
                        },
                        "new_condition": {
                            "type": "string",
                            "enum": _HULL_CONDITIONS_ENUM,
                            "description": (
                                "Estado resultante. Piora em geral UM degrau por beat; salto de "
                                "dois degraus so com catastrofe unica. Melhora conforme o reparo."
                            ),
                        },
                        "reason": {
                            "type": "string",
                            "description": "1-2 frases PT-BR factuais: o que castigou/consertou o casco e em que grau.",
                        },
                    },
                    "required": ["kind", "ship_card_id", "new_condition", "reason"],
                },
            },
            "ship_swap_events": {
                "type": "array",
                "description": (
                    "FASE 18. Troca de navio quando o navio novo JA TEM card (ship addendum §B). "
                    "Um event por troca. Vazio quando nao houve troca, OU quando o navio novo e "
                    "NOVO sem card (esse vai via dispatched_jobs[ship_generator], porque o "
                    "new_ship_card_id ainda nao existe — §B.3). O engine aplica os side-effects "
                    "(flip do anterior, migracao da Jolly Roger, cristal); voce so declara o event."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["ship_swap_event"]},
                        "swap_kind": {
                            "type": "string",
                            "enum": _SWAP_KINDS_ENUM,
                            "description": (
                                "acquired (primeiro navio pos-jangada), upgraded (trocou por "
                                "melhor), wrecked_replacement (afundou e repos), lost_and_recovered "
                                "(raro)."
                            ),
                        },
                        "previous_ship_card_id": {
                            "type": ["string", "null"],
                            "description": (
                                "id de SHIP card existente em active_cards, OU null no primeiro "
                                "'acquired' (nao havia navio antes da jangada)."
                            ),
                        },
                        "new_ship_card_id": {
                            "type": "string",
                            "description": (
                                "id de SHIP card que EXISTE — copy-paste de world_state."
                                "active_cards[].id (type SHIP). NUNCA id forjado: navio novo sem "
                                "card vai via ship_generator."
                            ),
                        },
                        "previous_ship_disposition": {
                            "type": ["string", "null"],
                            "enum": _DISPOSITIONS_ENUM + [None],
                            "description": (
                                "Sorte do navio anterior: dismantled / sunken / sold / abandoned / "
                                "given_away. null no primeiro 'acquired' (ou upgrade guardando o "
                                "antigo como reserva)."
                            ),
                        },
                        "reason": {
                            "type": "string",
                            "description": "1-2 frases PT-BR factuais: como a troca ocorreu na cena.",
                        },
                    },
                    "required": ["kind", "swap_kind", "new_ship_card_id", "reason"],
                },
            },
            "crew_alliance_events": {
                "type": "array",
                "description": (
                    "FASE 20. Eventos de alianca entre a crew do player e outra crew "
                    "(director_crew_alliances_addendum). Um event por mudanca. Vazio quando nenhuma "
                    "alianca foi selada nem rompida na cena — cooperacao tatica circunstancial e "
                    "divergencia de alignment NAO entram aqui (sem dissipar por tempo/drift). "
                    "alliance_formed exige cena de selagem narrada + crew_b existente (card FACTION "
                    "ou agrupamento de NamedNPCAgent); alliance_broken exige cena de ruptura com "
                    "trigger canon. O engine mutaciona world.crew_alliances + cristal de auditoria."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["alliance_formed", "alliance_broken"]},
                        "crew_b_id": {
                            "type": "string",
                            "description": (
                                "id de FACTION card que EXISTE (copy-paste de active_cards) OU id/"
                                "nome de agrupamento de NamedNPCAgent com affiliation comum presente no "
                                "mundo. NUNCA crew inventada na hora."
                            ),
                        },
                        "formality": {
                            "type": "string",
                            "enum": list(alliances.FORMALITIES),
                            "description": (
                                "alliance_formed only — pelo gesto: sake/declaracao/juramento = "
                                "formal; handshake/acordo verbal = informal; default informal."
                            ),
                        },
                        "hierarchy": {
                            "type": "string",
                            "enum": list(alliances.HIERARCHIES),
                            "description": (
                                "alliance_formed only — pelo tom: iguais = peer; subordinacao "
                                "gesticulada (crew_b jura) = subordinate; player jurou a crew maior = "
                                "sovereign; default peer."
                            ),
                        },
                        "origin_note": {
                            "type": "string",
                            "description": "alliance_formed only — 1-2 frases PT-BR: como surgiu, pro Narrador referenciar.",
                        },
                        "reason": {
                            "type": "string",
                            "enum": list(alliances.BROKEN_REASONS),
                            "description": "alliance_broken only — trigger canon: traicao / conflito / morte_capitao / renuncia / outro.",
                        },
                    },
                    "required": ["kind", "crew_b_id"],
                },
            },
            "bounty_hunter_events": {
                "type": "array",
                "description": (
                    "FASE 20. Eventos de cacador de recompensa nao-Marine (director_bounty_hunters_"
                    "addendum). Vazio quando nenhum cacador aparece nem e promovido. appearance EXIGE "
                    "npc_generator companion em dispatched_jobs[] pra cada id de hunter_npc_ids[] (sem "
                    "id fantasma) e nao pode ser de facao aliada vigente (spawn-blocking, consulte "
                    "world_state.crew_alliances). nemesis_paralelo_promoted e decisao RARA. Loot reusa "
                    "os canais da fase 16/17 (belly_delta / inventory_events / item_generator) — sem "
                    "item magico, sem faction_reputation_delta no loot."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["appearance", "nemesis_paralelo_promoted"]},
                        "hunter_archetype": {
                            "type": "string",
                            "description": (
                                "appearance only — descricao livre PT-BR canon-fit (sem enum), ex: "
                                "'atirador veterano solo com pistola pesada' ou 'esquadrao de capitao "
                                "menor de New World'."
                            ),
                        },
                        "hunter_npc_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "appearance only — ids placeholder dos cacadores; cada um exige npc_generator companion.",
                        },
                        "scene_hint": {"type": "string", "description": "appearance only — 1 frase: como aparecem em cena."},
                        "hunter_npc_id": {"type": "string", "description": "nemesis_paralelo_promoted only — id do cacador promovido."},
                        "reasoning": {
                            "type": "string",
                            "description": "nemesis_paralelo_promoted only — 1-2 frases PT-BR: por que merece tratamento de nemesis evolutivo agora.",
                        },
                    },
                    "required": ["kind"],
                },
            },
            "crew_departure_event": {
                "type": ["object", "null"],
                "description": (
                    "FASE 13. Um tripulante deixa o bando (director_crew_addendum §3). null na "
                    "imensa maioria dos turns. Nao-null SO quando os tres fatores se reunem: "
                    "insatisfacao ACUMULADA alta (world_state.crew[].dissatisfaction) + gatilho "
                    "concreto neste turn + valor de fundo violado — e crew_pre_audit.departure_"
                    "decision aponta este npc_id. Pico isolado, turno calmo, ou so insatisfacao "
                    "alta sem gatilho = null. bond_tier 2 so parte por traicao grave."
                ),
                "properties": {
                    "npc_id": {"type": "string"},
                    "reason": {"type": "string", "description": "1-2 frases PT-BR factuais: o gatilho da ruptura."},
                },
                "required": ["npc_id", "reason"],
            },
            "tier_change_event": {
                "type": ["object", "null"],
                "description": (
                    "Player subiu de tier (combat addendum §7). Default +1; skips raros. "
                    "Tier-down NAO existe. null quando nao se aplica."
                ),
                "properties": {
                    "new_tier": {
                        "type": "string",
                        "enum": ["NORMAL", "SKILLED", "STRONG", "ELITE", "MONSTER", "TITAN", "WORLD", "ABSURD"],
                    },
                    "reason": {"type": "string"},
                },
                "required": ["new_tier", "reason"],
            },
            "breakthrough_event": {
                "type": ["object", "null"],
                "description": (
                    "Confirmacao pos-turn de breakthrough canonico (combat addendum §9). "
                    "Unicidade: uma vez por kind por campanha. null quando nao se aplica."
                ),
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": [
                            "fruit_awakening", "black_blade", "haoshoku_imbuing",
                            "voice_of_all_things", "advanced_armament", "advanced_observation",
                        ],
                    },
                    "target_card_id": {"type": "string", "description": "FRUIT id (awakening) ou ITEM id (black_blade). Ausente nos 4 player-only."},
                    "trigger_context": {"type": "string"},
                },
                "required": ["kind", "trigger_context"],
            },
            "inspector_warnings": {
                "type": "array",
                "description": (
                    "Avisos de inconsistencia (diagnostico passivo; NAO criam card). "
                    "unsignaled_npc = nome proprio na prosa sem entry em "
                    "turn_meta.npcs_to_generate nem match em active_cards[]; preencha name com "
                    "esse nome (so registro — o player resolve via edit manual; geracao de NPC "
                    "e SEMPRE deliberada via turn_meta.npcs_to_generate). "
                    "schema_mismatch = formato fora do esperado. unsignaled_ship = navio "
                    "nomeado na prosa sem card e sem entry em ships_to_generate; se o PLAYER "
                    "passou a navega-lo na cena, preencha os campos de posse (o engine gera o "
                    "card e aplica a troca). Vazio quando nada."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["unsignaled_npc", "unsignaled_item", "unsignaled_ship", "schema_mismatch"]},
                        "context": {"type": "string"},
                        "name": {
                            "type": "string",
                            "description": "SO unsignaled_npc: nome proprio do personagem na prosa que precisa de card.",
                        },
                        "acquired_by_player": {
                            "type": "string",
                            "description": (
                                "SO unsignaled_ship: o player passou a navegar este navio na "
                                "cena (tomou/ganhou/comprou/herdou)? 'true: <como>' OR 'false: "
                                "<navio de passagem, nao assumido>'. 'true' faz o ENGINE gerar o "
                                "SHIP card e aplicar a troca (active); voce NAO forja id nem emite "
                                "ship_generator. 'false'/ausente = so diagnostico."
                            ),
                        },
                        "tentative_name": {
                            "type": "string",
                            "description": "SO unsignaled_ship assumido: nome do navio citado na prosa (vazio se anonimo).",
                        },
                        "subtype_hint": {
                            "type": "string",
                            "description": "SO unsignaled_ship assumido: porte/classe concreta pela prosa (sloop|brig|caravel|schooner|fishing_boat|junk|...).",
                        },
                        "ship_acquisition": {
                            "type": "string",
                            "description": "SO unsignaled_ship assumido: como o player obteve o navio (purchased | gifted | salvaged_wreck | stolen | ...). Colore o hull_condition; opcional (o gerador infere se ausente).",
                        },
                        "initial_hull_condition": {
                            "type": "string",
                            "enum": _HULL_CONDITIONS_ENUM,
                            "description": "SO unsignaled_ship assumido: estado do casco pela prosa.",
                        },
                        "previous_ship_card_id": {
                            "type": "string",
                            "description": (
                                "SO unsignaled_ship assumido: id (copy-paste de active_cards, type "
                                "SHIP) do casco que o player largou/rebocou ao assumir o novo. Vazio "
                                "se o player nao tinha navio proprio antes."
                            ),
                        },
                        "previous_ship_disposition": {
                            "type": "string",
                            "description": (
                                "SO unsignaled_ship assumido: destino do casco anterior. "
                                "sunken|sold|given_away|dismantled tiram-no da frota; vazio/abandoned "
                                "deixam-no como reserva (rebocado)."
                            ),
                        },
                        "swap_kind": {
                            "type": "string",
                            "enum": _SWAP_KINDS_ENUM,
                            "description": "SO unsignaled_ship assumido: tipo da troca (acquired pro primeiro navio proprio; upgraded; wrecked_replacement; lost_and_recovered).",
                        },
                    },
                    "required": ["kind", "context"],
                },
            },
            "dispatched_jobs": {
                "type": "array",
                "description": (
                    "Detectores e geradores que rodam em paralelo pos-turn. Engine consome "
                    "e dispara os prompts referenciados (master §3.3)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": [
                                "npc_generator", "item_generator", "ship_generator",
                                "ending_candidate_detector",
                            ],
                        },
                        "input_ref": {"type": "string"},
                        "moral_code_hint": {
                            "type": "string",
                            "enum": ["absolute", "humane", "personal", "unclear", "lazy", "corrupt"],
                            "description": "So pra npc_generator de Marine (marine_generation §3.1).",
                        },
                        "moral_code_rationale": {"type": "string"},
                        "previous_ship_card_id": {
                            "type": ["string", "null"],
                            "description": (
                                "ship_generator only — id do navio active anterior (copy-paste de "
                                "active_cards) cuja sorte mudou na cena, OU null se nao havia "
                                "(primeiro navio pos-jangada)."
                            ),
                        },
                        "previous_ship_disposition": {
                            "type": ["string", "null"],
                            "enum": _DISPOSITIONS_ENUM + [None],
                            "description": "ship_generator only — sorte do navio anterior.",
                        },
                        "swap_kind": {
                            "type": "string",
                            "enum": _SWAP_KINDS_ENUM,
                            "description": "ship_generator only — swap_kind do lado antigo da troca.",
                        },
                    },
                    "required": ["kind", "input_ref"],
                },
            },
            "card_corrections": {
                "type": "array",
                "description": (
                    "Correcao de summary defasado: um card que voce RECEBEU neste turn "
                    "(active_cards[] com campo summary) afirma um fato que a campanha ja "
                    "desmentiu (evento consumado, world_event, prosa estabelecida). Emita a "
                    "correcao com o fato e o que o desmente; na duvida, NAO corrija. O canal "
                    "escreve APENAS o summary_text — tier/status/affiliation/relationships "
                    "tem canais proprios. Vazio quando nada."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "card_id": {
                            "type": "string",
                            "description": "id LITERAL (copy-paste) de active_cards[] que veio COM campo summary neste turn.",
                        },
                        "contradicted_fact": {
                            "type": "string",
                            "description": "O fato defasado, copiado/parafraseado do summary do card.",
                        },
                        "contradicted_by": {
                            "type": "string",
                            "description": "O que na campanha o desmente (evento/turn/fato estabelecido).",
                        },
                        "corrected_summary_text": {
                            "type": "string",
                            "description": (
                                "summary_text novo COMPLETO, 1-2 frases, redacao atemporal "
                                "(afirme o estado; sem 'recem'/'acabou de')."
                            ),
                        },
                    },
                    "required": ["card_id", "contradicted_fact", "contradicted_by", "corrected_summary_text"],
                },
            },
            "time_advancement": {
                "type": ["object", "null"],
                "description": (
                    "Avanco de dias do mundo (navigation_addendum §1, "
                    "Decisao GDD #8). Emita advance_days = N (N>=1) quando a prosa salta tempo: "
                    "dormir/passar a noite, 'no dia seguinte', montagem de investigacao, OU travessia "
                    "entre ilhas. N e sua decisao (sem cap). null/omitido quando a acao foi continua "
                    "no mesmo dia (multiplos turns no mesmo dia sao normais)."
                ),
                "properties": {
                    "advance_days": {"type": "integer", "description": "Dias decorridos neste turn (>=1)."},
                    "reason": {"type": "string", "description": "1 frase: por que o tempo saltou."},
                },
                "required": ["advance_days"],
            },
            "world_movement": {
                "type": ["object", "null"],
                "description": (
                    "Mudanca de posicao do jogador no mapa "
                    "(navigation_addendum §2). arrive_island = chegou numa ilha neste turn; "
                    "set_sea = zarpou rumo a um destino NOMEADO e esta no mar; set_adrift = zarpou "
                    "pro mar aberto SEM destino escolhido (o pino sai do porto e fica a deriva; NAO "
                    "crave uma ilha que o jogador nao nomeou). destination_id obrigatorio em "
                    "set_sea/arrive_island, ausente em set_adrift; sai do <circle> do WORLD-MAP. "
                    "null/omitido quando ninguem se moveu. O engine atualiza posicao + fog + tempo "
                    "de mar."
                ),
                "properties": {
                    "kind": {"type": "string", "enum": ["set_sea", "arrive_island", "set_adrift"]},
                    "destination_id": {"type": ["string", "null"], "description": (
                        "island_id de destino/chegada (set_sea/arrive_island). Ilha do WORLD-MAP: copie "
                        "o id= do <circle>. Ilha inventada sem nome (carta/rota desconhecida, fora dos "
                        "mares canon): o slug vem da CARTA ou do RUMO que mandou o player pra la, nunca "
                        "de uma pessoa da cena (um civil, um NPC citado neste turn nao batiza a ilha). "
                        "O nome de exibicao real nasce na chegada, pelo Island Designer. Ausente/null "
                        "em set_adrift."
                    )},
                    "origin_id": {"type": ["string", "null"], "description": "island_id de partida (null = posicao atual)."},
                    "reason": {"type": "string"},
                },
                "required": ["kind"],
            },
            "condition_change_event": {
                "type": ["object", "null"],
                "description": (
                    "FASE 11 (Decisao GDD #14). Estado corporal/contextual do PLAYER que limita "
                    "sem mudar competencia — algemado com kairoseki (fruta suprimida), ferido "
                    "grave, envenenado, exausto. Emita quando a cena impoe/limpa esse estado. "
                    "NAO e tier-down: o tier fica intacto (Luffy MONSTER algemado segue MONSTER, "
                    "so com a fruta dormente). new_condition='normal' quando a cena resolve "
                    "(fuga/cura/libertacao). null/omitido quando nada muda na condicao."
                ),
                "properties": {
                    "new_condition": {
                        "type": "string",
                        "description": (
                            "Qualitativo, nao-exaustivo: normal | injured | bound_kairoseki | "
                            "poisoned | exhausted | ... — nomeie conforme a cena."
                        ),
                    },
                    "reason": {"type": "string", "description": "1 frase PT-BR: o que causou."},
                    "source_item_id": {
                        "type": ["string", "null"],
                        "description": "id do item causador (ex: algema kairoseki); null se nao ha.",
                    },
                },
                "required": ["new_condition", "reason"],
            },
            "nemesis_update": {
                "type": ["object", "null"],
                "description": (
                    "FASE 15. Trajetoria do NEMESIS MARINE PRINCIPAL evolutivo (director_nemesis_"
                    "addendum). SO quando o estado traz um nemesis ativo (nemesis_active); null na "
                    "imensa maioria dos turns — emita SO no MARCO, nao na aparicao rotineira. NAO e "
                    "bounty_hunter_events/nemesis_paralelo (aquele cria cacador nao-Marine; este move "
                    "o nemesis Marine que JA existe). change_kind: 'evolved' = cresceu na propria "
                    "trajetoria, on_scene=true apos confronto perdido/escapado OU on_scene=false "
                    "off-scene (Smoker some da cena mas evolui); 'posture_shift' = a relacao com o "
                    "jogador virou (hostile/rival_respectful/ally_leaning Coby-style); "
                    "'defeated_on_scene' = o nemesis SAIU de jogo numa cena COM o jogador "
                    "(captured/dead/missing; dead/missing encerra o ciclo: engine arquiva + gap de "
                    "substituto); 'clash' = houve luta real mas ninguem saiu de jogo (reves tatico "
                    "de qualquer lado — registro leve, nao muta estado). Recuo/JOGADOR perdendo = "
                    "clash (se houve luta) ou null. Em duvida, null."
                ),
                "properties": {
                    "change_kind": {
                        "type": "string",
                        "enum": ["evolved", "posture_shift", "defeated_on_scene", "clash"],
                    },
                    "evolution_facet": {
                        "type": ["string", "null"],
                        "enum": ["rank_up", "power_growth", "new_lieutenant", "bigger_squad", None],
                        "description": (
                            "SO em 'evolved'. rank_up sobe patente (engine cruza o piso de tier); "
                            "power_growth = fruta/Haki/tecnica nova; new_lieutenant = tenente nomeado; "
                            "bigger_squad = forca maior. null fora de 'evolved'."
                        ),
                    },
                    "new_rank": {
                        "type": ["string", "null"],
                        "enum": ["Capitão", "Comodoro", "Vice-Almirante", "Almirante", "Almirante de Frota", None],
                        "description": (
                            "SO em 'evolved'+rank_up: a patente NOVA que o nemesis alcanca (>= a "
                            "atual; monotonica). O engine cruza o piso de tier. null fora de rank_up."
                        ),
                    },
                    "on_scene": {
                        "type": ["boolean", "null"],
                        "description": (
                            "SO em 'evolved': true se a evolucao saiu de um confronto NESTA cena; "
                            "false se cresceu off-scene (Smoker-style). null nos outros change_kind."
                        ),
                    },
                    "new_posture": {
                        "type": ["string", "null"],
                        "enum": ["hostile", "rival_respectful", "ally_leaning", None],
                        "description": "SO em 'posture_shift'. null nos outros.",
                    },
                    "outcome": {
                        "type": ["string", "null"],
                        "enum": ["captured", "dead", "missing", None],
                        "description": (
                            "SO em 'defeated_on_scene' (o nemesis SAIU de jogo nesta cena). dead/"
                            "missing dispara permadeath + gap de substituto; captured poe sob "
                            "custodia. Recuo tatico/jogador perdendo NAO e defeated — e null. "
                            "null nos outros change_kind."
                        ),
                    },
                    "rationale": {
                        "type": "string",
                        "description": "1-2 frases PT-BR factuais: o que no turn/mundo justifica o marco.",
                    },
                },
                "required": ["change_kind", "rationale"],
            },
            "nemesis_spawn": {
                "type": ["object", "null"],
                "description": (
                    "FASE 15. Decisao de a Marinha DESPACHAR o nemesis Marine principal contra o "
                    "jogador (director_nemesis_addendum §0). null na imensa maioria dos turns. "
                    "NAO-null SO quando: (a) ainda NAO ha nemesis ativo (world_state.nemesis_active "
                    "e null) E o peso do jogador justifica o Governo mandar um perseguidor recorrente "
                    "(bounty, caos, ato publico contra a Marinha), OU (b) ha substituto pendente "
                    "(nemesis_dormant.substitute_pending) e a Marinha reagiu a queda do anterior. O "
                    "engine gera o card e fixa a identidade; voce so decide QUANDO e POR QUE. Nao "
                    "confunda com bounty_hunter_events (cacador nao-Marine) nem com nemesis_update "
                    "(move o nemesis que JA existe)."
                ),
                "properties": {
                    "rationale": {
                        "type": "string",
                        "description": "1-2 frases PT-BR factuais: por que o Governo despacha o nemesis agora.",
                    },
                    "initial_posture": {
                        "type": ["string", "null"],
                        "enum": ["hostile", "rival_respectful", "ally_leaning", None],
                        "description": (
                            "Postura com que o cacador comeca em relacao ao jogador. 'hostile' e o "
                            "default (perseguidor mandado pra capturar/matar); escolha outra so "
                            "quando o despacho ja nasce com relacao diferente (rival de honra, Marine "
                            "estilo Coby). Ausente/null = a engine assume hostile."
                        ),
                    },
                    "origin_location": {
                        "type": ["string", "null"],
                        "description": (
                            "De onde o cacador e despachado (base/ilha Marine do mundo). Opcional; a "
                            "engine usa so como fallback de localizacao quando o gerador omite "
                            "current_location, senao cai na cena atual do jogador."
                        ),
                    },
                },
                "required": ["rationale"],
            },
            "parallel_nemesis_updates": {
                "type": "array",
                "description": (
                    "FASE 20. Trajetoria dos CACADORES JA PROMOVIDOS a nemesis paralelo "
                    "(director_nemesis_paralelo_addendum). UM item por cacador que teve marco neste "
                    "turn; array VAZIO na imensa maioria dos turns (so com nemesis paralelo ativo em "
                    "active_parallel_nemeses; emita SO no MARCO). NAO cria cacador novo (isso e "
                    "bounty_hunter_events appearance) nem promove (nemesis_paralelo_promoted) — este "
                    "MOVE um caçador que JA foi promovido. DESACOPLADO de confronto: o caçador cresce "
                    "off-scene (on_scene=false) mesmo sem o jogador reencontra-lo — fugir do caçador "
                    "NAO impede a evolucao. change_kind igual ao nemesis Marine, mas a faceta de salto "
                    "e 'escalada' (caçador nao tem patente Marine)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "hunter_npc_id": {
                            "type": "string",
                            "description": "id do caçador promovido (deve constar em active_parallel_nemeses).",
                        },
                        "change_kind": {
                            "type": "string",
                            "enum": ["evolved", "posture_shift", "defeated_on_scene", "clash"],
                        },
                        "evolution_facet": {
                            "type": ["string", "null"],
                            "enum": ["escalada", "power_growth", "new_lieutenant", "bigger_squad", None],
                            "description": (
                                "SO em 'evolved'. escalada = subiu de escala como ameaca (engine sobe "
                                "o tier um degrau; sem patente Marine); power_growth = fruta/Haki/arma/"
                                "tecnica nova; new_lieutenant = subordinado nomeado; bigger_squad = "
                                "forca maior. null fora de 'evolved'."
                            ),
                        },
                        "on_scene": {
                            "type": ["boolean", "null"],
                            "description": (
                                "SO em 'evolved': true se cresceu num confronto NESTA cena; false se "
                                "cresceu off-scene (caçou/treinou longe do jogador). null nos outros."
                            ),
                        },
                        "new_posture": {
                            "type": ["string", "null"],
                            "enum": ["hostile", "rival_respectful", "ally_leaning", None],
                            "description": "SO em 'posture_shift' (Cross Guild-style pode virar ally_leaning). null nos outros.",
                        },
                        "outcome": {
                            "type": ["string", "null"],
                            "enum": ["captured", "dead", "missing", None],
                            "description": (
                                "SO em 'defeated_on_scene' (o caçador SAIU de jogo nesta cena). dead/"
                                "missing arquiva (sem substituto automatico — caçador era unico pela "
                                "promocao). Recuo tatico/jogador perdendo NAO e defeated — e clash/null."
                            ),
                        },
                        "rationale": {
                            "type": "string",
                            "description": "1-2 frases PT-BR factuais: o que no turn/mundo justifica o marco.",
                        },
                    },
                    "required": ["hunter_npc_id", "change_kind", "rationale"],
                },
            },
            "buster_call_triggered": {
                "type": ["object", "null"],
                "description": (
                    "Golden/Silver Den Den Mushi (mushi addendum §7.4): um NPC com autoridade "
                    "(CP0 / oficial Marine de patente) ACIONOU um Buster Call neste turn. Engine "
                    "registra metadata.buster_call_active + escalada militar. Emita TAMBEM o "
                    "chaos_delta correspondente em deltas[] (top, ~+0.5). null quando nao se aplica."
                ),
                "properties": {
                    "target_island": {"type": "string", "description": "ilha-alvo do Buster Call."},
                    "ordered_by_npc_id": {"type": ["string", "null"], "description": "NPC que ordenou, se sabido."},
                    "reason": {"type": "string", "description": "1 frase PT-BR: por que foi acionado."},
                },
                "required": ["target_island", "reason"],
            },
            "campaign_phase_update": {
                "type": ["string", "null"],
                "enum": ["early", "mid", "late", None],
                "description": (
                    "Fase global da campanha, julgada por voce pela trajetoria do jogador (fama, "
                    "bounty, arcos fechados, alcance): 'early' inicio de jornada, 'mid' jogador "
                    "estabelecido com reputacao regional, 'late' jogador de peso global. Emita SO "
                    "quando a fase MUDA de degrau; null/omitido mantem a atual. Calibra a "
                    "complexidade de ilhas inventadas geradas na chegada."
                ),
            },
        },
        "required": [
            "alignment_pre_audit", "bounty_pre_audit", "economy_pre_audit",
            "ship_pre_audit", "faction_reputation_pre_audit", "alliances_hunters_pre_audit",
            "agent_memory_writeback_pre_audit", "navigation_pre_audit", "world_pulse_pre_audit",
            "edit_primitives", "deltas", "inventory_events", "hull_condition_change_events",
            "ship_swap_events", "crew_alliance_events", "bounty_hunter_events",
            "tier_change_event", "breakthrough_event", "inspector_warnings", "dispatched_jobs",
        ],
    },
}

# Top-level channel defaults (engine discards the *_pre_audit fields).
_POST_TURN_DEFAULTS: dict = {
    "deltas": [],
    "inventory_events": [],
    "hull_condition_change_events": [],
    "ship_swap_events": [],
    "crew_alliance_events": [],
    "bounty_hunter_events": [],
    "crew_departure_event": None,
    "tier_change_event": None,
    "breakthrough_event": None,
    "buster_call_triggered": None,
    "nemesis_spawn": None,
    "campaign_phase_update": None,
    "edit_primitives": [],
    "inspector_warnings": [],
    "dispatched_jobs": [],
    "card_corrections": [],
    "scene_end": None,
}
_PRE_AUDIT_FIELDS = (
    "alignment_pre_audit", "bounty_pre_audit",
    "economy_pre_audit", "ship_pre_audit", "faction_reputation_pre_audit",
    "alliances_hunters_pre_audit", "crew_pre_audit", "agent_memory_writeback_pre_audit",
    "navigation_pre_audit", "world_pulse_pre_audit", "pre_emit_audit",
)

# Bounty tiers that count as a real gate decision (everything but omitir).
_BOUNTY_REAL_TIERS = frozenset({"small", "medium", "large", "massive", "absurd"})


def _instructions_post(extra_addenda: list[str] | None = None) -> str:
    files = _POST_PROMPT_FILES + list(extra_addenda or [])
    parts = [(config.PROMPTS_DIR / f).read_text(encoding="utf-8") for f in files]
    return "\n\n---\n\n".join(parts)


def _only_dicts(value) -> list:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _reconstruct_bounty_from_gate(deltas: list, bounty_audit) -> None:
    """If bounty_pre_audit chose a real tier but the model omitted the bounty_delta,
    rebuild it from the gate. In-place mutation."""
    if not isinstance(bounty_audit, dict):
        return
    tier = bounty_audit.get("escala_repercussao_eleita")
    if tier not in _BOUNTY_REAL_TIERS:
        return
    if any(isinstance(d, dict) and d.get("kind") == "bounty_delta" for d in deltas):
        return
    target = (bounty_audit.get("target_eleito") or "").strip()
    # A real tier with no/void target is a gate incoherence: don't invent 'player', skip + warn.
    if target in ("nenhum", "", "omitir", "nao_aplicavel"):
        return
    deltas.append({
        "kind": "bounty_delta",
        "tier": tier,
        "target": target,
        "source": "action",
        "reason": (bounty_audit.get("ato_publico_processavel_pelo_wg") or "")[:240],
        "_reconstructed_from_gate": True,
    })


def _reconstruct_belly_from_gate(deltas: list, economy_audit) -> None:
    """economy_pre_audit.belly_choice is source-of-truth for belly_delta. Rebuild it when the
    gate chose direction:tier but the model omitted it; remove it when the gate chose omitir
    but a belly_delta was emitted. In-place mutation of deltas."""
    if not isinstance(economy_audit, dict):
        return
    choice = economy_audit.get("belly_choice")
    belly = [d for d in deltas if isinstance(d, dict) and d.get("kind") == "belly_delta"]
    if choice and choice != "omitir" and ":" in choice and not belly:
        direction, tier = choice.split(":", 1)
        if direction in economy.BELLY_DIRECTIONS and tier in economy.BELLY_TIERS:
            src = economy_audit.get("belly_source_eleita")
            if src not in economy.BELLY_SOURCES:
                src = "action"
            deltas.append({
                "kind": "belly_delta",
                "direction": direction,
                "tier": tier,
                "source": src,
                "reason": (economy_audit.get("escala_justificativa") or "reconstruído do gate")[:240],
                "_reconstructed_from_gate": True,
            })
    elif choice == "omitir" and belly:
        deltas[:] = [d for d in deltas if not (isinstance(d, dict) and d.get("kind") == "belly_delta")]


def _reconstruct_faction_from_gate(deltas: list, faction_audit) -> None:
    """If faction_reputation_pre_audit chose a real tier for the MAIN faction but the model
    omitted the faction_reputation_delta, rebuild it (value = tier anchor magnitude, sign from
    sinal_principal). Only the main faction; additional factions have no id in the gate.
    In-place mutation of deltas."""
    if not isinstance(faction_audit, dict):
        return
    tier = faction_audit.get("tier_principal")
    if tier not in faction.TIER_MAGNITUDE:
        return
    if any(isinstance(d, dict) and d.get("kind") == "faction_reputation_delta" for d in deltas):
        return
    fid = (faction_audit.get("faction_id_principal") or "").strip()
    if not fid or fid in ("nenhum", "omitir", ""):
        return
    # A real tier requires a coherent sign / target / source from the gate (all schema-required).
    # Missing/invalid = gate incoherence: don't fabricate '+', 'player', 'action'. Skip the rebuild.
    signal = faction_audit.get("sinal_principal")
    if signal not in ("+", "-"):
        return
    target = (faction_audit.get("target_eleito") or "").strip()
    if target in ("nenhum", "", "omitir"):
        return
    src = faction_audit.get("source_eleita")
    if src not in ("action", "dialog", "meta"):
        return
    sign = -1.0 if signal == "-" else 1.0
    deltas.append({
        "kind": "faction_reputation_delta",
        "faction_id": fid,
        "target": target,
        # TIER_MAGNITUDE is the reconstruction ANCHOR only (the real value is the model's
        # float-guideline in the delta it forgot to emit); kept as bookkeeping, not content.
        "value": round(sign * faction.TIER_MAGNITUDE[tier], 4),
        "source": src,
        "reason": (faction_audit.get("ato_institucional_central") or "reconstruído do gate")[:240],
        "_reconstructed_from_gate": True,
    })


def _reconstruct_crew_from_gate(parsed: dict, crew_audit) -> None:
    """crew_pre_audit is source-of-truth. Per member: non-omitir choice without a delta
    synthesizes crew_dissatisfaction_delta; omitir choice with a delta drops it. Syncs
    crew_departure_event with departure_decision. In-place mutation of parsed."""
    if not isinstance(crew_audit, dict):
        return
    deltas = parsed["deltas"]
    per = [m for m in (crew_audit.get("per_member") or []) if isinstance(m, dict)]

    def _crew_target(d):
        return d.get("target") or d.get("target_npc_id")

    existing = {
        _crew_target(d) for d in deltas
        if isinstance(d, dict) and d.get("kind") == "crew_dissatisfaction_delta"
    }
    for m in per:
        nid = (m.get("npc_id") or "").strip()
        if not nid:
            continue
        choice = m.get("dissatisfaction_choice")
        target = None
        if choice and choice != "omitir":
            try:
                target = float(choice)
            except (TypeError, ValueError):
                target = None
        if target is None and nid in existing:
            parsed["deltas"] = [
                d for d in deltas
                if not (isinstance(d, dict) and d.get("kind") == "crew_dissatisfaction_delta"
                        and _crew_target(d) == nid)
            ]
            deltas = parsed["deltas"]
        elif target is not None and nid not in existing:
            deltas.append({
                "kind": "crew_dissatisfaction_delta", "target": nid,
                "value": round(target, 4), "source": "action",
                "reason": (m.get("touched_this_turn") or "reconstruído do gate")[:240],
                "_reconstructed_from_gate": True,
            })
            existing.add(nid)
    dd = (crew_audit.get("departure_decision") or "nenhum").strip()
    ev = parsed.get("crew_departure_event")
    if dd in ("nenhum", "") and ev:
        parsed["crew_departure_event"] = None
    elif dd not in ("nenhum", "") and not ev:
        parsed["crew_departure_event"] = {
            "npc_id": dd, "reason": "(reconstruído do gate)", "_reconstructed_from_gate": True,
        }


def parse_post_turn(emitted: dict | None) -> dict:
    """Normalize post-turn output: discard the *_pre_audit scratchpads (after using them for
    runtime gate reconstruction), default the channels, filter non-dict items, snap-to-enum the
    alignment/chaos/crew delta magnitudes, and rebuild bounty/belly/faction deltas
    from the gate when the model decided but did not emit."""
    emitted = dict(emitted or {})
    # Capture the gates before discarding; they feed runtime reconstruction.
    bounty_audit = emitted.get("bounty_pre_audit")
    economy_audit = emitted.get("economy_pre_audit")
    faction_audit = emitted.get("faction_reputation_pre_audit")
    crew_audit = emitted.get("crew_pre_audit")
    for f in _PRE_AUDIT_FIELDS:
        emitted.pop(f, None)

    out: dict = {k: (v.copy() if isinstance(v, (dict, list)) else v) for k, v in _POST_TURN_DEFAULTS.items()}
    for k in _POST_TURN_DEFAULTS:
        if k in emitted:
            out[k] = emitted[k]

    out["deltas"] = _only_dicts(out.get("deltas"))
    out["inventory_events"] = _only_dicts(out.get("inventory_events"))
    out["hull_condition_change_events"] = _only_dicts(out.get("hull_condition_change_events"))
    out["ship_swap_events"] = _only_dicts(out.get("ship_swap_events"))
    out["crew_alliance_events"] = _only_dicts(out.get("crew_alliance_events"))
    out["bounty_hunter_events"] = _only_dicts(out.get("bounty_hunter_events"))
    out["edit_primitives"] = _only_dicts(out.get("edit_primitives"))
    out["inspector_warnings"] = _only_dicts(out.get("inspector_warnings"))
    out["dispatched_jobs"] = _only_dicts(out.get("dispatched_jobs"))
    out["card_corrections"] = _only_dicts(out.get("card_corrections"))
    if not isinstance(out.get("tier_change_event"), dict):
        out["tier_change_event"] = None
    if not isinstance(out.get("breakthrough_event"), dict):
        out["breakthrough_event"] = None
    if not isinstance(out.get("buster_call_triggered"), dict):
        out["buster_call_triggered"] = None
    if not isinstance(out.get("scene_end"), dict):
        out["scene_end"] = None
    # nemesis_spawn: valid only as a dict with a non-empty rationale, else null.
    # initial_posture/origin_location are the Director's spawn identity (engine honors them).
    _ns = out.get("nemesis_spawn")
    if isinstance(_ns, dict) and (_ns.get("rationale") or "").strip():
        _spawn = {"rationale": _ns["rationale"].strip()}
        _posture = _ns.get("initial_posture")
        if _posture in ("hostile", "rival_respectful", "ally_leaning"):
            _spawn["initial_posture"] = _posture
        _origin = (_ns.get("origin_location") or "").strip()
        if _origin:
            _spawn["origin_location"] = _origin
        out["nemesis_spawn"] = _spawn
    else:
        out["nemesis_spawn"] = None
    # campaign_phase_update: valid only when it names a phase step, else null.
    if out.get("campaign_phase_update") not in ("early", "mid", "late"):
        out["campaign_phase_update"] = None
    # crew_departure_event only valid with an npc_id, else null.
    _cde = out.get("crew_departure_event")
    if not (isinstance(_cde, dict) and (_cde.get("npc_id") or "").strip()):
        out["crew_departure_event"] = None

    # time_advancement / world_movement: optional (adult world only), validated here for the runner.
    ta = emitted.get("time_advancement")
    if isinstance(ta, dict) and isinstance(ta.get("advance_days"), int) and ta["advance_days"] > 0:
        out["time_advancement"] = {"advance_days": int(ta["advance_days"]), "reason": ta.get("reason", "")}
    wm = emitted.get("world_movement")
    if (
        isinstance(wm, dict)
        and wm.get("kind") in ("set_sea", "arrive_island")
        and isinstance(wm.get("destination_id"), str)
        and wm["destination_id"].strip()
    ):
        out["world_movement"] = {
            "kind": wm["kind"],
            "destination_id": wm["destination_id"].strip(),
            "origin_id": (wm.get("origin_id") or None),
            "reason": wm.get("reason", ""),
        }
    elif isinstance(wm, dict) and wm.get("kind") == "set_adrift":
        # Open sea with no chosen destination: no destination_id.
        out["world_movement"] = {
            "kind": "set_adrift",
            "destination_id": None,
            "origin_id": (wm.get("origin_id") or None),
            "reason": wm.get("reason", ""),
        }

    # condition_change_event: optional (only when the scene changes the player's condition).
    # This channel does not touch tier.
    cce = emitted.get("condition_change_event")
    if isinstance(cce, dict) and isinstance(cce.get("new_condition"), str) and cce["new_condition"].strip():
        out["condition_change_event"] = {
            "new_condition": cce["new_condition"].strip(),
            "reason": cce.get("reason", ""),
            "source_item_id": cce.get("source_item_id") or None,
        }

    # nemesis_update: optional (only with an active nemesis). Validates the discriminator + facet.
    nu = emitted.get("nemesis_update")
    if isinstance(nu, dict) and nu.get("change_kind") in ("evolved", "posture_shift", "defeated_on_scene", "clash"):
        kind = nu["change_kind"]
        parsed_nu = {"change_kind": kind, "rationale": nu.get("rationale", "")}
        if kind == "evolved":
            facet = nu.get("evolution_facet")
            parsed_nu["evolution_facet"] = (
                facet if facet in ("rank_up", "power_growth", "new_lieutenant", "bigger_squad") else None
            )
            if parsed_nu["evolution_facet"] == "rank_up":
                nr = nu.get("new_rank")
                parsed_nu["new_rank"] = nr if nr in (
                    "Capitão", "Comodoro", "Vice-Almirante", "Almirante", "Almirante de Frota"
                ) else None
            parsed_nu["on_scene"] = bool(nu.get("on_scene")) if isinstance(nu.get("on_scene"), bool) else None
        elif kind == "posture_shift":
            posture = nu.get("new_posture")
            parsed_nu["new_posture"] = (
                posture if posture in ("hostile", "rival_respectful", "ally_leaning") else None
            )
        elif kind == "defeated_on_scene":
            outcome = nu.get("outcome")
            parsed_nu["outcome"] = (
                outcome if outcome in ("captured", "dead", "missing") else None
            )
        out["nemesis_update"] = parsed_nu

    # parallel_nemesis_updates: optional array (only with an active parallel nemesis).
    # Validates discriminator + facet per instance.
    pnu_in = emitted.get("parallel_nemesis_updates")
    if isinstance(pnu_in, list):
        parsed_pnu: list[dict] = []
        for ev in pnu_in:
            if not isinstance(ev, dict):
                continue
            hid = (ev.get("hunter_npc_id") or "").strip()
            kind = ev.get("change_kind")
            if not hid or kind not in ("evolved", "posture_shift", "defeated_on_scene", "clash"):
                continue
            item = {"hunter_npc_id": hid, "change_kind": kind, "rationale": ev.get("rationale", "")}
            if kind == "evolved":
                facet = ev.get("evolution_facet")
                item["evolution_facet"] = (
                    facet if facet in ("escalada", "power_growth", "new_lieutenant", "bigger_squad") else None
                )
                item["on_scene"] = bool(ev.get("on_scene")) if isinstance(ev.get("on_scene"), bool) else None
            elif kind == "posture_shift":
                posture = ev.get("new_posture")
                item["new_posture"] = posture if posture in ("hostile", "rival_respectful", "ally_leaning") else None
            elif kind == "defeated_on_scene":
                outcome = ev.get("outcome")
                item["outcome"] = outcome if outcome in ("captured", "dead", "missing") else None
            parsed_pnu.append(item)
        out["parallel_nemesis_updates"] = parsed_pnu

    for d in out["deltas"]:
        kind = d.get("kind")
        v = d.get("value")
        if kind in ("alignment_delta", "crew_alignment_delta") and isinstance(v, (int, float)):
            d["value"] = ws.snap_alignment_delta(v)
        elif kind == "chaos_delta" and isinstance(v, (int, float)):
            d["value"] = ws.snap_chaos_delta(v)

    # Runtime reconstruction from the gates: gate decided, model forgot to emit.
    _reconstruct_bounty_from_gate(out["deltas"], bounty_audit)
    _reconstruct_belly_from_gate(out["deltas"], economy_audit)
    _reconstruct_faction_from_gate(out["deltas"], faction_audit)
    _reconstruct_crew_from_gate(out, crew_audit)
    return out


def _post_turn_valid(parsed: dict) -> bool:
    return all(k in parsed for k in _POST_TURN_DEFAULTS) and isinstance(parsed.get("deltas"), list)


async def call_post_turn(
    post_turn_state: dict, *, retries: int = 1, extra_addenda: list[str] | None = None,
    cached_sections: list[tuple[str, object]] | None = None,
) -> dict:
    """Run the Director post-turn pass and return the parsed output (without *_pre_audit).
    cached_sections (near-static card catalog) gets its own cache breakpoint block before the
    dynamic state. Retries (up to `retries`) on invalid/truncated output or exception.
    extra_addenda appends conditional addenda."""
    parsed: dict | None = None
    last_exc: Exception | None = None
    for _attempt in range(retries + 1):
        try:
            emitted = await client.call_tool(
                model=config.DIRECTOR_MODEL,
                instructions=_instructions_post(),
                volatile_instructions=language.with_directive(_addenda_text(extra_addenda)),
                tag="director",
                sections=[("POST-TURN-STATE", post_turn_state)],
                cached_sections=cached_sections,
                tool=EMIT_POST_TURN_TOOL,
                tool_name="emit_post_turn_decisions",
                temperature=config.DIRECTOR_TEMPERATURE,
                max_tokens=6000,
                trace_label="Diretor · pós-turn",
            )
            parsed = parse_post_turn(emitted)
            if _post_turn_valid(parsed):
                return parsed
        except Exception as e:  # noqa: BLE001 retry covers truncation/parse
            last_exc = e
    if parsed is not None:
        return parsed
    if last_exc is not None:
        raise last_exc
    # Hard fallback: an empty post-turn never breaks the turn.
    return {k: (v.copy() if isinstance(v, (dict, list)) else v) for k, v in _POST_TURN_DEFAULTS.items()}


def cards_with_summary(post_state: dict) -> list[str]:
    """Ids of active_cards that reached the Director WITH a summary this turn: the eligible set
    for the card_corrections channel. Same source as the input, no recompute."""
    cards = (post_state.get("world_state") or {}).get("active_cards") or []
    return [c["id"] for c in cards if isinstance(c, dict) and "summary" in c and c.get("id")]


def _nemesis_dormant_summary(metadata: dict) -> dict:
    """Latent nemesis state so the Director can decide nemesis_spawn even with no active nemesis."""
    nem = metadata.get("nemesis") or {}
    return {
        "has_active": bool(nem.get("current_nemesis_id")),
        "substitute_pending": bool(nem.get("substitute_pending")),
    }


def _nemesis_summary(metadata: dict, npcs: dict, pre_turn_decisions: dict) -> dict | None:
    """Main Marine nemesis summary for the POST pass; None when no active nemesis (gates
    nemesis_update). in_scene matches the nemesis id against the PRE-turn npcs_in_scene."""
    nem = metadata.get("nemesis") or {}
    nid = nem.get("current_nemesis_id")
    if not nid:
        return None
    card = npcs.get(nid) or {}
    in_scene = nid in {
        n.get("agent_id") for n in (pre_turn_decisions.get("npcs_in_scene") or []) if isinstance(n, dict)
    }
    return {
        "nemesis_id": nid,
        "name": card.get("name", ""),
        "rank": nem.get("rank", ""),
        "tier": card.get("tier", ""),
        "moral_code": nem.get("moral_code", ""),
        "posture": nem.get("posture") or card.get("nemesis_posture", "hostile"),
        "status": card.get("status", "alive"),
        "in_scene": in_scene,
    }


_EVENT_STALE_AFTER_TURNS = 5  # a plausible ambient event the player never reached stops counting as live


def _live_background_events(events: list | None, turn_index: int | None) -> list:
    """world_pulse projection: hide a plausible ambient event the player never reached once it is
    stale, so it stops being cited as the live world event. Read-only; the stored event is untouched,
    closure stays LLM-authored, mirroring the foreshadow pool."""
    events = list(events or [])
    if turn_index is None:
        return events
    out = []
    for ev in events:
        stale = (
            isinstance(ev, dict)
            and ev.get("status") in ("active", "brewing")
            and ev.get("player_insertion_plausibility") == "plausible"
            and turn_index - int(ev.get("triggered_at_turn_index", turn_index) or turn_index) >= _EVENT_STALE_AFTER_TURNS
        )
        if not stale:
            out.append(ev)
    return out


def build_post_turn_state(
    player_action: dict,
    state: dict,
    *,
    prose: str,
    turn_meta: dict,
    agent_outputs: list[dict],
    pre_turn_decisions: dict,
    scene: dict,
    active_directives: list[str] | None = None,
    turn_index: int | None = None,
) -> dict:
    """Build the post-turn input contract. active_directives[] is injected so the Director
    honors player authority in the deltas."""
    player_card = state["player_card"]
    npcs: dict = state.get("npcs") or {}
    metadata = (state.get("campaign") or {}).get("metadata") or {}
    pc = player_card.get("player_character") or {}
    psnap = player_card.get("player_snapshot") or {}

    item_cards: dict = state.get("item_cards") or {}
    ship_cards: dict = state.get("ship_cards") or {}
    crew_obj = ship.get_crew(metadata)
    crew = [
        {
            "id": d.get("id", ""),
            "name": d.get("name", ""),
            "tier": d.get("tier", ""),
            "role": d.get("crew_role") or d.get("class", ""),
            "alignment": d.get("alignment_baseline", 0.0),
            # Crew addendum reads these for crew_dissatisfaction_delta + crew_departure_event.
            # bond_tier from the NPC->player relationship; dissatisfaction is the accumulated [0,1] measure.
            "bond_tier": int(((d.get("relationships") or {}).get("player") or {}).get("bond_tier", 0) or 0),
            "dissatisfaction": round(float(d.get("dissatisfaction", 0.0) or 0.0), 4),
            "current_goal": d.get("current_goal", ""),
            "core_traits": d.get("traits") or d.get("core_traits") or [],
        }
        for d in npcs.values()
        if d.get("affiliation") == "player_crew"
    ]
    # ITEM and SHIP cards enter active_cards so the Director can reference item_card_id/ship_card_id
    # under the copy-paste existence gate. SHIP carries role + hull_condition for the ship addendum gate.
    _ship_role_by_id = {e["ship_card_id"]: e.get("role", "reserve") for e in ship.fleet_entries(crew_obj)}
    # NPC in context this turn (on-scene in PRE or crewmate) carries summary in active_cards;
    # that field enables card_corrections, and the executor gate uses the same set.
    _in_scene_ids = {
        n.get("agent_id") for n in (pre_turn_decisions.get("npcs_in_scene") or []) if isinstance(n, dict)
    }

    # Dynamic part of active_cards[]: NPCs in context (with summary, enabling card_corrections)
    # + SHIPs (volatile role/hull). The rest goes in the cached WORLD-CARDS-CATALOG block;
    # the rules apply to the union of both parts.
    def _npc_active_card(d: dict) -> dict:
        return {
            "id": d.get("id", ""), "name": d.get("name", ""), "aliases": d.get("aliases", []),
            "type": "NPC", "summary": (d.get("current_state") or {}).get("summary_text", ""),
        }

    active_cards = [
        _npc_active_card(d)
        for d in npcs.values()
        if d.get("id") in _in_scene_ids or d.get("affiliation") == "player_crew"
    ] + [
        {"id": d.get("id", ""), "name": d.get("name", ""), "aliases": d.get("aliases", []),
         "type": "SHIP", "role": _ship_role_by_id.get(d.get("id"), "reserve"),
         "hull_condition": (d.get("current_state") or {}).get("hull_condition", "")}
        for d in ship_cards.values()
    ]
    alignment = psnap.get("alignment")
    if not isinstance(alignment, dict):
        alignment = ws.make_alignment(0.0)

    # belly + bucket + resolved inventory (card name) for calibrating belly_delta/inventory_events.
    cards_by_id = {**npcs, **item_cards}
    belly = economy.belly_amount(psnap)
    player_inventory = [
        {
            "item_card_id": e.get("item_card_id", ""),
            "name": (cards_by_id.get(e.get("item_card_id")) or {}).get("name", ""),
            "quantity": e.get("quantity"),
        }
        for e in (psnap.get("inventory") or []) if isinstance(e, dict) and e.get("item_card_id")
    ]

    world_state = {
        "player": {
            "id": player_card.get("id", "player"),
            "name": pc.get("name", ""),
            "dream": pc.get("dream") or (player_card.get("character_creation") or {}).get("dream") or "",
            "tier": psnap.get("tier") or pc.get("tier", ""),
            # Current player condition, exposed so the Director knows there is a state to keep or
            # to clear. Condition is ephemeral; tier is accumulated competence (kept separate).
            "condition": psnap.get("condition") or "normal",
            "fruit": psnap.get("fruit") or pc.get("fruit"),
            "haki": psnap.get("haki") or pc.get("haki", []),
            "bounty": {"current_amount": _bounty_amount(psnap)},
            "alignment": alignment,
            "breakthroughs": psnap.get("breakthroughs", []),
            # Accumulated institutional reputation (sparse map); the engine sums new deltas onto it.
            "faction_reputations": faction.reputations_of(psnap),
            # Captain's single pot + unlimited inventory. Raw belly; the model reads the magnitude.
            "belly": belly,
            "inventory": player_inventory,
            # The post-turn emits mushi/vivre edit_primitives; needs what the player already has + current cluster.
            "position_cluster": mushi.cluster_of(scene.get("location", "")),
            "paired_mushis": mushi.director_paired_mushis(psnap, npcs),
            "vivre_cards": mushi.director_vivre_cards(psnap, npcs),
            # Player taps + counter-tap (dedup for plant/remove/set in POST).
            "black_mushi_taps": mushi.director_black_taps(psnap, npcs),
            "white_mushi_active": mushi.white_mushi_active(psnap),
        },
        "crew": crew,
        "chaos_meter": metadata.get("chaos_meter") or {"value": 0.0, "bucket": "calm"},
        "active_cards": active_cards,
        # Crew fleet for deciding hull_condition_change_events / ship_swap_events; read, not output.
        "crew_fleet": ship.fleet_summary(crew_obj, ship_cards),
        "events_background_recent": _live_background_events(metadata.get("events_background"), turn_index),
        # Current public myth per target; the legend_update decision patches against this.
        "legend_state": legend.legend_brief(metadata),
        # Active alliances (matchmaking + spawn-blocking gate) + recent hunter encounters (the
        # Director reads the count for qualitative anti-saturation, no deterministic cap).
        "crew_alliances": alliances.crew_alliances_of(metadata),
        "recent_bounty_hunter_encounters": alliances.recent_bounty_hunter_encounters(metadata),
        # Main Marine nemesis state; gates nemesis_update (null when none). in_scene calibrates on_scene.
        "nemesis_active": _nemesis_summary(metadata, npcs, pre_turn_decisions),
        # Latent nemesis state so the Director can decide nemesis_spawn even with no active nemesis.
        "nemesis_dormant": _nemesis_dormant_summary(metadata),
        # Hunters already promoted to parallel nemesis; gates parallel_nemesis_updates.
        "active_parallel_nemeses": alliances.active_parallel_nemeses(npcs),
        # Position / navigable islands for emitting time_advancement/world_movement.
        **world_map.nav_summary(metadata),
    }

    pre_flags = {
        "surprise_actions": pre_turn_decisions.get("surprise_actions", []),
        "breakthrough_imminent": pre_turn_decisions.get("breakthrough_imminent"),
        "plot_armor_engaged": bool(pre_turn_decisions.get("plot_armor_engaged", False)),
        "arrival_triggers": pre_turn_decisions.get("arrival_triggers"),
        "incoming_mushi_call": pre_turn_decisions.get("incoming_mushi_call"),
        "outgoing_mushi_call": pre_turn_decisions.get("outgoing_mushi_call"),
        "offer_training": pre_turn_decisions.get("offer_training"),
    }

    out = {
        "player_input": {
            "type": player_action.get("type", "DO"),
            "raw": player_action.get("raw", ""),
        },
        "prose_do_opus": prose,
        "turn_meta_emitted_by_opus": turn_meta or {},
        "agent_outputs": agent_outputs or [],
        "world_state": world_state,
        "scene": scene,
        "pre_turn_flags_recap": pre_flags,
        "active_directives": active_directives or [],
    }
    return out
