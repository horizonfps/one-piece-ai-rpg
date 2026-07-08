"""Player fighting_style consolidation (FASE 11.4): Sonnet via the emit_fighting_style tool.

Runs on a player tier_change_event: reads the consolidated context and regenerates
player_snapshot.fighting_style {summary, tags, generated_at_turn_index}, overwriting the previous
version (no history).
"""
from __future__ import annotations

from .. import config
from ..db import repositories as repo
from ..proxy import client
from . import language

_PROMPT_FILE = "director_fighting_style_addendum.pt-br.md"
MAX_TOKENS = 1500

# Tool schema mirroring the prompt.
EMIT_FIGHTING_STYLE_TOOL = {
    "name": "emit_fighting_style",
    "description": (
        "Regera o descritor consolidado de fighting_style do player NESTE passe "
        "de tier-up. Chamada UNICA, zero texto fora. O descritor sai dos sinais "
        "consolidados do input (fruit, haki, techniques, traits, class, combate "
        "recente). Sinal ausente NAO entra (anti-fabricacao)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": (
                    "1-2 frases PT-BR descritivas da identidade de combate do player — "
                    "postura, ritmo, prioridade tatica, detalhe fisico dominante. "
                    "Factual-descritivo, NAO cena narrada. Sem vocab de sistema "
                    "(nome de tier, bounty, turn_index)."
                ),
            },
            "tags": {
                "type": "array",
                "description": (
                    "2 a 6 descritores-chave em minusculas (palavra ou compound curto). "
                    "Vocabulario de imagery, NAO titulo/epiteto/frase."
                ),
                "items": {"type": "string"},
            },
            "generated_at_turn_index": {
                "type": "integer",
                "description": "Copie literal o turn_index do input.",
            },
        },
        "required": ["summary", "tags", "generated_at_turn_index"],
    },
}


def _instructions() -> str:
    return (config.PROMPTS_DIR / _PROMPT_FILE).read_text(encoding="utf-8")


def _trait_names(player_card: dict) -> list[str]:
    """Player trait names (from character_creation)."""
    cc = player_card.get("character_creation") or {}
    out: list[str] = []
    for t in cc.get("traits") or []:
        if isinstance(t, dict) and t.get("name"):
            out.append(t["name"])
        elif isinstance(t, str) and t.strip():
            out.append(t.strip())
    return out


def _techniques(player_card: dict) -> list[dict]:
    """Player registered techniques as [{name, description}]. Normalizes loose strings."""
    cc = player_card.get("character_creation") or {}
    out: list[dict] = []
    for t in cc.get("starting_techniques") or []:
        if isinstance(t, dict) and t.get("name"):
            out.append({"name": t["name"], "description": t.get("description", "")})
        elif isinstance(t, str) and t.strip():
            out.append({"name": t.strip()})
    return out


def build_input(
    player_card: dict,
    *,
    tier_change_event: dict,
    turn_index: int,
    tier_before: str | None = None,
    recent_combat_summary: str = "",
) -> dict:
    """Build the consolidator input contract."""
    pc = player_card.get("player_character") or {}
    ps = player_card.get("player_snapshot") or {}
    cc = player_card.get("character_creation") or {}
    return {
        "turn_index": turn_index,
        "tier_change_event": {
            "new_tier": tier_change_event.get("new_tier", ""),
            "reason": tier_change_event.get("reason", ""),
        },
        "player": {
            "class": cc.get("class_display") or pc.get("class", ""),
            "tier_before": tier_before or "",
            "fruit": ps.get("fruit") or pc.get("fruit"),
            "haki": ps.get("haki") or pc.get("haki", []),
            "traits": _trait_names(player_card),
            "techniques": _techniques(player_card),
            "recent_combat_summary": recent_combat_summary,
            "previous_fighting_style": ps.get("fighting_style"),
        },
    }


def parse(emitted: dict | None) -> dict | None:
    """Validate the output: non-empty summary, non-empty tag list, integer turn index. Returns
    None if invalid."""
    if not isinstance(emitted, dict):
        return None
    summary = emitted.get("summary")
    tags = emitted.get("tags")
    if not isinstance(summary, str) or not summary.strip():
        return None
    if not isinstance(tags, list):
        return None
    clean_tags = [t for t in tags if isinstance(t, str) and t.strip()]
    if not clean_tags:
        return None
    gen_idx = emitted.get("generated_at_turn_index")
    return {
        "summary": summary.strip(),
        "tags": clean_tags,
        "generated_at_turn_index": int(gen_idx) if isinstance(gen_idx, int) else None,
    }


async def call_consolidate(fs_input: dict, *, retries: int = 1) -> dict | None:
    """Run the consolidator (Sonnet, DIRECTOR_TEMPERATURE) and return the parsed output."""
    last_exc: Exception | None = None
    for _attempt in range(retries + 1):
        try:
            emitted = await client.call_tool(
                model=config.DIRECTOR_MODEL,
                instructions=_instructions(),
                tag="fighting-style",
                sections=[("FIGHTING-STYLE-INPUT", fs_input)],
                volatile_instructions=language.output_directive(),
                tool=EMIT_FIGHTING_STYLE_TOOL,
                tool_name="emit_fighting_style",
                temperature=config.DIRECTOR_TEMPERATURE,
                max_tokens=MAX_TOKENS,
                trace_label="Diretor · fighting_style",
            )
            parsed = parse(emitted)
            if parsed is not None:
                return parsed
        except Exception as e:  # noqa: BLE001  retry covers truncation/parse
            last_exc = e
    if last_exc is not None:
        raise last_exc
    return None


async def regenerate(
    conn,
    campaign_id: str,
    *,
    tier_change_event: dict,
    turn_index: int,
    tier_before: str | None = None,
    recent_combat_summary: str = "",
) -> dict:
    """Orchestration: reload the player card (with the new tier applied), consolidate the
    fighting_style, persist it, and clear the fighting_style_regen_pending hook. Best-effort:
    returns a report (with error on failure)."""
    player_sc = await repo.get_player_story_card(conn, campaign_id)
    if player_sc is None:
        return {"error": "player story card ausente"}
    player_card = player_sc["data"]

    fs_input = build_input(
        player_card,
        tier_change_event=tier_change_event,
        turn_index=turn_index,
        tier_before=tier_before,
        recent_combat_summary=recent_combat_summary,
    )
    parsed = await call_consolidate(fs_input)
    if parsed is None:
        return {"error": "sem output utilizável"}

    data = dict(player_card)
    psnap = dict(data.get("player_snapshot") or {})
    psnap["fighting_style"] = parsed
    psnap.pop("fighting_style_regen_pending", None)
    data["player_snapshot"] = psnap
    await repo.update_story_card(conn, player_sc["id"], data)
    return {"summary": parsed["summary"], "tags": parsed["tags"]}
