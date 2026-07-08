"""Breakthrough generators (Opus 4.8), one dedicated tool per kind. The Director confirms a
breakthrough_event post-turn; the engine runs the right generator, parses the description,
and applies the state patch. The pre_emit_style_check gate is a reflexive forcing function
the engine discards on parse.

Breakthrough state lives in the player card JSON escape-hatch; the player fruit is singular
and never a FRUIT card. A cardified weapon (ITEM card) also mirrors black_blade into its
current_state. Prompt caching wired by client.call_tool."""
from __future__ import annotations

from .. import config
from ..db import repositories as repo
from ..proxy import client
from . import language

# kind -> {prompt_file, tool_name, has_target_card_id}.
PROMPT_CONFIG: dict[str, dict] = {
    "fruit_awakening": {
        "prompt_file": "fruit_awakening_generator.pt-br.md",
        "tool_name": "emit_fruit_awakening",
        "has_target_card_id": True,
    },
    "black_blade": {
        "prompt_file": "black_blade_generator.pt-br.md",
        "tool_name": "emit_black_blade",
        "has_target_card_id": True,
    },
    "haoshoku_imbuing": {
        "prompt_file": "haoshoku_imbuing_generator.pt-br.md",
        "tool_name": "emit_haoshoku_imbuing",
        "has_target_card_id": False,
    },
    "voice_of_all_things": {
        "prompt_file": "voice_of_all_things_generator.pt-br.md",
        "tool_name": "emit_voice_of_all_things",
        "has_target_card_id": False,
    },
    "advanced_armament": {
        "prompt_file": "advanced_armament_generator.pt-br.md",
        "tool_name": "emit_advanced_armament",
        "has_target_card_id": False,
    },
    "advanced_observation": {
        "prompt_file": "advanced_observation_generator.pt-br.md",
        "tool_name": "emit_advanced_observation",
        "has_target_card_id": False,
    },
}

MAX_TOKENS = 3000


def make_tool_schema(name: str, has_target_card_id: bool) -> dict:
    """Builds the tool schema: pre_emit_style_check (self-review gate, engine discards) +
    description + optional target_card_id (awakening/black_blade only)."""
    properties: dict = {
        "pre_emit_style_check": {
            "type": "object",
            "description": (
                "GATE OBRIGATORIO ANTES de commit. Re-leia o draft da description e marque "
                "cada item literal. 'ok' = draft passou. 'needs_rewrite' = vicio detectado, "
                "REESCREVA o draft inteiro antes de emitir. Marcar 'ok' com vicio presente nao "
                "trapaceia o audit programatico."
            ),
            "properties": {
                "avoided_contrastive_reveal": {
                    "type": "string",
                    "enum": ["ok", "needs_rewrite"],
                    "description": (
                        "Re-leia o draft. NAO contem estrutura 'nao X, e Y' / 'nao X. e Y.' / "
                        "'nao se trata de X, mas de Y' / 'nao X, mas Y' / 'nao pelo X, pelo Y'? "
                        "Esse padrao retorico de negar pra revelar e vicio gerativo IA. Se "
                        "aparece em QUALQUER frase, marque 'needs_rewrite' e reescreva afirmando "
                        "Z direto."
                    ),
                },
                "avoided_tell_words": {
                    "type": "string",
                    "enum": ["ok", "needs_rewrite"],
                    "description": (
                        "Re-leia o draft. NAO contem NENHUMA palavra-tell ('quase "
                        "imperceptivel', 'ressonante', 'ressoa', 'tapecaria', 'palpavel', "
                        "'vibrante', 'etereo', 'iridescente', 'caleidoscopico', 'meticuloso', "
                        "'deliberado', 'intricado', 'cuidadosamente', 'os olhos cintilaram')? "
                        "Se UMA aparece, marque 'needs_rewrite' e troque por formulacao concreta."
                    ),
                },
            },
            "required": ["avoided_contrastive_reveal", "avoided_tell_words"],
        },
        "description": {
            "type": "string",
            "description": (
                "Prosa contínua em PT-BR. 1-2 parágrafos (2-3 para Voice of All Things). "
                "Sem markdown, sem subseções, sem bullets, sem títulos. Segue voz do "
                "narrator_system_prompt §5.1 + anti-vícios §10. EMITIR APENAS APOS "
                "pre_emit_style_check confirmar 'ok' em ambos os subcampos."
            ),
        },
    }
    required = ["pre_emit_style_check", "description"]
    if has_target_card_id:
        properties["target_card_id"] = {
            "type": "string",
            "description": "UUID exato copiado do input (fruit_card.id ou item_card.id).",
        }
        required = ["pre_emit_style_check", "target_card_id", "description"]

    return {
        "name": name,
        "description": (
            "Emite a descricao canonica do breakthrough destravado. Chame UMA vez. Nenhum "
            "texto fora da tool. Preencha pre_emit_style_check ANTES de commitar description."
        ),
        "input_schema": {"type": "object", "properties": properties, "required": required},
    }


