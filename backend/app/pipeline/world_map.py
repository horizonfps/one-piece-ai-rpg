"""World map and position, pure logic.

Navigable world state lives in `campaign.metadata.world` (JSON escape-hatch). Position is
island or sea. The map is read-only: travel is decided narratively; these functions only
build and read state. The day counter lives in `game_clock.campaign_day`, not here.
"""
from __future__ import annotations

import copy
import math
import random
import re

from . import agent_state
from . import language

# Fog of war: discovered hides the island; discovered+unvisited shows a grey dot; visited
# shows a gold marker.
DISCOVERED_VIA = ("canon-known", "npc-mention", "news-coo", "visited")

# Seas where invented islands are never allocated: the catalog is rich enough (the East Blue
# alone carries 31 navigable canon islands), so destinations there stay 100% canon. A cluster
# listed here behaves like the Grand Line/New World (no blank slots): allocate_blank_slot
# returns None, so ensure_generated_island is a no-op and the Director routes to canon ids.
CANON_ONLY_CLUSTERS = frozenset({"east blue"})

# Container circles that are NOT dockable destinations: an abstract umbrella for a whole sea/Blue,
# the continent wall, or a landmass/archipelago whose real docks are OTHER circles (e.g. Dawn
# Island over Foosha + Goa). Cut by id from `_is_navigable`, so the Director never routes to them
# and they never draw as a dockable marker; they stay in the catalog for coords/region lookups.
# Curated across the 332-island catalog (curate-nav-containers workflow, 2026-07-02).
NON_NAVIGABLE_CONTAINERS = frozenset({
    # sea / Blue markers
    "east-blue", "north-blue", "south-blue", "west-blue",
    "calm-belt", "calm-belt-2", "calm-belt-3", "calm-belt-4", "sambas-sea-region",
    # continent wall / planet markers
    "bluestar", "red-line", "red-line-2", "red-line-3", "red-line-4", "red-line-5", "red-line-6",
    # landmass / archipelago umbrellas (real docks are their settlement circles)
    "dawn-island", "yotsuba-island", "conomi-archipelago", "gecko-archipelago",
    "organ-archipelago", "pole-star-archipelago", "island-of-women", "totto-land",
    "cactus-island", "kenzan-island", "momoiro-island",
})

# Fixed Grand Line / Paradise Log Pose route (the canonical Straw Hat chain). In Paradise the Log
# Pose locks the crew onto one route to Sabaody; the game pins it to this one to avoid inventing the
# other six. Ids match the world_islands catalog; the SVG draws it as an ordered polyline.
GRAND_LINE_PARADISE_ROUTE = (
    "reverse-mountain", "twin-capes", "whisky-peak", "giant-island-little-garden",
    "drum-island", "alabasta-kingdom", "jaya-island", "godland-skypiea",
    "long-ring-long-land", "water-seven", "enies-lobby", "thriller-bark",
    "sabaody-archipelago",
)

# Map-coord distance to sailing days. Provisional calibration; magnitude tunes in playtest.
_UNITS_PER_TRAVEL_DAY = 2000.0

# Ship speed factor: multiplies distance covered per day. Provisional scale. Phase 18 derives
# the active ship's factor from subtype x hull; without an active ship the field is absent and
# the reader falls back to SHIP_SPEED_STANDARD.
SHIP_SPEED_FACTORS = {
    "raft": 0.7,
    "standard": 1.0,
    "fast": 1.4,
    "exceptional": 2.0,
}
SHIP_SPEED_STANDARD = SHIP_SPEED_FACTORS["standard"]

# Hull penalty: broken barely sails. Non-zero so it stays below the reader's STANDARD fallback.
_SHIP_HULL_SPEED_MULT = {"pristine": 1.0, "scarred": 1.0, "damaged": 0.8, "broken": 0.3}


def derive_ship_speed_factor(speed_class: str | None, hull_condition: str | None) -> float:
    """Active ship speed factor: the card's emitted speed_class times hull penalty. Unknown
    speed_class/hull means standard with no penalty."""
    base = SHIP_SPEED_FACTORS.get((speed_class or "").strip().lower(), SHIP_SPEED_STANDARD)
    mult = _SHIP_HULL_SPEED_MULT.get((hull_condition or "").strip().lower(), 1.0)
    return round(base * mult, 3)


