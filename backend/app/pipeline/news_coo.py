"""News Coo: organic newspaper signals + edition registry.

The Director decides ORGANICALLY (PRE-turn) when a paper arrives — only when there is real news
(player bounty jump/milestone, major world event, important change to a bonded NPC). The Narrator
stages the delivery inline (the bird drops the paper, the player reads the cover, cuts to distant
NPCs reacting) and reports the edition via turn_meta.news_coo_edition; the engine registers it in
metadata.news_editions[] (the Jornal tab is a read-only archive).

This module no longer composes prose. It provides news_signals for the Director's decision, the
reaction-candidate roster for the Narrator (news_coo_incoming), and the edition record builder.
settle_day_advance keeps feeding metadata.news_pool (bounty_updates with raw old/new amounts),
the material the signals read; the Director judges the bounty jump from those amounts.
"""
from __future__ import annotations

import uuid

# Payload size cap for the reaction roster (truncation only, not curation of newsworthiness).
_ROSTER_TRUNCATE = 24


# --------------------------------------------------------------------------------------
# Relationship + NPC selection (reaction candidates for the Narrator)
# --------------------------------------------------------------------------------------
def player_relationship(card: dict, player_id: str = "player") -> dict | None:
    """Card's relationship with the player, tolerant of the key (real id or 'player')."""
    rels = card.get("relationships") or {}
    rel = rels.get(player_id)
    if not isinstance(rel, dict):
        rel = rels.get("player")
    return rel if isinstance(rel, dict) else None


def _is_crew(card: dict) -> bool:
    return card.get("affiliation") == "player_crew"


def _unreached_important_offscene(card: dict) -> dict | None:
    """Most recent important off_scene entry the player has not yet reached in person. An
    important on_scene entry at a later turn means the change was already reached; earlier
    on_scene entries about other events no longer mask an unreached off_scene change."""
    log = [e for e in (card.get("personal_event_log") or []) if isinstance(e, dict) and e.get("important")]
    off = [e for e in log if e.get("scene_mode") == "off_scene"]
    if not off:
        return None
    entry = max(off, key=lambda e: int(e.get("turn_index", 0) or 0))
    entry_turn = int(entry.get("turn_index", 0) or 0)
    reached = any(
        e.get("scene_mode") == "on_scene" and int(e.get("turn_index", 0) or 0) > entry_turn
        for e in log
    )
    return None if reached else entry


def select_cover_story_npcs(npcs: dict, *, present_npc_ids: set | None = None) -> list[dict]:
    """Persistent NPCs (non-crew, alive, not in the player's scene) whose last important change was
    off_scene (not yet reached in person). No recency window, rank or hard cap; recency only orders
    the list for size truncation. The Narrator chooses who makes the cover."""
    present = present_npc_ids or set()
    candidates = []
    for card in npcs.values():
        if _is_crew(card) or card.get("status", "alive") != "alive":
            continue
        if card.get("id") in present:
            continue
        entry = _unreached_important_offscene(card)
        if not entry:
            continue
        candidates.append((int(entry.get("turn_index", 0)), card, entry))
    candidates.sort(key=lambda t: t[0], reverse=True)
    return [{"card": c, "trigger_entry": e} for _w, c, e in candidates]


def select_cutaway_npcs(npcs: dict, *, player_id: str) -> list[dict]:
    """Reaction candidate pool: every alive NPC that HAS a real bond with the player (presence of
    a bond is a mechanical fact, not a score). No curated list, threshold or hard cap; the Narrator
    picks who reacts and knows the canon anchors (Garp/Makino/...) from the cards on its own."""
    out = []
    for card in npcs.values():
        if card.get("status", "alive") != "alive":
            continue
        rel = player_relationship(card, player_id)
        if not isinstance(rel, dict):
            continue
        knows = rel.get("what_npc_knows_about_player") or rel.get("what_they_know_about_other") or []
        has_bond = (
            bool(knows)
            or float(rel.get("bond_tier", 0) or 0) > 0
            or float(rel.get("affinity", 0.0) or 0.0) != 0.0
        )
        if has_bond:
            out.append(card)
    return out


# --------------------------------------------------------------------------------------
# news_signals: the Director's PRE-turn view of pending newsworthy material
# --------------------------------------------------------------------------------------
def _player_bounty(psnap: dict) -> int:
    b = psnap.get("bounty", 0)
    return int(b.get("current_amount", 0) or 0) if isinstance(b, dict) else int(b or 0)


def _bounty_updates_by_kind(news_pool: dict, kind: str) -> list[dict]:
    return [
        b for b in (news_pool.get("bounty_updates") or [])
        if isinstance(b, dict) and b.get("char_kind") == kind
    ]


def _unpublished_events(metadata: dict) -> list[dict]:
    """Every not-yet-published background event with its raw magnitude. The Director/Narrator
    judges the weight; no magnitude whitelist pre-filters what counts as news."""
    out = []
    for e in metadata.get("events_background") or []:
        if not isinstance(e, dict) or e.get("published_in_news"):
            continue
        out.append({
            "id": e.get("id", ""),
            "summary": e.get("summary", ""),
            "magnitude": e.get("magnitude", ""),
            "scope": e.get("scope", ""),
            "location": e.get("location", ""),
        })
    return out


