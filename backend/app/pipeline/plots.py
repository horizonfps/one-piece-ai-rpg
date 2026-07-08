"""Island arrival research + foreshadow pool (plot emergente, FASE 29).

Resolves an island (canonical vs invented, region, campaign_phase) and runs the
arrival RESEARCH only: the canonical briefing (research) or the invented context (designer),
cached, with the island marked visited. The island is born NEUTRAL — no plot is imposed. The
canonical briefing is injected into the Narrator every turn via its own channel (runner).

All best-effort: a failed research/designer degrades quality, never drops the turn.
"""
from __future__ import annotations

import re

import aiosqlite

from .. import config
from ..db import repositories as repo
from . import agent_state
from . import island_designer
from . import research

# Catalog cluster -> region enum.
_CLUSTER_TO_REGION = {
    "east blue": "east_blue",
    "west blue": "west_blue",
    "north blue": "north_blue",
    "south blue": "south_blue",
    "paradise": "paradise_first_half",
    "new world": "new_world",
    "calm belt": "calm_belt",
    "sky": "sky_island",
    "fishman": "fishman_island",
}
_DEFAULT_REGION = "paradise_first_half"

# Default post-arc mode for a canonical island without `post_arc_mode` in the catalog. The
# campaign sits after the canonical East Blue arcs, so "fame" (known for past events, no ongoing
# conflict asserted). The catalog may override per island.
_DEFAULT_CANON_MODE = "fame"


# --------------------------------------------------------------------------------------
# Island resolution / context calibration
# --------------------------------------------------------------------------------------
def cluster_to_region(cluster: str | None) -> str:
    if not cluster:
        return _DEFAULT_REGION
    return _CLUSTER_TO_REGION.get(str(cluster).strip().lower(), _DEFAULT_REGION)


def _find_catalog_island(world: dict, island_slug: str) -> dict | None:
    for i in (world or {}).get("islands") or []:
        if i.get("id") == island_slug:
            return i
    return None


def _current_cluster(world: dict) -> str | None:
    """Current island cluster (to derive the region of an invented off-catalog island)."""
    pos = ((world or {}).get("player") or {}).get("position") or {}
    iid = pos.get("island_id") or pos.get("dest_id") or pos.get("origin_id")
    isl = _find_catalog_island(world, iid) if iid else None
    return isl.get("cluster") if isl else None


def _humanize_slug(slug: str) -> str:
    return " ".join(w.capitalize() for w in re.split(r"[_\-/]+", slug or "") if w) or slug


def resolve_island_meta(
    world: dict,
    island_slug: str,
    arrival_triggers: dict,
    *,
    campaign_phase: str = "early",
) -> dict:
    """Build the island metadata. `is_canonical` comes from arrival_triggers (research_pipeline ->
    canonical; island_designer -> invented), falling back to the catalog. campaign_phase is the
    Director's qualitative call, passed through to the designer."""
    catalog = _find_catalog_island(world, island_slug)
    triggers = arrival_triggers or {}
    if triggers.get("research_pipeline"):
        is_canonical = True
    elif triggers.get("island_designer"):
        is_canonical = False
    else:  # ambiguous: catalog decides
        is_canonical = bool(catalog and (catalog.get("canonical") == "canon"))

    if catalog:
        cluster = catalog.get("cluster") or ""
        name = catalog.get("name") or _humanize_slug(island_slug)
        canon_arc_name = catalog.get("canon_arc_name", "")
        post_arc_mode = catalog.get("post_arc_mode") or _DEFAULT_CANON_MODE
    else:  # invented off-catalog island: cluster from the current position
        cluster = _current_cluster(world) or ""
        name = _humanize_slug(island_slug)
        canon_arc_name = ""
        post_arc_mode = _DEFAULT_CANON_MODE

    return {
        "island_slug": island_slug,
        "name": name,
        "is_canonical": is_canonical,
        "cluster": cluster,
        "region": cluster_to_region(cluster),
        "campaign_phase": campaign_phase if campaign_phase in ("early", "mid", "late") else "early",
        "canon_arc_name": canon_arc_name,
        "post_arc_mode": post_arc_mode,
    }