def refresh_player_ship_speed(meta: dict, ship_cards: dict | None = None) -> bool:
    """Recompute `metadata.world.player.ship_speed_factor` from the crew's active ship (subtype x
    hull). Mutates `meta` in place; returns True if changed. No-op without `world`. No active ship
    or missing card removes the field (reader falls back to STANDARD)."""
    from . import ship  # local import: avoids module import cycle
    world = meta.get("world")
    if not isinstance(world, dict):
        return False
    crew = ship.get_crew(meta)
    active_id = ship.active_ship_id(crew)
    card = (ship_cards or {}).get(active_id) if active_id else None
    player = world.setdefault("player", {})
    old = player.get("ship_speed_factor")
    if not card:
        if "ship_speed_factor" in player:
            del player["ship_speed_factor"]
        return old is not None
    cs = card.get("current_state") or {}
    new = derive_ship_speed_factor(card.get("speed_class"), cs.get("hull_condition"))
    player["ship_speed_factor"] = new
    return new != old


def _coords_of(islands: list[dict], island_id: str | None) -> tuple[float, float] | None:
    """Island coords as a float pair. None if missing or malformed."""
    c = _island_field(islands, island_id or "", "coords")
    if isinstance(c, (list, tuple)) and len(c) == 2:
        try:
            return float(c[0]), float(c[1])
        except (TypeError, ValueError):
            return None
    return None


def travel_days_hint(
    origin_coords: tuple[float, float] | None,
    dest_coords: tuple[float, float] | None,
    ship_speed_factor: float = SHIP_SPEED_STANDARD,
) -> int:
    """Estimated days of a crossing between two map points given the ship speed factor. Missing
    coords or zero distance returns 0; any real crossing returns at least 1 day."""
    if not origin_coords or not dest_coords:
        return 0
    dist = math.hypot(origin_coords[0] - dest_coords[0], origin_coords[1] - dest_coords[1])
    if dist <= 0:
        return 0
    factor = ship_speed_factor if (isinstance(ship_speed_factor, (int, float)) and ship_speed_factor > 0) else SHIP_SPEED_STANDARD
    return max(1, round(dist / (_UNITS_PER_TRAVEL_DAY * factor)))


def player_ship_speed_factor(world: dict) -> float:
    """Player active ship speed factor from `world.player.ship_speed_factor`; falls back to
    SHIP_SPEED_STANDARD when absent."""
    raw = (world.get("player") or {}).get("ship_speed_factor")
    if isinstance(raw, (int, float)) and raw > 0:
        return float(raw)
    return SHIP_SPEED_STANDARD


def crossing_days_hint(world: dict, origin_id: str | None, dest_id: str | None) -> int:
    """Engine-firm crossing duration between two known islands: coord distance over ship speed.
    0 for same island, missing ids, or no coords. Anchors the duration instead of the Director."""
    if not origin_id or not dest_id or origin_id == dest_id:
        return 0
    islands = world.get("islands") or []
    speed = player_ship_speed_factor(world)
    return travel_days_hint(_coords_of(islands, origin_id), _coords_of(islands, dest_id), speed)


def island_id_of_location(location: str) -> str:
    """Island slug of an 'island/sub-area' location."""
    return agent_state.island_of(location)


def make_fog(discovered: bool, visited: bool, via: str) -> dict:
    return {"discovered": bool(discovered), "visited": bool(visited), "discovered_via": via}


def default_fog_for(
    island: dict, start_id: str, start_region: str, known_ids: frozenset[str] | None = None
) -> dict:
    """Initial fog of an island for a campaign starting at `start_id`: start island is visited;
    islands the character plausibly knows (LLM-supplied `known_ids`, else same-region fallback)
    are discovered/canon-known; the rest start hidden."""
    iid = island.get("id")
    if iid == start_id:
        return make_fog(True, True, "visited")
    if known_ids is not None:
        return make_fog(True, False, "canon-known") if iid in known_ids else make_fog(False, False, "canon-known")
    if start_region and island.get("region") == start_region:
        return make_fog(True, False, "canon-known")
    return make_fog(False, False, "canon-known")


def raise_islands_known(world: dict, island_ids) -> bool:
    """Opening-only: mark the islands the Director listed (opening_known_island_ids) as canon-known
    (discovered) over the default fog. Mutates world in place; returns True if any fog changed."""
    ids = {str(i).strip() for i in (island_ids or []) if str(i).strip()} - NON_NAVIGABLE_CONTAINERS
    if not ids:
        return False
    changed = False
    for isl in world.get("islands") or []:
        if isl.get("id") in ids and not (isl.get("fog") or {}).get("discovered"):
            isl["fog"] = make_fog(True, False, "canon-known")
            changed = True
    return changed


def _start_region(islands_catalog: list[dict], start_id: str) -> str:
    for isl in islands_catalog:
        if isl.get("id") == start_id:
            return isl.get("region", "") or ""
    return ""


