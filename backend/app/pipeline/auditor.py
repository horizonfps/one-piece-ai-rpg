"""Post-turn Auditor (Opus) via tool emit_audit. Final gate over a turn before the player sees
the prose: cross-checks generated cards vs the cast/memory, the prose vs the narrator rubric, and
the deltas vs the prose, then rewrites prose / patches card content fields / fixes state. id and
type are immutable and no card is deleted (referential integrity, not a creative limit). Best-effort:
the runner releases the original prose on timeout/error."""
from __future__ import annotations

import asyncio

from .. import config
from ..db import repositories as repo
from ..proxy import client
from . import edit
from . import language

_PROMPT_FILE = "auditor_system_prompt.pt-br.md"
MAX_TOKENS = 6000  # prose rewrite + corrections + reasoning headroom


def _instructions() -> str:
    return (config.PROMPTS_DIR / _PROMPT_FILE).read_text(encoding="utf-8")


# Only id/type are immutable (referential integrity; other rows point at them). Every other field
# (text, appearance/history/personality, and mechanical state: tier, status, fruit, haki, alignment,
# armor, flags) is patchable through edit.merge_card_edit, the same validation path the human inline
# editor uses, so the Auditor heals any field the prose or memory contradict. List fields (flags,
# haki_profile, aliases, traits) arrive as CSV in new_value.
_CARD_IMMUTABLE_PATHS = {"id", "type"}
_AUDIT_CSV_LIST_PATHS = {"aliases", "traits", "voice_notes", "notable_traits"}
_AUDIT_NESTED_PARENTS = {"appearance", "personality", "history"}
# Structural metadata the Auditor may not overwrite: a stray string would corrupt load-bearing
# world/scene/crew structures. Factual delta keys (event text, etc.) stay reachable.
_STATE_PROTECTED = {
    "world", "scene", "scene_buffer", "scene_current", "present_npc_ids",
    "present_npc_ids_turn_index", "crew", "crew_offers", "crew_alliances",
    "foreshadow_pool", "timeskip_log", "endgame", "news_editions",
}

