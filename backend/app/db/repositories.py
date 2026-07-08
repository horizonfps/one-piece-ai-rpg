"""Async SQLite access. List/nested fields serialize to `_json TEXT` columns. Each function
takes an open connection; the caller owns the transaction. IDs are uuid hex; timestamps are
epoch seconds."""
from __future__ import annotations

import json
import re
import time
import uuid

import aiosqlite

from ..pipeline.narrator import sanitize_prose


def _now() -> int:
    return int(time.time())


def _fts_match_query(q: str) -> str:
    """Sanitize the user query into a safe FTS5 MATCH: extract unicode tokens into a prefix-AND.
    Avoids MATCH-syntax injection and matches the remove_diacritics tokenizer. Empty if no usable
    token."""
    terms = re.findall(r"\w+", q or "", re.UNICODE)
    return " ".join(f"{t}*" for t in terms)


def _row(r: aiosqlite.Row | None) -> dict | None:
    return dict(r) if r is not None else None


# --- campaigns ---
async def create_campaign(
    conn: aiosqlite.Connection,
    name: str,
    *,
    current_arc: str | None = None,
    metadata: dict | None = None,
    language: str = "pt-br",
) -> str:
    cid = uuid.uuid4().hex
    await conn.execute(
        "INSERT INTO campaigns (id, name, created_at, current_arc, metadata_json, language) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (cid, name, _now(), current_arc, json.dumps(metadata or {}, ensure_ascii=False), language),
    )
    return cid


async def get_campaign(conn: aiosqlite.Connection, campaign_id: str) -> dict | None:
    cur = await conn.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,))
    row = _row(await cur.fetchone())
    if row is None:
        return None
    row["metadata"] = json.loads(row.pop("metadata_json") or "{}")
    return row


async def list_campaigns(conn: aiosqlite.Connection) -> list[dict]:
    cur = await conn.execute(
        "SELECT id, name, created_at, current_arc, campaign_ended_kind, language "
        "FROM campaigns ORDER BY created_at DESC"
    )
    return [dict(r) for r in await cur.fetchall()]


async def update_campaign_metadata(
    conn: aiosqlite.Connection, campaign_id: str, metadata: dict
) -> None:
    """Overwrite metadata_json (world-state escape hatch)."""
    await conn.execute(
        "UPDATE campaigns SET metadata_json = ? WHERE id = ?",
        (json.dumps(metadata, ensure_ascii=False), campaign_id),
    )


async def update_campaign_arc(
    conn: aiosqlite.Connection, campaign_id: str, current_arc: str
) -> None:
    """Update the campaign's current_arc."""
    await conn.execute(
        "UPDATE campaigns SET current_arc = ? WHERE id = ?",
        (current_arc, campaign_id),
    )


