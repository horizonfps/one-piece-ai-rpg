"""Named item generator (Sonnet 4.6) via the `emit_item` tool. Emits one ITEM StoryCard,
a public card with no agent. Persisted as one `story_cards` row (`data["type"]="ITEM"`);
when `acquired_by_player`, the runner also creates an inventory_entry for the returned id.
Static-prefix caching (TTL 1h) is automatic in `call_tool`."""
from __future__ import annotations

import uuid

from .. import config
from ..proxy import client
from . import language

_PROMPT_FILE = "item_generator.pt-br.md"

_KNOWLEDGE_ENUM = ["common", "regional", "specialized", "esoteric", "classified"]

# Tool schema. API does not enforce strict; parse forces type/canonical, defaults, id.
EMIT_ITEM_TOOL = {
    "name": "emit_item",
    "description": (
        "Emite UM StoryCard ITEM completo (card publico sem agent — item nao tem mente "
        "privada). Inclui identidade, subtype, descricao, current_state e knowledge "
        "tiers. Item NAO tem tier de poder (isso e de NPC). Chame UMA vez. Nenhum texto "
        "fora do tool call."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "UUID novo do card."},
            "type": {"type": "string", "enum": ["ITEM"]},
            "subtype": {
                "type": "string",
                "description": (
                    "Forma fisica concreta snake_case (sword | gun | polearm | kairoseki | "
                    "log_pose | eternal_pose | map | blueprint | antidote | provisions | "
                    "ammo | mushi_spare | document | tool | ...). String livre."
                ),
            },
            "name": {"type": "string"},
            "aliases": {
                "type": "array",
                "items": {"type": "string"},
                "description": "0-2 epitetos (forja, dono anterior). Suprimento generico = vazio.",
            },
            "canonical": {"type": "string", "enum": ["generated"]},
            "description": {
                "type": "string",
                "description": "2-4 frases: o que e + aparencia + relevancia. Sem prosa romanceada.",
            },
            "current_state": {
                "type": "object",
                "description": (
                    "Estado atual do item. summary_text = em poder de quem/onde/condicao. "
                    "Campos por subtype: sword.is_black_blade (bool), "
                    "eternal_pose.tracked_island_id (LOCATION id). Quantidade de stack vive "
                    "na inventory_entry, NAO aqui."
                ),
                "properties": {
                    "summary_text": {"type": "string"},
                    "flags": {"type": "array", "items": {"type": "string"}},
                    "is_black_blade": {"type": "boolean"},
                    "tracked_island_id": {"type": "string"},
                },
                "required": ["summary_text", "flags"],
            },
            "state_history": {"type": "array", "items": {"type": "object"}, "description": "Vazio inicialmente."},
            "related_card_ids": {"type": "array", "items": {"type": "string"}, "description": "Vazio inicialmente."},
            "knowledge_tier_to_know_exists": {"type": "string", "enum": _KNOWLEDGE_ENUM},
            "knowledge_tier_to_know_details": {"type": "string", "enum": _KNOWLEDGE_ENUM},
            "duplicate_of_existing_id": {
                "type": ["string", "null"],
                "description": (
                    "Se o item pedido JA tem card no elenco (mesmo objeto, nao um segundo identico), "
                    "emita o id existente aqui em vez de cunhar um segundo card; senao null. Padrao FASE 31."
                ),
            },
        },
        "required": [
            "id", "type", "subtype", "name", "aliases", "canonical",
            "description", "current_state", "state_history", "related_card_ids",
            "knowledge_tier_to_know_exists", "knowledge_tier_to_know_details",
        ],
    },
}


def _instructions() -> str:
    return (config.PROMPTS_DIR / _PROMPT_FILE).read_text(encoding="utf-8")


def _as_list(v) -> list:
    return v if isinstance(v, list) else []


def parse_emit_item(emitted: dict | None, *, turn_index: int = 0) -> dict | None:
    """Normalize `emit_item` into a valid ITEM StoryCard (mints id if missing, forces
    type/canonical, defaults, stamps turn indexes). None if name missing."""
    emitted = emitted or {}
    name = (emitted.get("name") or "").strip()
    if not name:
        return None

    card = dict(emitted)
    card["id"] = card.get("id") or uuid.uuid4().hex
    card["type"] = "ITEM"
    card["canonical"] = "generated"
    card["name"] = name
    card.setdefault("subtype", "misc")
    card["aliases"] = _as_list(card.get("aliases"))
    card.setdefault("description", "")
    cs = card.get("current_state")
    if not isinstance(cs, dict):
        cs = {}
    cs.setdefault("summary_text", "")
    cs["flags"] = _as_list(cs.get("flags"))
    card["current_state"] = cs
    card["state_history"] = _as_list(card.get("state_history"))
    card["related_card_ids"] = _as_list(card.get("related_card_ids"))
    if card.get("knowledge_tier_to_know_exists") not in _KNOWLEDGE_ENUM:
        return None
    if card.get("knowledge_tier_to_know_details") not in _KNOWLEDGE_ENUM:
        return None
    # Model-side dedup: the id of an existing item card this object already is, if the generator matched.
    _dup = card.get("duplicate_of_existing_id")
    card["duplicate_of_existing_id"] = _dup if isinstance(_dup, str) and _dup.strip() else None
    card["created_at_turn_index"] = int(turn_index)
    card["last_updated_turn_index"] = int(turn_index)
    return card


def _is_valid(card: dict | None) -> bool:
    return bool(card) and bool(card.get("id")) and bool(card.get("name")) and card.get("type") == "ITEM"


async def call_generate_item(item_input: dict, *, turn_index: int = 0, retries: int = 1) -> dict | None:
    """Run the generator, returning the parsed ITEM StoryCard or None. Retries on
    invalid/truncated output or exception."""
    parsed: dict | None = None
    last_exc: Exception | None = None
    for _attempt in range(retries + 1):
        try:
            emitted = await client.call_tool(
                model=config.AGENT_MODEL,
                instructions=_instructions(),
                tag="item-generator",
                sections=[("ITEM-GENERATION-INPUT", item_input)],
                volatile_instructions=language.output_directive(),
                tool=EMIT_ITEM_TOOL,
                tool_name="emit_item",
                temperature=config.AGENT_TEMPERATURE,
                max_tokens=2000,
            )
            parsed = parse_emit_item(emitted, turn_index=turn_index)
            if _is_valid(parsed):
                return parsed
        except Exception as e:  # noqa: BLE001 retry covers truncation/parse
            last_exc = e
    if _is_valid(parsed):
        return parsed
    if last_exc is not None:
        raise last_exc
    return None


def build_item_input(
    entry: dict,
    *,
    arc_context: dict,
    naming_hint: str | None = None,
    plot_context: dict | None = None,
) -> dict:
    """Build the generator input contract from an `items_to_generate[]` entry plus arc_context
    and optional plot/naming hints."""
    return {
        "tentative_name": (entry.get("name") or "").strip() or None,
        "context": entry.get("context") or "",
        "item_category": entry.get("item_category") or "misc",
        "acquired_by_player": bool(entry.get("acquired_by_player")),
        "stackable": bool(entry.get("stackable")),
        "current_arc_context": arc_context,
        "naming_hint": naming_hint,
        "plot_context": plot_context,
    }
