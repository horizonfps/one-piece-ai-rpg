"""Narrator (Opus 4.8) — emits `emit_turn { prose, turn_meta }` via CLIProxyAPI.

Forced tool emits prose + structured turn_meta in one call (post-turn depends on turn_meta).
Prompt = narrator master + turn_meta addendum. Cloaking lives in app.proxy.client.
"""
from __future__ import annotations

import re

from .. import config
from ..proxy import client
from ..proxy.errors import ModelRefusalError, QuotaExceededError
from . import language

_PROMPT_FILES = [
    "narrator_system_prompt.pt-br.md",
    "narrator_turn_meta_addendum.pt-br.md",
]
MAX_TOKENS = 3600  # prose + turn_meta with headroom


def _read_prompts(files: list[str]) -> str:
    parts = [(config.PROMPTS_DIR / f).read_text(encoding="utf-8") for f in files]
    return "\n\n---\n\n".join(parts)


# emit_turn tool schema (prose + turn_meta). turn_meta channels feed the Director
# post-turn: fruit/techniques used, npcs/items/ships to generate, npc action summaries.
EMIT_TURN_TOOL = {
    "name": "emit_turn",
    "description": (
        "Emite a cena do turn: `prose` (o texto da narração — exatamente o que o player lê, "
        "seguindo TODAS as regras do narrator_system_prompt; sem JSON, sem metadata embutida) "
        "e `turn_meta` (metadata estruturado pra engine, NAO vaza na prosa). Chame UMA vez. "
        "Preencha pre_emit_audit PRIMEIRO: o gate é um compromisso de estilo que a prosa "
        "escrita depois honra."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            # Reflexive forcing function: gate-required string-enum filled before prose;
            # re-asserting the rule reduces style drift. Engine ignores it (return is
            # built only from prose + turn_meta).
            "pre_emit_audit": {
                "type": "object",
                "description": (
                    "Compromisso de estilo da prosa escrita logo abaixo. Emita o gate com seu "
                    "valor literal e escreva a prosa honrando-o."
                ),
                "properties": {
                    "agencia_do_jogador": {
                        "type": "string",
                        "enum": ["renderizo_so_o_que_o_jogador_declarou_e_paro_sem_por_fala_decisao_ou_poder_na_boca_dele"],
                        "description": (
                            "Renderizo a ação que o jogador descreveu e o efeito imediato dela, e "
                            "paro. A `raw` é o teto do que ele faz. Quando a `raw` não traz fala, o "
                            "personagem do jogador age calado neste turn: não invento diálogo dele, "
                            "nem plano declarado, mudança de objetivo, decisão social, emoção "
                            "escolhida ou acionamento de fruta/Haki/técnica que ele não pediu. "
                            "Pergunta direta de NPC pausa a cena, sem eu responder por ele."
                        ),
                    },
                    "gesto_sem_glosa": {
                        "type": "string",
                        "enum": ["mostro_o_gesto_e_paro_sem_clausula_que_o_interpreta"],
                        "description": (
                            "Cada gesto, olhar ou silêncio fica no concreto e para. Nenhum vem "
                            "seguido de cláusula que diz o que ele significou (\"como quem\", "
                            "\"de quem\", \"como se\", \"no jeito de quem\") nem de sentença "
                            "que o interpreta. Em inglês o mesmo vício entra pela comparação "
                            "hipotética que traduz o gesto (\"as if\", \"like\", \"the way\", "
                            "\"longer than ... would\") e pelo aposto curto que reclassifica o "
                            "ato recém-mostrado; a pausa também não sai em unidade teatral "
                            "(\"a beat\"). O leitor lê o ato, não a leitura dele."
                        ),
                    },
                    "eco_e_recap": {
                        "type": "string",
                        "enum": ["reajo_e_avanco_sem_recapitular_nem_repetir_palavra_para_efeito"],
                        "description": (
                            "A cena reage à ação do jogador e avança. NPC não enumera o que o "
                            "jogador acabou de fazer nem devolve as palavras dele. Mesmo em espanto "
                            "grande, ele reage a um fato concreto e segue, sem empilhar numa lista "
                            "os atos recentes do jogador para marcar o absurdo (a incredulidade "
                            "acumulada que enfileira o que ele fez e desemboca no pedido do "
                            "momento). E não repete a "
                            "própria palavra como recurso dramático (a mesma palavra ecoada duas "
                            "vezes pra carregar emoção): diz uma vez e segue. Inclui a anáfora de "
                            "série (a mesma abertura de frase repetida em frases consecutivas pra "
                            "efeito) e o mesmo molde de frase-soco reaparecendo turn após turn."
                        ),
                    },
                    "contraste": {
                        "type": "string",
                        "enum": ["afirmo_a_qualidade_que_vale_e_paro_sem_negar_alternativa_antes"],
                        "description": (
                            "Afirme a coisa direto. Sem a estrutura de negar uma ou mais "
                            "alternativas antes de revelar a verdadeira. Em inglês o mesmo vício "
                            "entra pelo aposto de negação pendurado na afirmação (o \"not/no ...\" "
                            "curto que descarta a alternativa depois de mostrar o ato) e pela "
                            "estrutura not-X-but-Y."
                        ),
                    },
                    "aforismo_e_oraculo": {
                        "type": "string",
                        "enum": ["npc_fala_no_registro_banal_da_pessoa_e_a_cena_fecha_no_ato_concreto"],
                        "description": (
                            "A fala de cada NPC fica no registro concreto e cotidiano de quem ele "
                            "é: justifica o que faz pelo motivo prático real, sem embrulhar a fala "
                            "em provérbio ou ditado de sabedoria fabricado, sem metáfora grave pra "
                            "dizer coisa simples, sem sentença que destila o momento. Significado "
                            "banal sai em palavra banal. Isso inclui o trabalhador de ofício "
                            "(pescador, cozinheiro, estivador): a perícia dele sai no detalhe prático "
                            "concreto, nunca num ditado sobre o próprio ramo. A cena fecha no ato "
                            "concreto, não num rótulo que a resume nem num aforismo, e nenhum NPC vira "
                            "oráculo (sem máxima nem profecia). O fecho também não personifica o "
                            "cenário em oráculo (o mar ou o mundo que espera, julga ou promete algo ao "
                            "protagonista) nem fecha em tríade cujo último item é uma abstração que "
                            "destila os dois concretos anteriores. O peso vem do que acontece, não de a "
                            "fala soar funda."
                        ),
                    },
                    "narrar_e_desnarrar": {
                        "type": "string",
                        "enum": ["narro_a_versao_consumada_sem_corrigir_no_proprio_texto"],
                        "description": (
                            "Narre a versão final do ato. Sem afirmar uma coisa e corrigi-la no "
                            "mesmo texto (\"não era X, era Y\" como auto-revisão)."
                        ),
                    },
                    "fragmentacao": {
                        "type": "string",
                        "enum": ["frases_respiram_com_virgula_e_conjuncao_sem_staccato_de_pontos_duros"],
                        "description": (
                            "Frases articuladas com vírgula e conjunção. Sem staccato de fragmentos "
                            "curtos cravados por ponto duro como recurso de tensão. Inclui a "
                            "frase-soco de uma ou duas palavras usada como beat dramático e a série "
                            "de orações curtas sem sujeito encadeadas por ponto."
                        ),
                    },
                    "quimica_sensorial": {
                        "type": "string",
                        "enum": ["descrevo_o_sentido_pelo_concreto_da_cena_sem_metal_ozonio_enxofre_nem_sal_de_atmosfera"],
                        "description": (
                            "Cheiro/gosto pelo concreto da cena. Sem elemento de tabela periódica "
                            "(metal, ozônio, enxofre, ferro) e sem sal/maresia como atmosfera "
                            "fora de cena de mar."
                        ),
                    },
                    "voz_expressiva_completa": {
                        "type": "string",
                        "enum": ["a_maioria_reage_alto_em_corpo_e_careta_o_contido_fala_pouco_mas_inteiro"],
                        "description": (
                            "Amplitude One Piece é o default: a maioria dos NPCs reage grande e por "
                            "fora, boca aberta, passo atrás, voz que sobe, careta, descrença em "
                            "pergunta alta, ancorada em gesto concreto. A fala alta sai com ponto de "
                            "exclamação e o espanto com interrogação, um sinal por fala, na medida do "
                            "gesto, sem racionar como recurso raro e sem enfileirar. Amplitude é de "
                            "corpo e volume, não de caixa-alta nem fala longa: a fala segue curta "
                            "e chã, só sai alta. Fechar toda fala em ponto final chapa o registro. O "
                            "contido é a minoria que o briefing sinaliza (mood ou voz reclusa): fala "
                            "pouco, mas em frase inteira e viva, nunca picada ou monossilábica. Cortar "
                            "vício é da forma do texto, não do tamanho da reação."
                        ),
                    },
                    "cena_avanca_por_gente_e_ato": {
                        "type": "string",
                        "enum": ["abro_no_concreto_e_a_cena_avanca_por_gente_e_ato_desde_o_primeiro_beat"],
                        "description": (
                            "A oração de lugar ancora e cede a vez à gente e ao ato no mesmo "
                            "movimento; a cena tem dianteira e energia pra fora desde o primeiro "
                            "beat. Numa cena de poucos ou nenhum NPC, o que carrega é o "
                            "personagem do jogador agindo e o evento concreto, com cor e movimento."
                        ),
                    },
                    "cenario_especifico_nao_molde": {
                        "type": "string",
                        "enum": ["o_cenario_entra_pelo_que_ESTE_lugar_e_navio_sao_variando_de_lugar_pra_lugar"],
                        "description": (
                            "O cenário entra pelo que ESTE lugar e ESTE navio especificamente são. "
                            "Um lugar novo se estabelece pela função, economia e cultura próprias que "
                            "o briefing lhe deu (do que a vida ali vive, quem manda, o que a move), e "
                            "isso varia de lugar pra lugar. Nenhuma cidade costeira recai no mesmo "
                            "molde de vila de pesca aplicado igual a toda parte; a pesca é uma vida "
                            "entre muitas, nunca o default. O navio entra "
                            "pela silhueta e pelo que muda na cena, sem litania recorrente de partes "
                            "estruturais e sem re-encenar como beat fresco um estado de casco já "
                            "estabelecido. Vocabulário de cenário já gasto nos turns recentes não se "
                            "repete: outro ângulo, ou fica de fora."
                        ),
                    },
                },
                "required": [
                    "agencia_do_jogador", "gesto_sem_glosa", "eco_e_recap", "contraste",
                    "aforismo_e_oraculo", "narrar_e_desnarrar", "fragmentacao",
                    "quimica_sensorial", "voz_expressiva_completa", "cena_avanca_por_gente_e_ato",
                    "cenario_especifico_nao_molde",
                ],
            },
            "prose": {
                "type": "string",
                "description": (
                    "A cena em prosa PT-BR. Voz consistente por NPC, diálogo com travessão (nunca aspas), "
                    "sem `tu`, sem fragmentação patológica. É o produto principal."
                ),
            },
            "turn_meta": {
                "type": "object",
                "description": "Metadata estruturado pra engine. Emita os arrays aplicáveis e [] nos demais.",
                "properties": {
                    "scene_status": {
                        "type": "string",
                        "enum": ["continua", "fecha"],
                        "description": (
                            "Decida se este beat FECHA a cena atual. `fecha` quando o foco vai "
                            "mudar de lugar, tempo ou companhia (saiu do local, pulou no tempo, a "
                            "conversa/confronto acabou e os personagens se dispersam) — aí a engine "
                            "cristaliza a cena inteira de uma vez. `continua` enquanto o mesmo "
                            "momento segue. Na dúvida, `continua`."
                        ),
                    },
                    "fruit_usage": {
                        "type": "array",
                        "description": "Player-only. Uma entry se o player usou a própria fruta neste turn.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "fruit_id": {"type": "string"},
                                "usage_summary": {"type": "string", "description": "1-2 frases do que o player fez com a fruta."},
                            },
                            "required": ["fruit_id", "usage_summary"],
                        },
                    },
                    "techniques_used": {
                        "type": "array",
                        "description": "Técnica nomeada por owner elegível (player / crew / nemesis Marine). Uma entry por técnica.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "owner_id": {"type": "string"},
                                "name": {"type": "string"},
                                "description": {"type": "string", "description": "Opcional; omita se a prosa já carrega."},
                            },
                            "required": ["owner_id", "name"],
                        },
                    },
                    "npcs_to_generate": {
                        "type": "array",
                        "description": (
                            "Nome próprio NOVO que apareceu na prosa e ainda não tem card. "
                            "O Diretor dispara o gerador por entry. Vazio se nenhum novo."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "role": {"type": "string", "description": "Obrigatório: papel do NPC na cena (marine, nemesis_marine, civil, pirata, mestre, aliado, vitima, ...). Calibra o gerador."},
                                "context": {"type": "string", "description": "1 frase do que o NPC fez/é na cena."},
                                "entity_kind": {
                                    "type": "string",
                                    "enum": ["person", "creature"],
                                    "description": (
                                        "person (default) = ser que fala/pensa. creature = animal/fera/"
                                        "Rei do Mar/pet que NÃO fala; vira card leve sem mente de agente. "
                                        "Marque creature para qualquer bicho nomeado na prosa."
                                    ),
                                },
                                "on_scene": {
                                    "type": "boolean",
                                    "description": (
                                        "true (default) = este nome novo está fisicamente na cena agora "
                                        "(aparece/age/fala aqui). false = só foi mencionado ou nomeado de "
                                        "longe (um capitão que um capanga cita, alguém noutro lugar): vira "
                                        "card, mas NÃO entra no elenco da cena. Marque false pra nome "
                                        "citado que o jogador não vê presente."
                                    ),
                                },
                            },
                            "required": ["name", "role"],
                        },
                    },
                    "npc_action_summaries": {
                        "type": "array",
                        "description": (
                            "Resumo factual da ação de cada NPC nomeado em cena (persistência multi-turn "
                            "/ defesa do Diretor). Uma entry por NPC ativo."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "npc_id": {"type": "string", "description": "id do card quando conhecido; senão omita."},
                                "name": {"type": "string"},
                                "summary": {"type": "string", "description": "1 frase factual do que o NPC fez."},
                            },
                            "required": ["name", "summary"],
                        },
                    },
                    "npc_tactical_outcomes": {
                        "type": "array",
                        "description": (
                            "FASE 27. Desfecho tático de um NPC em cena que a SUA prosa consumou: "
                            "rendeu-se, foi feito refém, ou recuou. Fato visível na cena, não intenção. "
                            "Uma entry por NPC com desfecho. Vazio quando nenhum (o normal numa cena social)."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "npc_id": {"type": "string", "description": "id do card quando conhecido; senão omita."},
                                "name": {"type": "string"},
                                "outcome": {
                                    "type": "string",
                                    "enum": ["surrender", "taken_hostage", "regroup"],
                                    "description": (
                                        "surrender = baixou as armas por vontade; taken_hostage = foi "
                                        "dominado como refém; regroup = recuou pra se reagrupar."
                                    ),
                                },
                                "captor_name": {"type": "string", "description": "Só em taken_hostage: quem o domina."},
                            },
                            "required": ["name", "outcome"],
                        },
                    },
                    "crew_offers": {
                        "type": "array",
                        "description": (
                            "FASE 27. NPC em cena que, na SUA prosa, pediu/ofereceu pra entrar no bando do "
                            "jogador. Vira oferta pendente (o jogador aceita ou recusa depois). Uma entry "
                            "por NPC. Vazio quando ninguém se ofereceu."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "npc_id": {"type": "string", "description": "id do card quando conhecido; senão omita."},
                                "name": {"type": "string"},
                            },
                            "required": ["name"],
                        },
                    },
                    "recruitment_resolutions": {
                        "type": "array",
                        "description": (
                            "FASE 27. Quando o jogador convidou um NPC pro bando (ou respondeu a uma oferta) "
                            "NESTE turn, o que o NPC decidiu na SUA prosa: aceitou e entrou, ou recusou. "
                            "Você decide o aceite encarnando o NPC (afinidade, sonho, código, momento da "
                            "cena); a engine só registra o fato. Uma entry por NPC resolvido. Vazio quando "
                            "não houve convite/resposta este turn."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "npc_id": {"type": "string", "description": "id do card quando conhecido; senão omita."},
                                "name": {"type": "string"},
                                "decision": {"type": "string", "enum": ["accepted", "declined"]},
                            },
                            "required": ["name", "decision"],
                        },
                    },
                    "items_to_generate": {
                        "type": "array",
                        "description": (
                            "FASE 17. Item material NOMEADO novo que apareceu na prosa e ainda não tem "
                            "card (uma Meito tomada, um Log Pose ganho, um mapa raro achado, provisões "
                            "compradas). O Diretor dispara o item_generator por entry. NÃO inclua fruta "
                            "(referencia o FRUIT card existente) nem item já com card. Vazio se nenhum novo."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "item_category": {
                                    "type": "string",
                                    "description": "weapon | navigation | consumable | document | kairoseki | communication | treasure | tool | misc | ...",
                                },
                                "context": {"type": "string", "description": "1 frase: o que é + como entrou na cena."},
                                "acquired_by_player": {
                                    "type": "boolean",
                                    "description": "true se o player ficou com o item pro inventário neste turn.",
                                },
                                "stackable": {
                                    "type": "boolean",
                                    "description": "true pra suprimento contável (provisões, balas, antídotos genéricos).",
                                },
                            },
                            "required": ["name"],
                        },
                    },
                    "ships_to_generate": {
                        "type": "array",
                        "description": (
                            "FASE 18. Navio NOMEADO original que o player passou a possuir e ainda "
                            "não tem card (comprado num estaleiro, presente, naufrágio recuperado, "
                            "tomado de inimigo não-cardificado). O Diretor dispara o ship_generator "
                            "por entry. NÃO inclua navio já com card, navio canônico, nem a jangada "
                            "inicial. Vazio se nenhum novo (narrator_ship_addendum §4)."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "tentative_name": {"type": "string", "description": "Nome do navio, ou omita se você não batizou (o gerador batiza)."},
                                "context": {"type": "string", "description": "1-3 frases: que navio é, de onde veio, como entrou em posse do player."},
                                "ship_acquisition": {
                                    "type": "string",
                                    "description": "Obrigatório: como o player obteve o navio (purchased | gifted | salvaged_wreck | stolen | ...). Calibra o hull_condition inicial do gerador.",
                                },
                                "acquired_by_player": {
                                    "type": "boolean",
                                    "description": "true se o navio entrou na frota do player neste turn.",
                                },
                            },
                            "required": ["context", "ship_acquisition"],
                        },
                    },
                    "threads_touched": {
                        "type": "array",
                        "description": (
                            "FASE 30. hook_id de cada fio aberto (de island_threads) que a SUA prosa "
                            "teceu neste turn porque o player tocou o tema/lugar. Só o id, um por fio "
                            "tocado. O fio PERMANECE aberto. Vazio se você não teceu nenhum (o normal)."
                        ),
                        "items": {"type": "string"},
                    },
                    "threads_resolved": {
                        "type": "array",
                        "description": (
                            "FASE 30. hook_id de cada fio que a SUA prosa FECHOU neste turn (o "
                            "desdobramento se consumou e não tem mais para onde ir). Só o id, um por "
                            "fio fechado. A engine remove o fio do pool. Vazio se nenhum fechou."
                        ),
                        "items": {"type": "string"},
                    },
                    "news_coo_edition": {
                        "type": "object",
                        "description": (
                            "PRESENTE SÓ no turn em que a ave entregou o jornal (news_coo_incoming "
                            "no input). Registro factual da edição pra aba Jornal; NÃO vaza na prosa "
                            "(a prosa já encenou a chegada + a repercussão). Ausente quando não "
                            "chegou jornal."
                        ),
                        "properties": {
                            "headline": {"type": "string", "description": "A manchete exata que ficou na capa."},
                            "cover_summary": {"type": "string", "description": "1-2 frases factuais do que a capa traz."},
                            "player_in_cover": {"type": "boolean", "description": "true se a capa é sobre o jogador."},
                            "primary_subject": {
                                "type": "string",
                                "enum": ["player_bounty", "world_event", "other_character"],
                                "description": "Obrigatório: sobre o que a edição entregue é primariamente (classifica a aba Jornal).",
                            },
                            "reactions": {
                                "type": "array",
                                "description": "Quem você encenou reagindo de longe. Uma entry por NPC.",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "note": {"type": "string", "description": "1 frase factual da reação."},
                                    },
                                    "required": ["name"],
                                },
                            },
                            "covered_event_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "Ids de pool.major_events que a SUA edição de fato noticiou "
                                    "(capa ou nota interna). Os demais continuam inéditos para "
                                    "edições futuras. Vazio quando a edição não tocou evento do pool."
                                ),
                            },
                        },
                        "required": ["headline", "primary_subject"],
                    },
                    "imagery_leaned_on": {
                        "type": "array",
                        "description": (
                            "Até ~6 imagens/epítetos/pares descritivos concretos em que você se apoiou "
                            "NESTE beat e que arriscam virar carimbo se repetidos. Strings curtas em "
                            "PT-BR. A engine acumula a lista recente e devolve como banco 'varie isto' "
                            "no próximo turn. Vazio se nada digno de nota."
                        ),
                        "items": {"type": "string"},
                    },
                },
                "required": ["fruit_usage", "techniques_used", "npcs_to_generate", "npc_action_summaries"],
            },
        },
        "required": ["pre_emit_audit", "prose", "turn_meta"],
    },
}