async def delete_campaign(conn: aiosqlite.Connection, campaign_id: str) -> bool:
    """Delete the campaign and ALL dependent state. No FK ON DELETE CASCADE, so rows go one by
    one; FTS tables re-sync via AFTER DELETE triggers. `canonical_briefings` is global, untouched.
    Returns False if the campaign did not exist."""
    cur = await conn.execute("SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,))
    if await cur.fetchone() is None:
        return False
    for table in (
        "turns", "crystals", "story_cards", "game_clock", "game_clock_snapshots",
        "directives", "invented_contexts", "bounty_pending_updates",
        "world_snapshots",  # FK into campaigns; omitting it makes the campaign DELETE violate the FK
    ):
        await conn.execute(f"DELETE FROM {table} WHERE campaign_id = ?", (campaign_id,))
    await conn.execute("DELETE FROM campaigns WHERE id = ?", (campaign_id,))
    return True


# --- story_cards (NPC/player/scene minds) ---
async def add_story_card(
    conn: aiosqlite.Connection, campaign_id: str, kind: str, data: dict
) -> str:
    scid = uuid.uuid4().hex
    now = _now()
    await conn.execute(
        "INSERT INTO story_cards (id, campaign_id, kind, data_json, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (scid, campaign_id, kind, json.dumps(data, ensure_ascii=False), now, now),
    )
    return scid


async def get_story_cards(
    conn: aiosqlite.Connection, campaign_id: str, kind: str | None = None
) -> list[dict]:
    if kind is None:
        cur = await conn.execute(
            "SELECT id, kind, data_json FROM story_cards WHERE campaign_id = ?",
            (campaign_id,),
        )
    else:
        cur = await conn.execute(
            "SELECT id, kind, data_json FROM story_cards WHERE campaign_id = ? AND kind = ?",
            (campaign_id, kind),
        )
    out = []
    for r in await cur.fetchall():
        out.append({"id": r["id"], "kind": r["kind"], "data": json.loads(r["data_json"])})
    return out


async def get_player_story_card(conn: aiosqlite.Connection, campaign_id: str) -> dict | None:
    """The 'player' story_card with its id (needed for update_story_card post-turn)."""
    cards = await get_story_cards(conn, campaign_id, kind="player")
    return cards[0] if cards else None


async def get_npc_agents(conn: aiosqlite.Connection, campaign_id: str) -> dict[str, dict]:
    """Map agent_id -> {story_card_id, data} for named NPCs. agent_id lives in data["id"];
    story_card_id is the row PK. NPCs without an id are skipped."""
    out: dict[str, dict] = {}
    for c in await get_story_cards(conn, campaign_id, kind="npc_agent"):
        aid = (c["data"] or {}).get("id")
        if aid:
            out[aid] = {"story_card_id": c["id"], "data": c["data"]}
    return out


async def update_story_card(conn: aiosqlite.Connection, story_card_id: str, data: dict) -> None:
    """Overwrite a story_card's data_json."""
    await conn.execute(
        "UPDATE story_cards SET data_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(data, ensure_ascii=False), _now(), story_card_id),
    )


async def get_story_card(
    conn: aiosqlite.Connection, campaign_id: str, story_card_id: str
) -> dict | None:
    """A story_card by PK, scoped to the campaign. None if missing or from another campaign."""
    cur = await conn.execute(
        "SELECT id, kind, data_json FROM story_cards WHERE id = ? AND campaign_id = ?",
        (story_card_id, campaign_id),
    )
    r = await cur.fetchone()
    if r is None:
        return None
    return {"id": r["id"], "kind": r["kind"], "data": json.loads(r["data_json"])}


async def get_card_by_entity_id(
    conn: aiosqlite.Connection, campaign_id: str, entity_id: str
) -> dict | None:
    """Find the row whose data["id"] (entity id) matches, any kind. None if absent. Used by
    paths that work by entity id rather than PK."""
    cur = await conn.execute(
        "SELECT id, kind, data_json FROM story_cards "
        "WHERE campaign_id = ? AND json_extract(data_json, '$.id') = ?",
        (campaign_id, entity_id),
    )
    r = await cur.fetchone()
    if r is None:
        return None
    return {"id": r["id"], "kind": r["kind"], "data": json.loads(r["data_json"])}


async def list_cards(
    conn: aiosqlite.Connection, campaign_id: str, kind: str | None = None
) -> list[dict]:
    """Summary list for the Memory Inspector: entity id, name, type, aliases, state summary,
    status. Omits the full data."""
    out: list[dict] = []
    for c in await get_story_cards(conn, campaign_id, kind):
        d = c["data"] or {}
        cs = d.get("current_state") or {}
        out.append({
            "story_card_id": c["id"],
            "kind": c["kind"],
            "id": d.get("id", ""),
            "name": d.get("name") or (d.get("player_character") or {}).get("name", ""),
            "subtype": d.get("subtype", ""),
            "aliases": d.get("aliases", []),
            "tier": cs.get("tier") or d.get("tier", ""),
            "summary": cs.get("summary_text", ""),
            "status": d.get("status", ""),
            "canonical": d.get("canonical", ""),
        })
    return out


# --- turns ---
async def next_turn_index(conn: aiosqlite.Connection, campaign_id: str) -> int:
    cur = await conn.execute(
        "SELECT COALESCE(MAX(turn_index), 0) AS m FROM turns WHERE campaign_id = ?",
        (campaign_id,),
    )
    row = await cur.fetchone()
    return int(row["m"]) + 1


async def append_turn(
    conn: aiosqlite.Connection,
    campaign_id: str,
    *,
    player_input: dict | str,
    narrator_prose: str,
    agent_decisions: dict,
    scene_snapshot: dict | None = None,
    trace: list | None = None,
) -> int:
    """Append a turn (sequential turn_index per campaign) and return it."""
    turn_index = await next_turn_index(conn, campaign_id)
    pi = json.dumps(player_input, ensure_ascii=False) if not isinstance(player_input, str) else player_input
    await conn.execute(
        "INSERT INTO turns (campaign_id, turn_index, player_input, narrator_prose, "
        "agent_decisions_json, scene_yaml_snapshot, trace_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            campaign_id,
            turn_index,
            pi,
            narrator_prose,
            json.dumps(agent_decisions, ensure_ascii=False),
            json.dumps(scene_snapshot, ensure_ascii=False) if scene_snapshot is not None else None,
            json.dumps(trace, ensure_ascii=False) if trace else None,
            _now(),
        ),
    )
    return turn_index


