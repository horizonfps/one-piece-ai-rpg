"""Creature generator (Sonnet 4.6) via the `emit_creature` tool. Emits one lightweight
beast/animal card (a pet, mount, wild predator, Sea King). Persisted as an `npc_agent`
row tagged `entity_kind="creature"` so scene presence + Narrator rendering reach it by id,
but it carries NO agent mind: no off-scene tick, no on-scene Sonnet call. The
Narrator renders it from species/disposition/behavior_notes. disposition is qualitative
(the generator decides, never the engine); owner_id is nullable (wild creatures stand alone)."""
from __future__ import annotations

import uuid

from .. import config
from ..proxy import client
from . import language

_PROMPT_FILE = "creature_generator.pt-br.md"

_TIER_ENUM = ["NORMAL", "SKILLED", "STRONG", "ELITE", "MONSTER", "TITAN", "WORLD", "ABSURD"]
_KNOWLEDGE_ENUM = ["common", "regional", "specialized", "esoteric", "classified"]

# Tool schema. API does not enforce strict; parse normalizes id/defaults/entity_kind.
EMIT_CREATURE_TOOL = {
    "name": "emit_creature",
    "description": (
        "Emite UMA criatura nao-falante (animal, fera, predador selvagem, Rei do Mar, "
        "pet, montaria). Card leve, SEM mente de agente: nao fala, nao tem voz/sonho/"
        "alinhamento-de-pessoa. Chame UMA vez. Nenhum texto fora do tool call."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "UUID novo do card."},
            "name": {"type": "string", "description": "Nome ou chamado da criatura."},
            "species": {
                "type": "string",
                "description": "Especie concreta: leao, lobo, Rei do Mar, aguia, tigre-do-mar, etc.",
            },
            "aliases": {
                "type": "array",
                "items": {"type": "string"},
                "description": "0-2 apelidos. Fera anonima = vazio.",
            },
            "description": {
                "type": "string",
                "description": "2-4 frases: aparencia + porte + traco fisico marcante. Sem prosa romanceada.",
            },
            "disposition": {
                "type": "string",
                "description": (
                    "QUALITATIVO, texto livre: como a criatura reage agora a estranhos/ao jogador "
                    "(hostil, arredia, indiferente, afeicoada ao dono, faminta, territorial...). "
                    "Voce decide pela cena; nao ha lista fixa."
                ),
            },
            "owner_id": {
                "type": ["string", "null"],
                "description": (
                    "id do NPC dono/domador quando a criatura pertence a alguem (pet, montaria, "
                    "fera amestrada). null se for selvagem ou sem dono (Rei do Mar, predador livre)."
                ),
            },
            "behavior_notes": {
                "type": "string",
                "description": (
                    "Como age em cena: o que faz, gatilhos de ataque/recuo, como (e se) e controlada. "
                    "Isto guia o Narrador no lugar de voice_notes; criatura nao tem fala."
                ),
            },
            "current_state": {
                "type": "object",
                "description": "Estado atual. tier = perigo/forca da criatura. summary_text = onde/condicao.",
                "properties": {
                    "tier": {"type": "string", "enum": _TIER_ENUM},
                    "summary_text": {"type": "string"},
                    "flags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["tier", "summary_text", "flags"],
            },
            "current_location": {"type": "string", "description": "Slug de localizacao (ilha/sub-area)."},
            "knowledge_tier_to_know_exists": {"type": "string", "enum": _KNOWLEDGE_ENUM},
            "knowledge_tier_to_know_details": {"type": "string", "enum": _KNOWLEDGE_ENUM},
        },
        "required": [
            "id", "name", "species", "aliases", "description", "disposition",
            "owner_id", "behavior_notes", "current_state", "current_location",
            "knowledge_tier_to_know_exists", "knowledge_tier_to_know_details",
        ],
    },
}


def _instructions() -> str:
    return (config.PROMPTS_DIR / _PROMPT_FILE).read_text(encoding="utf-8")


