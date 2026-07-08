"""Poneglyphs: content revelation (Opus) + card reads for the Director's context.

Poneglyph = StoryCard type=ITEM, subtype=poneglyph; current_state carries poneglyph_kind,
transcribed_by_player, translated, content_revealed, location/discovery fields.

Reactive: a card with transcribed_by_player and translated but empty content_revealed fires the
revelation once and stores content_revealed; revealing the rio marks metadata.endgame.
rio_poneglyph_read. The Laugh Tale position reveal lives in endgame.detect_and_persist (the read
helpers here only feed its context).
"""
from __future__ import annotations

from .. import config
from ..db import repositories as repo
from ..proxy import client
from . import language

_PROMPT_FILE = "rio_poneglyph_revelation.pt-br.md"

# --------------------------------------------------------------------------------------
# Tool schema for emit_poneglyph_content
# --------------------------------------------------------------------------------------
EMIT_PONEGLYPH_TOOL = {
    "name": "emit_poneglyph_content",
    "description": (
        "Emite o conteudo revelado de UM Poneglyph que o player traduziu. "
        "Chamada UNICA, sem texto fora. content_revealed em prosa PT-BR de "
        "registro antigo formal, conforme a estrutura do poneglyph_kind. "
        "metadata e auditoria pra a engine (kind_used, armas referenciadas, "
        "fatos canon ancorados, literacia aplicada, contagem aproximada de tokens)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "content_revealed": {
                "type": "string",
                "description": (
                    "Prosa PT-BR em registro antigo formal — o TEXTO do "
                    "Poneglyph em si, sem moldura externa de narrador, sem "
                    "markdown / heading / bullet. Estrutura e tamanho conforme "
                    "o poneglyph_kind (road curto direcional / rio longo central "
                    "/ historical medio cronica / instructional medio procedural). "
                    "Se reader_poneglyph_literacy == 'partial', insira lacunas "
                    "'[trecho ilegivel]' em ~30% das frases mantendo o sentido geral."
                ),
            },
            "metadata": {
                "type": "object",
                "description": (
                    "Auditoria — a engine usa pra debug e verificacao de "
                    "fidelidade. Preencha TODOS os cinco subcampos."
                ),
                "properties": {
                    "kind_used": {
                        "type": "string",
                        "enum": ["road", "rio", "historical", "instructional"],
                        "description": (
                            "Kind efetivamente usado na estrutura. DEVE bater "
                            "com poneglyph.poneglyph_kind do input."
                        ),
                    },
                    "ancient_weapons_referenced": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["pluton", "poseidon", "uranus"]},
                        "description": (
                            "Armas Ancestrais referenciadas no texto. Vazio [] "
                            "se nenhuma. Em Poneglyph instructional de Arma "
                            "Ancestral, contem a(s) arma(s) tratada(s)."
                        ),
                    },
                    "canon_anchors_used": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Fatos canon que voce ancorou no texto. Lista quais "
                            "fatos de canon_anchor.related_canon_facts (ou do "
                            "kind_specific_summary) alimentaram o conteudo. "
                            "Non-vazio quando o anchor forneceu fatos."
                        ),
                    },
                    "literacy_applied": {
                        "type": "string",
                        "enum": ["partial", "fluent"],
                        "description": (
                            "Literacia aplicada. Bate com "
                            "reader_context.reader_poneglyph_literacy. 'partial' "
                            "implica lacunas '[trecho ilegivel]' no texto; "
                            "'fluent' implica texto completo sem lacunas."
                        ),
                    },
                    "approx_token_count": {
                        "type": "integer",
                        "description": (
                            "Estimativa aproximada de tokens do content_revealed, "
                            "dentro do range do kind (road ~80-200, rio ~400-900, "
                            "historical ~200-500, instructional ~150-400)."
                        ),
                    },
                },
                "required": [
                    "kind_used", "ancient_weapons_referenced", "canon_anchors_used",
                    "literacy_applied", "approx_token_count",
                ],
            },
        },
        "required": ["content_revealed", "metadata"],
    },
}


# --------------------------------------------------------------------------------------
# Pure functions: Poneglyph card reads
# --------------------------------------------------------------------------------------
def is_poneglyph(card: dict) -> bool:
    return (card or {}).get("type") == "ITEM" and (card or {}).get("subtype") == "poneglyph"


def poneglyph_cards(item_cards: dict) -> list[dict]:
    """ITEM cards that are Poneglyphs (subtype=poneglyph)."""
    return [c for c in (item_cards or {}).values() if is_poneglyph(c)]


def _state(card: dict) -> dict:
    cs = (card or {}).get("current_state")
    return cs if isinstance(cs, dict) else {}


def road_transcribed_count(cards: list[dict]) -> int:
    """How many Road Poneglyphs the player has transcribed."""
    return sum(
        1 for c in cards
        if _state(c).get("poneglyph_kind") == "road" and _state(c).get("transcribed_by_player")
    )