def _instructions(kind: str) -> str:
    cfg = PROMPT_CONFIG[kind]
    return (config.PROMPTS_DIR / cfg["prompt_file"]).read_text(encoding="utf-8")


# Input assembly per kind.
def _gen_player_snapshot(player_card: dict) -> dict:
    """Player snapshot in the shape the generators expect."""
    pc = player_card.get("player_character") or {}
    ps = player_card.get("player_snapshot") or {}
    cc = player_card.get("character_creation") or {}
    traits = []
    for t in cc.get("traits") or []:
        if isinstance(t, dict) and t.get("name"):
            traits.append({
                "name": t["name"],
                "rarity": t.get("rarity", ""),
                "description": t.get("description", ""),
            })
        elif isinstance(t, str) and t.strip():
            traits.append({"name": t.strip()})
    weapon = cc.get("weapon") or pc.get("weapon") or ""
    klass = cc.get("class_display") or pc.get("class", "")
    return {
        "name": pc.get("name", "") or player_card.get("name", ""),
        "tier": ps.get("tier") or pc.get("tier", ""),
        "class": klass,
        "traits": traits,
        "haki": ps.get("haki") or pc.get("haki", []),
        "current_goal": cc.get("dream") or pc.get("dream", ""),
        "primary_weapon_or_style": weapon or klass,
    }


def _fruit_card(player_card: dict, target_card_id: str | None) -> dict:
    """Player fruit card, best-effort from the JSON escape-hatch."""
    pc = player_card.get("player_character") or {}
    ps = player_card.get("player_snapshot") or {}
    cc = player_card.get("character_creation") or {}
    df = cc.get("devil_fruit") or {}
    name = df.get("name_jp") or ps.get("fruit") or pc.get("fruit") or ""
    return {
        "id": df.get("id") or target_card_id or "player_fruit",
        "name": name,
        "type": df.get("type", ""),
        "removal_hook": df.get("removal_hook"),
    }


def _item_card(player_card: dict, target_card_id: str | None) -> dict:
    """Player weapon card for the generator input; a cardified weapon matches via target_card_id."""
    pc = player_card.get("player_character") or {}
    cc = player_card.get("character_creation") or {}
    weapon = cc.get("weapon") or pc.get("weapon") or "a espada do jogador"
    return {
        "id": target_card_id or "player_weapon",
        "name": weapon,
        "subtype": "katana",
    }


def build_input(
    kind: str,
    player_card: dict,
    *,
    trigger_context: str,
    turn_index: int,
    target_card_id: str | None = None,
) -> dict:
    """Builds the generator input for the given kind."""
    base = {
        "player_snapshot": _gen_player_snapshot(player_card),
        "trigger_context": trigger_context,
        "current_turn_index": turn_index,
    }
    if kind == "fruit_awakening":
        ps = player_card.get("player_snapshot") or {}
        base["fruit_card"] = _fruit_card(player_card, target_card_id)
        base["fruit_usage_log"] = ps.get("fruit_usage_log") or []
        # Consolidated fighting_style is offered as awakening context; omitted before the first tier-up.
        if ps.get("fighting_style"):
            base["fighting_style"] = ps["fighting_style"]
    elif kind == "black_blade":
        base["item_card"] = _item_card(player_card, target_card_id)
    return base


def parse(emitted: dict | None) -> dict | None:
    """Discards pre_emit_style_check; requires non-empty description. Keeps target_card_id."""
    if not isinstance(emitted, dict):
        return None
    desc = emitted.get("description")
    if not isinstance(desc, str) or not desc.strip():
        return None
    out: dict = {"description": desc.strip()}
    if isinstance(emitted.get("target_card_id"), str) and emitted["target_card_id"].strip():
        out["target_card_id"] = emitted["target_card_id"].strip()
    return out


async def call_generate(kind: str, gen_input: dict, *, retries: int = 1) -> dict | None:
    """Runs the generator for the kind (Opus 4.8) and returns the parsed output."""
    cfg = PROMPT_CONFIG[kind]
    tool = make_tool_schema(cfg["tool_name"], cfg["has_target_card_id"])
    last_exc: Exception | None = None
    for _attempt in range(retries + 1):
        try:
            emitted = await client.call_tool(
                model=config.NARRATOR_MODEL,
                instructions=_instructions(kind),
                tag="breakthrough",
                sections=[("INPUT", gen_input)],
                volatile_instructions=language.output_directive(),
                tool=tool,
                tool_name=cfg["tool_name"],
                max_tokens=MAX_TOKENS,
                trace_label=f"Breakthrough · {kind}",
            )
            parsed = parse(emitted)
            if parsed is not None:
                return parsed
        except Exception as e:  # noqa: BLE001 retry covers truncation/parse
            last_exc = e
    if last_exc is not None:
        raise last_exc
    return None


