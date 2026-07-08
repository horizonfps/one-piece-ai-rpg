"""Crystallizer (Sonnet 4.6) via tool emit_crystals. Extracts NEW/UPDATED crystals from the
current turn's prose; earlier turns are context only. game_clock, when present, is immutable
canon for ages and dates."""
from __future__ import annotations

from .. import config
from ..proxy import client
from . import language

_PROMPT_FILE = "crystallizer_system_prompt.pt-br.md"
MAX_TOKENS = 4096

CATEGORY_ENUM = [
    "character_trait", "relationship", "event", "object", "revelation",
    "promise", "combat_outcome", "world_fact", "skill_or_power", "romance",
]

# Schema gate: every UPDATE declares where the closure comes from. obsolescencia_externa is
# routed to NEW by _reconstruct, leaving the old crystal untouched (anti-double-counting).
UPDATE_BASIS_ENUM = ["fechamento_interno", "obsolescencia_externa"]

# Crystal is one concise fact line.
_CRYSTAL_FIELDS = {
    "category": {"type": "string", "enum": CATEGORY_ENUM},
    "fact": {"type": "string"},
    "characters": {"type": "array", "items": {"type": "string"}},
    "location": {"type": "string"},
    "participants": {"type": "array", "items": {"type": "string"}},
    "witnesses": {"type": "array", "items": {"type": "string"}},
    "hidden_witnesses": {"type": "array", "items": {"type": "string"}},
}
_NEW_REQUIRED = list(_CRYSTAL_FIELDS.keys())
_UPDATED_FIELDS = {
    "id": {"type": "string"},
    "update_basis": {"type": "string", "enum": UPDATE_BASIS_ENUM},
    **_CRYSTAL_FIELDS,
}
_UPDATED_REQUIRED = list(_UPDATED_FIELDS.keys())

CRYSTAL_TOOL = {
    "name": "emit_crystals",
    "description": (
        "Emite os cristais NEW e UPDATED extraídos da prosa do turn atual, seguindo todas "
        "as regras do cristalizador. SEMPRE chame esta tool — se nada vira cristal, chame "
        "com new_crystals=[] e updated_crystals=[]."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "new_crystals": {
                "type": "array",
                "items": {"type": "object", "properties": _CRYSTAL_FIELDS, "required": _NEW_REQUIRED},
            },
            "updated_crystals": {
                "type": "array",
                "items": {"type": "object", "properties": _UPDATED_FIELDS, "required": _UPDATED_REQUIRED},
            },
        },
        "required": ["new_crystals", "updated_crystals"],
    },
}


def _instructions() -> str:
    return (config.PROMPTS_DIR / _PROMPT_FILE).read_text(encoding="utf-8")


def _beats_section(turns_prose: list[dict], *, extract: bool) -> str:
    """Formats a list of turns (beats) into a block. extract labels it as the scene to
    extract from or as prior context."""
    label = "CENA ATUAL — EXTRAIA DAQUI" if extract else "ANTES DA CENA — CONTEXTO, NÃO EXTRAIR"
    if not turns_prose:
        return "(nenhum beat anterior — a cena abre a campanha)" if not extract else "(cena vazia)"
    blocks = [
        f"### Beat {t['turn_index']} ({t.get('scene_name', '')}) — {label}\n\n" + t["prose"].strip()
        for t in turns_prose
    ]
    return "\n\n---\n\n".join(blocks)


def _reconstruct(result: dict) -> dict:
    """Runtime reconstruction: an UPDATE tagged obsolescencia_externa becomes NEW (without
    id/update_basis), leaving the old crystal untouched. Strips update_basis from legitimate
    updates before persisting."""
    new = list(result.get("new_crystals", []) or [])
    updated_raw = list(result.get("updated_crystals", []) or [])
    clean_updated: list[dict] = []
    reconstructed = 0
    for u in updated_raw:
        if u.get("update_basis") == "obsolescencia_externa":
            reconstructed += 1
            new.append({k: v for k, v in u.items() if k not in ("id", "update_basis")})
        else:
            clean_updated.append({k: v for k, v in u.items() if k != "update_basis"})
    return {
        "new_crystals": new,
        "updated_crystals": clean_updated,
        "obsolescence_reconstructed": reconstructed,
    }


async def crystallize_scene(
    *,
    scene_turns_prose: list[dict],
    context_turns_prose: list[dict],
    existing_crystals: list[dict],
    scene_context: dict,
    game_clock: dict | None = None,
) -> dict:
    """Extracts crystals from a whole scene (list of beats/turns). Fired by the runner when
    the narrator closes the scene or at the turn cap. The scene prose is the extraction
    material; earlier turns are context only."""
    scene_brief = {
        "location": scene_context.get("location", ""),
        "tension_level": scene_context.get("tension_level", ""),
    }

    sections: list[tuple[str, object]] = [
        (
            "scene_context (use este nome canônico pro campo `location` dos cristais, "
            "cortando a parte ambient após o `—`)",
            scene_brief,
        ),
    ]
    if game_clock is not None:
        sections.append(
            (
                "game_clock (CANON IMUTÁVEL — use estes valores literalmente para idades/datas, "
                "NUNCA calcule)",
                game_clock,
            )
        )
    sections += [
        ("existing_crystals (todos os cristais já na campanha, COM id pra UPDATE)", existing_crystals or []),
        (
            f"contexto_anterior ({len(context_turns_prose)} beats antes da cena — não extrair daqui)",
            _beats_section(context_turns_prose, extract=False),
        ),
        (
            f"cena_atual ({len(scene_turns_prose)} beats — EXTRAIA OS CRISTAIS DESTA CENA INTEIRA)",
            _beats_section(scene_turns_prose, extract=True)
            + "\n\n---\n\nChame a tool `emit_crystals` com os cristais da cena seguindo todas as regras.",
        ),
    ]

    result = await client.call_tool(
        model=config.CRYSTALLIZER_MODEL,
        instructions=_instructions(),
        tag="crystallizer",
        sections=sections,
        volatile_instructions=language.output_directive(),
        tool=CRYSTAL_TOOL,
        tool_name="emit_crystals",
        max_tokens=MAX_TOKENS,
    )
    return _reconstruct(result)
