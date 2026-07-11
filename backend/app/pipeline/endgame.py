"""Endgame: qualitative ending detector (Sonnet) + cinematic epilogue (Opus).

Detector emits world_flag_changes / laugh_tale_revealed / ending_reached only when the turn
consummated the change. ending_reached fires the epilogue and appends to endings_reached[]; the
game never closes. State lives in metadata.endgame (JSON escape-hatch).
"""
from __future__ import annotations

from .. import config
from ..db import repositories as repo
from ..proxy import client
from . import language
from . import plots, poneglyph

# Catalogued ending kinds; mirrors the prompt enum.
ENDING_KINDS = (
    "pirate_king", "yonkou", "wg_admiral", "revolutionary_leader",
    "mary_geoise_conqueror", "legendary_disappearance", "???",
)

ENDING_VALENCES = ("good", "bad")

# Forward-only transitions the Director may consummate (no regressions).
IMU_MUTATIONS = ("wounded_by_player", "defeated_by_player")
MARY_GEOISE_MUTATIONS = ("infiltrated", "invaded", "fallen_to_player")

_DETECTOR_PROMPT = "ending_candidate_detector.pt-br.md"
_EPILOGUE_PROMPT = "ending_epilogue_generator.pt-br.md"


# --------------------------------------------------------------------------------------
# Tool schemas
# --------------------------------------------------------------------------------------
EMIT_ENDGAME_STATE_TOOL = {
    "name": "emit_endgame_state",
    "description": (
        "Emite o estado de endgame CONSUMADO neste turn: mutacoes de flag de mundo, "
        "revelacao de Laugh Tale e fim alcancado. TODOS os campos sao opcionais — o caso "
        "default (~99% dos turns) e tudo vazio/null. Preencha o pre_emit_audit PRIMEIRO "
        "(scratchpad obrigatorio; a engine ignora). Em duvida entre INTENCAO/anuncio e "
        "ATO consumado, NAO emita. Chamada UNICA, zero texto fora."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pre_emit_audit": {
                "type": "object",
                "description": (
                    "Scratchpad OBRIGATORIO antes de emitir; a engine descarta. Forca a "
                    "releitura do ATO consumado vs INTENCAO antes de qualquer emissao."
                ),
                "properties": {
                    "consummation_review": {
                        "type": "string",
                        "description": (
                            "Para cada marco potencial do turn (flag de mundo / Laugh Tale "
                            "/ fim), classifique: CONSUMADO (refletido em ato/estado "
                            "concreto) vs INTENCAO/ANUNCIO (vai fazer). So o consumado vira "
                            "emissao. Se nada se consumou, escreva 'nada consumado'."
                        ),
                    },
                    "laugh_tale_basis": {
                        "type": "string",
                        "description": (
                            "Se for revelar Laugh Tale: cite nº de Road transcritos + reader "
                            "disponivel + o ato que cristaliza a posicao. Senao 'n/a'."
                        ),
                    },
                    "ending_basis": {
                        "type": "string",
                        "description": (
                            "Se houver ending_reached: justifique kind + valence (good/bad "
                            "pela leitura do alinhamento/ato). Senao 'n/a'."
                        ),
                    },
                },
                "required": ["consummation_review"],
            },
            "world_flag_changes": {
                "type": ["object", "null"],
                "description": (
                    "Mutacoes de flag de mundo que o turn CONSUMOU. null/omitido se nenhuma. "
                    "So emita o que o ato concreto mudou (ferir Imu, romper Mary Geoise, "
                    "tomar/perder territorio)."
                ),
                "properties": {
                    "imu_status": {
                        "type": ["string", "null"],
                        "enum": ["wounded_by_player", "defeated_by_player", None],
                        "description": (
                            "Novo estado de Imu SO se o player o feriu/derrotou em combate "
                            "CONSUMADO neste turn. null se nada mudou."
                        ),
                    },
                    "mary_geoise_status": {
                        "type": ["string", "null"],
                        "enum": ["infiltrated", "invaded", "fallen_to_player", None],
                        "description": (
                            "Novo estado de Mary Geoise SO se o ato consumou a infiltracao / "
                            "invasao / queda. Anuncio de marcha NAO conta. null se nada mudou."
                        ),
                    },
                    "controlled_territories_add": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Territorios que o player passou a controlar de fato neste turn.",
                    },
                    "controlled_territories_remove": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Territorios que o player perdeu de fato neste turn.",
                    },
                },
            },
            "laugh_tale_revealed": {
                "type": ["boolean", "null"],
                "description": (
                    "true SO no turn em que a posicao de Laugh Tale e cristalizada pela "
                    "triangulacao dos Road Poneglyphs (julgamento qualitativo). Contexto canon: "
                    "4 Road transcritos + reader na crew tipicamente bastam; 3 podem bastar com "
                    "a trait mitica Voz de Todas as Coisas (estilo Roger, sem garantia). null/"
                    "false caso contrario."
                ),
            },
            "laugh_tale_crystal_fact": {
                "type": ["string", "null"],
                "description": (
                    "Obrigatorio quando laugh_tale_revealed=true: UMA frase factual PT-BR do que "
                    "este turn consumou na revelacao (leitor que fechou a triangulacao, ato "
                    "concreto, posicao alcancada), com base no recent_turn_summary. Nota factual, "
                    "sem prosa/adjetivo decorativo. null/omitido se laugh_tale_revealed nao for true."
                ),
            },
            "ending_reached": {
                "type": ["object", "null"],
                "description": (
                    "O fim CONSUMADO neste turn — o player chegou de fato a um desfecho "
                    "catalogado (nao 'esta perto'). null se nenhum. O jogo NAO encerra: e so a "
                    "deteccao de que um fim (bom ou mau) foi alcancado."
                ),
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": list(ENDING_KINDS),
                        "description": (
                            "O desfecho catalogado consumado. '???' so quando o padrao "
                            "emergente claramente nao cabe nos 6."
                        ),
                    },
                    "valence": {
                        "type": "string",
                        "enum": list(ENDING_VALENCES),
                        "description": (
                            "Tom do desfecho: 'good' (libertacao/realizacao) ou 'bad' "
                            "(tirania/ruina), pela leitura do alinhamento + ato consumado."
                        ),
                    },
                    "reasoning": {
                        "type": "string",
                        "description": (
                            "1-2 frases PT-BR analiticas citando o ato CONSUMADO e os sinais "
                            "concretos do snapshot. Sem prosa, sem adjetivo decorativo."
                        ),
                    },
                },
                "required": ["kind", "valence", "reasoning"],
            },
        },
        "required": ["pre_emit_audit"],
    },
}