async def save_turn_post_turn(
    conn: aiosqlite.Connection, campaign_id: str, turn_index: int, post_turn: dict
) -> None:
    """Persist the post-turn output on the turn."""
    await conn.execute(
        "UPDATE turns SET post_turn_json = ? WHERE campaign_id = ? AND turn_index = ?",
        (json.dumps(post_turn, ensure_ascii=False), campaign_id, turn_index),
    )


async def get_turn_state(
    conn: aiosqlite.Connection, campaign_id: str, turn_index: int
) -> dict | None:
    """The turn_state (Narrator input) persisted in agent_decisions_json, for prose reroll.
    None if the turn is missing."""
    cur = await conn.execute(
        "SELECT agent_decisions_json FROM turns WHERE campaign_id = ? AND turn_index = ?",
        (campaign_id, turn_index),
    )
    r = await cur.fetchone()
    if r is None:
        return None
    try:
        return json.loads(r["agent_decisions_json"] or "{}")
    except (json.JSONDecodeError, TypeError):
        return None


async def update_turn_prose(
    conn: aiosqlite.Connection, campaign_id: str, turn_index: int, prose: str
) -> bool:
    """Overwrite a persisted turn's prose (narration reroll). Leaves post-turn and crystals
    untouched."""
    cur = await conn.execute(
        "UPDATE turns SET narrator_prose = ? WHERE campaign_id = ? AND turn_index = ?",
        (prose, campaign_id, turn_index),
    )
    return cur.rowcount > 0


async def update_turn_state(
    conn: aiosqlite.Connection, campaign_id: str, turn_index: int, turn_state: dict
) -> None:
    """Rewrite a turn's agent_decisions_json (reroll preserves _reroll_addenda for the next one)."""
    await conn.execute(
        "UPDATE turns SET agent_decisions_json = ? WHERE campaign_id = ? AND turn_index = ?",
        (json.dumps(turn_state, ensure_ascii=False), campaign_id, turn_index),
    )


async def get_turns(conn: aiosqlite.Connection, campaign_id: str) -> list[dict]:
    cur = await conn.execute(
        "SELECT turn_index, player_input, narrator_prose, trace_json, created_at FROM turns "
        "WHERE campaign_id = ? ORDER BY turn_index",
        (campaign_id,),
    )
    out = []
    for r in await cur.fetchall():
        d = dict(r)
        raw_trace = d.pop("trace_json", None)
        try:
            d["trace"] = json.loads(raw_trace) if raw_trace else []
        except (json.JSONDecodeError, TypeError):
            d["trace"] = []
        try:
            d["player_input"] = json.loads(d["player_input"])
        except (json.JSONDecodeError, TypeError):
            pass  # legacy plain text
        # Sanitize on display: older persisted prose may carry a tool-call tail. Idempotent.
        d["narrator_prose"] = sanitize_prose(d.get("narrator_prose") or "")
        out.append(d)
    return out