# --------------------------------------------------------------------------------------
# Foreshadow pool (continuity threads)
# --------------------------------------------------------------------------------------
def build_foreshadow_pool(metadata: dict, current_turn_index: int) -> list[dict]:
    """Open-hook pool for the Director/Narrator to weigh (`age_in_turns` computed, no buckets).
    Resolved threads stay stored for the HUD history but leave this projection."""
    pool = (metadata or {}).get("foreshadow_pool") or []
    out: list[dict] = []
    for h in pool:
        if not isinstance(h, dict) or h.get("resolved_at_turn_index") is not None:
            continue
        created = int(h.get("created_at_turn_index") or 0)
        out.append({
            "hook_id": h.get("hook_id", ""),
            "source_island_name": h.get("source_island_name", ""),
            "theme_tag": h.get("theme_tag", ""),
            "description": h.get("description", ""),
            "where_hint": h.get("where_hint", ""),
            "age_in_turns": max(0, int(current_turn_index) - created),
        })
    return out


def _update_foreshadow_pool(
    metadata: dict, *, add: list[dict] | None = None, remove_ids: set | None = None
) -> None:
    pool = [h for h in ((metadata.get("foreshadow_pool") or [])) if isinstance(h, dict)]
    if remove_ids:
        pool = [h for h in pool if h.get("hook_id") not in remove_ids]
    if add:
        pool.extend(add)
    metadata["foreshadow_pool"] = pool


def plant_thread(
    metadata: dict,
    *,
    hook_summary: str,
    theme_tag: str = "",
    where_hint: str = "",
    source_name: str = "",
    turn_index: int,
    planter: str = "director",
    hook_id: str | None = None,
) -> dict | None:
    """Park an opt-in continuity thread in the foreshadow pool for future turns to weigh. The
    Director (FASE 30) plants only when it judges a moment worth a later payoff; the Auditor
    (FASE 32, via `planter`) may plant too. `where_hint` is kept SEPARATE from `description` (a
    loose pointer the Narrator may use or ignore, never the core fact). `hook_id` defaults to one
    unique per (turn, planter), so two planters in the same turn never collide. Idempotent per id.
    Returns the planted hook, or None when there is nothing to plant."""
    summary = str(hook_summary or "").strip()
    if not summary:
        return None
    hid = hook_id or f"{planter}_thread_{int(turn_index)}"
    hook = {
        "hook_id": hid,
        "source_island_name": source_name or "",
        "theme_tag": str(theme_tag or "").strip(),
        "description": summary,
        "where_hint": str(where_hint or "").strip(),
        "created_at_turn_index": int(turn_index),
        "planter": planter,
    }
    _update_foreshadow_pool(metadata, add=[hook], remove_ids={hid})
    return hook


def resolve_threads(metadata: dict, hook_ids: set, turn_index: int) -> None:
    """Mark threads as paid on scene. They leave the LLM projection but stay as HUD history."""
    for h in (metadata or {}).get("foreshadow_pool") or []:
        if isinstance(h, dict) and h.get("hook_id") in hook_ids:
            h["resolved_at_turn_index"] = int(turn_index)


_THREAD_EDIT_FIELDS = ("description", "theme_tag", "where_hint", "source_island_name")


def list_threads(metadata: dict, current_turn_index: int) -> list[dict]:
    """Full thread projection for the HUD panel (all stored fields plus age_in_turns)."""
    out: list[dict] = []
    for h in (metadata or {}).get("foreshadow_pool") or []:
        if not isinstance(h, dict):
            continue
        created = int(h.get("created_at_turn_index") or 0)
        out.append({
            "hook_id": h.get("hook_id", ""),
            "source_island_name": h.get("source_island_name", ""),
            "theme_tag": h.get("theme_tag", ""),
            "description": h.get("description", ""),
            "where_hint": h.get("where_hint", ""),
            "planter": h.get("planter", ""),
            "created_at_turn_index": created,
            "age_in_turns": max(0, int(current_turn_index) - created),
            "resolved_at_turn_index": h.get("resolved_at_turn_index"),
        })
    return out


def edit_thread(metadata: dict, hook_id: str, patch: dict) -> dict | None:
    """Whitelisted human edit of a pooled thread. Returns the hook, or None when unknown."""
    for h in (metadata or {}).get("foreshadow_pool") or []:
        if isinstance(h, dict) and h.get("hook_id") == hook_id:
            for f in _THREAD_EDIT_FIELDS:
                if patch.get(f) is not None:
                    h[f] = str(patch[f]).strip()
            return h
    return None


def remove_thread(metadata: dict, hook_id: str) -> bool:
    """Drop a thread from the pool. Returns False when the id is unknown."""
    pool = (metadata or {}).get("foreshadow_pool") or []
    if not any(isinstance(h, dict) and h.get("hook_id") == hook_id for h in pool):
        return False
    _update_foreshadow_pool(metadata, remove_ids={hook_id})
    return True