EMIT_EPILOGUE_TOOL = {
    "name": "emit_epilogue",
    "description": (
        "Emite a prosa do epilogo de ending. UMA chamada. A prosa segue TODAS "
        "as regras do ending_epilogue_generator: 4 movimentos (ato -> mundo -> "
        "tripulacao -> foreshadow/imagem), ~1200-1500 palavras (~2500-3300 tokens), prosa pura PT-BR, "
        "sem JSON / markdown / heading / bullet. Player NUNCA morre, mundo NUNCA "
        "acaba, sem pergunta ao jogador, sem nota do narrador."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "prose": {
                "type": "string",
                "description": (
                    "O epilogo completo em PT-BR. Prosa unica e continua, sem "
                    "subtitulo / marcacao de movimento. Tempo presente, terceira "
                    "pessoa. Nomes de NPC em narracao com prefixo @ (sem @ em "
                    "dialogo). Termina em imagem / gesto / silencio, nunca em "
                    "pergunta ao jogador."
                ),
            },
        },
        "required": ["prose"],
    },
}


# --------------------------------------------------------------------------------------
# metadata.endgame: state + defaults
# --------------------------------------------------------------------------------------
def default_world_flags() -> dict:
    return {
        "imu_status": "active",
        "mary_geoise_status": "untouched",
        "controlled_territories": [],
        "wg_relationship": "",
        "revolutionary_army_relationship": "",
        "ancient_weapons_aligned": [],
        "laugh_tale_revealed": False,
        "rio_poneglyph_read": False,
    }


