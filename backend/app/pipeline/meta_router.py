"""META input router (Sonnet 4.6) via the `emit_meta_action` tool. Sub-classifies a META
input into pergunta/lembre/esqueça without advancing the turn: pergunta returns an OOC
response_text, lembre extracts directives, esqueça only signals (UI opens the panel)."""
from __future__ import annotations

import unicodedata

from .. import config
from ..proxy import client
from . import language

_PROMPT_FILE = "meta_router.pt-br.md"

# Enum keeps the cedilla in "esqueça" as the prompt expects.
_KIND_VALUES = ["pergunta", "lembre", "esqueça"]

# Tool schema. Per-kind fields are optional; API does not enforce branching, parse normalizes.
EMIT_META_ACTION_TOOL = {
    "name": "emit_meta_action",
    "description": (
        "Emite a classificacao + execucao do input META do player. "
        "kind=pergunta gera response_text OOC. kind=lembre extrai diretivas. "
        "kind=esqueca apenas sinaliza ao engine. Chame UMA vez."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": _KIND_VALUES,
                "description": (
                    "Classificacao do META input. 'pergunta' = player pergunta algo OOC; "
                    "'lembre' = player adiciona diretiva persistente; "
                    "'esqueça' = player quer remover diretiva (frontend abre UI)."
                ),
            },
            "response_text": {
                "type": "string",
                "description": (
                    "Presente SE kind=pergunta. Resposta OOC PT-BR direta, factual, "
                    "1-4 paragrafos curtos. Sem prosa romanceada, sem disclaimer, "
                    "sem markdown decorativo, sem narrar cena, sem falar pelo player, "
                    "sem responder em personagem."
                ),
            },
            "directives_to_create": {
                "type": "array",
                "description": (
                    "Presente SE kind=lembre. Cada entry vira uma directive nova no DB. "
                    "Texto limpo, sem prefixo 'lembre:/anota ai:/etc.'. Multiplas "
                    "diretivas no mesmo input viram entries separadas."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "Texto literal limpo da diretiva, em PT-BR.",
                        },
                    },
                    "required": ["text"],
                },
            },
        },
        "required": ["kind"],
    },
}


def _instructions() -> str:
    return (config.PROMPTS_DIR / _PROMPT_FILE).read_text(encoding="utf-8")


def _normalize_kind(raw) -> str | None:
    """Strip accent/case to the canonical {pergunta, lembre, esqueca}, or None if off-enum."""
    if not isinstance(raw, str):
        return None
    s = unicodedata.normalize("NFKD", raw)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower().strip()
    return s if s in {"pergunta", "lembre", "esqueca"} else None


def parse_meta_action(emitted: dict | None) -> dict:
    """Normalize the router output to `{kind, response_text, directives}`, coercing fields
    per kind (pergunta keeps response_text, lembre keeps directives, esqueca neither)."""
    emitted = emitted or {}
    kind = _normalize_kind(emitted.get("kind"))
    response_text = (emitted.get("response_text") or "").strip()
    raw_directives = emitted.get("directives_to_create") or []
    directives = [
        d["text"].strip()
        for d in raw_directives
        if isinstance(d, dict) and isinstance(d.get("text"), str) and d["text"].strip()
    ]

    if kind == "pergunta":
        return {"kind": "pergunta", "response_text": response_text, "directives": []}
    if kind == "lembre":
        return {"kind": "lembre", "response_text": "", "directives": directives}
    if kind == "esqueca":
        return {"kind": "esqueca", "response_text": "", "directives": []}
    # Off-enum: invalid parse; carry kind=None so call_meta_router retries instead of guessing.
    return {"kind": None, "response_text": response_text, "directives": []}


def _is_valid(parsed: dict) -> bool:
    kind = parsed.get("kind")
    if kind == "pergunta":
        return bool(parsed.get("response_text"))
    if kind == "lembre":
        return bool(parsed.get("directives"))
    return kind == "esqueca"


async def call_meta_router(router_input: dict, *, retries: int = 1) -> dict:
    """Run the router and return the parsed canonical output. Retries on invalid/truncated
    output or parse exception."""
    parsed: dict | None = None
    last_exc: Exception | None = None
    for _attempt in range(retries + 1):
        try:
            emitted = await client.call_tool(
                model=config.META_ROUTER_MODEL,
                instructions=_instructions(),
                tag="router",
                sections=[("META-INPUT", router_input)],
                volatile_instructions=language.output_directive(),
                tool=EMIT_META_ACTION_TOOL,
                tool_name="emit_meta_action",
                temperature=config.META_ROUTER_TEMPERATURE,
                max_tokens=2000,
            )
            parsed = parse_meta_action(emitted)
            if _is_valid(parsed):
                return parsed
        except Exception as e:  # noqa: BLE001 retry covers truncation/parse
            last_exc = e
    if parsed is not None:
        # Retry exhausted with a still-invalid classification: last-resort pergunta so the
        # player at least gets an OOC turn, but only after the router genuinely failed twice.
        if parsed.get("kind") is None:
            parsed["kind"] = "pergunta"
        return parsed
    raise last_exc if last_exc is not None else RuntimeError("meta-router sem output utilizável")


def build_router_input(
    player_action: dict,
    *,
    active_directives: list[dict],
    game_context_brief: dict,
) -> dict:
    """Build the router input contract."""
    return {
        "player_input_raw": player_action.get("raw", ""),
        "active_directives": active_directives,
        "game_context_brief": game_context_brief,
    }