def rio_is_read(cards: list[dict]) -> bool:
    """True if a Rio Poneglyph is translated with revealed content."""
    return any(
        _state(c).get("poneglyph_kind") == "rio"
        and _state(c).get("translated")
        and (_state(c).get("content_revealed") or "").strip()
        for c in cards
    )


def rio_content_summary(cards: list[dict], *, max_chars: int = 600) -> str:
    """Short summary of the Rio content for the epilogue. Empty if unread."""
    for c in cards:
        st = _state(c)
        if st.get("poneglyph_kind") == "rio" and (st.get("content_revealed") or "").strip():
            text = st["content_revealed"].strip().replace("\n", " ")
            return text[:max_chars].rstrip() + ("…" if len(text) > max_chars else "")
    return ""


def pending_revelations(cards: list[dict]) -> list[dict]:
    """Cards ready to reveal: transcribed + translated, no content_revealed yet."""
    out: list[dict] = []
    for c in cards:
        st = _state(c)
        if st.get("transcribed_by_player") and st.get("translated") and not (st.get("content_revealed") or "").strip():
            out.append(c)
    return out


def is_reader(data: dict) -> bool:
    """Light heuristic: an NPC/player is a Poneglyph Reader if it has explicit literacy, a
    dedicated flag, or an archaeologist class/role."""
    if not isinstance(data, dict):
        return False
    lit = data.get("poneglyph_literacy") or (data.get("player_snapshot") or {}).get("poneglyph_literacy")
    if lit in ("partial", "fluent"):
        return True
    if data.get("is_poneglyph_reader"):
        return True
    role = " ".join(str(data.get(k, "")) for k in ("class", "role", "progression_vector")).lower()
    return "poneglyph" in role or "arqueolog" in role


def has_reader(player_card: dict, npcs: dict) -> bool:
    """Reader available = the player can read or some crewmate can."""
    if is_reader(player_card):
        return True
    return any(
        is_reader(d) for d in (npcs or {}).values()
        if d.get("affiliation") == "player_crew"
    )


def pick_reader(player_card: dict, npcs: dict) -> dict | None:
    """The reader doing the translation: the player if able, else the first able crewmate."""
    if is_reader(player_card):
        pc = (player_card or {}).get("player_character") or {}
        return {
            "reader_npc_id": player_card.get("id", "player"),
            "reader_name": pc.get("name", ""),
            "reader_is_player": True,
            "reader_poneglyph_literacy": (player_card.get("player_snapshot") or {}).get(
                "poneglyph_literacy"
            ) or "fluent",
        }
    for aid, d in (npcs or {}).items():
        if d.get("affiliation") == "player_crew" and is_reader(d):
            return {
                "reader_npc_id": aid,
                "reader_name": d.get("name", ""),
                "reader_is_player": False,
                "reader_poneglyph_literacy": d.get("poneglyph_literacy") or "fluent",
            }
    return None


# --------------------------------------------------------------------------------------
# Generator input build + parse
# --------------------------------------------------------------------------------------
def build_reveal_input(
    card: dict, *, player_card: dict, npcs: dict, metadata: dict, current_arc: str = ""
) -> dict:
    """rio_poneglyph_revelation contract from ONE Poneglyph card + state. canon_anchor comes from
    the card; when empty, Opus derives it from the theme and location_name."""
    st = _state(card)
    endgame = metadata.get("endgame") or {}
    canon = card.get("canon_anchor") if isinstance(card.get("canon_anchor"), dict) else {}
    reader = pick_reader(player_card, npcs) or {
        "reader_npc_id": player_card.get("id", "player"),
        "reader_name": ((player_card.get("player_character") or {}).get("name") or ""),
        "reader_is_player": True,
        "reader_poneglyph_literacy": "fluent",
    }
    return {
        "poneglyph": {
            "id": card.get("id", ""),
            "name": card.get("name", ""),
            "poneglyph_kind": st.get("poneglyph_kind", "historical"),
            "location_name": st.get("location_name") or st.get("summary_text") or card.get("description", ""),
            "discovered_at_turn_index": int(st.get("discovered_at_turn_index", 0) or 0),
        },
        "canon_anchor": {
            "kind_specific_summary": canon.get("kind_specific_summary") or card.get("description", ""),
            "related_canon_facts": canon.get("related_canon_facts") or [],
        },
        "alt_canon_campaign": {
            "world_events_relevant": [
                (e.get("summary") if isinstance(e, dict) else str(e))
                for e in (metadata.get("events_background_recent") or [])[:4]
            ],
            "player_traits_relevant": _player_traits(player_card),
            "ancient_weapons_aligned": endgame.get("ancient_weapons_aligned") or [],
        },
        "reader_context": reader,
        "world_state_brief": {
            "imu_status": endgame.get("imu_status", "active"),
            "mary_geoise_status": endgame.get("mary_geoise_status", "untouched"),
            "laugh_tale_revealed": bool(endgame.get("laugh_tale_revealed")),
            "current_arc": current_arc or "post-Egghead",
        },
    }