def endgame_state(metadata: dict) -> dict:
    """metadata.endgame with defaults applied (safe read, no mutation). endings_reached is the
    log of endings reached."""
    eg = dict((metadata or {}).get("endgame") or {})
    flags = default_world_flags()
    flags.update({k: eg[k] for k in flags if k in eg})
    flags["endings_reached"] = list(eg.get("endings_reached") or [])
    return flags


def merge_endgame_patch(metadata: dict, patch: dict) -> dict:
    """Merge a flat patch into metadata.endgame. Returns the mutated metadata."""
    if not patch:
        return metadata
    eg = dict((metadata or {}).get("endgame") or {})
    eg.update(patch)
    metadata["endgame"] = eg
    return metadata


def apply_flag_changes(eg: dict, changes: dict) -> bool:
    """Apply parsed world_flag_changes onto endgame block eg in-place. Returns True if changed.
    Territories are idempotent set-union/diff."""
    changed = False
    if changes.get("imu_status") in IMU_MUTATIONS:
        eg["imu_status"] = changes["imu_status"]
        changed = True
    if changes.get("mary_geoise_status") in MARY_GEOISE_MUTATIONS:
        eg["mary_geoise_status"] = changes["mary_geoise_status"]
        changed = True
    add = changes.get("controlled_territories_add") or []
    rem = changes.get("controlled_territories_remove") or []
    if add or rem:
        terr = list(eg.get("controlled_territories") or [])
        for t in add:
            if t not in terr:
                terr.append(t)
        for t in rem:
            if t in terr:
                terr.remove(t)
        eg["controlled_territories"] = terr
        changed = True
    return changed


# --------------------------------------------------------------------------------------
# Pure derivations
# --------------------------------------------------------------------------------------
def _bounty_int(psnap: dict) -> int:
    b = psnap.get("bounty", 0)
    return int(b.get("current_amount", 0) or 0) if isinstance(b, dict) else int(b or 0)


def _alignment_desc(psnap: dict) -> str:
    desc = psnap.get("alignment_descriptor")
    if desc:
        return str(desc)
    al = psnap.get("alignment")
    if isinstance(al, dict):
        return str(al.get("bucket", "neutral"))
    return str(al or "neutral")


def _fighting_style_summary(psnap: dict) -> str:
    fs = psnap.get("fighting_style")
    if isinstance(fs, dict):
        return str(fs.get("summary") or fs.get("summary_text") or "")
    return str(fs or "")


def _player_traits(player_card: dict) -> list[str]:
    psnap = (player_card or {}).get("player_snapshot") or {}
    if psnap.get("traits_active"):
        return [str(t) for t in psnap["traits_active"]][:8]
    cc = (player_card or {}).get("character_creation") or {}
    out = []
    for t in cc.get("traits") or []:
        name = t.get("name") if isinstance(t, dict) else t
        if name:
            out.append(str(name))
    return out[:8]


def _chaos_descriptor(metadata: dict) -> str:
    """Qualitative chaos bucket from the engine."""
    return ((metadata or {}).get("chaos_meter") or {}).get("bucket") or "calm"


def _crew_members(npcs: dict) -> list[dict]:
    return [d for d in (npcs or {}).values() if d.get("affiliation") == "player_crew"]


def crew_snapshot(npcs: dict, metadata: dict, player_card: dict) -> dict:
    """Detector crew_snapshot: size, alignment drift, reader hint, short summary.
    has_poneglyph_reader is a context hint; the Laugh Tale reveal is the Director's call."""
    members = _crew_members(npcs)
    drift = ((metadata or {}).get("crew_alignment") or {}).get("bucket") or "desconhecido"
    summary_parts = [
        f"{d.get('name', '')} ({d.get('class') or d.get('role') or 'tripulante'})".strip()
        for d in members[:3] if d.get("name")
    ]
    return {
        "size": len(members),
        "alignment_drift": drift,
        "has_poneglyph_reader": poneglyph.has_reader(player_card, npcs),
        "members_summary": "; ".join(summary_parts),
    }


