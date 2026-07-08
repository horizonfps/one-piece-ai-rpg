"""Named NPC generator (Sonnet 4.6) via the `emit_npc` tool. Emits card (public NPC
StoryCard) + agent (private NamedNPCAgent) sharing one id, merged into a single
`npc_agent` story_cards row by `merge_card_agent`."""
from __future__ import annotations

from .. import config
from ..proxy import client
from . import language

_PROMPT_FILE = "npc_generator.pt-br.md"
_REFERENCE_BASE = "npc_reference_characters"

_TIER_ENUM = ["NORMAL", "SKILLED", "STRONG", "ELITE", "MONSTER", "TITAN", "WORLD", "ABSURD"]
_KNOWLEDGE_ENUM = ["common", "regional", "specialized", "esoteric", "classified"]
_MORAL_ENUM = ("absolute", "humane", "personal", "unclear", "lazy", "corrupt")
_MARINE_RANK_ENUM = ("Capitão", "Comodoro", "Vice-Almirante", "Almirante", "Almirante de Frota")

# Tool schema. API does not enforce strict; parse normalizes id-match, defaults, type/canonical.
EMIT_NPC_TOOL = {
    "name": "emit_npc",
    "description": (
        "Emite UM NPC nomeado completo: card (StoryCard NPC, dado publico) + agent "
        "(NamedNPCAgent, mente privada). card.id e agent.id IDENTICOS. Chame UMA vez. "
        "Nenhum texto fora do tool call."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            # Reflexive forcing function: gate-required string-enum filled before card/agent;
            # re-asserting the rule reduces drift. Engine discards on parse (reads card/agent).
            "pre_emit_audit": {
                "type": "object",
                "description": "Compromissos de estilo. Emita cada gate com seu valor literal e honre-o.",
                "properties": {
                    "nome_nao_canonico": {
                        "type": "string",
                        "enum": ["nome_cunhado_nao_e_de_personagem_canonico_de_one_piece"],
                        "description": (
                            "O nome cunhado para este NPC genérico não é o de um personagem "
                            "canônico de One Piece. Sonoridade do estilo, identidade própria."
                        ),
                    },
                    "coerencia_de_pessoa": {
                        "type": "string",
                        "enum": ["um_so_sexo_e_pronome_em_todos_os_campos_do_card_e_do_agent"],
                        "description": (
                            "O NPC tem UM sexo (card.sex) e um só conjunto de pronomes em "
                            "description, appearance, base_backstory, history, personality, "
                            "current_goal, long_term_dream e mood. Releio antes de emitir: nenhum "
                            "campo troca ela por ele nem atribui traço físico incoerente com o sexo."
                        ),
                    },
                    "gesto_sem_glosa": {
                        "type": "string",
                        "enum": ["mostro_o_traco_concreto_e_paro_sem_clausula_que_o_interprete"],
                        "description": (
                            "Nos campos de texto mostro o gesto, o traço ou a sensação física e "
                            "paro. Sem cláusula comparativa que explique por dentro o que ele "
                            "revela (\"como quem\", \"como se\", \"de quem\", \"no jeito de quem\"; "
                            "em inglês \"as if\", \"like\", \"the way\", \"than ... would\"). "
                            "O detalhe concreto carrega o sentido sozinho."
                        ),
                    },
                    "nome_proprio_e_presenca": {
                        "type": "string",
                        "enum": ["o_nome_e_dele_proprio_e_so_entra_na_cena_se_o_texto_o_poe_aqui_agora"],
                        "description": (
                            "O nome que cunho é DESTA pessoa, não emprestado de outra citada na cena "
                            "nem de um PARES-DESTE-TURN (o capitão que um capanga nomeia, o aliado "
                            "mencionado de longe): recém-chegado sem nome ganha nome próprio distinto, "
                            "nunca o de quem já foi falado. E present_in_scene só é true quando o "
                            "texto-âncora põe este NPC fisicamente aqui e agora; quem foi apenas "
                            "mencionado ou está noutro lugar nasce present_in_scene false."
                        ),
                    },
                },
                "required": [
                    "nome_nao_canonico", "coerencia_de_pessoa", "gesto_sem_glosa",
                    "nome_proprio_e_presenca",
                ],
            },
            "card": {
                "type": "object",
                "description": (
                    "StoryCard NPC publico. Inclui identidade, descricao visual, "
                    "current_state (tier/summary/flags), e knowledge tiers de "
                    "quem pode saber que existe + detalhes."
                ),
                "properties": {
                    "id": {"type": "string", "description": "UUID novo. Identico ao agent.id."},
                    "type": {"type": "string", "enum": ["NPC"]},
                    "subtype": {
                        "type": "string",
                        "description": (
                            "Subtype livre snake_case (dock_brawler, tavern_keeper, "
                            "street_vendor, young_marine, marine_officer, bandit_leader, "
                            "scholar, fishman_merchant, ronin etc). Em path nemesis_marine, "
                            "contem archetype keyword (workaholic | hot-blooded | "
                            "strategist | honor-bound | fanatic)."
                        ),
                    },
                    "name": {"type": "string"},
                    "sex": {
                        "type": "string",
                        "enum": ["male", "female"],
                        "description": (
                            "Sexo do NPC. Declare ANTES de escrever qualquer campo de texto: "
                            "rege todos os pronomes e traços físicos do card e do agent. female é "
                            "'ela' em tudo, sem barba; male é 'ele'. Coerência entre campos é obrigatória."
                        ),
                    },
                    "aliases": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Lista de epitetos/apelidos. 0-3 strings.",
                    },
                    "canonical": {"type": "string", "enum": ["generated"]},
                    "description": {
                        "type": "string",
                        "description": "Impressao geral curta (1-2 frases): quem e a pessoa a primeira vista. O detalhe fisico vai em appearance.",
                    },
                    "appearance": {
                        "type": "object",
                        "description": (
                            "Aparencia visivel, factual, 3a pessoa, honrando sex. E o registro que "
                            "o Narrador rele pra manter o NPC consistente entre cenas (nao reinventar "
                            "cabelo/porte/marca a cada turn)."
                        ),
                        "properties": {
                            "build_and_age": {"type": "string", "description": "Porte, altura aproximada, faixa etaria aparente. 1 frase."},
                            "face_and_hair": {"type": "string", "description": "Cabelo (cor, corte), olhos, traços de rosto, pelos faciais coerentes com o sexo. 1-2 frases."},
                            "clothing": {"type": "string", "description": "Roupa e silhueta caracteristica, sem patine de epoca nem imundicie (§0.2). 1 frase."},
                            "distinctive_mark": {"type": "string", "description": "O traço que identifica a primeira vista (cicatriz, tatuagem, objeto gasto, protese). 1 frase."},
                        },
                        "required": ["build_and_age", "face_and_hair", "clothing", "distinctive_mark"],
                    },
                    "current_state": {
                        "type": "object",
                        "properties": {
                            "tier": {"type": "string", "enum": _TIER_ENUM},
                            "summary_text": {"type": "string", "description": "1-2 frases sobre estado atual."},
                            "flags": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["tier", "summary_text", "flags"],
                    },
                    "state_history": {"type": "array", "items": {"type": "object"}, "description": "Vazio inicialmente."},
                    "related_card_ids": {"type": "array", "items": {"type": "string"}, "description": "Vazio inicialmente."},
                    "knowledge_tier_to_know_exists": {"type": "string", "enum": _KNOWLEDGE_ENUM},
                    "knowledge_tier_to_know_details": {"type": "string", "enum": _KNOWLEDGE_ENUM},
                },
                "required": [
                    "id", "type", "subtype", "name", "sex", "aliases", "canonical",
                    "description", "appearance", "current_state", "state_history",
                    "related_card_ids", "knowledge_tier_to_know_exists",
                    "knowledge_tier_to_know_details",
                ],
            },
            "agent": {
                "type": "object",
                "description": (
                    "NamedNPCAgent privado. Inclui race, idade, affiliation, tier, "
                    "class, fruta (nullable), haki (nullable), history, personality, "
                    "expressiveness, traits, alignment, knowledge_clearance, "
                    "narrative_armor + estado dinamico inicial. Nao define estilo de fala fixo: "
                    "a voz emerge da history, da personality, da emocao e da cena no momento. "
                    "id IDENTICO ao card.id."
                ),
                "properties": {
                    "id": {"type": "string", "description": "Identico ao card.id."},
                    "name": {"type": "string"},
                    "race": {
                        "type": "string",
                        "description": (
                            "Human | Fishman | Merfolk | Mink | Giant | Lunarian | "
                            "Long-arm | Long-leg | Snake-neck | Three-eyed | Skypiean "
                            "| Birkan | Shandian | ... (extensivel)."
                        ),
                    },
                    "age_at_creation": {"type": "integer", "minimum": 0},
                    "birth_year_canon": {"type": "integer"},
                    "affiliation": {
                        "type": "string",
                        "description": (
                            "marine | revolutionary | player_crew | pirate_independent | "
                            "civilian_<vila> | scholar | merchant | bandit | noble | "
                            "outro (snake_case)."
                        ),
                    },
                    "tier": {"type": "string", "enum": _TIER_ENUM},
                    "class": {
                        "type": "string",
                        "description": (
                            "swordsman | gunslinger | brawler | scholar | navigator | "
                            "sniper | medic | shipwright | fruit_user | marine_officer | "
                            "assassin | merchant | doctor | outro (snake_case ou compound)."
                        ),
                    },
                    "devil_fruit": {
                        "type": ["string", "null"],
                        "description": "Nome canonico ou inventado <RaizJP>-<RaizJP> no Mi. null na maioria.",
                    },
                    "haki_profile": {
                        "type": ["array", "null"],
                        "items": {"type": "string", "enum": ["KENBUNSHOKU", "BUSOSHOKU", "HAOSHOKU"]},
                        "description": (
                            "null na esmagadora maioria, mais raro que devil_fruit. Nenhum Haki "
                            "em NPC dos Quatro Mares (East/West/North/South Blue) nem em civil/"
                            "bandido/marinheiro raso. So tier alto (ELITE+) com formacao de "
                            "combate em Grand Line/Novo Mundo. HAOSHOKU so em figura de estatura "
                            "de rei (TITAN+). Na duvida, null."
                        ),
                    },
                    "base_backstory": {
                        "type": "string",
                        "description": "Resumo de 1 frase: origem + vinculo central. A historia detalhada vai em history.",
                    },
                    "history": {
                        "type": "object",
                        "description": "Historia do NPC, factual, 3a pessoa, honrando sex.",
                        "properties": {
                            "origin": {"type": "string", "description": "De onde vem, formacao, oficio. 1-2 frases."},
                            "defining_event": {"type": "string", "description": "O evento que moldou quem e hoje, com agencia (nao so vitima passiva). 1 frase."},
                            "central_bond": {"type": "string", "description": "O vinculo ou rivalidade que ainda move o NPC. 1 frase."},
                        },
                        "required": ["origin", "defining_event", "central_bond"],
                    },
                    "personality": {
                        "type": "object",
                        "description": (
                            "Disposicao e COMO ela aparece em comportamento concreto. NAO e estilo de "
                            "fala (a voz emerge na cena, §0.1): descreve o que o NPC FAZ, nao como soa."
                        ),
                        "properties": {
                            "disposition": {"type": "string", "description": "O temperamento base em 1 frase, com afeto variado (ver a referencia de personagens no fim do prompt)."},
                            "shows_as": {"type": "string", "description": "2-3 comportamentos concretos que essa disposicao produz em cena (o que faz quando contrariado, a vontade, com estranhos). Sem prescrever fala/bordao."},
                        },
                        "required": ["disposition", "shows_as"],
                    },
                    "traits": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "2-5 traits. Palavras unicas ou compounds de fala real. Sem epiteto LARP."
                        ),
                    },
                    "expressiveness": {
                        "type": "string",
                        "enum": ["alto", "medio", "contido"],
                        "description": (
                            "Amplitude expressiva default deste NPC em cena. One Piece e gente grande "
                            "e barulhenta na maioria: 'alto' (reage grande, em corpo e voz, careta, "
                            "descrenca alta) e o default. 'contido' e a minoria que contrasta (recluso, "
                            "assassino, profissional frio). Na duvida, 'alto'."
                        ),
                    },
                    "alignment_baseline": {"type": "number", "minimum": -2.0, "maximum": 2.0},
                    "knowledge_clearance": {"type": "string", "enum": _KNOWLEDGE_ENUM},
                    "narrative_armor": {
                        "type": "string",
                        "enum": ["none", "crew_armor", "nemesis_armor", "canon_top_armor"],
                    },
                    "current_location": {"type": "string"},
                    "current_goal": {"type": "string"},
                    "long_term_dream": {"type": "string"},
                    "mood": {"type": "string"},
                    "status": {"type": "string", "description": "alive | dead | missing | captured | etc."},
                    "relationships": {"type": "object", "description": "Vazio inicialmente ou {player_id: {...}} em crew path."},
                    "personal_event_log": {"type": "array", "items": {"type": "object"}, "description": "Vazio inicialmente."},
                    "duplicate_of_existing_id": {
                        "type": ["string", "null"],
                        "description": (
                            "Decisao sua. Se a pessoa pedida JA e um card do ELENCO-EXISTENTE "
                            "(mesma pessoa, nao so papel parecido), ecoe aqui o id dela: o engine "
                            "reusa o card existente em vez de criar um segundo. null quando e gente "
                            "nova. Na duvida, null: so marque quando for inequivocamente a mesma pessoa."
                        ),
                    },
                    "duplicate_present_in_scene": {
                        "type": "boolean",
                        "description": (
                            "So quando voce dedupa (duplicate_of_existing_id preenchido): ateste se ELA "
                            "esta fisicamente na cena atual (o texto-ancora a colocou aqui e agora) ou se "
                            "so foi mencionada/esta noutro lugar. true = entra no elenco da cena; false = "
                            "so reusa o card sem trazer pra cena."
                        ),
                    },
                    "present_in_scene": {
                        "type": "boolean",
                        "description": (
                            "So quando NAO dedupa (gente nova): ateste se este NPC recem-cunhado esta "
                            "fisicamente na cena atual (o texto-ancora o poe aqui e agora) ou se so foi "
                            "mencionado/nomeado de longe (um capitao que outro cita, um aliado noutro "
                            "lugar). Use intended_presence + PARES-DESTE-TURN do input pra decidir. "
                            "true = entra no elenco da cena; false = ganha card mas fica fora da cena. "
                            "Default true quando omitido."
                        ),
                    },
                    "moral_code": {
                        "type": ["string", "null"],
                        "enum": ["absolute", "humane", "personal", "unclear", "lazy", "corrupt", None],
                        "description": (
                            "So quando affiliation e marine (inclui nemesis_marine): o codigo moral "
                            "que rege este Marine, coerente com rank+base+regiao (ver marine_generation "
                            "addendum). Fixo na criacao. null nos demais NPCs."
                        ),
                    },
                    "marine_rank": {
                        "type": ["string", "null"],
                        "enum": ["Capitão", "Comodoro", "Vice-Almirante", "Almirante", "Almirante de Frota", None],
                        "description": (
                            "So quando o NPC e nemesis_marine (ou Marine nomeado de patente definida): "
                            "patente coerente com o tier gerado (Capitao em STRONG, Comodoro em ELITE, "
                            "e acima). null nos demais."
                        ),
                    },
                    "is_displaced_fruit_owner": {
                        "type": ["boolean", "null"],
                        "description": (
                            "So quando o input traz active_fruit_removal_hook. true se a pessoa que "
                            "voce esta gerando E o dono canonico daquela fruta (owner_name_canon; mesma "
                            "pessoa, nao papel parecido): entao nasce sem a fruta (devil_fruit null) e "
                            "status/summary refletem o hook_text. false/null quando e outra pessoa. Na duvida, false."
                        ),
                    },
                },
                "required": [
                    "id", "name", "race", "age_at_creation", "birth_year_canon",
                    "affiliation", "tier", "class", "devil_fruit", "haki_profile",
                    "base_backstory", "history", "personality", "traits", "expressiveness",
                    "alignment_baseline", "knowledge_clearance", "narrative_armor",
                    "current_location", "current_goal", "long_term_dream", "mood",
                    "status", "relationships", "personal_event_log",
                ],
            },
        },
        "required": ["pre_emit_audit", "card", "agent"],
    },
}


