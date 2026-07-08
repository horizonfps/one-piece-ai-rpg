"""Snapshot/restore of a campaign's world state for Rewind/Regen. Capture runs BEFORE each
DO turn (including before the off-scene tick, which mutates and commits early); restore is
delete+reinsert, and the FTS triggers re-sync on their own. Snapshot is JSON; the schema
uses no BLOB, so all SQLite values are JSON-safe."""
from __future__ import annotations

import json
import time

import aiosqlite

# Mutable campaign_id tables in INSERT order; DELETE runs in reverse. `turns` is excluded
# (append-only; rewind deletes only the reverted row); `canonical_briefings` is global.
_CAMPAIGN_TABLES = [
    "crystals",
    "story_cards",
    "game_clock",
    "game_clock_snapshots",
    "directives",
    "bounty_pending_updates",
    "invented_contexts",
]

# Mutable `campaigns` columns; the row is not deleted (FKs point to it).
_CAMPAIGN_COLS = [
    "name", "current_arc", "metadata_json",
    "campaign_ended_kind", "campaign_ended_at_turn_index", "campaign_ended_epilogue_summary",
]

KEEP_SNAPSHOTS = 20  # per-campaign retention


async def _dump_table(conn: aiosqlite.Connection, sql: str, params: tuple) -> dict:
    cur = await conn.execute(sql, params)
    columns = [d[0] for d in cur.description]
    rows = [list(r) for r in await cur.fetchall()]
    return {"columns": columns, "rows": rows}


async def capture_world(conn: aiosqlite.Connection, campaign_id: str) -> dict:
    """Full dump of the campaign's mutable state. Call BEFORE any write."""
    tables: dict = {}
    for t in _CAMPAIGN_TABLES:
        tables[t] = await _dump_table(
            conn, f"SELECT * FROM {t} WHERE campaign_id = ?", (campaign_id,)
        )
    cur = await conn.execute(
        f"SELECT {', '.join(_CAMPAIGN_COLS)} FROM campaigns WHERE id = ?", (campaign_id,)
    )
    row = await cur.fetchone()
    campaign = dict(zip(_CAMPAIGN_COLS, list(row))) if row else {}
    return {"v": 1, "campaign": campaign, "tables": tables}


async def restore_world(conn: aiosqlite.Connection, campaign_id: str, snapshot: dict) -> None:
    """Restore captured state: delete current campaign rows + reinsert the snapshot. Does NOT
    commit (the caller closes the transaction together with the turn delete)."""
    tables = snapshot.get("tables") or {}
    for t in reversed(_CAMPAIGN_TABLES):
        await conn.execute(f"DELETE FROM {t} WHERE campaign_id = ?", (campaign_id,))
    for t in _CAMPAIGN_TABLES:
        dump = tables.get(t) or {"columns": [], "rows": []}
        cols, rows = dump["columns"], dump["rows"]
        if not cols or not rows:
            continue
        placeholders = ", ".join("?" for _ in cols)
        await conn.executemany(
            f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({placeholders})", rows
        )
    campaign = snapshot.get("campaign") or {}
    if campaign:
        sets = ", ".join(f"{c} = ?" for c in campaign)
        await conn.execute(
            f"UPDATE campaigns SET {sets} WHERE id = ?",
            (*campaign.values(), campaign_id),
        )


async def save_snapshot(
    conn: aiosqlite.Connection, campaign_id: str, turn_index: int, snapshot: dict
) -> None:
    """Save the pre-turn snapshot (INSERT OR IGNORE so a retried turn keeps the first attempt's
    pristine snapshot) and prune beyond KEEP_SNAPSHOTS. Does not commit (joins the turn's
    transaction)."""
    await conn.execute(
        "INSERT OR IGNORE INTO world_snapshots (campaign_id, turn_index, snapshot_json, created_at) "
        "VALUES (?, ?, ?, ?)",
        (campaign_id, turn_index, json.dumps(snapshot, ensure_ascii=False), int(time.time())),
    )
    await conn.execute(
        "DELETE FROM world_snapshots WHERE campaign_id = ? AND turn_index NOT IN ("
        "  SELECT turn_index FROM world_snapshots WHERE campaign_id = ? "
        "  ORDER BY turn_index DESC LIMIT ?)",
        (campaign_id, campaign_id, KEEP_SNAPSHOTS),
    )


async def get_snapshot(
    conn: aiosqlite.Connection, campaign_id: str, turn_index: int
) -> dict | None:
    cur = await conn.execute(
        "SELECT snapshot_json FROM world_snapshots WHERE campaign_id = ? AND turn_index = ?",
        (campaign_id, turn_index),
    )
    row = await cur.fetchone()
    return json.loads(row[0]) if row else None


async def delete_snapshots_from(
    conn: aiosqlite.Connection, campaign_id: str, turn_index: int
) -> None:
    """Delete snapshots from the reverted turn onward (they describe a discarded future)."""
    await conn.execute(
        "DELETE FROM world_snapshots WHERE campaign_id = ? AND turn_index >= ?",
        (campaign_id, turn_index),
    )