def world_block(metadata: dict, player_card: dict, item_cards: dict) -> dict:
    """Detector world_state block (and base of the epilogue world_state_final). Combines
    metadata.endgame flags with Road transcribed count and chaos. wg/RA are textual flags the
    Director maintains; the raw faction_reputations map rides alongside so the model characterizes
    the standing itself."""
    flags = endgame_state(metadata)
    psnap = (player_card or {}).get("player_snapshot") or {}
    cards = poneglyph.poneglyph_cards(item_cards)
    return {
        "chaos_meter": _chaos_descriptor(metadata),
        "laugh_tale_revealed": bool(flags["laugh_tale_revealed"]),
        "rio_poneglyph_read": bool(flags["rio_poneglyph_read"]) or poneglyph.rio_is_read(cards),
        "road_poneglyphs_transcribed": poneglyph.road_transcribed_count(cards),
        "ancient_weapons_aligned": list(flags["ancient_weapons_aligned"]),
        "wg_relationship": flags["wg_relationship"],
        "revolutionary_army_relationship": flags["revolutionary_army_relationship"],
        "faction_reputations": dict(psnap.get("faction_reputations") or {}),
        "controlled_territories": list(flags["controlled_territories"]),
        "imu_status": flags["imu_status"],
        "mary_geoise_status": flags["mary_geoise_status"],
    }


# --------------------------------------------------------------------------------------
# Detector: input build + parse + persistence
# --------------------------------------------------------------------------------------
def build_detector_input(
    player_card: dict, npcs: dict, metadata: dict, item_cards: dict, *,
    turn_index: int, campaign_day: int, recent_turn_summary: str,
) -> dict:
    psnap = (player_card or {}).get("player_snapshot") or {}
    pc = (player_card or {}).get("player_character") or {}
    reached = endgame_state(metadata)["endings_reached"]
    return {
        "turn_index": int(turn_index),
        "campaign_day": int(campaign_day),
        "player_snapshot": {
            "tier": psnap.get("tier") or pc.get("tier", ""),
            "bounty": _bounty_int(psnap),
            "alignment": _alignment_desc(psnap),
            "fruit": psnap.get("fruit") or pc.get("fruit"),
            "haki": psnap.get("haki") or pc.get("haki", []),
            "fighting_style_summary": _fighting_style_summary(psnap),
            "traits_active": _player_traits(player_card),
        },
        "crew_snapshot": crew_snapshot(npcs, metadata, player_card),
        "world_state": world_block(metadata, player_card, item_cards),
        "recent_turn_summary": recent_turn_summary or "",
        "endings_already_reached": [
            e.get("kind") for e in reached if isinstance(e, dict) and e.get("kind")
        ],
    }


def parse_endgame_state(emitted: dict | None) -> dict:
    """Normalize emit_endgame_state: world_flag_changes (cleaned), laugh_tale_revealed (bool),
    ending_reached (dict or None). pre_emit_audit is scratchpad and ignored."""
    emitted = emitted or {}
    out: dict = {"world_flag_changes": {}, "laugh_tale_revealed": False,
                 "laugh_tale_crystal_fact": "", "ending_reached": None}

    wfc = emitted.get("world_flag_changes")
    if isinstance(wfc, dict):
        clean: dict = {}
        if wfc.get("imu_status") in IMU_MUTATIONS:
            clean["imu_status"] = wfc["imu_status"]
        if wfc.get("mary_geoise_status") in MARY_GEOISE_MUTATIONS:
            clean["mary_geoise_status"] = wfc["mary_geoise_status"]
        add = [t.strip() for t in (wfc.get("controlled_territories_add") or []) if isinstance(t, str) and t.strip()]
        rem = [t.strip() for t in (wfc.get("controlled_territories_remove") or []) if isinstance(t, str) and t.strip()]
        if add:
            clean["controlled_territories_add"] = add
        if rem:
            clean["controlled_territories_remove"] = rem
        out["world_flag_changes"] = clean

    out["laugh_tale_revealed"] = bool(emitted.get("laugh_tale_revealed"))
    if out["laugh_tale_revealed"]:
        out["laugh_tale_crystal_fact"] = (emitted.get("laugh_tale_crystal_fact") or "").strip()

    er = emitted.get("ending_reached")
    if isinstance(er, dict) and er.get("kind") in ENDING_KINDS:
        reasoning = (er.get("reasoning") or "").strip()
        valence = er.get("valence")
        # Strict: an ending with a bad/missing valence or empty reasoning is dropped, never
        # defaulted to a tone. call_detector retries before accepting the drop.
        if reasoning and valence in ENDING_VALENCES:
            out["ending_reached"] = {
                "kind": er["kind"],
                "valence": valence,
                "reasoning": reasoning,
            }
    return out


