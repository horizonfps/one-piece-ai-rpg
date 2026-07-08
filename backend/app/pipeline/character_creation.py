"""Pure character creation: roller, validation, sheet assembly. No I/O, no LLM; the roller
is deterministic given a random.Random. Sheet is fixed at age 17 (decided settings); target
tier caps at STRONG."""
from __future__ import annotations

import random

from . import world_state

# Target tier at 17, cap STRONG. Higher tiers only via in-game progression.
TIERS = ("NORMAL", "SKILLED", "STRONG")

# Mutual-exclusion group: only the Haki Geniuses share it; player never stacks two.
GENIO_HAKI = "genio_haki"

FRUIT_USER_CLASS_ID = "fruit-user"

# Fixed sheet locks (not from the menu).
LOCKED_AGE = 17
LOCKED_RACE = "Humano"
LOCKED_FAMILY = "unknown"


# roller
def roll_count(rng: random.Random) -> int:
    """1d4+1 = 2-5 traits."""
    return rng.randint(1, 4) + 1


def _is_genio(trait: dict) -> bool:
    return trait.get("stacking_exclusion") == GENIO_HAKI


def roll_traits(
    traits: list[dict], rng: random.Random, *, count: int | None = None
) -> list[dict]:
    """Draws `count` (default 1d4+1) traits without replacement from the whole catalog.
    Stacking-exclusion: at most one Haki Genius; a second is discarded and replaced by a
    non-conflicting positive trait."""
    n = roll_count(rng) if count is None else max(0, count)
    order = traits[:]
    rng.shuffle(order)

    hand: list[dict] = []
    chosen_ids: set[str] = set()
    has_genio = False

    for trait in order:
        if len(hand) >= n:
            break
        if trait["id"] in chosen_ids:
            continue
        if _is_genio(trait) and has_genio:
            # Second Genius: discard and draw a positive replacement.
            chosen_ids.add(trait["id"])
            sub = _draw_replacement_positive(order, chosen_ids)
            if sub is not None:
                chosen_ids.add(sub["id"])
                hand.append(sub)
            continue
        chosen_ids.add(trait["id"])
        hand.append(trait)
        if _is_genio(trait):
            has_genio = True
    return hand


def _draw_replacement_positive(order: list[dict], chosen_ids: set[str]) -> dict | None:
    """First unchosen non-Genius positive trait in the shuffled order (deterministic)."""
    for trait in order:
        if trait["id"] in chosen_ids:
            continue
        if trait["polarity"] != "positive":
            continue
        if _is_genio(trait):  # a Genius is already in hand here
            continue
        return trait
    return None


# validation
def validate_sheet(
    sheet: dict, traits: list[dict], classes: list[dict], fruits: list[dict]
) -> list[str]:
    """Validates the sheet against catalogs and locks. Returns the error list ([] = valid)."""
    errors: list[str] = []
    trait_ids = {t["id"] for t in traits}
    trait_by_id = {t["id"]: t for t in traits}
    class_ids = {c["id"] for c in classes}
    fruit_ids = {f["id"] for f in fruits}

    name = (sheet.get("name") or "").strip()
    if not name:
        errors.append("nome obrigatório")

    tier = sheet.get("tier_alvo")
    if tier not in TIERS:
        errors.append(f"tier_alvo inválido: {tier!r} (esperado um de {TIERS})")

    class_id = sheet.get("class_id")
    if class_id not in class_ids:
        errors.append(f"class_id inválido: {class_id!r}")

    chosen_traits = sheet.get("trait_ids") or []
    if not isinstance(chosen_traits, list):
        errors.append("trait_ids deve ser lista")
        chosen_traits = []
    if len(chosen_traits) != len(set(chosen_traits)):
        errors.append("trait_ids com duplicata")
    unknown = [t for t in chosen_traits if t not in trait_ids]
    if unknown:
        errors.append(f"trait_ids desconhecidos: {unknown}")
    genios = [t for t in chosen_traits if t in trait_by_id and _is_genio(trait_by_id[t])]
    if len(genios) > 1:
        errors.append(f"mais de um Gênio do Haki (stacking-exclusion): {genios}")

    fruit_id = sheet.get("devil_fruit_id")
    if fruit_id is not None and fruit_id not in fruit_ids:
        errors.append(f"devil_fruit_id inválido: {fruit_id!r}")

    # Fruit User requires a chosen fruit.
    if class_id == FRUIT_USER_CLASS_ID and not fruit_id:
        errors.append("classe Fruit User exige uma Fruta do Diabo escolhida")

    return errors