async def get_recent_turns_prose(
    conn: aiosqlite.Connection, campaign_id: str, n: int = 30
) -> list[dict]:
    """Last N turns as raw prose, oldest to newest (narrator contract)."""
    cur = await conn.execute(
        "SELECT turn_index, narrator_prose, scene_yaml_snapshot FROM turns "
        "WHERE campaign_id = ? ORDER BY turn_index DESC LIMIT ?",
        (campaign_id, n),
    )
    rows = list(await cur.fetchall())
    rows.reverse()
    out = []
    for r in rows:
        scene_name = ""
        if r["scene_yaml_snapshot"]:
            try:
                scene_name = json.loads(r["scene_yaml_snapshot"]).get("location", "")
            except (json.JSONDecodeError, AttributeError):
                pass
        out.append(
            {
                "turn_index": r["turn_index"],
                "scene_name": scene_name,
                # Sanitize in narrator context too: never feed a tool-call tail as a prior turn.
                "prose": sanitize_prose(r["narrator_prose"] or ""),
            }
        )
    return out


async def get_turns_prose_range(
    conn: aiosqlite.Connection, campaign_id: str, start_index: int, end_index: int
) -> list[dict]:
    """Raw prose for turns in [start_index, end_index] inclusive, oldest to newest. Used by the
    scene crystallizer. Empty/invalid range returns []."""
    if start_index > end_index:
        return []
    cur = await conn.execute(
        "SELECT turn_index, narrator_prose, scene_yaml_snapshot FROM turns "
        "WHERE campaign_id = ? AND turn_index BETWEEN ? AND ? ORDER BY turn_index",
        (campaign_id, start_index, end_index),
    )
    out = []
    for r in await cur.fetchall():
        scene_name = ""
        if r["scene_yaml_snapshot"]:
            try:
                scene_name = json.loads(r["scene_yaml_snapshot"]).get("location", "")
            except (json.JSONDecodeError, AttributeError):
                pass
        out.append(
            {
                "turn_index": r["turn_index"],
                "scene_name": scene_name,
                "prose": sanitize_prose(r["narrator_prose"] or ""),
            }
        )
    return out


# --- crystals ---
async def append_new_crystals(
    conn: aiosqlite.Connection,
    campaign_id: str,
    new_crystals: list[dict],
    source_turn_index: int,
) -> list[str]:
    if not new_crystals:
        return []
    now = _now()
    created: list[str] = []
    for c in new_crystals:
        cid = uuid.uuid4().hex[:12]
        await conn.execute(
            "INSERT INTO crystals (id, campaign_id, category, fact, characters_json, "
            "location, participants_json, witnesses_json, hidden_witnesses_json, source_turn_index, "
            "updated_turn_indices_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                cid,
                campaign_id,
                c["category"],
                c["fact"],
                json.dumps(c.get("characters", []), ensure_ascii=False),
                c.get("location", ""),
                json.dumps(c.get("participants", []), ensure_ascii=False),
                json.dumps(c.get("witnesses", []), ensure_ascii=False),
                json.dumps(c.get("hidden_witnesses", []), ensure_ascii=False),
                source_turn_index,
                json.dumps([], ensure_ascii=False),
                now,
                now,
            ),
        )
        created.append(cid)
    return created