def _player_traits(player_card: dict) -> list[str]:
    cc = (player_card or {}).get("character_creation") or {}
    out: list[str] = []
    for t in cc.get("traits") or []:
        name = t.get("name") if isinstance(t, dict) else t
        if name:
            out.append(str(name))
    return out[:6]


def parse_reveal(emitted: dict | None, *, expected_kind: str = "") -> dict | None:
    """Normalize emit_poneglyph_content. None if content_revealed is missing. kind_used is audit
    only; falls back to expected_kind when omitted (state derives from the CARD, never this field)."""
    emitted = emitted or {}
    content = (emitted.get("content_revealed") or "").strip()
    if not content:
        return None
    meta = emitted.get("metadata") if isinstance(emitted.get("metadata"), dict) else {}
    return {
        "content_revealed": content,
        "kind_used": (meta.get("kind_used") or "").strip() or expected_kind,
        "ancient_weapons_referenced": [w for w in (meta.get("ancient_weapons_referenced") or []) if isinstance(w, str)],
        "canon_anchors_used": [a for a in (meta.get("canon_anchors_used") or []) if isinstance(a, str)],
        "literacy_applied": meta.get("literacy_applied", ""),
    }


async def call_reveal(reveal_input: dict, *, retries: int = 1) -> dict | None:
    """Run the Poneglyph Revelation Generator (Opus) and return parsed content."""
    instructions = (config.PROMPTS_DIR / _PROMPT_FILE).read_text(encoding="utf-8")
    last_exc: Exception | None = None
    for _attempt in range(retries + 1):
        try:
            emitted = await client.call_tool(
                model=config.NARRATOR_MODEL,
                instructions=instructions,
                tag="poneglyph",
                sections=[("PONEGLYPH-INPUT", reveal_input)],
                volatile_instructions=language.output_directive(),
                tool=EMIT_PONEGLYPH_TOOL,
                tool_name="emit_poneglyph_content",
                max_tokens=3000,
                trace_label="Poneglyph · revelação",
            )
            expected_kind = str((reveal_input.get("poneglyph") or {}).get("poneglyph_kind") or "")
            parsed = parse_reveal(emitted, expected_kind=expected_kind)
            if parsed is not None:
                return parsed
        except Exception as e:  # noqa: BLE001  retry covers truncation/parse
            last_exc = e
    if last_exc is not None:
        raise last_exc
    return None


# --------------------------------------------------------------------------------------
# Orchestration (engine): reveal pending cards
# --------------------------------------------------------------------------------------
def _laugh_tale_crystal(fact: str = "") -> dict:
    fact = (fact or "").strip() or (
        "A posição de Laugh Tale foi revelada pela triangulação dos Road Poneglyphs."
    )
    return {
        "category": "world_fact",
        "fact": fact,
        "characters": [],
        "location": "Laugh Tale",
        "participants": [],
    }


async def process(
    conn,
    campaign_id: str,
    *,
    item_cards: dict,
    player_card: dict,
    npcs: dict,
    metadata: dict,
    current_arc: str,
    turn_index: int,
) -> dict:
    """Process Poneglyphs post-turn: reveal each ready card (Opus, once) + store content_revealed;
    revealing the Rio marks endgame.rio_poneglyph_read. The Laugh Tale reveal lives in
    endgame.detect_and_persist. Best-effort.

    Does NOT write metadata here (returns rio_poneglyph_read in report['endgame_patch'] for the
    caller to merge); only persists the revealed cards."""
    cards = poneglyph_cards(item_cards)
    report: dict = {"revealed": [], "endgame_patch": {}}
    if not cards:
        return report

    endgame_patch: dict = {}

    # Pending revelations, one per card, sequential (rare; avoids an Opus burst).
    for card in pending_revelations(cards):
        try:
            reveal_input = build_reveal_input(
                card, player_card=player_card, npcs=npcs, metadata=metadata, current_arc=current_arc
            )
            parsed = await call_reveal(reveal_input)
        except Exception as exc:  # noqa: BLE001  revelation is best-effort
            report.setdefault("errors", []).append({"id": card.get("id"), "error": f"{type(exc).__name__}: {exc}"})
            continue
        if parsed is None:
            continue
        # Reload fresh and write content_revealed into the card current_state.
        fresh = await repo.get_card_by_entity_id(conn, campaign_id, card.get("id", ""))
        if fresh is None:
            continue
        data = dict(fresh["data"])
        cs = dict(data.get("current_state") or {})
        cs["content_revealed"] = parsed["content_revealed"]
        cs["content_revealed_at_turn_index"] = turn_index
        data["current_state"] = cs
        await repo.update_story_card(conn, fresh["id"], data)
        report["revealed"].append({
            "id": card.get("id"), "name": card.get("name"),
            "poneglyph_kind": _state(card).get("poneglyph_kind"),
        })
        if _state(card).get("poneglyph_kind") == "rio":
            endgame_patch["rio_poneglyph_read"] = True

    report["endgame_patch"] = endgame_patch
    return report