def _apply_patch(player_card: dict, kind: str, description: str, target_card_id: str | None, turn_index: int) -> dict:
    """Applies the state patch to the player card (copy). Always writes description into the
    kind's breakthroughs[] entry; awakening/black_blade also patch the fruit/weapon."""
    data = dict(player_card)
    psnap = dict(data.get("player_snapshot") or {})

    brks = [dict(b) for b in (psnap.get("breakthroughs") or []) if isinstance(b, dict)]
    found = False
    for b in brks:
        if b.get("kind") == kind:
            b["description"] = description
            if target_card_id:
                b["target_card_id"] = target_card_id
            found = True
    if not found:
        # Fallback: apply_post_turn usually creates the entry; create it here if missing.
        entry = {"kind": kind, "unlocked_at_turn_index": turn_index, "description": description}
        if target_card_id:
            entry["target_card_id"] = target_card_id
        brks.append(entry)
    psnap["breakthroughs"] = brks

    if kind == "fruit_awakening":
        psnap["fruit_awakened"] = True
        psnap["fruit_awakening_description"] = description
        cc = data.get("character_creation")
        if isinstance(cc, dict) and isinstance(cc.get("devil_fruit"), dict):
            cc = dict(cc)
            df = dict(cc["devil_fruit"])
            df["awakened"] = True
            df["awakening_description"] = description
            df["awakening_unlocked_at_turn_index"] = turn_index
            cc["devil_fruit"] = df
            data["character_creation"] = cc
    elif kind == "black_blade":
        psnap["weapon_state"] = {
            "is_black_blade": True,
            "black_blade_description": description,
            "black_blade_unlocked_at_turn_index": turn_index,
        }

    data["player_snapshot"] = psnap
    return data


async def mirror_black_blade_to_card(
    conn, campaign_id: str, target_card_id: str | None, description: str, turn_index: int
) -> str | None:
    """Mirrors black_blade state into an ITEM card's current_state when the player weapon is
    cardified and target_card_id matches a story card. No-op (None) when the target is empty
    or unmatched."""
    if not target_card_id:
        return None
    card = await repo.get_card_by_entity_id(conn, campaign_id, target_card_id)
    if card is None:
        return None
    cdata = dict(card["data"])
    cstate = dict(cdata.get("current_state") or {})
    cstate["is_black_blade"] = True
    cstate["black_blade_description"] = description
    cstate["black_blade_unlocked_at_turn_index"] = turn_index
    cdata["current_state"] = cstate
    await repo.update_story_card(conn, card["id"], cdata)
    return target_card_id


async def run(conn, campaign_id: str, *, breakthrough_event: dict, turn_index: int) -> dict:
    """Orchestration: reloads the player card, runs the kind's generator, applies the patch,
    and persists. Best-effort: returns a report (with error/skipped if it does not run)."""
    kind = (breakthrough_event or {}).get("kind")
    if kind not in PROMPT_CONFIG:
        return {"skipped": f"kind desconhecido: {kind!r}"}
    player_sc = await repo.get_player_story_card(conn, campaign_id)
    if player_sc is None:
        return {"error": "player story card ausente"}
    player_card = player_sc["data"]
    target_card_id = breakthrough_event.get("target_card_id")

    gen_input = build_input(
        kind, player_card,
        trigger_context=breakthrough_event.get("trigger_context", ""),
        turn_index=turn_index, target_card_id=target_card_id,
    )
    parsed = await call_generate(kind, gen_input)
    if parsed is None:
        return {"kind": kind, "error": "sem output utilizável"}

    description = parsed["description"]
    out_target = parsed.get("target_card_id") or target_card_id
    new_data = _apply_patch(player_card, kind, description, out_target, turn_index)
    await repo.update_story_card(conn, player_sc["id"], new_data)

    # Black blade on a cardified weapon mirrors into that ITEM card's current_state.
    patched_card = None
    if kind == "black_blade":
        patched_card = await mirror_black_blade_to_card(
            conn, campaign_id, out_target, description, turn_index
        )

    report = {"kind": kind, "description_chars": len(description)}
    if patched_card:
        report["patched_card"] = patched_card
    return report
