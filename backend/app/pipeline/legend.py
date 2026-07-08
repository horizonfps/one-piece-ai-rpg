"""Living legend: the public myth of the player and crewmates.

The Director writes it through the legend_update edit_primitive (epithet, public image,
poster portrait, wanted directive). State lives in metadata.legend_state keyed by target
card id; every update also snapshots into a history list that feeds the HUD poster
gallery. Reactions from past News Coo editions are exposed back to the Director as
germinable seeds (legend_repercussions). Everything here is bookkeeping: whether and when
the legend moves is always the Director's qualitative call.
"""
from __future__ import annotations

WANTED_STATUSES = ("none", "alive_only", "dead_or_alive")

# Payload truncation caps (size only, not curation of relevance).
_REACTION_SEED_EDITIONS = 3
_REACTION_SEED_CAP = 18


def legend_state_of(metadata: dict) -> dict:
    ls = metadata.get("legend_state")
    return ls if isinstance(ls, dict) else {}


def apply_legend_update(
    metadata: dict, p: dict, *, turn_index: int, target_name: str = ""
) -> dict | None:
    """Merge one legend_update primitive into metadata.legend_state (field patch; absent
    fields persist) + append the post-patch snapshot to the target's history. Returns the
    applied summary, or None when the payload carries no substance."""
    target = (p.get("card_id") or "").strip()
    epithet = (p.get("epithet") or "").strip()
    public_image = (p.get("public_image") or "").strip()
    divergence = (p.get("divergence_note") or "").strip()
    poster_note = (p.get("poster_note") or "").strip()
    wanted = p.get("wanted_status") if p.get("wanted_status") in WANTED_STATUSES else None
    if not target or not (epithet or public_image or divergence or poster_note or wanted):
        return None

    state = dict(legend_state_of(metadata))
    entry = dict(state.get(target) or {"target_card_id": target, "history": []})
    if target_name:
        entry["target_name"] = target_name
    if epithet:
        entry["epithet"] = epithet
    if public_image:
        entry["public_image"] = public_image
    if divergence:
        entry["divergence_note"] = divergence
    if poster_note:
        entry["poster_note"] = poster_note
    if wanted:
        entry["wanted_status"] = wanted
    entry.setdefault("wanted_status", "none")
    entry["updated_at_turn_index"] = turn_index

    hist = list(entry.get("history") or [])
    hist.append({
        "turn_index": turn_index,
        "epithet": entry.get("epithet"),
        "public_image": entry.get("public_image", ""),
        "divergence_note": entry.get("divergence_note"),
        "poster_note": entry.get("poster_note"),
        "wanted_status": entry["wanted_status"],
        "reason": (p.get("reason") or "").strip(),
    })
    entry["history"] = hist
    state[target] = entry
    metadata["legend_state"] = state
    return {
        "card_id": target,
        "epithet": entry.get("epithet"),
        "wanted_status": entry["wanted_status"],
    }


def apply_human_edit(metadata: dict, card_id: str, patch: dict, *, target_name: str = "") -> dict:
    """Direct HUD edit: fields present in the patch overwrite the current state (empty string
    clears the field); no history append. Creates the entry when absent."""
    state = dict(legend_state_of(metadata))
    entry = dict(state.get(card_id) or {"target_card_id": card_id, "history": []})
    if target_name and not entry.get("target_name"):
        entry["target_name"] = target_name
    for f in ("epithet", "public_image", "divergence_note", "poster_note"):
        if f in patch:
            v = (patch.get(f) or "").strip()
            if v:
                entry[f] = v
            else:
                entry.pop(f, None)
    if patch.get("wanted_status") in WANTED_STATUSES:
        entry["wanted_status"] = patch["wanted_status"]
    entry.setdefault("wanted_status", "none")
    state[card_id] = entry
    metadata["legend_state"] = state
    return entry


def remove_entry(metadata: dict, card_id: str) -> bool:
    state = dict(legend_state_of(metadata))
    if card_id not in state:
        return False
    state.pop(card_id)
    metadata["legend_state"] = state
    return True


def legend_brief(metadata: dict) -> list[dict]:
    """History-free shape for the Director briefings (PRE and POST)."""
    out = []
    for entry in legend_state_of(metadata).values():
        if not isinstance(entry, dict):
            continue
        out.append({
            "target_card_id": entry.get("target_card_id", ""),
            "target_name": entry.get("target_name", ""),
            "epithet": entry.get("epithet"),
            "public_image": entry.get("public_image", ""),
            "divergence_note": entry.get("divergence_note"),
            "poster_note": entry.get("poster_note"),
            "wanted_status": entry.get("wanted_status", "none"),
            "updated_at_turn_index": entry.get("updated_at_turn_index"),
        })
    out.sort(key=lambda e: e.get("updated_at_turn_index") or 0, reverse=True)
    return out


def player_public_view(metadata: dict, player_id: str) -> dict | None:
    """What the poster and word of mouth say about the player. Feeds the mind snapshot
    of on-scene NPCs with no bond: they react to the myth, not the person."""
    entry = legend_state_of(metadata).get(player_id)
    if not isinstance(entry, dict):
        return None
    view = {
        "epithet": entry.get("epithet"),
        "public_image": entry.get("public_image", ""),
        "poster_note": entry.get("poster_note"),
        "wanted_status": entry.get("wanted_status", "none"),
    }
    return view if (view["epithet"] or view["public_image"] or view["poster_note"]) else None


def reaction_seeds(metadata: dict, *, editions: int = _REACTION_SEED_EDITIONS) -> list[dict]:
    """Named reactions from the latest News Coo editions, newest first. They are seeds the
    Director MAY germinate into scenes/hooks through the normal channels; no quota, no timer."""
    all_editions = [e for e in (metadata.get("news_editions") or []) if isinstance(e, dict)]
    seeds = []
    for ed in reversed(all_editions[-editions:]):
        for r in ed.get("reactions") or []:
            if not isinstance(r, dict) or not (r.get("name") or "").strip():
                continue
            seeds.append({
                "name": r["name"].strip(),
                "note": (r.get("note") or "").strip(),
                "edition_headline": ed.get("headline", ""),
                "published_at_turn_index": ed.get("published_at_turn_index"),
            })
    return seeds[:_REACTION_SEED_CAP]