_TURN_META_ARRAYS = (
    "fruit_usage", "techniques_used", "npcs_to_generate",
    "npc_action_summaries", "npc_tactical_outcomes", "crew_offers",
    "recruitment_resolutions", "items_to_generate", "ships_to_generate",
)

# FASE 30 continuity threads: arrays of hook_id strings (not objects).
_TURN_META_STR_ARRAYS = ("threads_touched", "threads_resolved", "imagery_leaned_on")

# Defense: the model sometimes echoes the tool structure inside `prose` (closing `</prose>`
# then re-emitting turn_meta). Cut at the first tool-call artifact and strip a leading
# `<prose>` tag.
_PROSE_TAIL_RE = re.compile(r"</prose\s*>|<\s*/?\s*parameter\b|<\s*/?\s*function_calls\b|<\s*/?\s*invoke\b", re.IGNORECASE)
_PROSE_OPEN_RE = re.compile(r"^\s*<\s*prose\s*>\s*", re.IGNORECASE)


def sanitize_prose(prose: str) -> str:
    """Strip tool-call artifacts the model sometimes appends to `prose`."""
    s = _PROSE_OPEN_RE.sub("", prose or "")
    m = _PROSE_TAIL_RE.search(s)
    if m:
        s = s[: m.start()]
    return s.strip()