def _is_empty_state(parsed: dict) -> bool:
    return (
        not parsed.get("world_flag_changes")
        and not parsed.get("laugh_tale_revealed")
        and not parsed.get("ending_reached")
    )


async def call_detector(detector_input: dict, *, retries: int = 1) -> dict:
    """Run the ending detector (Sonnet, DIRECTOR_TEMPERATURE). Fallback = empty state."""
    instructions = (config.PROMPTS_DIR / _DETECTOR_PROMPT).read_text(encoding="utf-8")
    last_exc: Exception | None = None
    for _attempt in range(retries + 1):
        try:
            emitted = await client.call_tool(
                model=config.DIRECTOR_MODEL,
                instructions=instructions,
                tag="ending-detector",
                sections=[("ENDGAME-DETECTOR-INPUT", detector_input)],
                tool=EMIT_ENDGAME_STATE_TOOL,
                tool_name="emit_endgame_state",
                temperature=config.DIRECTOR_TEMPERATURE,
                max_tokens=2000,
                trace_label="Endgame · detector",
            )
            parsed = parse_endgame_state(emitted)
            # A raw ending_reached the parser rejected (bad valence / no reasoning): retry once
            # before accepting the drop, so the tone is never invented.
            raw_er = isinstance(emitted, dict) and isinstance(emitted.get("ending_reached"), dict)
            if raw_er and parsed["ending_reached"] is None and _attempt < retries:
                continue
            # Laugh Tale revealed but no crystal phrase: retry before honoring, so the crystal is
            # never engine-templated.
            if parsed["laugh_tale_revealed"] and not parsed["laugh_tale_crystal_fact"] and _attempt < retries:
                continue
            return parsed
        except Exception as e:  # noqa: BLE001  retry covers truncation/parse
            last_exc = e
    if last_exc is not None:
        raise last_exc
    return {"world_flag_changes": {}, "laugh_tale_revealed": False,
            "laugh_tale_crystal_fact": "", "ending_reached": None}


def _laugh_tale_crystal(fact: str = "") -> dict:
    return poneglyph._laugh_tale_crystal(fact)


