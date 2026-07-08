"""SQLite connection via aiosqlite: row factory + foreign keys + WAL."""
from __future__ import annotations

import aiosqlite

from .. import config


async def connect() -> aiosqlite.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(str(config.DB_PATH))
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys = ON;")
    await conn.execute("PRAGMA journal_mode = WAL;")
    # Multiple writers coexist; without busy_timeout, write-lock contention raises
    # "database is locked" immediately. With it, the writer waits (WAL keeps reads free).
    await conn.execute("PRAGMA busy_timeout = 30000;")
    return conn