def _instructions() -> str:
    base = (config.PROMPTS_DIR / _PROMPT_FILE).read_text(encoding="utf-8")
    reference_file = language.prompt_file(_REFERENCE_BASE)
    reference = (config.PROMPTS_DIR / reference_file).read_text(encoding="utf-8")
    return base + "\n\n---\n\n" + reference


def _as_list(v) -> list:
    return v if isinstance(v, list) else []


def parse_emit_npc(emitted: dict | None) -> dict | None:
    """Normalize `emit_npc` into a valid `{card, agent}` pair. None if id or name missing."""
    emitted = emitted or {}
    card = dict(emitted.get("card") or {})
    agent = dict(emitted.get("agent") or {})
    if not card and not agent:
        return None

    shared_id = card.get("id") or agent.get("id")
    name = card.get("name") or agent.get("name")
    if not shared_id or not name:
        return None
    card["id"] = agent["id"] = shared_id
    card.setdefault("name", name)
    agent.setdefault("name", name)

    card["type"] = "NPC"
    card["canonical"] = "generated"
    card.setdefault("subtype", "")
    card["aliases"] = _as_list(card.get("aliases"))
    card.setdefault("description", "")
    cs = card.get("current_state")
    if not isinstance(cs, dict):
        cs = {}
    tier = cs.get("tier") if cs.get("tier") in _TIER_ENUM else (
        agent.get("tier") if agent.get("tier") in _TIER_ENUM else None)
    if tier is None:
        return None
    cs["tier"] = tier
    cs.setdefault("summary_text", "")
    cs["flags"] = _as_list(cs.get("flags"))
    card["current_state"] = cs
    card["state_history"] = _as_list(card.get("state_history"))
    card["related_card_ids"] = _as_list(card.get("related_card_ids"))
    card.setdefault("knowledge_tier_to_know_exists", "common")
    card.setdefault("knowledge_tier_to_know_details", "regional")

    # Person coherence: one sex shared by card+agent; structured appearance/personality/history.
    sex = card.get("sex") or agent.get("sex") or ""
    card["sex"] = agent["sex"] = sex
    if not isinstance(card.get("appearance"), dict):
        card["appearance"] = {}
    if not isinstance(agent.get("personality"), dict):
        agent["personality"] = {}
    if not isinstance(agent.get("history"), dict):
        agent["history"] = {}
    if agent.get("expressiveness") not in ("alto", "medio", "contido"):
        agent["expressiveness"] = "alto"

    # Initial dynamic state matching the agent_state contract.
    agent.setdefault("status", "alive")
    agent.setdefault("tier", cs["tier"])
    if not isinstance(agent.get("relationships"), dict):
        agent["relationships"] = {}
    agent["personal_event_log"] = _as_list(agent.get("personal_event_log"))
    agent["traits"] = _as_list(agent.get("traits"))
    if agent.get("haki_profile") is not None and not isinstance(agent.get("haki_profile"), list):
        agent["haki_profile"] = None

    # Model-side dedup: the id of an existing card this person already is, if the generator matched.
    dup = agent.get("duplicate_of_existing_id")
    agent["duplicate_of_existing_id"] = dup if isinstance(dup, str) and dup.strip() else None
    # When deduped, the generator attests whether the reused person is physically in THIS scene.
    agent["duplicate_present_in_scene"] = bool(agent.get("duplicate_present_in_scene"))
    # New-mint presence attest (non-dedup path): default present unless the generator says off-scene.
    pv = agent.get("present_in_scene")
    agent["present_in_scene"] = bool(pv) if pv is not None else True

    # Marine identity emitted by the generator (nemesis honors these); null on non-Marine.
    mc = agent.get("moral_code") or card.get("moral_code")
    agent["moral_code"] = mc if mc in _MORAL_ENUM else None
    mr = agent.get("marine_rank") or card.get("marine_rank")
    agent["marine_rank"] = mr if mr in _MARINE_RANK_ENUM else None
    # Fruit alt-canon: the model's call on whether this NPC is the displaced canonical owner.
    disp = agent.get("is_displaced_fruit_owner")
    agent["is_displaced_fruit_owner"] = bool(disp) if disp is not None else False

    return {"card": card, "agent": agent}