def build_initial_world(
    islands_catalog: list[dict], start_location: str, blank_slots: list[dict] | None = None
) -> dict:
    """Build the initial `metadata.world` from the catalog plus the seed scene location. Does not
    mutate the catalog (copies each island and injects fog). Unknown start location still gets a
    position; only the map pin is skipped. `blank_slots` are real drawn-but-uncatalogued landmasses
    the engine anchors invented islands onto (stored so it travels with the campaign / snapshots)."""
    start_id = island_id_of_location(start_location)
    start_region = _start_region(islands_catalog, start_id)
    islands = []
    for isl in islands_catalog:
        entry = dict(isl)
        entry["fog"] = default_fog_for(isl, start_id, start_region)
        islands.append(entry)
    world: dict = {
        "player": {"position": {"kind": "island", "island_id": start_id}},
        "islands": islands,
        "world_total": len(islands),
    }
    if blank_slots:
        world["blank_slots"] = [dict(s) for s in blank_slots]
    return world


def world_view(metadata: dict, clock: dict | None) -> dict:
    """Read-only contract for the endpoint/frontend: islands, position, day_counter (from the
    clock) and world_total. Each island carries a `navigable` flag so the frontend hides
    non-dockable containers (a sea/marker/umbrella) from the map while their coords stay
    resolvable for the player pin. `world_total` counts navigable destinations only. Campaigns
    without `world` return a coherent empty structure."""
    world = (metadata or {}).get("world") or {}
    islands = [{**i, "navigable": _is_navigable(i)} for i in (world.get("islands") or [])]
    position = (world.get("player") or {}).get("position")
    world_total = sum(1 for i in islands if i.get("navigable"))
    return {
        "islands": islands,
        "position": position,
        "day_counter": int((clock or {}).get("campaign_day", 0)),
        "world_total": world_total,
    }


# ======================================================================================
# Travel and sea (position/fog mutations + sea events + News Coo)
# ======================================================================================
def current_island_id(world: dict) -> str | None:
    """Current island of the position: the island itself on land, the destination at sea. None if
    the position is absent or incoherent."""
    pos = (world.get("player") or {}).get("position") or {}
    if pos.get("kind") == "island":
        return pos.get("island_id")
    if pos.get("kind") == "sea":
        return pos.get("dest_id") or pos.get("origin_id")
    return None


def normalize_area_slug(area: str) -> str:
    """Island sub-area as a stable byte-comparable slug: lowercase, alphanumerics collapsed by
    `_`, no slash or island prefix. Empty input returns "". Deterministic so `location_relation`
    matches `island/sub` turn to turn. Accepts a ready slug, Director prose, or a full path."""
    s = (area or "").strip().lower()
    if not s:
        return ""
    s = s.rsplit("/", 1)[-1].strip()  # drop the island prefix if a full path arrives
    out: list[str] = []
    prev_sep = True  # start True so output never opens with `_`
    for ch in s:
        if ch.isalnum():
            out.append(ch)
            prev_sep = False
        elif not prev_sep:
            out.append("_")
            prev_sep = True
    return "".join(out).rstrip("_")


def scene_anchor_location(world: dict | None, area_slug: str = "", fallback: str = "") -> str:
    """Mechanical `"island/sub-area"` slug of the player's current position, anchoring the
    `current_location` of in-scene NPCs and the `player_location` of proximity matches.

    The island comes from the map (deterministic slug); the sub-area comes from the Director's
    per-turn `area_slug`, normalized here. `location_relation` then classifies positions as
    same_subarea, same_island, or elsewhere. The Director's free-prose `scene.location` is not
    used here (its prefix diverges from the map slug). Without `area_slug`, falls to island
    granularity; without a world position, falls back to prose."""
    iid = current_island_id(world) if isinstance(world, dict) else None
    if not iid:
        return fallback or ""
    sub = normalize_area_slug(area_slug)
    return f"{iid}/{sub}" if sub else f"{iid}/"


def _island_field(islands: list[dict], island_id: str, field: str):
    for i in islands:
        if i.get("id") == island_id:
            return i.get(field)
    return None


def _set_position_island(world: dict, island_id: str) -> None:
    world.setdefault("player", {})["position"] = {"kind": "island", "island_id": island_id}


def world_arc_label(metadata: dict | None) -> str:
    """Header arc label from the real world position: '<cluster> — <island name>'. A sea position
    reads as the destination. Empty when there is no world/position (pre-map campaigns) so the
    caller keeps the existing arc."""
    world = (metadata or {}).get("world") or {}
    iid = current_island_id(world)
    if not iid:
        return ""
    islands = world.get("islands") or []
    pos = (world.get("player") or {}).get("position") or {}
    at_sea = pos.get("kind") == "sea"
    raw_name = _island_field(islands, iid, "name")
    # A sea destination with no catalog name is an invented island the designer has not named yet:
    # show the neutral placeholder, never the raw slug (a mis-formed slug could surface a scene
    # NPC's name on the map/header). On land, humanize the id as a canon last resort.
    name = raw_name or (
        language.engine_str("uncharted_island") if at_sea else _humanize_island_slug(iid)
    )
    cluster = _island_field(islands, iid, "cluster") or ""
    if at_sea:
        if not pos.get("dest_id"):  # adrift: no chosen destination
            open_sea = language.engine_str("open_sea")
            return f"{cluster} — {open_sea}" if cluster else open_sea
        bound = language.engine_str("bound_for", name=name)
        return f"{cluster} — {bound}" if cluster else bound
    return f"{cluster} — {name}" if cluster else name