def _world_memory_bullets(crystals: list[dict]) -> list[str]:
    """Markdown bullet per crystal: `- [<category> @ <location>, turn N] <fact>`. All crystals."""
    out: list[str] = []
    for c in crystals or []:
        cat = c.get("category", "")
        loc = c.get("location", "") or "?"
        turn = c.get("source_turn_index", "?")
        out.append(f"- [{cat} @ {loc}, turn {turn}] {c.get('fact', '')}")
    return out


# --------------------------------------------------------------------------------------
# Arrival research (no plot; island born neutral)
# --------------------------------------------------------------------------------------
async def run_island_research(
    conn: aiosqlite.Connection,
    campaign_id: str,
    *,
    island_slug: str,
) -> dict:
    """Arrival research only (FASE 29): resolve the island, fetch the canonical briefing (research)
    or invented context (designer), cache both, mark it visited. Creates NO plot. Idempotent: the
    briefing/context cache makes a re-call a pure read. Best-effort: a failed research/designer
    degrades quality, never raises. Returns {is_canonical, briefing_md, quality, invented_context}."""
    if not island_slug:
        return {"is_canonical": False, "briefing_md": "", "quality": "degraded", "invented_context": None}

    campaign = await repo.get_campaign(conn, campaign_id)
    metadata = dict((campaign or {}).get("metadata") or {})
    world = metadata.get("world") or {}
    campaign_phase = str(metadata.get("campaign_phase") or "early")
    meta = resolve_island_meta(world, island_slug, {}, campaign_phase=campaign_phase)

    briefing_md = ""
    invented_context: dict | None = None

    if meta["is_canonical"]:
        briefing = await repo.get_canonical_briefing(conn, island_slug, config.CANON_VERSION)
        if briefing is None:  # cache miss -> research once
            res = await research.run_research({
                "island_slug": island_slug,
                "canonical_name": meta["name"],
                "sea_cluster": meta["cluster"],
                "canonical_mode": meta["post_arc_mode"],
                "canon_arc_name": meta["canon_arc_name"],
                "timeline_anchor": config.CANON_VERSION,
            })
            briefing = res["briefing_md"]
            if briefing:  # only cache a non-empty briefing
                await repo.save_canonical_briefing(conn, island_slug, config.CANON_VERSION, briefing)
        briefing_md = briefing or ""
        quality = "ok" if briefing_md else "degraded"
    else:
        ctx = await repo.get_invented_context(conn, campaign_id, island_slug)
        if ctx is None:  # cache miss -> design once
            designer_input = island_designer.build_designer_input(
                island_slug=island_slug, island_name=meta["name"], region=meta["region"],
                campaign_phase=meta["campaign_phase"],
            )
            try:
                ctx = await island_designer.call_island_designer(designer_input)
            except Exception:  # noqa: BLE001 -- best-effort
                ctx = None
            if ctx:
                await repo.save_invented_context(conn, campaign_id, island_slug, ctx)
        invented_context = ctx
        quality = "ok" if ctx else "degraded"

    visited = list(metadata.get("visited_islands") or [])
    if island_slug not in visited:  # re-trigger gate; only write when it changes
        visited.append(island_slug)
        metadata["visited_islands"] = visited
        await repo.update_campaign_metadata(conn, campaign_id, metadata)

    return {
        "is_canonical": meta["is_canonical"],
        "briefing_md": briefing_md,
        "quality": quality,
        "invented_context": invented_context,
    }


async def get_island_briefing(
    conn: aiosqlite.Connection, campaign_id: str, island_slug: str
) -> dict | None:
    """Cached island briefing for the Narrator (FASE 29), read every turn on a known island.
    Returns {briefing_md, quality, invented_context} (None off-island). quality=ok when any
    background is cached, degraded when the island is known but has none yet (research not run /
    failed). Pure cache read: no LLM work on ordinary turns."""
    if not island_slug:
        return None
    canon = await repo.get_canonical_briefing(conn, island_slug, config.CANON_VERSION)
    invented = await repo.get_invented_context(conn, campaign_id, island_slug)
    has_background = bool((canon or "").strip() or invented)
    return {
        "briefing_md": canon or "",
        "quality": "ok" if has_background else "degraded",
        "invented_context": invented,
    }


def island_slug_of_scene(scene: dict) -> str:
    """Canonical island slug of the scene (consistent pre/post)."""
    return agent_state.island_of((scene or {}).get("location", ""))