def _is_valid(parsed: dict | None) -> bool:
    if not parsed:
        return False
    card, agent = parsed.get("card") or {}, parsed.get("agent") or {}
    return bool(card.get("id")) and card.get("id") == agent.get("id") and bool(card.get("name"))


def merge_card_agent(card: dict, agent: dict, *, turn_index: int = 0) -> dict:
    """Merge card + agent into one `npc_agent` row (agent fields on top, card-only fields
    merged, tick bookkeeping initialized). Requires `card.id == agent.id`."""
    data = dict(agent)
    # Generation-only metadata: never persisted on the card.
    data.pop("duplicate_of_existing_id", None)
    data.pop("duplicate_present_in_scene", None)
    data.pop("present_in_scene", None)
    data.pop("is_displaced_fruit_owner", None)
    # Card-only fields (no collision with the agent contract beyond id/name).
    data["subtype"] = card.get("subtype", "")
    data["sex"] = card.get("sex", "")
    data["aliases"] = _as_list(card.get("aliases"))
    data["canonical"] = card.get("canonical", "generated")
    data["description"] = card.get("description", "")
    data["appearance"] = card.get("appearance") or {}
    data["current_state"] = card.get("current_state") or {}
    data["state_history"] = _as_list(card.get("state_history"))
    data["related_card_ids"] = _as_list(card.get("related_card_ids"))
    data["knowledge_tier_to_know_exists"] = card.get("knowledge_tier_to_know_exists", "common")
    data["knowledge_tier_to_know_details"] = card.get("knowledge_tier_to_know_details", "regional")
    # Bookkeeping: mirrors seed fields + recency for off-scene ranking.
    data.setdefault("relationships", {})
    data.setdefault("personal_event_log", [])
    data["last_tick_index"] = turn_index
    data["last_seen_by_player_index"] = turn_index
    data["created_at_turn_index"] = turn_index
    data["last_updated_turn_index"] = turn_index
    return data


