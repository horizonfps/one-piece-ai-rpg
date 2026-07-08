"""Crew alliances and non-Marine bounty hunters: pure functions, no I/O, no LLM.

1. Formal/informal alliances between the player crew (crew_a) and another crew (crew_b).
   Born and broken only by an explicit narrated event; no time or alignment drift. State
   in metadata.crew_alliances[] (JSON escape-hatch, no migration).
2. Opportunistic bounty hunters (non-persistent): the Director emits appearance events
   when bounty+chaos rise; the engine spawns the NPCs and keeps a light log for
   anti-saturation. Loot reuses existing channels.
"""
from __future__ import annotations

from . import language

# enums mirroring the addenda + harness schema.
FORMALITIES = ("informal", "formal")
HIERARCHIES = ("peer", "subordinate", "sovereign")
BROKEN_REASONS = ("traição", "conflito", "morte_capitão", "renúncia", "outro")

# Player crew is always crew_a by convention.
PLAYER_CREW_ID = "player_crew"

# Hunter is independent by default; guild when the archetype points at an organization.
BOUNTY_HUNTER_INDEPENDENT = "bounty_hunter_independent"
BOUNTY_HUNTER_GUILD_PREFIX = "bounty_hunter_guild"
# Recent-encounters window exposed to the Director for anti-saturation.
RECENT_BH_WINDOW = 6


# Crew alliances.
def crew_alliances_of(metadata: dict | None) -> list[dict]:
    """Reads metadata.crew_alliances[] in a normalized shape (default []). Tolerates
    absence/garbage; a player with no alliances is the common case."""
    raw = (metadata or {}).get("crew_alliances")
    if not isinstance(raw, list):
        return []
    return [a for a in raw if isinstance(a, dict) and a.get("crew_b_id")]


def make_alliance_entry(
    crew_b_id: str, *, formality, hierarchy, origin_note: str, turn_index: int
) -> dict:
    """Canonical crew_alliances[] entry. crew_a is always the player crew; out-of-enum
    formality/hierarchy fall back to the default."""
    f = formality if formality in FORMALITIES else "informal"
    h = hierarchy if hierarchy in HIERARCHIES else "peer"
    return {
        "crew_a_id": PLAYER_CREW_ID,
        "crew_b_id": crew_b_id,
        "formed_at_turn_index": int(turn_index),
        "formality": f,
        "hierarchy": h,
        "origin_note": (origin_note or "").strip(),
    }