_CORRECTION_PROPS = {
    "target": {
        "type": "string",
        "enum": ["prose", "card", "state", "mint_npc", "presence", "merge_card"],
    },
    "card_id": {
        "type": "string",
        "description": (
            "target=card|presence: id do card. target=merge_card: id do card DUPLICADO a arquivar."
        ),
    },
    "field_path": {"type": "string"},
    "new_value": {
        "type": "string",
        "description": (
            "target=card|state: o valor novo (texto). target=presence: 'present' ou 'absent'."
        ),
    },
    "entity_name": {
        "type": "string",
        "description": (
            "target=mint_npc: o nome próprio que a prosa encena como personagem e que ficou sem card."
        ),
    },
    "entity_role": {
        "type": "string",
        "description": (
            "target=mint_npc: o papel/contexto do personagem na cena (1 frase), para o gerador ancorar."
        ),
    },
    "canonical_id": {
        "type": "string",
        "description": "target=merge_card: id do card CANÔNICO que fica (o duplicado passa a apontar para ele).",
    },
    "rule_violated": {"type": "string"},
    "reasoning": {"type": "string"},
}
# Reflexive forcing functions (string-enum attested). Two re-read the cross-check rules before
# emitting; the act of re-reading closes the vice (project pattern).
_PRE_EMIT_PROPS = {
    "default_clean": {
        "type": "string",
        "enum": ["so_corrigi_violacao_concreta_e_checavel_nao_estilo"],
        "description": "Corrigi só violação nomeável e checável, não gosto/estilo/preferência. Em dúvida, clean.",
    },
    "reli_regua_de_prosa": {
        "type": "string",
        "enum": ["varri_a_prosa_por_eco_recap_enumeracao_repeticao_e_os_vicios_de_forma_do_3_3"],
        "description": (
            "Reli cada fala de NPC e cada parágrafo. Nenhuma fala enumera em cadeia as ações que o "
            "jogador acabou de fazer antes de responder, devolve a palavra-chave dele, repete a "
            "própria palavra, a mesma abertura de frase ou o mesmo molde sintático para efeito; e a "
            "prosa não traz os vícios de forma do §3.3 (contraste por negação, glosa de gesto, "
            "aforismo de fecho, fragmentação em staccato). Em prosa inglesa os mesmos vícios entram "
            "pela comparação hipotética que traduz o gesto (as if / like / the way / than ... "
            "would), pelo aposto de negação pendurado na afirmação, pela tríade de fecho com item "
            "abstrato e pelo cenário personificado em oráculo no fecho. Onde reciclava, reescrevi."
        ),
    },
    "cruzei_elenco_e_presenca": {
        "type": "string",
        "enum": ["todo_personagem_encenado_tem_card_sem_duplicata_e_a_presenca_bate_com_a_prosa"],
        "description": (
            "Varri todo nome próprio que a prosa encena como personagem (age, fala, tem presença). "
            "Cada um tem card (catálogo, gerados-do-turn ou cena); o que faltava, cunhei via mint_npc "
            "(menção de passagem não vira card). Nenhum card gerado neste turn repete pessoa/objeto já "
            "fichado; a duplicata eu reconciliei via merge_card. A presença da cena bate com a prosa: "
            "quem a cena encena está no elenco, quem saiu foi removido, via presence."
        ),
    },
    "correcao_minima": {
        "type": "string",
        "enum": ["mudei_o_minimo_e_preservei_voz_conteudo_e_intencao"],
        "description": "Mudei o mínimo que conserta e preservei voz, conteúdo e intenção de quem escreveu.",
    },
    "poder_nos_limites": {
        "type": "string",
        "enum": ["nao_apaguei_card_nem_toquei_id_type_e_toda_correcao_tem_regra"],
        "description": (
            "Não apaguei card nem toquei id/type. Toda correção (inclusive estado mecânico, mint, "
            "merge e presença) carrega regra ferida concreta; estado mecânico só mudou quando a "
            "prosa ou a memória o contradiz; só cunhei personagem que a cena encena de fato."
        ),
    },
    "reescrita_sem_vicio": {
        "type": "string",
        "enum": ["a_prosa_que_reescrevi_nao_planta_o_vicio_que_fiscalizo"],
        "description": "A prosa que reescrevi não planta nenhum vício da régua §3.3.",
    },
    "idioma_da_campanha": {
        "type": "string",
        "enum": ["prosa_final_inteira_no_idioma_da_campanha"],
        "description": (
            "Varri a prosa que o jogador vê: sai 100% no idioma da campanha (a diretiva volátil o "
            "nomeia). Palavra ou expressão de outro idioma que vazou dos inputs (card, cristal, "
            "briefing, decisão do Diretor) é violação corrigível: reescrevi o trecho no idioma da "
            "campanha. Termo canônico One Piece fica na forma oficial desse idioma."
        ),
    },
    "reasoning_por_correcao": {
        "type": "string",
        "enum": ["toda_correcao_carrega_rule_violated_e_reasoning"],
        "description": "Toda correção carrega rule_violated e reasoning.",
    },
}
_PRE_EMIT_KEYS = tuple(_PRE_EMIT_PROPS)

EMIT_AUDIT_TOOL = {
    "name": "emit_audit",
    "description": (
        "Emite o veredito do Auditor sobre o turn: clean (nada feriu regra) ou corrected (com a "
        "lista de correções). SEMPRE chame esta tool; um turn limpo vai com corrections=[] e sem "
        "final_prose."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["clean", "corrected"]},
            "corrections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": _CORRECTION_PROPS,
                    "required": ["target", "rule_violated", "reasoning"],
                },
            },
            "final_prose": {"type": "string"},
            "reasoning_summary": {"type": "string"},
            "pre_emit_audit": {
                "type": "object",
                "properties": _PRE_EMIT_PROPS,
                "required": list(_PRE_EMIT_KEYS),
            },
        },
        "required": ["verdict", "corrections", "reasoning_summary", "pre_emit_audit"],
    },
}


# Card fields dropped from the in-scene snapshot fed to the Auditor: bulky, low-signal for the
# cross-check. personal_event_log is trimmed to the tail (recent continuity) instead of dropped.
_AUDIT_CARD_DROP = ("state_history",)
_AUDIT_LOG_TAIL = 6