async def call_generate_npc(
    npc_input: dict, *, retries: int = 1,
    cached_sections: list[tuple[str, object]] | None = None,
) -> dict | None:
    """Run the generator, returning the parsed `{card, agent}` pair or None. Retries on
    invalid/truncated output or exception. cached_sections (existing cast + world memory) sits
    in a cached block with a shared breakpoint, byte-stable across the turn's parallel NPCs."""
    parsed: dict | None = None
    last_exc: Exception | None = None
    for _attempt in range(retries + 1):
        try:
            emitted = await client.call_tool(
                model=config.AGENT_MODEL,
                instructions=_instructions(),
                tag="npc-generator",
                cached_sections=cached_sections,
                sections=[("NPC-GENERATION-INPUT", npc_input)],
                volatile_instructions=language.output_directive(),
                tool=EMIT_NPC_TOOL,
                tool_name="emit_npc",
                temperature=config.AGENT_TEMPERATURE,
                max_tokens=3800,
            )
            parsed = parse_emit_npc(emitted)
            if _is_valid(parsed):
                return parsed
        except Exception as e:  # noqa: BLE001 retry covers truncation/parse
            last_exc = e
    if _is_valid(parsed):
        return parsed
    if last_exc is not None:
        raise last_exc
    return None


def _world_memory_bullets(crystals: list[dict]) -> list[str]:
    """One markdown bullet per crystal: `- [<category> @ <location>, turn N] <fact>`."""
    out: list[str] = []
    for c in crystals or []:
        loc = c.get("location", "") or "?"
        out.append(f"- [{c.get('category', '')} @ {loc}, turn {c.get('source_turn_index', '?')}] {c.get('fact', '')}")
    return out


