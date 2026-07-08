"""Named ship generator (Sonnet) via the emit_ship tool (FASE 18.3).

The Narrator flags turn_meta.ships_to_generate[] and the Director dispatches the job; the runner
runs this module per job and emits ONE SHIP StoryCard. A ship is a public card with no agent.
Persistence: one story_cards row (data.type=SHIP). When it joins the player fleet, the runner
applies the swap.
"""
from __future__ import annotations

import uuid

from .. import config
from ..proxy import client
from . import language

_PROMPT_FILE = "ship_generator.pt-br.md"

_KNOWLEDGE_ENUM = ["common", "regional", "specialized", "esoteric", "classified"]
_HULL_CONDITIONS = ["pristine", "scarred", "damaged", "broken"]
_SPEED_CLASSES = ["raft", "standard", "fast", "exceptional"]

# --------------------------------------------------------------------------------------
# Tool schema for emit_ship. API is not strict; the parse forces type/canonical + defaults.
# --------------------------------------------------------------------------------------
EMIT_SHIP_TOOL = {
    "name": "emit_ship",
    "description": (
        "Emite UM StoryCard SHIP completo (card publico sem agent — navio nao tem mente "
        "privada). Inclui identidade, subtype, descricao, current_state (com hull_condition) "
        "e knowledge tiers. Navio NAO tem tier de poder nem stat numerico de resistencia "
        "(isso e de NPC). NAO emita role nem acquired_at_turn_index (isso e do engine via "
        "ship_swap_event). Chame UMA vez. Nenhum texto fora do tool call."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "UUID novo do card."},
            "type": {"type": "string", "enum": ["SHIP"]},
            "subtype": {
                "type": "string",
                "description": (
                    "Classe/porte do casco snake_case (sloop | caravel | brig | schooner | "
                    "galleon | warship | fishing_boat | junk | paddle_steamer | ...). "
                    "String livre — reflete porte e uso concretos, sem inflar escala."
                ),
            },
            "speed_class": {
                "type": "string",
                "enum": _SPEED_CLASSES,
                "description": (
                    "Classe de velocidade coerente com o subtype: 'raft' bote/jangada/junco/barca "
                    "de pesca (lento); 'standard' sloop/caravela/brigue/galeao comum; 'fast' "
                    "clipper/escuna veloz/vapor de roda rapido/corsario leve; 'exceptional' casco "
                    "de design extraordinario. Calibre pelo porte real, sem inflar."
                ),
            },
            "name": {"type": "string", "description": "Nome do navio (ou casco anonimo sem nome forte)."},
            "aliases": {
                "type": "array",
                "items": {"type": "string"},
                "description": "0-2 epitetos (apodo do casco, batismo de dono anterior). Anonimo = vazio.",
            },
            "canonical": {"type": "string", "enum": ["generated"]},
            "description": {
                "type": "string",
                "description": (
                    "2-4 frases: classe e porte + silhueta marcante + origem/relevancia. "
                    "Sem prosa romanceada, sem consciencia propria do navio."
                ),
            },
            "current_state": {
                "type": "object",
                "description": (
                    "Estado atual do navio. summary_text = em poder de quem/onde/condicao "
                    "visivel. hull_condition calibrado pela aquisicao (salvaged_wreck nasce "
                    "comprometido; purchased novo nasce integro)."
                ),
                "properties": {
                    "summary_text": {"type": "string"},
                    "hull_condition": {"type": "string", "enum": _HULL_CONDITIONS},
                    "flags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["summary_text", "hull_condition", "flags"],
            },
            "state_history": {"type": "array", "items": {"type": "object"}, "description": "Vazio inicialmente."},
            "related_card_ids": {"type": "array", "items": {"type": "string"}, "description": "Vazio inicialmente."},
            "knowledge_tier_to_know_exists": {"type": "string", "enum": _KNOWLEDGE_ENUM},
            "knowledge_tier_to_know_details": {"type": "string", "enum": _KNOWLEDGE_ENUM},
        },
        "required": [
            "id", "type", "subtype", "speed_class", "name", "aliases", "canonical",
            "description", "current_state", "state_history", "related_card_ids",
            "knowledge_tier_to_know_exists", "knowledge_tier_to_know_details",
        ],
    },
}


