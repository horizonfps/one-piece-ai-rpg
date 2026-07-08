"""Invented island designer (Sonnet 4.6) via the `emit_context` tool. Designs the physical
and demographic setting of a Grand Line island calibrated to the canon region (no plot;
that is the Arc Agent's). Output cached per campaign for replayability. Caching automatic
in the proxy."""
from __future__ import annotations

from .. import config
from ..proxy import client
from . import language

_PROMPT_FILE = "island_designer.pt-br.md"

# Accepted regions; the island resolver maps a catalog `cluster` to one of these.
_REGION_ENUM = [
    "east_blue", "west_blue", "north_blue", "south_blue", "reverse_mountain",
    "paradise_first_half", "paradise_second_half", "calm_belt", "sky_island",
    "fishman_island", "new_world", "mariejoise",
]
_PHASE_ENUM = ["early", "mid", "late"]

_CONTEXT_FIELDS = (
    "climate_paradigm", "geography_hint", "fauna_flora_hint",
    "inhabitants_hint", "civilization_level", "economy_and_culture_hint",
)
# Display name the designer coins; cached with the context and used for the map marker + plot.
_NAME_FIELD = "island_name"

EMIT_CONTEXT_TOOL = {
    "name": "emit_context",
    "description": (
        "Emite o nome proprio da ilha (island_name, formato One Piece) + o contexto "
        "fisico/demografico: 6 campos freeform (climate_paradigm, geography_hint, "
        "fauna_flora_hint, inhabitants_hint, civilization_level, economy_and_culture_hint), "
        "1-2 frases cada. Uma chamada, nenhum texto fora."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "island_name": {
                "type": "string",
                "description": "Nome proprio da ilha em formato One Piece (ver prompt). Cunhe um.",
            },
            "climate_paradigm": {"type": "string"},
            "geography_hint": {"type": "string"},
            "fauna_flora_hint": {"type": "string"},
            "inhabitants_hint": {"type": "string"},
            "civilization_level": {"type": "string"},
            "economy_and_culture_hint": {
                "type": "string",
                "description": (
                    "Do que a vida ali vive + o traco cultural que a distingue. VARIE a base "
                    "economica de ilha pra ilha (comercio, industria, mineracao, construcao naval, "
                    "agricultura, guarnicao, realeza, turismo, contrabando, pesca) — a pesca e uma "
                    "opcao entre muitas, nunca o default de toda ilha costeira."
                ),
            },
        },
        "required": [_NAME_FIELD, *_CONTEXT_FIELDS],
    },
}


def _instructions() -> str:
    return (config.PROMPTS_DIR / _PROMPT_FILE).read_text(encoding="utf-8")


def parse_context(emitted: dict | None) -> dict:
    """Normalize `emit_context`: the coined island_name + the 6 string fields (default '')."""
    emitted = emitted or {}
    ctx = {f: str(emitted.get(f) or "").strip() for f in _CONTEXT_FIELDS}
    ctx[_NAME_FIELD] = str(emitted.get(_NAME_FIELD) or "").strip()
    return ctx


def _is_valid(ctx: dict) -> bool:
    # Name + climate + geography + inhabitants must be filled; the arc generator tolerates the rest.
    return (
        bool(ctx.get(_NAME_FIELD))
        and bool(ctx.get("climate_paradigm"))
        and bool(ctx.get("geography_hint"))
        and bool(ctx.get("inhabitants_hint"))
    )


def build_designer_input(
    *, island_slug: str, island_name: str, region: str, campaign_phase: str
) -> dict:
    """Build the Island Designer input contract; enum fields are sanitized with safe fallbacks.
    `island_name` is a placeholder hint (humanized slug); the designer coins the real name."""
    return {
        "island_slug": island_slug,
        "placeholder_name": island_name,
        "region": region if region in _REGION_ENUM else "paradise_first_half",
        "campaign_phase": campaign_phase if campaign_phase in _PHASE_ENUM else "early",
    }


async def call_island_designer(designer_input: dict, *, retries: int = 1) -> dict | None:
    """Run the designer, returning the parsed `invented_context` or None."""
    parsed: dict | None = None
    last_exc: Exception | None = None
    for _attempt in range(retries + 1):
        try:
            emitted = await client.call_tool(
                model=config.AGENT_MODEL,
                instructions=_instructions(),
                tag="island-designer",
                sections=[("ISLAND-DESIGN-INPUT", designer_input)],
                volatile_instructions=language.output_directive(),
                tool=EMIT_CONTEXT_TOOL,
                tool_name="emit_context",
                temperature=config.AGENT_TEMPERATURE,
                max_tokens=900,
                trace_label="Island Designer",
            )
            parsed = parse_context(emitted)
            if _is_valid(parsed):
                return parsed
        except Exception as e:  # noqa: BLE001 retry covers truncation/parse
            last_exc = e
    if parsed is not None and _is_valid(parsed):
        return parsed
    if last_exc is not None:
        raise last_exc
    return parsed