async def detect_and_persist(
    conn,
    campaign_id: str,
    *,
    player_card: dict,
    npcs: dict,
    metadata: dict,
    item_cards: dict,
    campaign_day: int,
    recent_turn_summary: str,
    turn_index: int,
    scene: dict | None = None,
    present_names: list[str] | None = None,
    current_age: int = 0,
) -> dict:
    """Run the detector and persist what the Director consummated this turn: world_flag_changes,
    laugh_tale_revealed (+ crystal), and ending_reached (generates the Opus epilogue + appends to
    endings_reached[]). Fresh read-modify-write of metadata. Best-effort. Returns a change report."""
    detector_input = build_detector_input(
        player_card, npcs, metadata, item_cards,
        turn_index=turn_index, campaign_day=campaign_day, recent_turn_summary=recent_turn_summary,
    )
    parsed = await call_detector(detector_input)
    if _is_empty_state(parsed):
        return {"changed": False}

    campaign = await repo.get_campaign(conn, campaign_id)
    meta = dict((campaign or {}).get("metadata") or {})
    eg = dict(meta.get("endgame") or {})
    report: dict = {"changed": False}

    # (1) World flag mutations consummated this turn.
    if apply_flag_changes(eg, parsed["world_flag_changes"]):
        report["world_flag_changes"] = parsed["world_flag_changes"]
        report["changed"] = True

    # (2) Laugh Tale reveal (Director's call; idempotent via flag). The crystal fact comes from the
    # detector's own emission (real circumstances of this turn), not an engine template.
    if parsed["laugh_tale_revealed"] and not bool(eg.get("laugh_tale_revealed")):
        eg["laugh_tale_revealed"] = True
        await repo.append_new_crystals(
            conn, campaign_id, [_laugh_tale_crystal(parsed.get("laugh_tale_crystal_fact", ""))],
            source_turn_index=turn_index,
        )
        report["laugh_tale_revealed"] = True
        report["changed"] = True

    # (3) Ending reached: auto epilogue + log (game does not close).
    er = parsed["ending_reached"]
    if er:
        already = {e.get("kind") for e in (eg.get("endings_reached") or []) if isinstance(e, dict)}
        if er["kind"] not in already:
            meta["endgame"] = eg  # mutated flags feed the epilogue input
            reasoning_with_valence = f"[tom: {er['valence']}] {er['reasoning']}"
            epilogue_input = build_epilogue_input(
                er["kind"], reasoning_with_valence,
                player_card=player_card, npcs=npcs, metadata=meta, item_cards=item_cards,
                scene=scene or {}, present_names=present_names or [], current_age=current_age,
                turn_index=turn_index,
            )
            prose = await call_epilogue(epilogue_input)
            # Auditor gate over the epilogue montage (form vices §3.3 + player agency). The cinematic
            # closing is a summary BY DESIGN; no live cast to mint/re-presence. Best-effort, lazy
            # import to avoid any cycle.
            if prose:
                try:
                    from . import auditor
                    _epi_crystals = await repo.get_all_crystals_for_narrator(conn, campaign_id)
                    prose, _epi_audit = await auditor.audit_prose(
                        conn, campaign_id,
                        prose=prose, player_action={"type": "ENDING", "raw": ""},
                        scene=scene or {}, prose_kind="epilogue",
                        crystals=_epi_crystals, player_card=player_card,
                    )
                except Exception:  # noqa: BLE001 epilogue auditor best-effort
                    pass
            entry = {
                "kind": er["kind"],
                "valence": er["valence"],
                "reasoning": er["reasoning"],
                "at_turn_index": int(turn_index),
                "reached_at_day": int(campaign_day),
                "epilogue_summary": prose,
            }
            eg["endings_reached"] = list(eg.get("endings_reached") or []) + [entry]
            report["ending_reached"] = entry
            report["epilogue"] = prose
            report["changed"] = True

    if not report["changed"]:
        return {"changed": False}

    meta["endgame"] = eg
    await repo.update_campaign_metadata(conn, campaign_id, meta)
    return report


# --------------------------------------------------------------------------------------
# Epilogue: input build + generation
# --------------------------------------------------------------------------------------
def _crew_final(npcs: dict) -> list[dict]:
    out: list[dict] = []
    for d in _crew_members(npcs):
        rels = d.get("relationships")
        rel_with_player = ""
        if isinstance(rels, dict):
            pr = rels.get("player") or rels.get("player_character")
            if isinstance(pr, dict):
                rel_with_player = str(pr.get("descriptor") or pr.get("type") or pr.get("disposition") or "")
            elif isinstance(pr, str):
                rel_with_player = pr
        out.append({
            "name": d.get("name", ""),
            "role": d.get("class") or d.get("role") or "tripulante",
            "tier": d.get("tier", ""),
            "voice_notes": d.get("voice_notes", ""),
            "personal_arc_summary": (d.get("base_backstory") or d.get("backstory") or "")[:300],
            "relationship_with_player": rel_with_player,
        })
    return out


def _weapon_name(player_card: dict) -> str:
    cc = (player_card or {}).get("character_creation") or {}
    weapon = cc.get("weapon") or cc.get("weapon_name")
    if isinstance(weapon, dict):
        weapon = weapon.get("name")
    return str(weapon or "")


