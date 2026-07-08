"""Custom Techniques registry; pure functions. The Narrator emits `techniques_used[]`
inline and the engine upserts by `(owner_id, name)`: player into player_snapshot,
crew/nemesis into the card, other NPCs ignored.

The Narrator emits `owner_id` as a NAME (player placeholder or NPC name/alias), not the
card id; `resolve_owner_id` translates name to id before `classify_owner`."""
from __future__ import annotations

import uuid


def resolve_owner_id(
    token: str | None,
    *,
    player_id: str,
    player_names=None,
    npcs: dict,
) -> str | None:
    """Reconcile the Narrator's `owner_id` (a name) with the canonical registry id. Returns
    `player_id` for the player name/placeholder/literal, the card id for an NPC name/alias,
    the token unchanged if already a known id, else the raw token (classify_owner drops it).
    `player_names` is the lowercased set of accepted player names/placeholders."""
    if not isinstance(token, str):
        return token
    tok = token.strip()
    if not tok:
        return token
    low = tok.lower()
    if tok == player_id or tok in npcs:
        return tok
    if low == "player" or (player_names and low in player_names):
        return player_id
    for cid, data in npcs.items():
        if not isinstance(data, dict):
            continue
        if (data.get("name") or "").strip().lower() == low:
            return cid
        for a in data.get("aliases") or []:
            if isinstance(a, str) and a.strip().lower() == low:
                return cid
    return token


def classify_owner(owner_id: str | None, player_id: str, npcs: dict) -> str | None:
    """Where the technique lives: `"player"` (player id/placeholder), `"npc"` (any NPC with a
    card), or `None` (unresolved token / no card). The Narrator already curated by naming the
    move and its owner; a technique of any carded NPC is persisted on that NPC's card."""
    if not owner_id:
        return None
    if owner_id == player_id or owner_id == "player":
        return "player"
    if isinstance(npcs.get(owner_id), dict):
        return "npc"
    return None


def upsert(
    techniques: list,
    name: str,
    *,
    owner_id: str,
    turn_index: int,
    description: str = "",
    fruit_id: str | None = None,
) -> tuple[list, dict | None]:
    """Case-insensitive upsert by `(owner_id, name)`. Returns `(new_list, new_entry_or_None)`;
    the entry is non-None only when the pair is new. Does not mutate the input list."""
    name = (name or "").strip()
    out = [dict(t) for t in techniques if isinstance(t, dict)]
    if not name:
        return out, None
    key = name.lower()
    for t in out:
        if (t.get("name") or "").strip().lower() == key:
            t["usage_count"] = int(t.get("usage_count", 1) or 1) + 1
            # backfill description if the old entry lacked one
            if description and not (t.get("description") or "").strip():
                t["description"] = description.strip()
            return out, None
    entry = {
        "id": uuid.uuid4().hex[:12],
        "name": name,
        "owner_id": owner_id,
        "description": (description or "").strip(),
        "first_used_turn_index": turn_index,
        "usage_count": 1,
    }
    if fruit_id:
        entry["fruit_id"] = fruit_id
    out.append(entry)
    return out, entry


def register_from_turn_meta(
    techniques_used: list,
    *,
    player_id: str,
    player_techniques: list,
    npcs: dict,
    turn_index: int,
    player_names=None,
) -> dict:
    """Process `techniques_used[]` in one pass, returning `{player_techniques, npc_updates,
    registered, ignored}`. Pure; `post_turn` persists. `registered` are this turn's new pairs."""
    player_techs = [dict(t) for t in (player_techniques or []) if isinstance(t, dict)]
    npc_cur: dict[str, list] = {}
    registered: list[dict] = []
    ignored: list[dict] = []

    for raw in techniques_used or []:
        if not isinstance(raw, dict):
            continue
        name = (raw.get("name") or "").strip()
        owner_token = raw.get("owner_id")
        desc = raw.get("description") or ""
        if not name:
            continue
        owner_id = resolve_owner_id(
            owner_token, player_id=player_id, player_names=player_names, npcs=npcs
        )
        kind = classify_owner(owner_id, player_id, npcs)
        if kind == "player":
            player_techs, new = upsert(
                player_techs, name, owner_id=player_id, turn_index=turn_index, description=desc
            )
        elif kind == "npc":
            base = npc_cur.get(owner_id)
            if base is None:
                base = list((npcs.get(owner_id) or {}).get("techniques") or [])
            base, new = upsert(
                base, name, owner_id=owner_id, turn_index=turn_index, description=desc
            )
            npc_cur[owner_id] = base
        else:
            ignored.append({"name": name, "owner_id": owner_token, "why": "owner fora do escopo (player/crew/nemesis)"})
            continue
        if new is not None:
            registered.append({"name": name, "owner_id": new["owner_id"]})

    return {
        "player_techniques": player_techs,
        "npc_updates": npc_cur,
        "registered": registered,
        "ignored": ignored,
    }