def build_npc_cached_block(
    npcs_known: dict, crystals: list[dict] | None
) -> list[tuple[str, object]]:
    """Near-static cache block (shared breakpoint after it) feeding the generator's cast awareness
    + dedup: the existing person-cast (id/name/aliases/affiliation/status/one_line_summary) + world
    memory (crystals). Only immutable-after-creation fields go in (base_backstory/description, not
    the volatile current_state), and ordering is append-only (created_at_turn_index, id), so the
    block stays byte-stable across the turn's parallel NPCs and a cache read across turns. Creatures
    are excluded: people-only dedup."""
    rows: list[tuple] = []
    for d in (npcs_known or {}).values():
        if (d.get("entity_kind") or "person") == "creature":
            continue
        ident = d.get("id", "")
        summary = (d.get("base_backstory") or d.get("description") or "").strip()
        entry = {
            "id": ident,
            "name": d.get("name", ""),
            "aliases": [a for a in (d.get("aliases") or []) if isinstance(a, str) and a.strip()],
            "affiliation": d.get("affiliation", ""),
            "status": d.get("status", "alive"),
            "one_line_summary": summary,
        }
        rows.append(((int(d.get("created_at_turn_index", 0) or 0), ident), entry))
    cast = [e for _, e in sorted(rows, key=lambda r: r[0])]
    memory = _world_memory_bullets(crystals)
    return [
        ("ELENCO-EXISTENTE (todo NPC que já tem card: id, nome, apelidos, afiliação, status, "
         "resumo. Se a pessoa pedida já está aqui e viva, retorne agent.duplicate_of_existing_id "
         "com o id dela)", cast),
        ("MEMÓRIA-DO-MUNDO (fatos cristalizados: o que cada um já fez ou é)",
         "\n".join(memory) if memory else "(sem cristais ainda)"),
    ]