# ======================================================================================
# Generated islands: anchor an invented off-catalog island onto a real blank map slot
# ======================================================================================
def _humanize_island_slug(slug: str) -> str:
    return " ".join(w.capitalize() for w in re.split(r"[_\-/]+", slug or "") if w) or (slug or "")


def _norm_cluster(c: str | None) -> str:
    return (c or "").strip().lower()


def _slot_taken(world: dict, coords) -> bool:
    """A slot is taken when some island already sits on it (canon or generated)."""
    if not (isinstance(coords, (list, tuple)) and len(coords) == 2):
        return True
    cy, cx = round(coords[0]), round(coords[1])
    for i in world.get("islands") or []:
        c = i.get("coords")
        if isinstance(c, (list, tuple)) and len(c) == 2 and round(c[0]) == cy and round(c[1]) == cx:
            return True
    return False


def allocate_blank_slot(
    world: dict, *, near_coords: tuple[float, float] | None = None, cluster: str | None = None
) -> dict | None:
    """Nearest free blank slot of the given cluster to `near_coords`. Free = no island sits on it.
    None when the pool is empty/exhausted or no slot matches the cluster — a Grand Line/New World
    cluster has no slots, and a CANON_ONLY_CLUSTERS sea (East Blue) is refused here on purpose, so
    both return None and fall back to the canon catalog."""
    want = _norm_cluster(cluster)
    if want in CANON_ONLY_CLUSTERS:
        return None
    free = [
        s for s in (world.get("blank_slots") or [])
        if isinstance(s, dict)
        and (not want or _norm_cluster(s.get("cluster")) == want)
        and not _slot_taken(world, s.get("coords"))
    ]
    if not free:
        return None
    if near_coords:
        free.sort(key=lambda s: math.hypot(
            s["coords"][0] - near_coords[0], s["coords"][1] - near_coords[1]
        ))
    return free[0]


def ensure_generated_island(
    world: dict, slug: str, *, name: str | None = None, near_island_id: str | None = None
) -> dict | None:
    """Register an off-catalog invented island onto a real blank map slot so it gets coords and a
    marker instead of a phantom position. Idempotent: a canon island is left untouched; an existing
    generated island only gets its placeholder name upgraded to a designer name. Returns the catalog
    entry, or None when nothing was done (already canon, or no free slot for the cluster: invention
    is Blues-only)."""
    if not isinstance(world, dict):
        return None
    slug = (slug or "").strip()
    if not slug:
        return None
    islands = world.setdefault("islands", [])
    existing = next((i for i in islands if i.get("id") == slug), None)
    if existing is not None:
        if name and existing.get("canonical") == "generated" and existing.get("name") != name:
            existing["name"] = name
            return existing
        return None
    near_id = near_island_id or current_island_id(world)
    near_coords = _coords_of(islands, near_id) or player_position_coords(world)
    cluster = _island_field(islands, near_id or "", "cluster")
    slot = allocate_blank_slot(world, near_coords=near_coords, cluster=cluster)
    if slot is None:
        return None
    entry = {
        "id": slug,
        "name": name or language.engine_str("uncharted_island"),
        "coords": [int(slot["coords"][0]), int(slot["coords"][1])],
        "cluster": slot.get("cluster") or cluster or "",
        "region": slot.get("region") or slot.get("cluster") or "",
        "canonical": "generated",
        "fog": make_fog(True, False, "npc-mention"),
    }
    islands.append(entry)
    world["world_total"] = len(islands)
    return entry


def _lerp_t_of(days_elapsed: int, total: int) -> float:
    """Visual crossing progress: fraction of days already sailed."""
    total = max(1, int(total))
    return round(max(0.0, min(1.0, int(days_elapsed) / total)), 3)


