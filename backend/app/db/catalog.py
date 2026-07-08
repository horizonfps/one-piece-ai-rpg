"""Import creation catalogs (traits/classes/fruits) from the canon YAML blocks into SQLite.
Upsert by id (idempotent): re-running boot syncs canon fields without duplicating; YAML
removals are left as orphans, not deleted. Runs in the FastAPI lifespan after migrations."""
from __future__ import annotations

import json
import re

import aiosqlite
import yaml

from .. import config

# yaml fenced block following the importable-catalog header.
_YAML_BLOCK_RE = re.compile(
    r"##\s*Catálogo\s*\(YAML.*?\n```ya?ml\n(.*?)\n```", re.S
)


def _extract_yaml(md_path) -> list[dict]:
    txt = md_path.read_text(encoding="utf-8")
    m = _YAML_BLOCK_RE.search(txt)
    if not m:
        raise ValueError(f"bloco YAML importável não encontrado em {md_path}")
    data = yaml.safe_load(m.group(1)) or {}
    # each doc wraps the list under a single top-level key
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                return v
        return []
    return data if isinstance(data, list) else []


def _docs(*parts) -> "object":
    return config.REPO_ROOT.joinpath("docs", *parts)


async def import_catalogs(conn: aiosqlite.Connection) -> dict:
    """Read the 3 YAMLs and upsert into the catalog tables. Returns imported counts."""
    traits = _extract_yaml(_docs("traits", "catalog.md"))
    classes = _extract_yaml(_docs("classes", "catalog.md"))
    fruits = _extract_yaml(_docs("fruits", "catalog.md"))

    for t in traits:
        await conn.execute(
            "INSERT INTO trait_catalog (id, name, bucket, polarity, rarity, stacking_exclusion, "
            "canon_anchor, description, state_hooks_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name, bucket=excluded.bucket, "
            "polarity=excluded.polarity, rarity=excluded.rarity, "
            "stacking_exclusion=excluded.stacking_exclusion, canon_anchor=excluded.canon_anchor, "
            "description=excluded.description, state_hooks_json=excluded.state_hooks_json",
            (
                t["id"], t["name"], t["bucket"], t["polarity"], t["rarity"],
                t.get("stacking_exclusion"), t.get("canon_anchor"), t["description"],
                json.dumps(t.get("state_hooks", []), ensure_ascii=False),
            ),
        )

    for c in classes:
        await conn.execute(
            "INSERT INTO class_catalog (id, name, archetype, description, starting_loadout_json, "
            "starting_techniques_json, progression_vector, fruit_dependency, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name, archetype=excluded.archetype, "
            "description=excluded.description, starting_loadout_json=excluded.starting_loadout_json, "
            "starting_techniques_json=excluded.starting_techniques_json, "
            "progression_vector=excluded.progression_vector, "
            "fruit_dependency=excluded.fruit_dependency, notes=excluded.notes",
            (
                c["id"], c["name"], c["archetype"], c["description"],
                json.dumps(c.get("starting_loadout", []), ensure_ascii=False),
                json.dumps(c.get("starting_techniques", []), ensure_ascii=False),
                c.get("progression_vector"), c["fruit_dependency"], c.get("notes"),
            ),
        )

    for f in fruits:
        await conn.execute(
            "INSERT INTO fruit_catalog (id, name_jp, name_pt, type, canon_owner, tier, "
            "removal_hook, arc_unlock) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name_jp=excluded.name_jp, name_pt=excluded.name_pt, "
            "type=excluded.type, canon_owner=excluded.canon_owner, tier=excluded.tier, "
            "removal_hook=excluded.removal_hook, arc_unlock=excluded.arc_unlock",
            (
                f["id"], f["name_jp"], f.get("name_pt"), f["type"], f.get("canon_owner"),
                f["tier"], f.get("removal_hook"), f.get("arc_unlock"),
            ),
        )

    await conn.commit()
    return {"traits": len(traits), "classes": len(classes), "fruits": len(fruits)}


# --- read queries (catalog API + roller) ---
async def get_traits(conn: aiosqlite.Connection) -> list[dict]:
    cur = await conn.execute(
        "SELECT id, name, bucket, polarity, rarity, stacking_exclusion, canon_anchor, "
        "description, state_hooks_json FROM trait_catalog ORDER BY bucket, id"
    )
    return [
        {
            "id": r["id"], "name": r["name"], "bucket": r["bucket"], "polarity": r["polarity"],
            "rarity": r["rarity"], "stacking_exclusion": r["stacking_exclusion"],
            "canon_anchor": r["canon_anchor"], "description": r["description"],
            "state_hooks": json.loads(r["state_hooks_json"] or "[]"),
        }
        for r in await cur.fetchall()
    ]


async def get_classes(conn: aiosqlite.Connection) -> list[dict]:
    cur = await conn.execute(
        "SELECT id, name, archetype, description, starting_loadout_json, "
        "starting_techniques_json, progression_vector, fruit_dependency, notes "
        "FROM class_catalog ORDER BY archetype, id"
    )
    return [
        {
            "id": r["id"], "name": r["name"], "archetype": r["archetype"],
            "description": r["description"],
            "starting_loadout": json.loads(r["starting_loadout_json"] or "[]"),
            "starting_techniques": json.loads(r["starting_techniques_json"] or "[]"),
            "progression_vector": r["progression_vector"],
            "fruit_dependency": r["fruit_dependency"], "notes": r["notes"],
        }
        for r in await cur.fetchall()
    ]


async def get_fruits(conn: aiosqlite.Connection) -> list[dict]:
    cur = await conn.execute(
        "SELECT id, name_jp, name_pt, type, canon_owner, tier, removal_hook, arc_unlock "
        "FROM fruit_catalog ORDER BY tier, id"
    )
    return [dict(r) for r in await cur.fetchall()]