def _scene_card_for_audit(data: dict) -> dict:
    """Full descriptive card of an in-scene NPC for the Auditor: identity + appearance + goal/mood
    + current_state + history + personality + the relationship to the player, trimming only the
    bulky log/history. This is what lets the Auditor catch a card whose descriptive fields drifted
    out of sync with the crystallized memory (freed captive still 'wearing handcuffs', etc.)."""
    out = {k: v for k, v in (data or {}).items() if k not in _AUDIT_CARD_DROP}
    log = out.get("personal_event_log")
    if isinstance(log, list) and len(log) > _AUDIT_LOG_TAIL:
        out["personal_event_log"] = log[-_AUDIT_LOG_TAIL:]
    return out


def _player_card_for_audit(data: dict) -> dict:
    """Player card for the Auditor, minus the vestigial player_snapshot.current_arc (a stale seed
    field nothing authoritative reads; the live arc rides scene.location + game_clock)."""
    out = dict(data or {})
    snap = out.get("player_snapshot")
    if isinstance(snap, dict) and "current_arc" in snap:
        snap = dict(snap)
        snap.pop("current_arc", None)
        out["player_snapshot"] = snap
    return out


def _memory_bullets(crystals: list[dict] | None) -> str:
    out: list[str] = []
    for c in crystals or []:
        loc = c.get("location", "") or "?"
        # Witness roster inline: the anti-omniscience cross-check (§3.1) compares the speaker to who
        # actually presenced the fact. Without it the Auditor re-infers presence from the fact text
        # alone, which fails for facts that never name the leaker.
        seen: list[str] = []
        for k in ("participants", "witnesses", "hidden_witnesses"):
            seen += [w for w in (c.get(k) or []) if isinstance(w, str) and w.strip()]
        who = f" | quem presenciou: {', '.join(dict.fromkeys(seen))}" if seen else ""
        out.append(
            f"- [{c.get('category', '')} @ {loc}, turn {c.get('source_turn_index', '?')}]"
            f"{who} {c.get('fact', '')}"
        )
    return "\n".join(out) if out else "(sem cristais ainda)"


# What each prose path scopes the audit to. The main turn ("turn") gets the full power; the three
# side paths narrow it (a recap/epilogue is a summary BY DESIGN, so the recap vice never fires on the
# time compression, and there is no live cast to mint/re-presence).
_PROSE_KIND_SCOPE = {
    "opening": (
        "Esta prosa é a ABERTURA da campanha (cold open, sem ação do jogador ainda). Audite forma "
        "(§3.3), agência (não aja/fale/decida pelo jogador) e elenco/presença normalmente. Não há "
        "post-turn nem deltas mecânicos para cruzar."
    ),
    "timeskip_recap": (
        "Esta prosa é um RECAP de salto de tempo (montagem: treino → mundo em paralelo → chegada). A "
        "compressão temporal e o tom de resumo são POR DESIGN: NÃO trate a natureza-resumo como vício "
        "de recap/eco. Audite os vícios de FORMA do §3.3, a agência do jogador e a continuidade. Não "
        "cunhe card nem mexa em presença: a cena fecha no salto."
    ),
    "epilogue": (
        "Esta prosa é o EPÍLOGO de um final alcançado (montagem cinematográfica de fecho). A montagem "
        "e o salto no tempo são POR DESIGN. Audite os vícios de FORMA do §3.3 e a agência. Não cunhe "
        "card nem mexa em presença: o jogo encerra a cena."
    ),
}