def normalize_turn_meta(raw) -> dict:
    """Ensure the turn_meta arrays exist, dropping non-dict items. Keep `scene_status`
    (continua|fecha) when emitted; the runner uses it to close the scene and run the
    crystallizer, and assumes continua when absent or invalid."""
    raw = raw if isinstance(raw, dict) else {}
    out: dict = {}
    for k in _TURN_META_ARRAYS:
        v = raw.get(k)
        out[k] = [it for it in v if isinstance(it, dict)] if isinstance(v, list) else []
    for k in _TURN_META_STR_ARRAYS:
        v = raw.get(k)
        out[k] = [s.strip() for s in v if isinstance(s, str) and s.strip()] if isinstance(v, list) else []
    if raw.get("scene_status") in ("continua", "fecha"):
        out["scene_status"] = raw["scene_status"]
    edition = raw.get("news_coo_edition")
    if isinstance(edition, dict) and (edition.get("headline") or "").strip():
        out["news_coo_edition"] = edition
    return out


async def call_narrator(
    turn_state: dict,
    *,
    retries: int = 1,
    extra_addenda: list[str] | None = None,
    reroll_note: str | None = None,
    emit_tool: dict | None = None,
) -> dict:
    """Return `{prose, turn_meta}`. Forced tool guarantees the shape; retry on empty prose
    or tool failure; final fallback = recoverable prose + empty turn_meta (a turn never
    breaks on missing turn_meta). `extra_addenda` = per-turn conditional addenda; they go in
    a volatile block OUTSIDE the cached prefix (inside block 0 they would bust the master
    cache every turn). `reroll_note` = optional player instruction on prose reroll; enters as
    a one-shot dynamic section, not persisted. `emit_tool` overrides the emit schema (A/B
gate testing); production defaults to EMIT_TURN_TOOL with the pre_emit_audit gate."""
    instructions = _read_prompts(_PROMPT_FILES)
    addenda = _read_prompts(list(extra_addenda)) if extra_addenda else None
    sections: list[tuple[str, object]] = [("TURN-STATE", turn_state)]
    if reroll_note and reroll_note.strip():
        sections.append((
            "INSTRUÇÃO DO JOGADOR PARA ESTA REGENERAÇÃO",
            reroll_note.strip(),
        ))
    last_prose = ""
    last_exc: Exception | None = None
    for _attempt in range(retries + 1):
        try:
            emitted = await client.call_tool(
                model=config.NARRATOR_MODEL,
                instructions=instructions,
                tag="narrator",
                sections=sections,
                volatile_instructions=language.with_directive(addenda),
                tool=emit_tool or EMIT_TURN_TOOL,
                tool_name="emit_turn",
                max_tokens=MAX_TOKENS,
            )
            prose = sanitize_prose(emitted.get("prose") or "")
            if prose:
                return {"prose": prose, "turn_meta": normalize_turn_meta(emitted.get("turn_meta"))}
            last_prose = last_prose or prose
        except (QuotaExceededError, ModelRefusalError):
            # Quota exhaustion and content refusal are not retried or masked; they bubble
            # straight to the runner to surface.
            raise
        except Exception as e:  # noqa: BLE001 retry covers truncation/parse
            last_exc = e
    if last_prose:
        return {"prose": last_prose, "turn_meta": normalize_turn_meta(None)}
    raise last_exc if last_exc is not None else RuntimeError("narrador sem prosa utilizável")