def _set_position_sea(
    world: dict,
    origin_id: str | None,
    dest_id: str,
    *,
    travel_days_total: int,
    days_elapsed: int,
    started_day: int,
) -> None:
    """Sea position with real progress: total duration is engine-firm; `days_elapsed` (capped at
    total) advances as the player spends time; `lerp_t` derives from both. `started_day` anchors
    the newspaper window."""
    total = max(1, int(travel_days_total))
    elapsed = max(0, min(total, int(days_elapsed)))
    world.setdefault("player", {})["position"] = {
        "kind": "sea",
        "origin_id": origin_id,
        "dest_id": dest_id,
        "travel_days_total": total,
        "days_elapsed": elapsed,
        "started_day": int(started_day),
        "lerp_t": _lerp_t_of(elapsed, total),
    }


def _set_position_adrift(
    world: dict, origin_id: str | None, *, started_day: int, days_adrift: int
) -> None:
    """Adrift at open sea: the player left port without a chosen destination. No `dest_id`, so no
    ETA/lerp — the pin holds at the origin. `days_adrift` counts days spent wandering; naming a
    destination later converts this into a directed crossing via set_sea."""
    world.setdefault("player", {})["position"] = {
        "kind": "sea",
        "origin_id": origin_id,
        "dest_id": None,
        "adrift": True,
        "days_elapsed": max(0, int(days_adrift)),
        "started_day": int(started_day),
    }


def _reveal_island(world: dict, island_id: str, *, via: str, visited: bool) -> bool:
    """Raise an island's fog (monotonic, never downgrades). Returns True if changed. Unknown
    island is a no-op. `discovered_via` reflects the real channel: visiting wins; a previously
    hidden island adopts the discovery `via`; an already-discovered island keeps its label."""
    for i in world.get("islands") or []:
        if i.get("id") != island_id:
            continue
        fog = dict(i.get("fog") or {})
        was_discovered = bool(fog.get("discovered"))
        now_visited = bool(visited) or bool(fog.get("visited"))
        if now_visited:
            new_via = "visited"
        elif was_discovered:
            new_via = fog.get("discovered_via") or via
        else:
            new_via = via
        new_fog = {"discovered": True, "visited": now_visited, "discovered_via": new_via}
        if new_fog != fog:
            i["fog"] = new_fog
            return True
        return False
    return False


def apply_scene_island_relocation(world: dict, island_slug: str) -> bool:
    """Player reached another catalogued island ON FOOT (same landmass, no sea crossing): sync
    world.position + fog to it so the map, HUD and location_relation follow the scene instead of
    trailing the seed island. Returns True when the position moved.

    No-op unless the target is an island already in `world.islands` (canon OR in-game generated),
    discovered, in the SAME region as the current position, and the player is on land. An unknown
    slug, a sea position, or a different-region target is left untouched: sea crossings own the
    position while at sea and go through apply_movement, and a brand-new place that is not its own
    catalogued island stays a sub-area (area_slug) of the current island."""
    if not isinstance(world, dict):
        return False
    target = (island_slug or "").strip()
    if not target:
        return False
    pos = (world.get("player") or {}).get("position") or {}
    if pos.get("kind") != "island":
        return False
    cur = pos.get("island_id")
    if not cur or target == cur:
        return False
    islands = world.get("islands") or []
    tgt = next((i for i in islands if i.get("id") == target), None)
    if tgt is None or not (tgt.get("fog") or {}).get("discovered"):
        return False
    cur_region, tgt_region = _island_field(islands, cur, "region"), tgt.get("region")
    if cur_region and tgt_region and tgt_region != cur_region:
        return False
    _set_position_island(world, target)
    _reveal_island(world, target, via="overland", visited=True)
    return True


def apply_movement(
    world: dict, movement: dict, *, days: int, arrival_day: int, rng: random.Random | None = None
) -> tuple[dict, dict]:
    """Apply `world_movement` to a copy of `world` (does not mutate input). Updates position and
    fog. `set_sea` starts a crossing (fixes duration); `arrive_island` seals arrival. Progress
    between boarding and arrival goes through `advance_sea_travel`. Returns (new_world, report)."""
    world = copy.deepcopy(world or {})
    report: dict = {"moved_to": None, "revealed": []}

    kind = movement.get("kind")
    dest_id = movement.get("destination_id")
    # Default crossing origin: the trip origin when already at sea, so multi-turn set_sea/arrive
    # keeps the crossing. The Director may override with explicit origin_id.
    pos = (world.get("player") or {}).get("position") or {}
    default_origin = pos.get("origin_id") if pos.get("kind") == "sea" else current_island_id(world)
    origin_id = movement.get("origin_id") or default_origin
    days = max(0, int(days or 0))

    if kind == "set_adrift":
        # Left port with no chosen destination: adrift at open sea, pin holds at origin. No fog
        # reveal (nothing was named). The player names a destination later (set_sea).
        _set_position_adrift(world, origin_id, started_day=arrival_day - days, days_adrift=days)
        report["moved_to"] = {"kind": "sea", "origin_id": origin_id, "dest_id": None, "adrift": True}
        return world, report

    if not dest_id:
        return world, report

    if kind == "arrive_island":
        _set_position_island(world, dest_id)
        report["moved_to"] = {"kind": "island", "island_id": dest_id}
        if _reveal_island(world, dest_id, via="visited", visited=True):
            report["revealed"].append(dest_id)

    elif kind == "set_sea":
        # Total duration is engine-firm: coord distance over ship speed. Missing coords fall back
        # to this turn's advanced days (min 1).
        hint = crossing_days_hint(world, origin_id, dest_id)
        total = hint if hint >= 1 else max(1, days)
        started_day = arrival_day - days
        _set_position_sea(
            world, origin_id, dest_id,
            travel_days_total=total, days_elapsed=days, started_day=started_day,
        )
        report["moved_to"] = {"kind": "sea", "origin_id": origin_id, "dest_id": dest_id}
        report["travel_days_total"] = total
        if _reveal_island(world, dest_id, via="npc-mention", visited=False):
            report["revealed"].append(dest_id)

    return world, report