def _as_list(v) -> list:
    return v if isinstance(v, list) else []


def parse_emit_creature(emitted: dict | None, *, turn_index: int = 0) -> dict | None:
    """Normalize `emit_creature` into a creature-tagged npc_agent row (mints id if missing,
    mirrors tier to top level for card-only briefing, stamps turn indexes, inert agent
    bookkeeping). None if name missing."""
    emitted = emitted or {}
    name = (emitted.get("name") or "").strip()
    if not name:
        return None

    cs = emitted.get("current_state")
    if not isinstance(cs, dict):
        return None
    if cs.get("tier") not in _TIER_ENUM:
        return None
    cs.setdefault("summary_text", "")
    cs["flags"] = _as_list(cs.get("flags"))

    owner = emitted.get("owner_id")
    owner = owner if isinstance(owner, str) and owner.strip() else None

    data = {
        "id": (emitted.get("id") or uuid.uuid4().hex),
        "name": name,
        "entity_kind": "creature",
        "canonical": "generated",
        "species": (emitted.get("species") or "").strip(),
        "aliases": _as_list(emitted.get("aliases")),
        "description": emitted.get("description") or "",
        "disposition": emitted.get("disposition") or "",
        "owner_id": owner,
        "behavior_notes": emitted.get("behavior_notes") or "",
        "current_state": cs,
        "tier": cs["tier"],
        "current_location": emitted.get("current_location") or "",
        # Inert mind: a creature carries no persona, ticks never run.
        "affiliation": "creature",
        "status": "alive",
        "relationships": {},
        "personal_event_log": [],
        "state_history": [],
        "related_card_ids": [],
        "knowledge_tier_to_know_exists": emitted.get("knowledge_tier_to_know_exists") or "common",
        "knowledge_tier_to_know_details": emitted.get("knowledge_tier_to_know_details") or "common",
        "created_at_turn_index": int(turn_index),
        "last_updated_turn_index": int(turn_index),
        "last_tick_index": int(turn_index),
        "last_seen_by_player_index": int(turn_index),
    }
    return data


def _is_valid(data: dict | None) -> bool:
    return bool(data) and bool(data.get("id")) and bool(data.get("name")) and data.get("entity_kind") == "creature"


async def call_generate_creature(creature_input: dict, *, turn_index: int = 0, retries: int = 1) -> dict | None:
    """Run the generator, returning the parsed creature row or None. Retries on
    invalid/truncated output or exception."""
    parsed: dict | None = None
    last_exc: Exception | None = None
    for _attempt in range(retries + 1):
        try:
            emitted = await client.call_tool(
                model=config.AGENT_MODEL,
                instructions=_instructions(),
                tag="creature-generator",
                sections=[("CREATURE-GENERATION-INPUT", creature_input)],
                volatile_instructions=language.output_directive(),
                tool=EMIT_CREATURE_TOOL,
                tool_name="emit_creature",
                temperature=config.AGENT_TEMPERATURE,
                max_tokens=1500,
            )
            parsed = parse_emit_creature(emitted, turn_index=turn_index)
            if _is_valid(parsed):
                return parsed
        except Exception as e:  # noqa: BLE001 retry covers truncation/parse
            last_exc = e
    if _is_valid(parsed):
        return parsed
    if last_exc is not None:
        raise last_exc
    return None


def build_creature_input(
    entry: dict,
    *,
    arc_context: dict,
    owner_hint: str | None = None,
    scene_prose_anchor: str | None = None,
) -> dict:
    """Build the generator input from a creature `npcs_to_generate[]` entry plus arc_context.
    scene_prose_anchor is the prose the Narrator already wrote; appearance/behavior there is
    scene canon the generator matches, not reinvents."""
    return {
        "tentative_name": (entry.get("name") or "").strip() or None,
        "context": entry.get("context") or "",
        "scene_prose_anchor": (scene_prose_anchor or None),
        "owner_hint": owner_hint,
        "current_arc_context": arc_context,
    }