# sheet assembly
def build_player_card(
    sheet: dict,
    traits: list[dict],
    classes: list[dict],
    fruits: list[dict],
    *,
    current_arc: str | None = None,
) -> dict:
    """Builds the kind=player card data from the validated sheet: the editable creation sheet
    (source of truth) plus the derived player_character/player_snapshot contracts."""
    trait_by_id = {t["id"]: t for t in traits}
    class_by_id = {c["id"]: c for c in classes}
    fruit_by_id = {f["id"]: f for f in fruits}

    name = (sheet.get("name") or "").strip()
    tier = sheet.get("tier_alvo")
    class_id = sheet.get("class_id")
    class_def = class_by_id.get(class_id) or {}
    chosen_traits = [trait_by_id[t] for t in (sheet.get("trait_ids") or []) if t in trait_by_id]

    fruit_id = sheet.get("devil_fruit_id")
    fruit_def = fruit_by_id.get(fruit_id) if fruit_id else None
    fruit_name = fruit_def["name_jp"] if fruit_def else None
    removal_hook = fruit_def.get("removal_hook") if fruit_def else None

    sub_focus = (sheet.get("sub_focus") or "").strip() or None
    dream = (sheet.get("dream") or "").strip()
    gender = (sheet.get("gender") or "").strip()
    weapon = (sheet.get("weapon") or "").strip()
    appearance = (sheet.get("appearance") or "").strip()

    class_name = class_def.get("name", class_id or "")
    if sub_focus and class_name:
        class_display = f"{class_name}: {sub_focus}"
    else:
        class_display = class_name

    devil_fruit = None
    if fruit_def is not None:
        devil_fruit = {
            "id": fruit_def["id"],
            "name_jp": fruit_def["name_jp"],
            "name_pt": fruit_def.get("name_pt"),
            "type": fruit_def["type"],
            "removal_hook": removal_hook,
        }

    # Creation sheet: editable source of truth.
    character_creation = {
        "name": name,
        "gender": gender,
        "appearance": appearance,
        "weapon": weapon,
        "tier_alvo": tier,
        "class_id": class_id,
        "class_name": class_name,
        "class_display": class_display,
        "sub_focus": sub_focus,
        "traits": chosen_traits,
        "devil_fruit": devil_fruit,
        "dream": dream,
        # fixed locks
        "race": LOCKED_RACE,
        "age": LOCKED_AGE,
        "bounty": 0,
        "alignment": 0,
        "family_backstory": LOCKED_FAMILY,
        "starting_loadout": class_def.get("starting_loadout", []),
        "starting_techniques": class_def.get("starting_techniques", []),
    }

    loadout = list(class_def.get("starting_loadout", []))
    if weapon:
        loadout = [weapon, *loadout]
    inventory_summary = "; ".join(loadout)

    visible_state = _visible_state(name, tier, class_display, fruit_def, appearance)

    # Contract consumed by the Narrator/Director (mirrors the seed shape).
    player_character = {
        "name": name,
        "gender": gender,
        "appearance": appearance,
        "race": LOCKED_RACE,
        "age": LOCKED_AGE,
        "tier": tier,
        "class": class_display,
        "weapon": weapon,
        "fruit": fruit_name,
        "haki": [],  # Haki unlocks in-game, never at setup
        "dream": dream,
        "inventory_summary": inventory_summary,
        "visible_state": visible_state,
    }

    # Post-turn contract: bounty/alignment/breakthroughs.
    player_snapshot = {
        "tier": tier,
        "bounty": {"current_amount": 0, "scheduled_day": None, "history": []},
        "alignment": world_state.make_alignment(0.0),
        "breakthroughs": [],
        "fruit": fruit_name,
        "haki": [],
        "current_arc": current_arc,
        "player_visible_state": visible_state,
        "player_public_facts": [],
    }

    card = {
        "id": "player",
        "name": name,
        "character_creation": character_creation,
        "player_character": player_character,
        "player_snapshot": player_snapshot,
        "crew_snapshot": {"size": 0, "members": [], "missing_roles_hint": []},
    }
    if removal_hook:
        # Pick-conditional alt-canon: one hook per campaign. The previous owner is born without
        # the fruit when later generated as an NPC; owner matches that NPC at runtime.
        card["removal_hook"] = removal_hook
        card["removal_hook_fruit"] = fruit_name
        card["removal_hook_owner"] = fruit_def.get("canon_owner")
    return card


def _visible_state(
    name: str, tier: str, class_display: str, fruit_def: dict | None, appearance: str = ""
) -> str:
    """Factual visible_state: the player's own appearance leads, mechanical tags (class/fruit)
    complement. No fabricated narrative framing — the world/Director sets the context, not a
    hardcoded 'leaving home for the first time'."""
    parts: list[str] = []
    appearance = (appearance or "").strip()
    if appearance:
        parts.append(appearance.rstrip(".;,"))
    if class_display:
        parts.append(class_display.lower())
    if fruit_def is not None:
        parts.append(f"usuário da {fruit_def['name_jp']}")
    return ", ".join(parts) if parts else name