def _full_inventory(player_card: dict, item_cards: dict | None = None) -> list[str]:
    """Raw inventory names for the epilogue; the Opus picks what is iconic (no engine curation).
    Resolves item_card_id -> card name (mirrors economy.inventory_summary) so a card-backed item is
    not dropped; falls back to the chargen starting loadout when nothing was ever carded."""
    psnap = (player_card or {}).get("player_snapshot") or {}
    cards = item_cards or {}
    out: list[str] = []
    for entry in psnap.get("inventory") or []:
        if isinstance(entry, dict):
            name = entry.get("display_name") or entry.get("name")
            if not name and entry.get("item_card_id"):
                name = (cards.get(entry["item_card_id"]) or {}).get("name") or entry["item_card_id"]
        else:
            name = entry
        if name:
            out.append(str(name))
    if not out:
        loadout = ((player_card or {}).get("character_creation") or {}).get("starting_loadout") or []
        out = [str(x) for x in loadout if x]
    return out


def _nemesis_raw(metadata: dict, npcs: dict) -> dict:
    """Raw nemesis state for the epilogue loose_ends; empty when there is no active nemesis."""
    nem = (metadata or {}).get("nemesis") or {}
    nid = nem.get("current_nemesis_id")
    card = (npcs or {}).get(nid) or {}
    if not nid or not card:
        return {}
    return {"name": card.get("name", ""), "status": card.get("status", "alive"), "tier": card.get("tier", "")}


def build_epilogue_input(
    kind: str, reasoning: str, *,
    player_card: dict, npcs: dict, metadata: dict, item_cards: dict,
    scene: dict, present_names: list[str], current_age: int, turn_index: int,
) -> dict:
    psnap = (player_card or {}).get("player_snapshot") or {}
    pc = (player_card or {}).get("player_character") or {}
    world = world_block(metadata, player_card, item_cards)
    world["rio_content_summary"] = (
        poneglyph.rio_content_summary(poneglyph.poneglyph_cards(item_cards))
        if world["rio_poneglyph_read"] else ""
    )
    return {
        "ending_kind": kind,
        "ending_reasoning": reasoning or "",
        "player_character": {
            "name": pc.get("name", ""),
            "tier": psnap.get("tier") or pc.get("tier", ""),
            "fruit": psnap.get("fruit") or pc.get("fruit"),
            "haki": psnap.get("haki") or pc.get("haki", []),
            "fighting_style_summary": _fighting_style_summary(psnap),
            "traits_active": _player_traits(player_card),
            "current_age": int(current_age or 0),
            "visible_state": psnap.get("player_visible_state", ""),
            "weapon": _weapon_name(player_card),
            "inventory": _full_inventory(player_card, item_cards),
        },
        "crew_final": _crew_final(npcs),
        "world_state_final": world,
        "ending_scene_anchor": {
            "location": scene.get("location", ""),
            "ambient": scene.get("ambient", ""),
            "npcs_present": list(present_names or []),
        },
        "loose_ends": {
            "nemesis": _nemesis_raw(metadata, npcs),
            "imu_status": endgame_state(metadata)["imu_status"],
            "mary_geoise_status": endgame_state(metadata)["mary_geoise_status"],
            "foreshadow_pool": plots.build_foreshadow_pool(metadata, turn_index),
        },
    }


async def call_epilogue(epilogue_input: dict, *, retries: int = 1) -> str:
    """Run the Epilogue Generator (Opus). Returns prose, or '' on failure."""
    instructions = (config.PROMPTS_DIR / _EPILOGUE_PROMPT).read_text(encoding="utf-8")
    last_exc: Exception | None = None
    for _attempt in range(retries + 1):
        try:
            emitted = await client.call_tool(
                model=config.NARRATOR_MODEL,
                instructions=instructions,
                tag="epilogue",
                sections=[("ENDING-INPUT", epilogue_input)],
                volatile_instructions=language.output_directive(),
                tool=EMIT_EPILOGUE_TOOL,
                tool_name="emit_epilogue",
                max_tokens=4500,
                trace_label="Ending · epílogo",
            )
            prose = (emitted.get("prose") or "").strip() if isinstance(emitted, dict) else ""
            if prose:
                return prose
        except Exception as e:  # noqa: BLE001  retry covers truncation/parse
            last_exc = e
    if last_exc is not None:
        raise last_exc
    return ""
