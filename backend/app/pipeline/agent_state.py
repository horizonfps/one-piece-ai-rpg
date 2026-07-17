"""Pure NPC agent logic: no I/O, no proxy, no DB. Pure functions over dicts."""
from __future__ import annotations

# Domain constants (playtest-tunable).
LOG_WINDOW = 20               # personal_event_log rolling window in prompt
IMPORTANT_CAP = 30           # cap of important entries in slice
BOND_TIER1_AFFINITY = 0.6    # affinity threshold that counts as a close bond (recruitment modifier)

_ARCHIVED_STATUSES = ("dead", "missing")  # captured still counts as active


# Intra-island location: "island/sub-area" path convention.
def island_of(location: str) -> str:
    """Island = segment before first slash. Location without slash is the island itself."""
    if not location:
        return ""
    return location.split("/", 1)[0].strip()


def same_subarea(a: str, b: str) -> bool:
    """Same sub-area = exact full-string match, both non-empty."""
    a, b = (a or "").strip(), (b or "").strip()
    return bool(a) and a == b


def same_island(a: str, b: str) -> bool:
    """Same island = equal island prefix, both non-empty."""
    ia, ib = island_of(a), island_of(b)
    return bool(ia) and ia == ib


def location_relation(a: str, b: str) -> str:
    """same_subarea, same_island, or elsewhere between two locations."""
    if same_subarea(a, b):
        return "same_subarea"
    if same_island(a, b):
        return "same_island"
    return "elsewhere"


def sub_area_of(location: str) -> str:
    """Sub-area = segment after the first slash. Empty for a bare island."""
    parts = (location or "").split("/", 1)
    return parts[1].strip() if len(parts) > 1 else ""


def is_slug_location(s: str) -> bool:
    """Slug-space position (`island/sub` or `island/`): has the path separator, no spaces.
    A free-prose `current_location` ("Goa Kingdom — base da muralha") is not, so the sector
    gate cannot prove a mismatch from it and must defer to the Director's intent."""
    s = (s or "").strip()
    return "/" in s and " " not in s


def shares_scene_sector(anchor: str, loc: str) -> bool:
    """Whether loc counts as physically IN the scene anchored at `anchor`.

    True on an exact sub-area match, or when either side is not a parseable slug position
    (prose / generic island, ambiguous, trust the Director's npcs_in_scene). False only when
    both name an explicit differing sub-area of the same island, or when they are on different
    islands. Empty anchor (open sea/travel) keeps everyone. A generated NPC whose
    current_location is still free prose can only be kept here, never proven elsewhere.
    """
    if not anchor or not loc:
        return True
    if not is_slug_location(anchor) or not is_slug_location(loc):
        return True
    rel = location_relation(anchor, loc)
    if rel == "same_subarea":
        return True
    if rel == "elsewhere":
        return False
    a_sub, l_sub = sub_area_of(anchor), sub_area_of(loc)
    return not (a_sub and l_sub and a_sub != l_sub)


# Perception: salience by action_type + public manifestation.
_SALIENCE_RANK = {"invisible": 0, "low": 1, "medium": 2, "high": 3}
_RANK_TO_SALIENCE = {0: None, 1: "low", 2: "medium", 3: "high"}

# Public visibility of an act is the actor's call (action_details.publicly_noticeable).
# The engine only applies the spatial step-down (geometry = bookkeeping).
_DEFAULT_VISIBILITY = "low"  # actor omitted the field


def salience_for(action_type: str, action_details: dict | None = None, *, relation: str = "same_subarea") -> str | None:
    """Salience an act is perceived with by another agent. The base level is what the acting agent
    declared (action_details.publicly_noticeable); the engine only steps it down by spatial
    relation. Same island but not same sub-area drops one step; elsewhere is not perceived."""
    if relation == "elsewhere":
        return None
    d = action_details or {}
    base = str(d.get("publicly_noticeable") or _DEFAULT_VISIBILITY).lower()
    rank = _SALIENCE_RANK.get(base, 1)
    if relation == "same_island":   # same prefix, different sub-area, one step down
        rank -= 1
    return _RANK_TO_SALIENCE[max(0, rank)]


def manifestation_for(action_type: str, action_details: dict | None, npc_name: str) -> str:
    """Public text of what other agents perceive: the acting agent wrote it in
    action_details.public_manifestation. Fallback stays generic when absent."""
    d = action_details or {}
    manifest = (d.get("public_manifestation") or "").strip()
    if manifest:
        return manifest
    return f"{npc_name or 'alguém'} por perto"


def is_active_for_tick(status: str | None) -> bool:
    """Agent counts as active unless archived; captured still counts."""
    return (status or "alive") not in _ARCHIVED_STATUSES


