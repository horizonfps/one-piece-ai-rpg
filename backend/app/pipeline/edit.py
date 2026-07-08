"""FASE 23: global edit mode (pure entity-edit functions).

Editing does not advance the turn and does not re-crystallize; it only persists, and the next turn
reconstructs from the edited state. Only pure mutations live here (defensive merge, field
whitelist); persistence is in the repositories called by the PATCH/DELETE endpoints. No I/O.
"""
from __future__ import annotations

from . import world_state as ws

# Full game ladder. Edits off-enum are ignored to avoid corrupting matchmaking.
TIERS = ("NORMAL", "SKILLED", "STRONG", "ELITE", "MONSTER", "TITAN", "WORLD", "ABSURD")
HULL_CONDITIONS = ("pristine", "scarred", "damaged", "broken")
KNOWLEDGE_TIERS = ("common", "regional", "specialized", "esoteric", "classified")
NARRATIVE_ARMORS = ("none", "crew_armor", "nemesis_armor", "canon_top_armor")
EXPRESSIVENESS = ("alto", "medio", "contido")
HAKI_TYPES = ("KENBUNSHOKU", "BUSOSHOKU", "HAOSHOKU")

# Top-level card fields editable from the UI (defensive whitelist).
_CARD_STR_FIELDS = (
    "name", "description", "status", "subtype", "current_goal", "mood", "long_term_dream",
    "base_backstory", "race", "class", "affiliation", "devil_fruit",
)
_CARD_LIST_FIELDS = ("aliases", "traits", "voice_notes", "notable_traits")
# Nested text blocks the Narrator rereads; each merges per known sub-field, leaving the rest intact.
_CARD_NESTED_FIELDS = {
    "appearance": ("build_and_age", "face_and_hair", "clothing", "distinctive_mark"),
    "personality": ("disposition", "shows_as"),
    "history": ("origin", "defining_event", "central_bond"),
}
_CARD_ENUM_FIELDS = {
    "expressiveness": EXPRESSIVENESS,
    "knowledge_clearance": KNOWLEDGE_TIERS,
    "knowledge_tier_to_know_exists": KNOWLEDGE_TIERS,
    "knowledge_tier_to_know_details": KNOWLEDGE_TIERS,
    "narrative_armor": NARRATIVE_ARMORS,
}

def merge_card_edit(card_data: dict, patch: dict) -> dict:
    """Merge an edit patch into a card (whitelist only; unknown keys ignored). The whole card is
    editable: text fields, the nested appearance/personality/history blocks, the mechanical enums
    (tier, knowledge, armor, expressiveness), alignment, haki and flags. Maps summary to
    current_state.summary_text, tier to top-level + current_state.tier, flags to current_state.flags.
    Off-enum and ill-typed values are ignored. Does not mutate the input."""
    out = dict(card_data)
    cs = dict(out.get("current_state") or {})

    for f in _CARD_STR_FIELDS:
        if f in patch and isinstance(patch[f], str):
            v = patch[f].strip() if f in ("name", "devil_fruit") else patch[f]
            out[f] = (v or None) if f == "devil_fruit" else v
    for f in _CARD_LIST_FIELDS:
        if f in patch and isinstance(patch[f], list):
            out[f] = [str(x).strip() for x in patch[f] if isinstance(x, str) and str(x).strip()]

    for parent, subfields in _CARD_NESTED_FIELDS.items():
        if isinstance(patch.get(parent), dict):
            sub = dict(out.get(parent) or {})
            for sf in subfields:
                if isinstance(patch[parent].get(sf), str):
                    sub[sf] = patch[parent][sf]
            out[parent] = sub

    for f, allowed in _CARD_ENUM_FIELDS.items():
        if patch.get(f) in allowed:
            out[f] = patch[f]

    if "alignment_baseline" in patch and patch["alignment_baseline"] is not None:
        try:
            out["alignment_baseline"] = max(-2.0, min(2.0, float(patch["alignment_baseline"])))
        except (TypeError, ValueError):
            pass
    if isinstance(patch.get("haki_profile"), list):
        out["haki_profile"] = [h for h in patch["haki_profile"] if h in HAKI_TYPES]

    if "age_at_creation" in patch:
        v = patch["age_at_creation"]
        if v is None:
            out["age_at_creation"] = None
        else:
            try:
                out["age_at_creation"] = max(0, int(v))
            except (TypeError, ValueError):
                pass

    if "summary" in patch and isinstance(patch["summary"], str):
        cs["summary_text"] = patch["summary"]
    if "tier" in patch and patch["tier"] in TIERS:
        out["tier"] = patch["tier"]
        cs["tier"] = patch["tier"]
    if "hull_condition" in patch and patch["hull_condition"] in HULL_CONDITIONS:
        cs["hull_condition"] = patch["hull_condition"]
    if isinstance(patch.get("flags"), list):
        cs["flags"] = [str(x).strip() for x in patch["flags"] if isinstance(x, str) and str(x).strip()]

    out["current_state"] = cs
    return out