async def apply_crystal_updates(
    conn: aiosqlite.Connection,
    campaign_id: str,
    updates: list[dict],
    source_turn_index: int,
) -> tuple[list[str], list[dict]]:
    """Apply updates by id. Returns (applied_ids, ignored_for_unknown_id)."""
    if not updates:
        return [], []
    now = _now()
    applied: list[str] = []
    ignored: list[dict] = []
    for u in updates:
        uid = u.get("id")
        if not uid:
            ignored.append(u)
            continue
        cur = await conn.execute(
            "SELECT updated_turn_indices_json FROM crystals WHERE id = ? AND campaign_id = ?",
            (uid, campaign_id),
        )
        row = await cur.fetchone()
        if row is None:
            ignored.append(u)
            continue
        history = json.loads(row["updated_turn_indices_json"] or "[]")
        if source_turn_index not in history:
            history.append(source_turn_index)
        # Editable fields.
        sets = []
        params: list = []
        col_map = {
            "category": "category",
            "fact": "fact",
            "location": "location",
            "characters": "characters_json",
            "participants": "participants_json",
            "witnesses": "witnesses_json",
            "hidden_witnesses": "hidden_witnesses_json",
        }
        for field, col in col_map.items():
            if field in u:
                val = u[field]
                sets.append(f"{col} = ?")
                params.append(json.dumps(val, ensure_ascii=False) if col.endswith("_json") else val)
        sets.append("updated_turn_indices_json = ?")
        params.append(json.dumps(history, ensure_ascii=False))
        sets.append("updated_at = ?")
        params.append(now)
        params.extend([uid, campaign_id])
        await conn.execute(
            f"UPDATE crystals SET {', '.join(sets)} WHERE id = ? AND campaign_id = ?", params
        )
        applied.append(uid)
    return applied, ignored


async def delete_crystal(
    conn: aiosqlite.Connection, campaign_id: str, crystal_id: str
) -> bool:
    """Remove a crystal; the delete trigger syncs FTS. True if removed, False if the id is
    not in this campaign."""
    cur = await conn.execute(
        "DELETE FROM crystals WHERE id = ? AND campaign_id = ?", (crystal_id, campaign_id)
    )
    return cur.rowcount > 0


async def _load_crystal_rows(conn: aiosqlite.Connection, campaign_id: str) -> list[aiosqlite.Row]:
    cur = await conn.execute(
        "SELECT * FROM crystals WHERE campaign_id = ? ORDER BY source_turn_index, created_at",
        (campaign_id,),
    )
    return list(await cur.fetchall())


async def get_all_crystals_for_narrator(conn: aiosqlite.Connection, campaign_id: str) -> list[dict]:
    """Lightweight shape for the narrator (no id, no timestamps)."""
    rows = await _load_crystal_rows(conn, campaign_id)
    return [
        {
            "category": r["category"],
            "fact": r["fact"],
            "characters": json.loads(r["characters_json"]),
            "location": r["location"] or "",
            "participants": json.loads(r["participants_json"]),
            "witnesses": json.loads(r["witnesses_json"]),
            "hidden_witnesses": json.loads(r["hidden_witnesses_json"]),
            "source_turn_index": r["source_turn_index"],
        }
        for r in rows
    ]


async def get_promise_crystals(conn: aiosqlite.Connection, campaign_id: str) -> list[dict]:
    """Promise-category crystals in a light shape for the Director briefing. Whether a
    promise is still open is the Director's qualitative read, not a stored flag."""
    cur = await conn.execute(
        "SELECT fact, characters_json, location, participants_json, source_turn_index "
        "FROM crystals WHERE campaign_id = ? AND category = 'promise' "
        "ORDER BY source_turn_index, created_at",
        (campaign_id,),
    )
    rows = await cur.fetchall()
    return [
        {
            "fact": r["fact"],
            "characters": json.loads(r["characters_json"]),
            "participants": json.loads(r["participants_json"]),
            "location": r["location"] or "",
            "source_turn_index": r["source_turn_index"],
        }
        for r in rows
    ]


async def get_all_crystals_for_crystallizer(conn: aiosqlite.Connection, campaign_id: str) -> list[dict]:
    """With id (the crystallizer needs it to UPDATE)."""
    rows = await _load_crystal_rows(conn, campaign_id)
    return [
        {
            "id": r["id"],
            "category": r["category"],
            "fact": r["fact"],
            "characters": json.loads(r["characters_json"]),
            "location": r["location"] or "",
            "participants": json.loads(r["participants_json"]),
            "witnesses": json.loads(r["witnesses_json"]),
            "hidden_witnesses": json.loads(r["hidden_witnesses_json"]),
        }
        for r in rows
    ]