def advance_sea_travel(
    world: dict, days: int, *, rng: random.Random | None = None
) -> tuple[dict, dict]:
    """Advance an in-progress crossing (sea position) by `days` without changing islands.

    When time passes aboard without a `world_movement`, the engine increments `days_elapsed`
    (capped at total), recomputes `lerp_t`, and samples sea events for the days actually consumed.
    Excess beyond total does not advance the trip. No-op off-sea or with days <= 0. Returns
    (new_world, report)."""
    rng = rng or random
    world = copy.deepcopy(world or {})
    report: dict = {"days_advanced": 0}
    pos = (world.get("player") or {}).get("position") or {}
    days = max(0, int(days or 0))
    if pos.get("kind") != "sea" or days <= 0:
        return world, report

    if not pos.get("dest_id"):  # adrift: days at sea accrue, but there is no crossing to progress
        _set_position_adrift(
            world, pos.get("origin_id"),
            started_day=int(pos.get("started_day") or 0),
            days_adrift=int(pos.get("days_elapsed") or 0) + days,
        )
        report["days_advanced"] = days
        return world, report

    total = max(1, int(pos.get("travel_days_total") or 1))
    elapsed = max(0, min(total, int(pos.get("days_elapsed") or 0)))
    new_elapsed = min(total, elapsed + days)
    actual = new_elapsed - elapsed  # trip days actually consumed (capped at total)

    origin_id = pos.get("origin_id")
    dest_id = pos.get("dest_id")
    _set_position_sea(
        world, origin_id, dest_id,
        travel_days_total=total, days_elapsed=new_elapsed,
        started_day=int(pos.get("started_day") or 0),
    )
    report["days_advanced"] = actual
    return world, report


def sea_crossing_id(world: dict) -> str:
    """Stable anchor key for an in-progress sea crossing (origin->dest), constant across the
    crossing's days so a sea plot isn't regenerated each day. '' when off-sea."""
    pos = (world.get("player") or {}).get("position") or {}
    if pos.get("kind") != "sea":
        return ""
    origin = pos.get("origin_id") or "open"
    dest = pos.get("dest_id") or "open"
    return f"{origin}->{dest}"


def sea_days_remaining(world: dict) -> int:
    """Days left to complete the in-progress crossing. 0 off-sea or when already in sight. The
    runner uses this to complete the trip on arrival."""
    pos = (world.get("player") or {}).get("position") or {}
    if pos.get("kind") != "sea" or not pos.get("dest_id"):  # off-sea or adrift: no ETA
        return 0
    total = max(1, int(pos.get("travel_days_total") or 1))
    elapsed = max(0, min(total, int(pos.get("days_elapsed") or 0)))
    return max(0, total - elapsed)


def _is_navigable(island: dict) -> bool:
    """A navigable place the Director may route to and the player docks at. Non-place markers
    (poneglyph/faction/meta) render but are not destinations; a missing marker_kind (generated
    islands) is a place by default. NON_NAVIGABLE_CONTAINERS are cut by id: an abstract umbrella
    (a sea, the Red Line, a landmass/archipelago whose real docks are other circles)."""
    if (island.get("id") or "") in NON_NAVIGABLE_CONTAINERS:
        return False
    return (island.get("marker_kind") or "place") == "place"