def build_news_signals(metadata: dict, current_turn_index: int) -> dict:
    """PRE-turn newsworthiness material for the Director. Raw signals only: the Director's
    news_coo_decision carries the judgment of what has real weight (no pre-computed gate)."""
    news_pool = metadata.get("news_pool") or {}
    last_news_turn = int(news_pool.get("last_news_turn", 0) or 0)
    return {
        "player_bounty_updates": _bounty_updates_by_kind(news_pool, "player"),
        "crew_bounty_updates": _bounty_updates_by_kind(news_pool, "crewmate"),
        "major_unpublished_events": _unpublished_events(metadata),
        "turns_since_last_edition": max(0, current_turn_index - last_news_turn),
    }


# --------------------------------------------------------------------------------------
# news_coo_incoming: material handed to the Narrator to stage the delivery
# --------------------------------------------------------------------------------------
def _reaction_candidate(card: dict, player_id: str, reason: str) -> dict:
    rel = player_relationship(card, player_id) or {}
    knows = rel.get("what_npc_knows_about_player") or rel.get("what_they_know_about_other") or []
    return {
        "name": card.get("name", ""),
        "current_location": card.get("current_location", ""),
        "affiliation": card.get("affiliation", ""),
        "affinity": rel.get("affinity"),
        "bond_tier": rel.get("bond_tier"),
        "what_they_know_about_player": list(knows)[:2],
        "why_candidate": reason,
    }


def build_news_incoming(
    arrival: dict, *, metadata: dict, npcs: dict, player_card: dict, current_turn: int
) -> dict:
    """Material the Narrator stages inline: the Director's seed, what is on the cover (pool), and a
    SUGGESTED roster of distant NPCs who could react. The Narrator chooses freely and may add
    others from the world."""
    player_id = player_card.get("id") or "player"
    psnap = player_card.get("player_snapshot") or {}
    pc = player_card.get("player_character") or {}
    news_pool = metadata.get("news_pool") or {}
    present_ids = set(metadata.get("present_npc_ids") or [])

    # Single deduped roster, truncated only by payload size (no rank/cap curation). The Narrator
    # chooses who reacts and may add any world figure that fits the canon.
    candidates: list[dict] = []
    seen: set = set()
    for card in select_cutaway_npcs(npcs, player_id=player_id):
        cid = card.get("id")
        if cid in seen:
            continue
        seen.add(cid)
        candidates.append(_reaction_candidate(card, player_id, "bonded"))
    for spec in select_cover_story_npcs(npcs, present_npc_ids=present_ids):
        card = spec["card"]
        cid = card.get("id")
        if cid in seen:
            continue
        seen.add(cid)
        candidates.append(_reaction_candidate(card, player_id, "recent_offscreen_change"))

    return {
        "trigger_reason": arrival.get("trigger_reason", ""),
        "headline_seed": arrival.get("headline_seed", ""),
        "cover_focus": arrival.get("cover_focus", ""),
        "context_memo": arrival.get("context_memo", ""),
        "player": {"name": pc.get("name", ""), "current_bounty": _player_bounty(psnap)},
        "pool": {
            "player_bounty_updates": _bounty_updates_by_kind(news_pool, "player"),
            "crew_bounty_updates": _bounty_updates_by_kind(news_pool, "crewmate"),
            "major_events": _unpublished_events(metadata),
        },
        "reaction_candidates": candidates[:_ROSTER_TRUNCATE],
    }


# --------------------------------------------------------------------------------------
# Edition record built from the Narrator's turn_meta.news_coo_edition for the Jornal tab
# --------------------------------------------------------------------------------------
def _edition_markdown(headline: str, cover: str, reactions: list[dict]) -> str:
    lines = [f"# {headline}"] if headline else []
    if cover:
        lines.append(cover)
    if reactions:
        lines.append("## Repercussão pelo mundo")
        for r in reactions:
            nm = (r.get("name") or "").strip()
            note = (r.get("note") or "").strip()
            if not nm:
                continue
            lines.append(f"- **{nm}** — {note}" if note else f"- **{nm}**")
    return "\n\n".join(lines)


def build_edition_record(edition_in: dict, *, campaign_day: int, turn_index: int) -> dict:
    """Build the news_editions[] record from turn_meta.news_coo_edition. Carries a short markdown
    the Jornal tab renders with the existing parser (the prose already happened in the turn)."""
    headline = (edition_in.get("headline") or "").strip()
    cover = (edition_in.get("cover_summary") or "").strip()
    reactions = [
        {"name": (r.get("name") or "").strip(), "note": (r.get("note") or "").strip()}
        for r in (edition_in.get("reactions") or [])
        if isinstance(r, dict) and (r.get("name") or "").strip()
    ]
    subject = (edition_in.get("primary_subject") or "").strip()
    return {
        "id": uuid.uuid4().hex[:12],
        "scheduled_day": int(campaign_day),
        "published_at_turn_index": int(turn_index),
        "headline": headline,
        "lead": cover,
        "player_in_cover": bool(edition_in.get("player_in_cover")),
        "primary_subject": subject,
        "reactions": reactions,
        "markdown": _edition_markdown(headline, cover, reactions),
        "counts": {"reactions": len(reactions)},
    }