def _instructions() -> str:
    return (config.PROMPTS_DIR / _PROMPT_FILE).read_text(encoding="utf-8")


def _as_list(v) -> list:
    return v if isinstance(v, list) else []


def parse_emit_ship(emitted: dict | None, *, turn_index: int = 0) -> dict | None:
    """Normalize emit_ship into a valid SHIP StoryCard: ensure id, force type/canonical, default
    arrays/current_state and hull_condition, stamp turn indices. None if name is missing."""
    emitted = emitted or {}
    name = (emitted.get("name") or "").strip()
    if not name:
        return None

    card = dict(emitted)
    card["id"] = card.get("id") or uuid.uuid4().hex
    card["type"] = "SHIP"
    card["canonical"] = "generated"
    card["name"] = name
    if not (isinstance(card.get("subtype"), str) and card["subtype"].strip()):
        return None
    card["speed_class"] = card.get("speed_class") if card.get("speed_class") in _SPEED_CLASSES else "standard"
    card["aliases"] = _as_list(card.get("aliases"))
    card.setdefault("description", "")
    cs = card.get("current_state")
    if not isinstance(cs, dict):
        cs = {}
    cs.setdefault("summary_text", "")
    hull = cs.get("hull_condition")
    cs["hull_condition"] = hull if hull in _HULL_CONDITIONS else "scarred"
    cs["flags"] = _as_list(cs.get("flags"))
    card["current_state"] = cs
    card["state_history"] = _as_list(card.get("state_history"))
    card["related_card_ids"] = _as_list(card.get("related_card_ids"))
    card.setdefault("knowledge_tier_to_know_exists", "regional")
    card.setdefault("knowledge_tier_to_know_details", "regional")
    card["created_at_turn_index"] = int(turn_index)
    card["last_updated_turn_index"] = int(turn_index)
    return card


def _is_valid(card: dict | None) -> bool:
    return bool(card) and bool(card.get("id")) and bool(card.get("name")) and card.get("type") == "SHIP"


async def call_generate_ship(ship_input: dict, *, turn_index: int = 0, retries: int = 1) -> dict | None:
    """Run the generator and return the parsed SHIP StoryCard, or None on failure. Retries on
    invalid/truncated output or exception."""
    parsed: dict | None = None
    last_exc: Exception | None = None
    for _attempt in range(retries + 1):
        try:
            emitted = await client.call_tool(
                model=config.AGENT_MODEL,
                instructions=_instructions(),
                tag="ship-generator",
                sections=[("SHIP-GENERATION-INPUT", ship_input)],
                volatile_instructions=language.output_directive(),
                tool=EMIT_SHIP_TOOL,
                tool_name="emit_ship",
                temperature=config.AGENT_TEMPERATURE,
                max_tokens=2000,
            )
            parsed = parse_emit_ship(emitted, turn_index=turn_index)
            if _is_valid(parsed):
                return parsed
        except Exception as e:  # noqa: BLE001  retry covers truncation/parse
            last_exc = e
    if _is_valid(parsed):
        return parsed
    if last_exc is not None:
        raise last_exc
    return None


def build_ship_input(
    entry: dict,
    *,
    arc_context: dict,
    naming_hint: str | None = None,
    plot_context: dict | None = None,
) -> dict:
    """Build the generator contract from a ships_to_generate[] entry + arc_context (built by the
    runner). plot_context comes from the Arc Generator; naming_hint colors a regional ship."""
    return {
        "tentative_name": (entry.get("tentative_name") or entry.get("name") or "").strip() or None,
        "context": entry.get("context") or "",
        "ship_acquisition": (entry.get("ship_acquisition") or "").strip() or None,
        "acquired_by_player": bool(entry.get("acquired_by_player")),
        "initial_hull_condition": entry.get("initial_hull_condition"),
        "current_arc_context": arc_context,
        "naming_hint": naming_hint,
        "plot_context": plot_context,
    }