def nav_summary(metadata: dict) -> dict:
    """Volatile navigation state for the Director input: current position + per-island travel-day
    hints from that position (place islands only), keyed by id. The island geography + routes live in
    the cached WORLD-MAP block (`world_map_svg`); the Director crosses the two by id, the way
    agents_locations complements the agents catalog. Empty without `world`.

    Hints span the FULL navigable catalog on purpose: the hint is advisory (the engine firms a
    crossing's real duration in apply_movement), and the routable set is never fog-filtered —
    funnelling departures to the nearest known neighbour was the bug that motivated keeping it full."""
    world = (metadata or {}).get("world") or {}
    islands = world.get("islands") or []
    cur_coords = _coords_of(islands, current_island_id(world))
    speed = player_ship_speed_factor(world)
    return {
        "position": (world.get("player") or {}).get("position"),
        "navigable_hints": {
            i.get("id"): travel_days_hint(cur_coords, _coords_of(islands, i.get("id")), speed)
            for i in islands
            if _is_navigable(i)
        },
    }


def _svg_attr(value: object) -> str:
    """Escape a string for an SVG attribute value."""
    return (str(value or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _svg_xy(island: dict) -> tuple[int, int] | None:
    """Island coords as integer SVG (x, y): x = coords[1] (west->east), y = coords[0]."""
    c = island.get("coords")
    if isinstance(c, (list, tuple)) and len(c) == 2:
        try:
            return int(round(float(c[1]))), int(round(float(c[0])))
        except (TypeError, ValueError):
            return None
    return None


def _reference_geography_svg(islands: list[dict], by_id: dict) -> list[str]:
    """The Red Line crossings, drawn straight from the red-line markers (vertical continent-wall; the
    only Blue<->Grand Line passages are Reverse Mountain west and Sabaody/Fish-Man Island east). The
    Calm Belts are deliberately NOT drawn as a band: a uniform band would falsely cover the New World
    islands that sit along the same Grand Line cy. That barrier is a RULE (legend + prompt), and the
    real Calm Belt is the data-sea="Calm Belt" circles."""
    red = [i for i in islands if (i.get("id") or "").startswith("red-line")]
    if not red:
        return []
    red_x = sorted({_svg_xy(i)[0] for i in red})
    # The map wraps horizontally, so the markers carry a duplicate edge crossing. Keep the two real
    # crossings: the one nearest Reverse Mountain (west) and the one nearest Sabaody (east).
    anchor_xs = [_svg_xy(by_id[a])[0] for a in ("reverse-mountain", "sabaody-archipelago") if a in by_id]
    if anchor_xs:
        red_x = sorted({min(red_x, key=lambda rx: abs(rx - ax)) for ax in anchor_xs})
    ry = [_svg_xy(i)[1] for i in red]
    y0, y1 = min(ry), max(ry)
    out = ['<g id="reference-geography">']
    for rx in red_x:
        out.append(
            f'<line id="red-line-x{rx}" x1="{rx}" y1="{y0}" x2="{rx}" y2="{y1}" stroke="#cc3333" '
            f'stroke-width="200" data-note="Red Line: muralha-continente; o Blue so passa para a Grand '
            f'Line em Reverse Mountain (oeste) e Sabaody/Fish-Man Island (leste)"/>'
        )
    out.append("</g>")
    return out


def world_map_svg(metadata: dict) -> str:
    """Cache-stable semantic SVG of the navigable world for the Director's CACHED block. Each place
    island is a <circle> (id = the destination_id to emit, cx/cy = position, data-name/data-region);
    islands group by <g data-sea> (cluster); the fixed Grand Line Log Pose route is an ordered
    <polyline>. The model reads the markup to reason geography (what is near / on the way) instead of
    routing to the most salient name. Sorted deterministically so the markup is byte-stable turn to
    turn and caches cleanly (one bust when a generated island lands). Empty world -> minimal shell."""
    world = (metadata or {}).get("world") or {}
    islands = [i for i in (world.get("islands") or []) if _is_navigable(i) and _svg_xy(i)]
    by_id = {i.get("id"): i for i in islands if i.get("id")}

    xs = [_svg_xy(i)[0] for i in islands]
    ys = [_svg_xy(i)[1] for i in islands]
    if xs and ys:
        minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    else:
        minx = miny = 0
        maxx = maxy = 1000
    pad = 500
    vb = f"{minx - pad} {miny - pad} {maxx - minx + 2 * pad} {maxy - miny + 2 * pad}"

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}">',
        "<style>circle{r:120}</style>",
        ("<!-- MAPA-MUNDO navegavel (One Piece). Cada <circle> e uma ilha-destino: id = o "
         "destination_id que voce emite, cx/cy = posicao, data-name, data-region, data-canon. "
         "data-canon=1 e ilha CANONICA de One Piece (na chegada dispara research_pipeline); "
         "circle SEM data-canon e terra a inventar (dispara island_designer). Eixo cx: oeste "
         "(menor) -> leste (maior). Ilhas agrupadas por <g data-sea> (o mar: os quatro Blues, "
         "Paradise, New World, Calm Belt, etc.). <g id=reference-geography> tem a Red Line como <line> "
         "verticais (muralha-continente; o Blue so cruza para a Grand Line em Reverse Mountain, "
         "cx~34800, e em Sabaody/Fish-Man Island, leste — leia o data-note). Os Calm Belts ladeiam a "
         "Grand Line e nao se atravessam a navio comum: um Blue funila pela Reverse Mountain, nao corta "
         "reto (as ilhas data-sea=Calm Belt marcam onde ficam). A <polyline> e a rota fixa do Log Pose "
         "em Paradise, ilha a ilha na ordem de data-islands. Distancia em dias: navigable_hints. -->"),
    ]
    lines += _reference_geography_svg(islands, by_id)
    # Destination circles exclude the Bluestar geo-junk cluster (Red Line markers + poles): those are
    # barriers/landmarks drawn above, not islands you sail to.
    destinations = [i for i in islands if (i.get("cluster") or "") != "Bluestar"]
    for cl in sorted({(i.get("cluster") or "—") for i in destinations}):
        members = sorted(
            (i for i in destinations if (i.get("cluster") or "—") == cl),
            key=lambda e: e.get("id") or "",
        )
        lines.append(f'<g data-sea="{_svg_attr(cl)}">')
        for i in members:
            x, y = _svg_xy(i)
            # data-canon=1 marks a canonical One Piece island: the Director routes its arrival to
            # research_pipeline. Absence (generated/blank land) routes to island_designer.
            canon = ' data-canon="1"' if (i.get("canonical") == "canon") else ""
            lines.append(
                f'<circle id="{_svg_attr(i.get("id"))}" cx="{x}" cy="{y}" '
                f'data-name="{_svg_attr(i.get("name"))}" data-region="{_svg_attr(i.get("region"))}"{canon}/>'
            )
        lines.append("</g>")

    route = [rid for rid in GRAND_LINE_PARADISE_ROUTE if rid in by_id]
    if len(route) >= 2:
        pts = " ".join(f"{_svg_xy(by_id[r])[0]},{_svg_xy(by_id[r])[1]}" for r in route)
        lines.append(
            f'<polyline id="grand-line-log-pose-route" fill="none" stroke="#000" '
            f'data-islands="{" ".join(route)}" points="{pts}"/>'
        )
    lines.append("</svg>")
    return "\n".join(lines)