def apply_alliance_events(
    crew_alliances: list[dict] | None,
    events: list[dict] | None,
    *,
    turn_index: int,
    valid_crew_b_ids: set | None = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Applies crew_alliance_events[] to the alliance list (fresh copy). Returns
    (new_list, applied[], rejected[]).

    alliance_formed: crew_b_id must be in valid_crew_b_ids or it is rejected (anti-invention);
    an existing alliance is updated in place. alliance_broken: removes the alliance;
    rejected when none is active."""
    out = [dict(a) for a in crew_alliances_of({"crew_alliances": crew_alliances})]
    valid = valid_crew_b_ids or set()
    applied: list[dict] = []
    rejected: list[dict] = []
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        kind = ev.get("kind")
        cb = (ev.get("crew_b_id") or "").strip()
        if not cb:
            rejected.append({"event": ev, "why": "crew_alliance_event sem crew_b_id"})
            continue
        if kind == "alliance_formed":
            if cb not in valid:
                rejected.append({"event": ev, "why": "alliance_formed.crew_b_id sem card FACTION nem agrupamento de NPC"})
                continue
            entry = make_alliance_entry(
                cb, formality=ev.get("formality"), hierarchy=ev.get("hierarchy"),
                origin_note=ev.get("origin_note", ""), turn_index=turn_index,
            )
            existing = next((a for a in out if a.get("crew_b_id") == cb), None)
            if existing is not None:
                existing["formality"] = entry["formality"]
                existing["hierarchy"] = entry["hierarchy"]
                existing["origin_note"] = entry["origin_note"]
                applied.append({"kind": "alliance_formed", "crew_b_id": cb, "updated": True,
                                "formality": entry["formality"], "hierarchy": entry["hierarchy"]})
            else:
                out.append(entry)
                applied.append({"kind": "alliance_formed", "crew_b_id": cb,
                                "formality": entry["formality"], "hierarchy": entry["hierarchy"]})
        elif kind == "alliance_broken":
            before = len(out)
            out = [a for a in out if a.get("crew_b_id") != cb]
            if len(out) < before:
                reason = ev.get("reason") if ev.get("reason") in BROKEN_REASONS else "outro"
                applied.append({"kind": "alliance_broken", "crew_b_id": cb, "reason": reason})
            else:
                rejected.append({"event": ev, "why": "alliance_broken sem aliança vigente com crew_b_id"})
        else:
            rejected.append({"event": ev, "why": f"crew_alliance_event kind inválido: {kind}"})
    return out, applied, rejected


def crew_b_display_name(crew_b_id: str, faction_cards: dict | None, npcs: dict | None) -> str:
    """Display name of the allied crew, resolved from FACTION card, matching NPC,
    captain of a matching affiliation grouping, or the id itself."""
    fc = (faction_cards or {}).get(crew_b_id)
    if isinstance(fc, dict) and fc.get("name"):
        return fc["name"]
    by_id = (npcs or {}).get(crew_b_id)
    if isinstance(by_id, dict) and by_id.get("name"):
        return by_id["name"]
    for d in (npcs or {}).values():
        if isinstance(d, dict) and d.get("affiliation") == crew_b_id and d.get("name"):
            return d["name"]
    return crew_b_id


def narrator_alliance_summary(
    crew_alliances: list[dict] | None,
    faction_cards: dict | None = None,
    npcs: dict | None = None,
) -> list[dict]:
    """active_crew_alliances[] for the narrator turn_state and Director briefing: all active
    alliances, unprioritized."""
    out: list[dict] = []
    for a in crew_alliances_of({"crew_alliances": crew_alliances}):
        cb = a.get("crew_b_id")
        out.append({
            "crew_b_id": cb,
            "crew_b_display_name": crew_b_display_name(cb, faction_cards, npcs),
            "formality": a.get("formality", "informal"),
            "hierarchy": a.get("hierarchy", "peer"),
            "origin_note": a.get("origin_note", ""),
        })
    return out


def alliance_signal_for_npc(
    npc: dict | None,
    crew_alliances: list[dict] | None,
    *,
    faction_card_ids: set | None = None,
) -> dict | None:
    """The agent's alliance_with_player_crew when the NPC belongs to crew_b of an active
    alliance. None keeps the addendum silent. Matches by affiliation, id, or resolved faction.
    you_are_on_side equals hierarchy since the NPC is always crew_b."""
    if not isinstance(npc, dict):
        return None
    aff = (npc.get("affiliation") or "").strip()
    nid = (npc.get("id") or "").strip()
    fac = (npc.get("faction_id") or "").strip()
    fids = faction_card_ids or set()
    for a in crew_alliances_of({"crew_alliances": crew_alliances}):
        cb = a.get("crew_b_id")
        matches = cb and (cb == aff or cb == nid or (cb == fac and cb in fids))
        if matches:
            return {
                "formality": a.get("formality", "informal"),
                "hierarchy": a.get("hierarchy", "peer"),
                "you_are_on_side": a.get("hierarchy", "peer"),
                "origin_note": a.get("origin_note", ""),
            }
    return None


def valid_crew_b_ids(faction_card_ids: set | None, npcs: dict | None) -> set:
    """crew_b_id values acceptable in an alliance_formed: FACTION cards, present NPC
    affiliations, and NPC ids. Anti-invention gate."""
    out: set = set(faction_card_ids or set())
    for nid, d in (npcs or {}).items():
        if not isinstance(d, dict):
            continue
        if nid:
            out.add(nid)
        aff = (d.get("affiliation") or "").strip()
        if aff:
            out.add(aff)
    return out


def alliance_audit_crystal(
    kind: str, crew_b_name: str, *, formality: str = "", hierarchy: str = "",
    reason: str = "", origin_note: str = "", location: str = "",
) -> dict:
    """world_fact crystal recording alliance formation or rupture."""
    where = language.engine_str("at_location", location=location) if location else ""
    nome = crew_b_name or language.engine_str("fallback_other_crew")
    if kind == "alliance_formed":
        tipo = language.engine_str(
            "alliance_kind_formal" if formality == "formal" else "alliance_kind_informal"
        )
        hier = ""
        if hierarchy in ("subordinate", "sovereign"):
            hier = language.engine_str(f"alliance_hier_{hierarchy}")
        extra = f" {origin_note}".rstrip() if origin_note else ""
        fact = language.engine_str(
            "alliance_formed", kind=tipo, name=nome, hier=hier, where=where, extra=extra
        )
    else:
        why = f" ({reason})" if reason else ""
        fact = language.engine_str("alliance_broken", name=nome, why=why, where=where)
    return {
        "category": "world_fact",
        "fact": fact.strip(),
        "characters": [],
        "location": location or "",
        "participants": [],
    }


# Non-Marine bounty hunters.
def affiliation_for_archetype(archetype: str, *, input_ref: str = "") -> str:
    """Derives the hunter affiliation from the free archetype (+ optional input_ref):
    organization/guild keyword to a guild affiliation, otherwise independent."""
    blob = f"{archetype} {input_ref}".lower()
    # Reuse the companion job's explicit affiliation when already canonical.
    for token in blob.replace(",", " ").split():
        if token.startswith(BOUNTY_HUNTER_GUILD_PREFIX):
            return token.strip(".;:")
    if any(k in blob for k in ("guild", "cross guild", "cross_guild", "organiz", "esquadr", "sindicato")):
        return f"{BOUNTY_HUNTER_GUILD_PREFIX}_emergente"
    return BOUNTY_HUNTER_INDEPENDENT


def bounty_hunter_log_of(metadata: dict | None) -> list[dict]:
    """Reads metadata.bounty_hunter_log[] (default []). Each entry is a spawned encounter."""
    raw = (metadata or {}).get("bounty_hunter_log")
    return [e for e in raw if isinstance(e, dict)] if isinstance(raw, list) else []


def append_bounty_hunter_log(
    log: list[dict] | None, *, turn_index: int, archetype: str, affiliation: str,
    hunter_ids: list[str], location: str = "", summary: str = "",
) -> list[dict]:
    """Appends an encounter to the light anti-saturation log (fresh copy)."""
    out = [e for e in (log or []) if isinstance(e, dict)]
    out.append({
        "turn_index": int(turn_index),
        "archetype": (archetype or "").strip(),
        "affiliation": affiliation or BOUNTY_HUNTER_INDEPENDENT,
        "hunter_ids": [h for h in (hunter_ids or []) if h],
        "location": location or "",
        "summary": (summary or "").strip(),
    })
    return out


def recent_bounty_hunter_encounters(
    metadata: dict | None, *, current_turn_index: int | None = None, window: int = RECENT_BH_WINDOW
) -> list[dict]:
    """Digest of the N most recent encounters for the Director to calibrate anti-saturation.
    Annotates turns_ago when current_turn_index is given."""
    log = sorted(bounty_hunter_log_of(metadata), key=lambda e: int(e.get("turn_index", 0)))
    recent = log[-int(window):] if window else log
    out: list[dict] = []
    for e in recent:
        entry = {
            "turn_index": int(e.get("turn_index", 0)),
            "archetype": e.get("archetype", ""),
            "affiliation": e.get("affiliation", BOUNTY_HUNTER_INDEPENDENT),
            "summary": e.get("summary", ""),
        }
        if current_turn_index is not None:
            entry["turns_ago"] = max(0, int(current_turn_index) - int(e.get("turn_index", 0)))
        out.append(entry)
    return out


def active_parallel_nemeses(npcs: dict | None) -> list[dict]:
    """Summary of still-active hunters promoted to parallel nemesis for the Director POST,
    gating the parallel_nemesis_updates channel. Source of truth is the card itself
    (is_nemesis_paralelo + status), so a downed hunter drops out naturally."""
    out: list[dict] = []
    for nid, d in (npcs or {}).items():
        if not isinstance(d, dict) or not d.get("is_nemesis_paralelo"):
            continue
        if d.get("status", "alive") not in ("alive", ""):
            continue
        out.append({
            "hunter_npc_id": d.get("id") or nid,
            "name": d.get("name", ""),
            "tier": (d.get("current_state") or {}).get("tier") or d.get("tier", ""),
            "affiliation": d.get("affiliation", ""),
            "posture": d.get("nemesis_posture", "hostile"),
            "promoted_reasoning": d.get("nemesis_paralelo_reasoning", ""),
        })
    return out


def bounty_hunter_audit_crystal(
    archetype: str, *, affiliation: str = "", location: str = "", hunter_names: list[str] | None = None
) -> dict:
    """combat_outcome crystal recording the hunter's appearance. affiliation goes into the
    fact so reads can filter by bounty_hunter_*."""
    where = language.engine_str("at_location", location=location) if location else ""
    quem = ", ".join(n for n in (hunter_names or []) if n) or (
        archetype or language.engine_str("fallback_bounty_hunter")
    )
    aff = f" [{affiliation}]" if affiliation else ""
    return {
        "category": "combat_outcome",
        "fact": language.engine_str("bounty_hunter_appeared", where=where, who=quem, aff=aff),
        "characters": [n for n in (hunter_names or []) if n],
        "location": location or "",
        "participants": [],
    }