def apply_player_edit(player_data: dict, patch: dict) -> dict:
    """Edit the player sheet. Mirrors each identity field across the three card faces
    (character_creation, player_character, top-level name). alignment_value goes to
    player_snapshot.alignment (clamp+bucket), belly to player_snapshot.belly, tier to
    snapshot+character+creation (validated). Does not mutate the input."""
    out = dict(player_data)
    snap = dict(out.get("player_snapshot") or {})
    char = dict(out.get("player_character") or {})
    cc = dict(out.get("character_creation") or {})

    if "alignment_value" in patch:
        try:
            snap["alignment"] = ws.make_alignment(float(patch["alignment_value"]))
        except (TypeError, ValueError):
            pass
    if "belly" in patch:
        try:
            snap["belly"] = max(0, int(patch["belly"]))
        except (TypeError, ValueError):
            pass
    if "tier" in patch and patch["tier"] in TIERS:
        snap["tier"] = patch["tier"]
        char["tier"] = patch["tier"]
        cc["tier_alvo"] = patch["tier"]

    name = patch.get("name")
    if isinstance(name, str) and name.strip():
        out["name"] = cc["name"] = char["name"] = name.strip()
    for f in ("dream", "weapon", "gender", "appearance"):
        if f in patch and isinstance(patch[f], str):
            cc[f] = patch[f].strip()
            if f in char:
                char[f] = patch[f].strip()

    out["player_snapshot"] = snap
    out["player_character"] = char
    out["character_creation"] = cc
    return out


def edit_technique(techniques: list, technique_id: str, patch: dict) -> tuple[list, dict | None]:
    """Edit name/description of the technique with technique_id. Returns (new_list, edited|None).
    Does not mutate the input."""
    out = [dict(t) for t in techniques if isinstance(t, dict)]
    edited = None
    for t in out:
        if t.get("id") == technique_id:
            name = patch.get("name")
            if isinstance(name, str) and name.strip():
                t["name"] = name.strip()
            if isinstance(patch.get("description"), str):
                t["description"] = patch["description"]
            edited = t
            break
    return out, edited


def remove_technique(techniques: list, technique_id: str) -> tuple[list, dict | None]:
    """Remove the technique with technique_id. Returns (new_list, removed|None)."""
    out: list = []
    removed = None
    for t in techniques:
        if isinstance(t, dict) and t.get("id") == technique_id and removed is None:
            removed = t
            continue
        out.append(t)
    return out, removed


# --- player breakthroughs + fruit_usage_log (FASE 11, edit mode) ---------------------
# Operate on the whole player_data: editing/removing an awakening or black_blade must mirror the
# derived fields the Narrator reads, or the edited sheet and the narration diverge.

def edit_breakthrough(player_data: dict, kind: str, patch: dict) -> tuple[dict, dict | None]:
    """Edit the description of the breakthrough entry for kind, mirroring the derived fields
    (fruit_awakening and black_blade descriptions). Returns (new_player_data, edited|None). Does
    not mutate the input."""
    out = dict(player_data)
    snap = dict(out.get("player_snapshot") or {})
    brks = [dict(b) for b in (snap.get("breakthroughs") or []) if isinstance(b, dict)]
    new_desc = patch.get("description")
    edited = None
    for b in brks:
        if b.get("kind") == kind:
            if isinstance(new_desc, str):
                b["description"] = new_desc
            edited = b
            break
    if edited is None:
        return out, None
    snap["breakthroughs"] = brks
    if isinstance(new_desc, str):
        if kind == "fruit_awakening":
            snap["fruit_awakening_description"] = new_desc
            cc = dict(out.get("character_creation") or {})
            if isinstance(cc.get("devil_fruit"), dict):
                df = dict(cc["devil_fruit"])
                df["awakening_description"] = new_desc
                cc["devil_fruit"] = df
                out["character_creation"] = cc
        elif kind == "black_blade":
            wst = dict(snap.get("weapon_state") or {})
            wst["black_blade_description"] = new_desc
            snap["weapon_state"] = wst
    out["player_snapshot"] = snap
    return out, edited


def remove_breakthrough(player_data: dict, kind: str) -> tuple[dict, dict | None]:
    """Remove the breakthrough entry for kind and clear the derived mirrors (the fruit/weapon
    itself persists). Returns (new_player_data, removed|None). Does not mutate the input."""
    out = dict(player_data)
    snap = dict(out.get("player_snapshot") or {})
    kept, removed = [], None
    for b in (snap.get("breakthroughs") or []):
        if isinstance(b, dict) and b.get("kind") == kind and removed is None:
            removed = b
            continue
        kept.append(b)
    if removed is None:
        return out, None
    snap["breakthroughs"] = kept
    if kind == "fruit_awakening":
        snap.pop("fruit_awakened", None)
        snap.pop("fruit_awakening_description", None)
        cc = dict(out.get("character_creation") or {})
        if isinstance(cc.get("devil_fruit"), dict):
            df = dict(cc["devil_fruit"])
            for k in ("awakened", "awakening_description", "awakening_unlocked_at_turn_index"):
                df.pop(k, None)
            cc["devil_fruit"] = df
            out["character_creation"] = cc
    elif kind == "black_blade":
        snap.pop("weapon_state", None)
    out["player_snapshot"] = snap
    return out, removed