async def run_audit(
    *,
    prose: str,
    player_action: dict,
    scene: dict,
    turn_meta: dict | None,
    generated_cards: list[dict] | None = None,
    post_turn: dict | None = None,
    cards_catalog: list[dict] | None = None,
    agents_catalog: list[dict] | None = None,
    crystals: list[dict] | None = None,
    prose_kind: str = "turn",
    scene_cards: list[dict] | None = None,
    player_card: dict | None = None,
    present_cast: list[dict] | None = None,
    generator_skips: list[dict] | None = None,
    recent_turns_prose: list[dict] | None = None,
    game_clock: dict | None = None,
) -> dict:
    """Run the Auditor over the finished turn. Returns the raw emit_audit tool input. The static
    catalogs + memory go in cached_sections (byte-stable, append-only) so the prefix caches; only
    this turn's prose/cards/deltas pay full price."""
    cached_sections: list[tuple[str, object]] = [
        ("WORLD-CARDS-CATALOG (parte estável: todo NPC/ITEM/FACTION com id+nome+tipo)", cards_catalog or []),
        ("AGENTS-KNOWN-CATALOG (elenco: id, nome, status, voz, tier, alinhamento)", agents_catalog or []),
        ("MEMÓRIA-DO-MUNDO (fatos cristalizados, com quem testemunhou)", _memory_bullets(crystals)),
    ]
    sections: list[tuple[str, object]] = []
    scope = _PROSE_KIND_SCOPE.get(prose_kind)
    if scope:
        sections.append(("tipo_de_prosa (o que está sendo auditado; escopo das regras)", scope))
    sections.append(
        ("scene (lugar + tensão da cena auditada)",
         {"location": scene.get("location", ""), "tension_level": scene.get("tension_level", "")}),
    )
    if game_clock is not None:
        sections.append(("game_clock (CANON: idades/datas literais, nunca recalcule)", game_clock))
    sections += [
        ("player_action (o input que o turn renderizou)", player_action),
        ("prosa_do_turn (o que o Narrador escreveu; o material auditado)", prose),
        ("cards_gerados_neste_turn (cunhados após a prosa; cruze contra o catálogo e a memória)",
         generated_cards or []),
        ("director_post (deltas aplicados + decisões; confira se batem com a prosa)", post_turn or {}),
    ]
    if scene_cards:
        sections.append((
            "cards_dos_npcs_em_cena (ficha COMPLETA de cada NPC que a prosa encena: aparência, "
            "objetivo, humor, current_state, história, personalidade, log recente; cruze cada "
            "campo descritivo contra a prosa e a memória e conserte o que envelheceu)",
            [_scene_card_for_audit(c) for c in scene_cards],
        ))
    if player_card:
        sections.append((
            "player_card (ficha do jogador; card_id para corrigir belly/alignment/tier é 'player': "
            "confira que a prosa não agiu/falou/decidiu por ele e que os deltas do jogador batem)",
            _player_card_for_audit(player_card),
        ))
    if present_cast is not None:
        sections.append((
            "present_npc_ids (elenco que o engine tem como em cena AGORA; cruze contra a prosa: quem "
            "a cena encena tem de estar aqui, quem saiu tem de sair — corrija via target presence)",
            present_cast,
        ))
    if turn_meta:
        sections.append(("turn_meta (sinais do Narrador: npcs_to_generate, fios, etc.)", turn_meta))
    if generator_skips:
        sections.append((
            "geracao_pulada_ou_falha (nomes que o Diretor NÃO despachou ou que o gerador falhou; um "
            "personagem aqui que a prosa encena precisa de mint_npc)",
            generator_skips,
        ))
    if recent_turns_prose:
        sections.append(
            ("recent_turns_prose (continuidade física imediata, não material de extração)",
             recent_turns_prose)
        )
    sections.append(("instrução", "Audite o turn contra as regras. Chame emit_audit com o veredito."))

    return await client.call_tool(
        model=config.AUDITOR_MODEL,
        instructions=_instructions(),
        tag="auditor",
        cached_sections=cached_sections,
        sections=sections,
        volatile_instructions=language.output_directive(),
        tool=EMIT_AUDIT_TOOL,
        tool_name="emit_audit",
        max_tokens=MAX_TOKENS,
        trace_label="Auditor",
    )