def build_perception(self_location: str, other_recent_acts: list[dict]) -> dict:
    """Builds agent_perception.same_location_events[] from other agents' recent (T-1)
    acts, filtered by salience derived from location relation."""
    events: list[dict] = []
    for act in other_recent_acts:
        rel = location_relation(self_location, act.get("location", ""))
        sal = salience_for(act.get("action_type", ""), act.get("action_details"), relation=rel)
        if sal is None:
            continue
        events.append({
            "npc_id": act.get("npc_id", ""),
            "npc_name": act.get("npc_name", ""),
            "action_type": act.get("action_type", ""),
            "manifestation": manifestation_for(act.get("action_type", ""), act.get("action_details"), act.get("npc_name", "")),
            "salience": sal,
        })
    return {"same_location_events": events}


# personal_event_log: prompt slice + append + ranking.
def _entry_key(e: dict) -> tuple:
    return (e.get("turn_index"), e.get("action_summary"), e.get("source"))


def log_slice(log: list | None, *, window: int = LOG_WINDOW, important_cap: int = IMPORTANT_CAP) -> list[dict]:
    """Agent prompt slice: last `window` entries plus all important ones (capped),
    deduped, sorted by ascending turn_index."""
    entries = [e for e in (log or []) if isinstance(e, dict)]
    recent = entries[-window:]
    important = [e for e in entries if e.get("important")][-important_cap:]
    out: list[dict] = []
    seen: set = set()
    for e in important + recent:
        k = _entry_key(e)
        if k in seen:
            continue
        seen.add(k)
        out.append(e)
    out.sort(key=lambda e: e.get("turn_index") or 0)
    return out


def make_log_entry(
    *,
    turn_index: int,
    action_summary: str,
    location: str,
    scene_mode: str = "off_scene",
    npcs_involved: list | None = None,
    important: bool = False,
    source: str = "self",
    subject_npc_id: str | None = None,
) -> dict:
    """Builds a personal_event_log entry with provenance."""
    entry = {
        "turn_index": turn_index,
        "scene_mode": scene_mode,
        "action_summary": action_summary or "",
        "location": location or "",
        "npcs_involved": list(npcs_involved or []),
        "important": bool(important),
        "source": source,
    }
    if subject_npc_id:
        entry["subject_npc_id"] = subject_npc_id
    return entry


def append_log_entry(agent: dict, entry: dict) -> dict:
    """Returns an agent copy with `entry` appended to personal_event_log."""
    out = dict(agent)
    out["personal_event_log"] = list(agent.get("personal_event_log") or []) + [entry]
    return out


def split_merged(npcs: dict) -> tuple[dict, dict]:
    """Split the roster into live cards and a duplicate->canonical redirect map (chains
    collapsed). Merged duplicates leave every catalog/prompt; writes addressed to them
    follow the redirect to the canonical card."""
    redirects: dict = {}
    for aid, d in (npcs or {}).items():
        tgt = (d or {}).get("merged_into")
        if isinstance(tgt, str) and tgt and tgt != aid:
            redirects[aid] = tgt
    for aid in list(redirects):
        tgt, hops = redirects[aid], 0
        while tgt in redirects and hops < 8:
            tgt = redirects[tgt]
            hops += 1
        redirects[aid] = tgt
    live = {aid: d for aid, d in (npcs or {}).items() if aid not in redirects}
    return live, redirects


# relationships: per-NPC affinity (per-faction lives in faction.py).
def clamp_affinity(value: float) -> float:
    return round(max(-1.0, min(1.0, value)), 4)


def apply_relationship_deltas(
    agent: dict, deltas: list | None, *, turn_index: int, bond_tier_changes: list | None = None
) -> dict:
    """Accumulates relationship_delta[] into relationships{} (affinity clamp, marks
    last_interaction_turn_index). Returns a copy. bond_tier is set only from an explicit
    bond_tier_change emitted by the NPC (the NPC feels the bond turned; engine persists), never
    inferred from affinity. bond_tier 2 stays a canon event the Director confirms."""
    rels = {k: dict(v) for k, v in (agent.get("relationships") or {}).items() if isinstance(v, dict)}
    for d in deltas or []:
        if not isinstance(d, dict):
            continue
        tid = d.get("target_npc_id")
        if not tid:
            continue
        rec = rels.get(tid) or {"affinity": 0.0, "bond_tier": 0, "last_interaction_turn_index": None, "what_they_know_about_other": []}
        try:
            val = float(d.get("value") or 0.0)
        except (TypeError, ValueError):
            val = 0.0
        rec["affinity"] = clamp_affinity(float(rec.get("affinity", 0.0) or 0.0) + val)
        rec["last_interaction_turn_index"] = turn_index
        rels[tid] = rec
    for c in bond_tier_changes or []:
        if not isinstance(c, dict):
            continue
        tid = c.get("target_npc_id")
        try:
            new_tier = int(c.get("bond_tier"))
        except (TypeError, ValueError):
            continue
        if not tid or new_tier not in (0, 1, 2):
            continue
        rec = rels.get(tid) or {"affinity": 0.0, "bond_tier": 0, "last_interaction_turn_index": turn_index, "what_they_know_about_other": []}
        rec["bond_tier"] = new_tier
        rels[tid] = rec
    out = dict(agent)
    out["relationships"] = rels
    return out