def build_npc_input(
    entry: dict,
    *,
    arc_context: dict,
    affiliation_hint: str | None = None,
    expected_recurrence: str | None = None,
    active_fruit_removal_hook: dict | None = None,
    naming_hint: str | None = None,
    nemesis_context: dict | None = None,
    recent_archetypes: list | None = None,
    scene_prose_anchor: str | None = None,
    anchor_location: str | None = None,
    peers_this_turn: list | None = None,
) -> dict:
    """Build the generator input contract from a `npcs_to_generate[]` entry plus arc_context
    and optional Director hints. scene_prose_anchor is the turn prose the Narrator already wrote;
    appearance/age there is scene canon the generator must match, not reinvent. anchor_location is
    the mechanical scene slug the NPC's current_location must take (the engine also enforces it
    post-merge). peers_this_turn are the other names minted/named THIS turn (name/role/on_scene) so
    a parallel gen sees siblings and off-scene mentions and never borrows their name. intended_presence
    carries the Narrator's on_scene flag for this entry. The existing cast + world memory travel in
    cached_sections, not here."""
    role = (entry.get("role") or "").strip() or None
    return {
        "tentative_name": entry.get("name") or None,
        "context": entry.get("context") or "",
        "scene_prose_anchor": (scene_prose_anchor or None),
        "anchor_location": (anchor_location or None),
        "first_appearance_role": role,
        "intended_presence": ("on_scene" if bool(entry.get("on_scene", True)) else "off_scene_mention"),
        "peers_this_turn": (peers_this_turn or None),
        "expected_recurrence": expected_recurrence or "medium",
        "affiliation_hint": affiliation_hint,
        "current_arc_context": arc_context,
        "active_fruit_removal_hook": active_fruit_removal_hook,
        "naming_hint": naming_hint,
        "nemesis_context": nemesis_context,
        "recent_archetypes": recent_archetypes or None,
    }
