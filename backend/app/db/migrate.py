"""Minimal SQL migration runner. Version tracked via PRAGMA user_version. Files
migrations/NNNN_*.sql apply in ascending order, only those above the current version;
each runs in executescript and bumps user_version at the end."""
from __future__ import annotations

import re
from pathlib import Path

import aiosqlite

from .. import config

_FNAME_RE = re.compile(r"^(\d+)_.*\.sql$")
# A statement-level BEGIN (not a trigger body's `... BEGIN ... END`) means the migration manages
# its own transaction; the runner wraps only the ones that don't.
_HAS_TXN_CONTROL = re.compile(r"(?im)^\s*BEGIN\s*(TRANSACTION|IMMEDIATE|EXCLUSIVE|DEFERRED)?\s*;")


def _discover(migrations_dir: Path) -> list[tuple[int, Path]]:
    found: list[tuple[int, Path]] = []
    for p in sorted(migrations_dir.glob("*.sql")):
        m = _FNAME_RE.match(p.name)
        if m:
            found.append((int(m.group(1)), p))
    found.sort(key=lambda t: t[0])
    return found


async def run_migrations(conn: aiosqlite.Connection | None = None) -> dict:
    own = conn is None
    if own:
        config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(str(config.DB_PATH))
    try:
        cur = await conn.execute("PRAGMA user_version;")
        row = await cur.fetchone()
        current = int(row[0]) if row else 0

        applied: list[str] = []
        for version, path in _discover(config.MIGRATIONS_DIR):
            if version <= current:
                continue
            sql = path.read_text(encoding="utf-8")
            # executescript commits any open transaction then runs statements in autocommit, so a
            # mid-script failure leaves earlier DDL committed and user_version un-bumped -> the next
            # boot re-runs and bricks the save. Wrap in one transaction for atomic rollback;
            # migrations that manage their own control (BEGIN/COMMIT around PRAGMA foreign_keys) run
            # verbatim.
            script = sql if _HAS_TXN_CONTROL.search(sql) else f"BEGIN;\n{sql}\nCOMMIT;"
            await conn.executescript(script)
            # user_version takes no parameter; version comes from a \d+ regex, safe to interpolate.
            await conn.execute(f"PRAGMA user_version = {version};")
            await conn.commit()
            applied.append(path.name)
            current = version

        return {"schema_version": current, "applied": applied}
    finally:
        if own:
            await conn.close()