def edit_fruit_usage(player_data: dict, index: int, patch: dict) -> tuple[dict, dict | None]:
    """Edit the usage_summary of the fruit_usage_log entry at index. Returns (new_player_data,
    edited|None). Out-of-range index returns None. Does not mutate the input."""
    out = dict(player_data)
    snap = dict(out.get("player_snapshot") or {})
    log = [dict(e) for e in (snap.get("fruit_usage_log") or []) if isinstance(e, dict)]
    if not 0 <= index < len(log):
        return out, None
    if isinstance(patch.get("usage_summary"), str):
        log[index]["usage_summary"] = patch["usage_summary"]
    snap["fruit_usage_log"] = log
    out["player_snapshot"] = snap
    return out, log[index]


def remove_fruit_usage(player_data: dict, index: int) -> tuple[dict, dict | None]:
    """Remove the fruit_usage_log entry at index. Returns (new_player_data, removed|None).
    Out-of-range index returns None. Does not mutate the input."""
    out = dict(player_data)
    snap = dict(out.get("player_snapshot") or {})
    log = [dict(e) for e in (snap.get("fruit_usage_log") or []) if isinstance(e, dict)]
    if not 0 <= index < len(log):
        return out, None
    removed = log.pop(index)
    snap["fruit_usage_log"] = log
    out["player_snapshot"] = snap
    return out, removed


# --- inventory (edit mode) -----------------------------------------------------------
# The entry (item_card_id, quantity, origin_note) lives in player_snapshot.inventory; the item's
# name/subtype/summary live in its ITEM story_card (edited via merge_card_edit by the caller).

def add_inventory_entry(player_data: dict, entry: dict) -> dict:
    """Append an inventory_entry to the player snapshot. Does not mutate the input."""
    out = dict(player_data)
    snap = dict(out.get("player_snapshot") or {})
    inv = [dict(e) for e in (snap.get("inventory") or []) if isinstance(e, dict)]
    inv.append(dict(entry))
    snap["inventory"] = inv
    out["player_snapshot"] = snap
    return out


def edit_inventory_entry(player_data: dict, item_card_id: str, patch: dict) -> tuple[dict, dict | None]:
    """Edit quantity/origin_note of the entry for item_card_id (quantity None clears the stack
    count, making the item unique). Returns (new_player_data, edited|None); None if absent. Does
    not mutate the input."""
    out = dict(player_data)
    snap = dict(out.get("player_snapshot") or {})
    inv = [dict(e) for e in (snap.get("inventory") or []) if isinstance(e, dict)]
    edited = None
    for e in inv:
        if e.get("item_card_id") == item_card_id:
            if "quantity" in patch:
                q = patch["quantity"]
                if q is None:
                    e.pop("quantity", None)
                else:
                    try:
                        e["quantity"] = max(0, int(q))
                    except (TypeError, ValueError):
                        pass
            if isinstance(patch.get("origin_note"), str):
                e["origin_note"] = patch["origin_note"].strip()
            edited = e
            break
    if edited is None:
        return out, None
    snap["inventory"] = inv
    out["player_snapshot"] = snap
    return out, edited


def remove_inventory_entry(player_data: dict, item_card_id: str) -> tuple[dict, dict | None]:
    """Remove the entry for item_card_id (the ITEM card itself persists in the acervo). Returns
    (new_player_data, removed|None); None if absent. Does not mutate the input."""
    out = dict(player_data)
    snap = dict(out.get("player_snapshot") or {})
    inv = [dict(e) for e in (snap.get("inventory") or []) if isinstance(e, dict)]
    kept, removed = [], None
    for e in inv:
        if e.get("item_card_id") == item_card_id and removed is None:
            removed = e
            continue
        kept.append(e)
    if removed is None:
        return out, None
    snap["inventory"] = kept
    out["player_snapshot"] = snap
    return out, removed


def list_techniques(player_snapshot: dict, npcs: dict) -> list[dict]:
    """Aggregate registered techniques (player + crew/nemesis) for the inspector, each with a
    resolved owner_name."""
    out: list[dict] = []
    for t in (player_snapshot.get("techniques") or []):
        if isinstance(t, dict) and t.get("id"):
            out.append({**t, "owner_name": "Você", "owner_kind": "player"})
    for aid, data in npcs.items():
        if not isinstance(data, dict):
            continue
        for t in (data.get("techniques") or []):
            if isinstance(t, dict) and t.get("id"):
                out.append({**t, "owner_name": data.get("name", aid), "owner_kind": "npc"})
    return out