def _csv(s: str) -> list[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def _clean_tool_text(s: str) -> str:
    """Trim tool-call syntax leaked into a streamed string value."""
    s = str(s or "")
    cut = len(s)
    for marker in ("</", "<parameter"):
        i = s.find(marker)
        if i != -1:
            cut = min(cut, i)
    return s[:cut].strip()


def _correction_to_patch(path: str, val: str) -> dict | None:
    """Map an Auditor (field_path, new_value) to a merge_card_edit patch. None when the path is
    immutable (id/type). Lists and floats parse from the string; merge_card_edit validates enums,
    clamps and types, so an off-enum value lands as no-op (rejected by the no-change check)."""
    path = (path or "").strip()
    if path in _CARD_IMMUTABLE_PATHS:
        return None
    if path in ("summary_text", "current_state.summary_text"):
        return {"summary": val}
    if path in ("flags", "current_state.flags"):
        return {"flags": _csv(val)}
    if path == "haki_profile":
        return {"haki_profile": [h.upper() for h in _csv(val)]}
    if path in _AUDIT_CSV_LIST_PATHS:
        return {path: _csv(val)}
    if path == "alignment_baseline":
        try:
            return {"alignment_baseline": float(val)}
        except (TypeError, ValueError):
            return None
    if "." in path:
        parent, _, sub = path.partition(".")
        return {parent: {sub: val}} if parent in _AUDIT_NESTED_PARENTS else None
    return {path: val}


# Player sheet has its own shape (player_snapshot/player_character/character_creation), so a player
# correction routes through edit.apply_player_edit. Maps the Auditor field_path to its patch key.
_PLAYER_IDS = {"player"}
_PLAYER_FIELD_MAP = {
    "belly": "belly",
    "alignment_baseline": "alignment_value", "alignment_value": "alignment_value",
    "alignment": "alignment_value",
    "tier": "tier", "name": "name",
    "long_term_dream": "dream", "dream": "dream",
    "weapon": "weapon", "appearance": "appearance",
    "sex": "gender", "gender": "gender",
}


def _player_correction_to_patch(path: str, val: str) -> dict | None:
    key = _PLAYER_FIELD_MAP.get((path or "").strip())
    return {key: val} if key else None


def _presence_correction(c: dict) -> dict:
    """A presence correction: add/remove an NPC id from the scene cast. The engine (runner) owns the
    present_npc_ids write, so this only validates + returns the op for the runner to apply typed."""
    pid = (c.get("card_id") or "").strip()
    val = (c.get("new_value") or "").strip().lower()
    base = {"target": "presence", "card_id": pid,
            "rule_violated": c.get("rule_violated", ""), "reasoning": c.get("reasoning", "")}
    if not pid or val not in ("present", "absent"):
        return {**base, "ok": False, "why": "card_id ou new_value inválido (present|absent)"}
    return {**base, "ok": True, "op": "add" if val == "present" else "remove", "id": pid}


async def _mint_npc(conn, campaign_id: str, c: dict, mint_context: dict | None, *, scene_prose: str) -> dict:
    """Mint the card the prose introduced but no generator produced. Runs the REAL npc generator
    (its coherence/name gates + model-side dedup intact), a model decision, not a deterministic
    engine rule. Anchors on the final prose + scene slug. Best-effort."""
    name = (c.get("entity_name") or "").strip()
    base = {"target": "mint_npc", "entity_name": name,
            "rule_violated": c.get("rule_violated", ""), "reasoning": c.get("reasoning", "")}
    ctx = mint_context or {}
    if not name:
        return {**base, "ok": False, "why": "sem entity_name"}
    if not ctx:
        return {**base, "ok": False, "why": "sem contexto de geração"}
    from . import npc_generator, fruit_alt_canon  # lazy: keep module load light
    npcs_known = ctx.get("npcs_known") or {}
    anchor = ctx.get("anchor_location") or ""
    role = (c.get("entity_role") or "").strip()
    entry = {"name": name, "role": role, "context": role}
    try:
        active_hook = fruit_alt_canon.active_hook_for(ctx.get("player_card") or {}, name)
        npc_input = npc_generator.build_npc_input(
            entry, arc_context=ctx.get("arc_context") or {},
            affiliation_hint=role or None,
            active_fruit_removal_hook=active_hook,
            scene_prose_anchor=scene_prose or None, anchor_location=anchor or None,
            recent_archetypes=npc_generator.recent_archetype_lines(npcs_known) or None,
        )
        cached = npc_generator.build_npc_cached_block(npcs_known, ctx.get("crystals") or [])
        parsed = await npc_generator.call_generate_npc(npc_input, cached_sections=cached)
    except Exception as exc:  # noqa: BLE001 best-effort
        return {**base, "ok": False, "why": f"{type(exc).__name__}: {exc}"}
    if not parsed:
        return {**base, "ok": False, "why": "gerador sem output"}
    agent = parsed.get("agent") or {}
    dup_id = agent.get("duplicate_of_existing_id")
    if dup_id and dup_id in npcs_known:
        return {**base, "ok": True, "reused_id": dup_id, "name": name}
    merged = npc_generator.merge_card_agent(
        parsed["card"], parsed["agent"], turn_index=int(ctx.get("turn_index") or 0)
    )
    if anchor:
        merged["current_location"] = anchor
    scid = await repo.add_story_card(conn, campaign_id, "npc_agent", merged)
    return {**base, "ok": True, "id": merged.get("id"), "name": merged.get("name"),
            "story_card_id": scid}


async def _apply_merge_card(conn, campaign_id: str, c: dict) -> dict:
    """Reconcile a same-person/same-object duplicate: archive the duplicate (status merged +
    merged_into pointer + flag), never a physical delete (referential integrity). The canonical card
    stays. Returns presence_remove so the runner drops the ghost from the scene."""
    dup_id = (c.get("card_id") or "").strip()
    canon_id = (c.get("canonical_id") or "").strip()
    base = {"target": "merge_card", "card_id": dup_id, "canonical_id": canon_id,
            "rule_violated": c.get("rule_violated", ""), "reasoning": c.get("reasoning", "")}
    if not dup_id or not canon_id or dup_id == canon_id:
        return {**base, "ok": False, "why": "ids inválidos"}
    row = await repo.get_card_by_entity_id(conn, campaign_id, dup_id)
    if row is None:
        row = await repo.get_story_card(conn, campaign_id, dup_id)
    if row is None:
        return {**base, "ok": False, "why": "duplicado inexistente"}
    canon = await repo.get_card_by_entity_id(conn, campaign_id, canon_id)
    if canon is None:
        canon = await repo.get_story_card(conn, campaign_id, canon_id)
    if canon is None:
        return {**base, "ok": False, "why": "canônico inexistente"}
    data = dict(row["data"])
    data["status"] = "merged"
    data["merged_into"] = canon_id
    cs = dict(data.get("current_state") or {})
    flags = [f for f in (cs.get("flags") or []) if isinstance(f, str)]
    if "merged_duplicate" not in flags:
        flags.append("merged_duplicate")
    cs["flags"] = flags
    data["current_state"] = cs
    await repo.update_story_card(conn, row["id"], data)
    # The duplicate's lived history and identity handles migrate to the canonical card, so the
    # story keeps accruing on the card that stays.
    canon_data = dict(canon["data"])
    dup_log = [e for e in (data.get("personal_event_log") or []) if isinstance(e, dict)]
    if dup_log:
        canon_log = [e for e in (canon_data.get("personal_event_log") or []) if isinstance(e, dict)]
        seen = {(e.get("turn_index"), e.get("action_summary"), e.get("source")) for e in canon_log}
        moved = [
            e for e in dup_log
            if (e.get("turn_index"), e.get("action_summary"), e.get("source")) not in seen
        ]
        if moved:
            canon_data["personal_event_log"] = sorted(
                canon_log + moved, key=lambda e: e.get("turn_index") or 0
            )
    aliases = list(canon_data.get("aliases") or [])
    seen_alias = {str(a).strip().lower() for a in aliases if isinstance(a, str)}
    seen_alias.add(str(canon_data.get("name", "")).strip().lower())
    for handle in [data.get("name", "")] + list(data.get("aliases") or []):
        h = str(handle or "").strip()
        if h and h.lower() not in seen_alias:
            seen_alias.add(h.lower())
            aliases.append(h)
    if aliases:
        canon_data["aliases"] = aliases
    if canon_data != canon["data"]:
        await repo.update_story_card(conn, canon["id"], canon_data)
    return {**base, "ok": True, "presence_remove": dup_id}


def _set_by_path(data: dict, path: str, value) -> None:
    parts = path.split(".")
    d = data
    for p in parts[:-1]:
        nxt = d.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            d[p] = nxt
        d = nxt
    d[parts[-1]] = value


async def _apply_card_correction(conn, campaign_id: str, c: dict) -> dict:
    card_id = (c.get("card_id") or "").strip()
    path = (c.get("field_path") or "").strip()
    val = c.get("new_value")
    base = {"target": "card", "card_id": card_id, "field_path": path,
            "rule_violated": c.get("rule_violated", ""), "reasoning": c.get("reasoning", "")}
    if not card_id or not isinstance(val, str):
        return {**base, "ok": False, "why": "card_id ou valor inválido"}
    row = await repo.get_card_by_entity_id(conn, campaign_id, card_id)
    if row is None:
        row = await repo.get_story_card(conn, campaign_id, card_id)
    # Player sheet has no top-level entity id and is not in the catalog; it is addressed by the
    # well-known id 'player'.
    if row is None and card_id in _PLAYER_IDS:
        row = await repo.get_player_story_card(conn, campaign_id)
    if row is None:
        return {**base, "ok": False, "why": "card inexistente"}
    # Player sheet: distinct structure; route through apply_player_edit (belly/alignment/tier/name/...).
    if "player_snapshot" in (row["data"] or {}):
        ppatch = _player_correction_to_patch(path, val)
        if ppatch is None:
            return {**base, "ok": False, "why": "campo do jogador não editável por este caminho"}
        new_pdata = edit.apply_player_edit(row["data"], ppatch)
        if new_pdata == row["data"]:
            return {**base, "ok": False, "why": "valor fora do tipo/enum do campo ou sem mudança"}
        await repo.update_story_card(conn, row["id"], new_pdata)
        return {**base, "ok": True}
    patch = _correction_to_patch(path, val)
    if patch is None:
        return {**base, "ok": False, "why": "campo imutável (id/type)"}
    new_data = edit.merge_card_edit(row["data"], patch)
    if new_data == row["data"]:
        return {**base, "ok": False, "why": "valor fora do enum/tipo do campo ou sem mudança"}
    await repo.update_story_card(conn, row["id"], new_data)
    return {**base, "ok": True}


async def _apply_state_correction(conn, campaign_id: str, c: dict) -> dict:
    path = (c.get("field_path") or "").strip()
    val = c.get("new_value")
    base = {"target": "state", "field_path": path,
            "rule_violated": c.get("rule_violated", ""), "reasoning": c.get("reasoning", "")}
    if not path or not isinstance(val, str):
        return {**base, "ok": False, "why": "caminho ou valor inválido"}
    if path.split(".")[0] in _STATE_PROTECTED:
        return {**base, "ok": False, "why": "metadata estrutural protegido"}
    campaign = await repo.get_campaign(conn, campaign_id)
    meta = dict((campaign or {}).get("metadata") or {})
    _set_by_path(meta, path, val)
    await repo.update_campaign_metadata(conn, campaign_id, meta)
    return {**base, "ok": True}


async def apply_audit(
    conn, campaign_id: str, *, original_prose: str, audit: dict, mint_context: dict | None = None,
) -> tuple[str, dict]:
    """Apply the Auditor's corrections. Prose -> final_prose (the caller persists + reveals it).
    Card -> content field patch (player sheet routed through apply_player_edit). State -> metadata
    patch. mint_npc -> runs the real generator, mints the missing card. presence -> scene-cast op the
    runner applies. merge_card -> archive the duplicate. Returns (final_prose, report); the report
    carries minted_npcs/presence_add/presence_remove for the runner to reconcile the scene cast."""
    corrections = audit.get("corrections") or []
    final_prose = original_prose
    fp = audit.get("final_prose")
    if isinstance(fp, str) and fp.strip() and fp.strip() != (original_prose or "").strip():
        final_prose = fp

    applied: list[dict] = []
    rejected: list[dict] = []
    minted: list[dict] = []          # [{id, name}] freshly minted NPC cards
    presence_add: list[str] = []     # ids to add to the scene cast
    presence_remove: list[str] = []  # ids to drop from the scene cast
    for c in corrections:
        if not isinstance(c, dict):
            continue
        target = c.get("target")
        if target == "prose":
            rec = {"target": "prose", "rule_violated": c.get("rule_violated", ""),
                   "reasoning": c.get("reasoning", "")}
            if final_prose != original_prose:
                applied.append(rec)
            else:
                rejected.append({**rec, "ok": False, "why": "sem final_prose"})
        elif target == "card":
            r = await _apply_card_correction(conn, campaign_id, c)
            (applied if r.get("ok") else rejected).append(r)
        elif target == "state":
            r = await _apply_state_correction(conn, campaign_id, c)
            (applied if r.get("ok") else rejected).append(r)
        elif target == "mint_npc":
            r = await _mint_npc(conn, campaign_id, c, mint_context, scene_prose=final_prose)
            if r.get("ok"):
                applied.append(r)
                if r.get("id"):
                    minted.append({"id": r["id"], "name": r.get("name")})
                    presence_add.append(r["id"])
                elif r.get("reused_id"):
                    presence_add.append(r["reused_id"])
            else:
                rejected.append(r)
        elif target == "presence":
            r = _presence_correction(c)
            if r.get("ok"):
                (presence_add if r["op"] == "add" else presence_remove).append(r["id"])
                applied.append({k: v for k, v in r.items() if k != "op"})
            else:
                rejected.append(r)
        elif target == "merge_card":
            r = await _apply_merge_card(conn, campaign_id, c)
            if r.get("ok"):
                if r.get("presence_remove"):
                    presence_remove.append(r["presence_remove"])
                applied.append(r)
            else:
                rejected.append(r)
        else:
            rejected.append({"target": target, "ok": False, "why": "target desconhecido"})

    report = {
        "verdict": "corrected" if (applied or final_prose != original_prose) else "clean",
        "model_verdict": audit.get("verdict"),
        "reasoning_summary": _clean_tool_text(audit.get("reasoning_summary", "")),
        "prose_rewritten": final_prose != original_prose,
        "applied": applied,
        "rejected": rejected,
        "minted_npcs": minted,
        "presence_add": sorted(set(presence_add)),
        "presence_remove": sorted(set(presence_remove)),
        "pre_emit_audit": audit.get("pre_emit_audit"),
    }
    return final_prose, report


async def audit_prose(
    conn, campaign_id: str, *,
    prose: str,
    player_action: dict,
    scene: dict,
    prose_kind: str = "turn",
    turn_meta: dict | None = None,
    generated_cards: list[dict] | None = None,
    post_turn: dict | None = None,
    cards_catalog: list[dict] | None = None,
    agents_catalog: list[dict] | None = None,
    crystals: list[dict] | None = None,
    scene_cards: list[dict] | None = None,
    player_card: dict | None = None,
    present_cast: list[dict] | None = None,
    generator_skips: list[dict] | None = None,
    recent_turns_prose: list[dict] | None = None,
    game_clock: dict | None = None,
    mint_context: dict | None = None,
    timeout_s: float | None = None,
) -> tuple[str, dict]:
    """One-call gate: run_audit (with timeout) + apply_audit, best-effort. On timeout/error returns
    the untouched prose + an error report, so every caller reveals prose the same way. Shared by the
    normal turn and the three side prose paths (opening, timeskip recap, ending epilogue)."""
    to = config.AUDIT_TIMEOUT_S if timeout_s is None else timeout_s
    try:
        result = await asyncio.wait_for(
            run_audit(
                prose=prose, player_action=player_action, scene=scene, turn_meta=turn_meta,
                prose_kind=prose_kind, generated_cards=generated_cards, post_turn=post_turn,
                cards_catalog=cards_catalog, agents_catalog=agents_catalog, crystals=crystals,
                scene_cards=scene_cards, player_card=player_card, present_cast=present_cast,
                generator_skips=generator_skips, recent_turns_prose=recent_turns_prose,
                game_clock=game_clock,
            ),
            timeout=to,
        )
        return await apply_audit(
            conn, campaign_id, original_prose=prose, audit=result, mint_context=mint_context,
        )
    except Exception as exc:  # noqa: BLE001 best-effort: caller reveals the untouched prose
        return prose, {"error": f"{type(exc).__name__}: {exc}"}