# ======================================================================================
# Bearing (Vivre Card direction on the map)
# ======================================================================================
# 8-point compass. The map renders NORTH = +y (coords[0]), EAST = +x (coords[1]), so a bearing
# of 0deg=North/up, clockwise, rotates a CSS arrow 1:1. `L`/`O` are East/West (PT-BR labels).
_COMPASS_8 = ("N", "NE", "L", "SE", "S", "SO", "O", "NO")


def island_coords(world: dict, island_id: str | None) -> tuple[float, float] | None:
    """Coords [y, x] of an island in the current world (public wrapper of `_coords_of`)."""
    return _coords_of(world.get("islands") or [], island_id)


def player_position_coords(world: dict) -> tuple[float, float] | None:
    """Coords [y, x] of the player's current position: the island on land, or the `lerp_t`
    interpolated point between origin and destination at sea. None if it cannot resolve."""
    pos = (world.get("player") or {}).get("position") or {}
    islands = world.get("islands") or []
    if pos.get("kind") == "island":
        return _coords_of(islands, pos.get("island_id"))
    if pos.get("kind") == "sea":
        o = _coords_of(islands, pos.get("origin_id"))
        d = _coords_of(islands, pos.get("dest_id"))
        if not o:
            return None
        if not d:  # adrift: no destination, hold at origin
            return o
        t = max(0.0, min(1.0, float(pos.get("lerp_t") or 0.0)))
        return (o[0] + (d[0] - o[0]) * t, o[1] + (d[1] - o[1]) * t)
    return None


def compass_bearing(
    from_coords: tuple[float, float] | None, to_coords: tuple[float, float] | None
) -> dict | None:
    """Bearing from->to in map space: `{bearing_deg, cardinal}` with 0deg=North, clockwise. None
    if a point is missing or both coincide."""
    if not from_coords or not to_coords:
        return None
    dy_north = to_coords[0] - from_coords[0]  # +y = North (up on screen)
    dx_east = to_coords[1] - from_coords[1]   # +x = East (right on screen)
    if dy_north == 0 and dx_east == 0:
        return None
    deg = math.degrees(math.atan2(dx_east, dy_north)) % 360.0
    idx = int((deg + 22.5) % 360.0 // 45.0)
    return {"bearing_deg": round(deg, 1), "cardinal": _COMPASS_8[idx]}