# --- text search (FTS5) ---
async def search_crystals(
    conn: aiosqlite.Connection,
    campaign_id: str,
    q: str,
    *,
    category: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Keyword search over crystals + optional category filter, scoped to the campaign.
    Accent-insensitive. Empty query returns []. Ordered by rank."""
    match = _fts_match_query(q)
    if not match:
        return []
    sql = (
        "SELECT c.id, c.category, c.fact, c.location, c.source_turn_index "
        "FROM crystals_fts JOIN crystals c ON c.rowid = crystals_fts.rowid "
        "WHERE crystals_fts MATCH ? AND c.campaign_id = ?"
    )
    params: list = [match, campaign_id]
    if category:
        sql += " AND c.category = ?"
        params.append(category)
    sql += " ORDER BY crystals_fts.rank LIMIT ?"
    params.append(int(limit))
    cur = await conn.execute(sql, params)
    return [
        {
            "id": r["id"],
            "category": r["category"],
            "fact": r["fact"],
            "location": r["location"] or "",
            "source_turn_index": r["source_turn_index"],
        }
        for r in await cur.fetchall()
    ]


async def search_cards(
    conn: aiosqlite.Connection,
    campaign_id: str,
    q: str,
    *,
    kind: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Keyword search over cards (indexes the whole data_json) + optional kind filter, scoped
    to the campaign. Accent-insensitive. Empty query returns []. Same summary shape as list_cards."""
    match = _fts_match_query(q)
    if not match:
        return []
    sql = (
        "SELECT s.id, s.kind, s.data_json "
        "FROM cards_fts JOIN story_cards s ON s.rowid = cards_fts.rowid "
        "WHERE cards_fts MATCH ? AND s.campaign_id = ?"
    )
    params: list = [match, campaign_id]
    if kind:
        sql += " AND s.kind = ?"
        params.append(kind)
    sql += " ORDER BY cards_fts.rank LIMIT ?"
    params.append(int(limit))
    cur = await conn.execute(sql, params)
    out: list[dict] = []
    for r in await cur.fetchall():
        d = json.loads(r["data_json"])
        cs = d.get("current_state") or {}
        out.append({
            "story_card_id": r["id"],
            "kind": r["kind"],
            "id": d.get("id", ""),
            "name": d.get("name") or (d.get("player_character") or {}).get("name", ""),
            "subtype": d.get("subtype", ""),
            "aliases": d.get("aliases", []),
            "tier": cs.get("tier") or d.get("tier", ""),
            "summary": cs.get("summary_text", ""),
            "status": d.get("status", ""),
            "canonical": d.get("canonical", ""),
        })
    return out


# --- directives (persistent META directives) ---
async def create_directive(
    conn: aiosqlite.Connection,
    campaign_id: str,
    text: str,
    *,
    source_turn_index: int | None = None,
) -> str:
    """Insert an active directive. Returns the id."""
    did = uuid.uuid4().hex
    now = _now()
    await conn.execute(
        "INSERT INTO directives (id, campaign_id, text, active, source_turn_index, "
        "created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?, ?)",
        (did, campaign_id, text, source_turn_index, now, now),
    )
    return did


async def get_active_directives(conn: aiosqlite.Connection, campaign_id: str) -> list[dict]:
    """Active directives as {id, text} for the router + context injection."""
    cur = await conn.execute(
        "SELECT id, text FROM directives WHERE campaign_id = ? AND active = 1 "
        "ORDER BY created_at",
        (campaign_id,),
    )
    return [{"id": r["id"], "text": r["text"]} for r in await cur.fetchall()]


async def get_all_directives(conn: aiosqlite.Connection, campaign_id: str) -> list[dict]:
    """All directives (active and deactivated) for the forget panel."""
    cur = await conn.execute(
        "SELECT id, text, active, source_turn_index, created_at FROM directives "
        "WHERE campaign_id = ? ORDER BY created_at",
        (campaign_id,),
    )
    return [
        {
            "id": r["id"],
            "text": r["text"],
            "active": bool(r["active"]),
            "source_turn_index": r["source_turn_index"],
            "created_at": r["created_at"],
        }
        for r in await cur.fetchall()
    ]


async def deactivate_directive(
    conn: aiosqlite.Connection, campaign_id: str, directive_id: str
) -> bool:
    """Soft-delete a directive (deactivate, not delete). Returns whether anything changed."""
    cur = await conn.execute(
        "UPDATE directives SET active = 0, updated_at = ? "
        "WHERE id = ? AND campaign_id = ? AND active = 1",
        (_now(), directive_id, campaign_id),
    )
    return cur.rowcount > 0


# --- game_clock ---
async def get_clock(conn: aiosqlite.Connection, campaign_id: str) -> dict | None:
    cur = await conn.execute(
        "SELECT * FROM game_clock WHERE campaign_id = ?", (campaign_id,)
    )
    r = await cur.fetchone()
    if r is None:
        return None
    return {
        "campaign_day": r["campaign_day"],
        "current_player_age": r["current_player_age"],
        "current_arc": r["current_arc"],
        "active_characters_by_age": json.loads(r["active_characters_by_age_json"]),
        "player_birth_day": r["player_birth_day"],
        "last_updated_at_turn_index": r["last_updated_at_turn_index"],
    }


async def save_clock(conn: aiosqlite.Connection, campaign_id: str, clock: dict) -> None:
    """Upsert the current clock state (one row per campaign)."""
    await conn.execute(
        "INSERT INTO game_clock (campaign_id, campaign_day, current_player_age, current_arc, "
        "active_characters_by_age_json, player_birth_day, last_updated_at_turn_index) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(campaign_id) DO UPDATE SET "
        "campaign_day=excluded.campaign_day, current_player_age=excluded.current_player_age, "
        "current_arc=excluded.current_arc, "
        "active_characters_by_age_json=excluded.active_characters_by_age_json, "
        "player_birth_day=excluded.player_birth_day, "
        "last_updated_at_turn_index=excluded.last_updated_at_turn_index",
        (
            campaign_id,
            clock["campaign_day"],
            clock["current_player_age"],
            clock.get("current_arc"),
            json.dumps(clock["active_characters_by_age"], ensure_ascii=False),
            clock["player_birth_day"],
            clock["last_updated_at_turn_index"],
        ),
    )


async def append_clock_snapshot(
    conn: aiosqlite.Connection, campaign_id: str, turn_index: int, snapshot: dict
) -> None:
    await conn.execute(
        "INSERT INTO game_clock_snapshots (campaign_id, turn_index, snapshot_json) "
        "VALUES (?, ?, ?) ON CONFLICT(campaign_id, turn_index) DO UPDATE SET "
        "snapshot_json=excluded.snapshot_json",
        (campaign_id, turn_index, json.dumps(snapshot, ensure_ascii=False)),
    )


# --- bounty pending updates (narrative delay) ---
async def add_bounty_pending_update(
    conn: aiosqlite.Connection,
    campaign_id: str,
    *,
    target: str,
    tier: str,
    delta: int,
    reason: str,
    source: str,
    source_turn_index: int,
    scheduled_day: int,
) -> str:
    """Schedule a resolved bounty_delta, applied when the day counter reaches scheduled_day."""
    bid = uuid.uuid4().hex
    await conn.execute(
        "INSERT INTO bounty_pending_updates (id, campaign_id, target, tier, delta, reason, "
        "source, source_turn_index, scheduled_day, applied, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
        (bid, campaign_id, target, tier, int(delta), reason, source,
         source_turn_index, int(scheduled_day), _now()),
    )
    return bid


async def get_open_bounty_pending(
    conn: aiosqlite.Connection, campaign_id: str, target: str
) -> dict | None:
    """The still-unpublished pending bounty for a target, if any. Acts accumulate into this one
    until the day comes and it settles into a single poster (oldest open row wins)."""
    cur = await conn.execute(
        "SELECT id, tier, delta, reason, scheduled_day FROM bounty_pending_updates "
        "WHERE campaign_id = ? AND target = ? AND applied = 0 ORDER BY created_at LIMIT 1",
        (campaign_id, target),
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def bump_bounty_pending(
    conn: aiosqlite.Connection,
    update_id: str,
    *,
    delta: int,
    tier: str,
    reason: str,
    scheduled_day: int,
) -> None:
    """Fold a new act into an open pending bounty: raise the total, keep the headline act's tier
    and reason, and pull the publish day to the earliest so the news still circulates on time."""
    await conn.execute(
        "UPDATE bounty_pending_updates SET delta = ?, tier = ?, reason = ?, scheduled_day = ? "
        "WHERE id = ?",
        (int(delta), tier, reason, int(scheduled_day), update_id),
    )


async def get_due_bounty_updates(
    conn: aiosqlite.Connection, campaign_id: str, current_day: int
) -> list[dict]:
    """Due pending updates (scheduled_day <= current_day) not yet applied."""
    cur = await conn.execute(
        "SELECT id, target, tier, delta, reason, scheduled_day FROM bounty_pending_updates "
        "WHERE campaign_id = ? AND applied = 0 AND scheduled_day <= ? ORDER BY scheduled_day",
        (campaign_id, int(current_day)),
    )
    return [dict(r) for r in await cur.fetchall()]


async def get_pending_bounty_updates(
    conn: aiosqlite.Connection, campaign_id: str
) -> list[dict]:
    """All unapplied pending updates (inspector/debug/turn_complete)."""
    cur = await conn.execute(
        "SELECT id, target, tier, delta, reason, scheduled_day FROM bounty_pending_updates "
        "WHERE campaign_id = ? AND applied = 0 ORDER BY scheduled_day",
        (campaign_id,),
    )
    return [dict(r) for r in await cur.fetchall()]


async def mark_bounty_update_applied(
    conn: aiosqlite.Connection, update_id: str, applied_at_day: int
) -> None:
    await conn.execute(
        "UPDATE bounty_pending_updates SET applied = 1, applied_at_day = ? WHERE id = ?",
        (int(applied_at_day), update_id),
    )


# --- research/designer caches ---
async def get_canonical_briefing(
    conn: aiosqlite.Connection, island_slug: str, canon_version: str
) -> str | None:
    """Global cached canon briefing (per island + canon version, not per campaign). None on
    miss to trigger the research pipeline."""
    cur = await conn.execute(
        "SELECT briefing_md FROM canonical_briefings WHERE island_slug = ? AND canon_version = ?",
        (island_slug, canon_version),
    )
    r = await cur.fetchone()
    return r["briefing_md"] if r is not None else None


async def save_canonical_briefing(
    conn: aiosqlite.Connection, island_slug: str, canon_version: str, briefing_md: str
) -> None:
    await conn.execute(
        "INSERT OR REPLACE INTO canonical_briefings (island_slug, canon_version, briefing_md, "
        "generated_at) VALUES (?, ?, ?, ?)",
        (island_slug, canon_version, briefing_md, _now()),
    )


async def get_invented_context(
    conn: aiosqlite.Connection, campaign_id: str, island_slug: str
) -> dict | None:
    """Per-campaign cached invented-island context (invented islands vary between runs). None
    on miss to trigger the Island Designer."""
    cur = await conn.execute(
        "SELECT context_json FROM invented_contexts WHERE campaign_id = ? AND island_slug = ?",
        (campaign_id, island_slug),
    )
    r = await cur.fetchone()
    return json.loads(r["context_json"]) if r is not None else None


async def save_invented_context(
    conn: aiosqlite.Connection, campaign_id: str, island_slug: str, context: dict
) -> None:
    await conn.execute(
        "INSERT OR REPLACE INTO invented_contexts (campaign_id, island_slug, context_json, "
        "generated_at) VALUES (?, ?, ?, ?)",
        (campaign_id, island_slug, json.dumps(context, ensure_ascii=False), _now()),
    )
