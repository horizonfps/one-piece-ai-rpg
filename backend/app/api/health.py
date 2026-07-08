"""GET /api/health: proxy + DB + model lineup liveness. Also serves GET /api/player-guide."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import config
from ..db import connection
from ..proxy import spawn as proxy_spawn
from ..proxy.health import check_proxy

router = APIRouter(prefix="/api", tags=["health"])

PLAYER_GUIDE_PATHS = {
    "en": config.REPO_ROOT / "docs" / "PLAYER_GUIDE.md",
    "pt-br": config.REPO_ROOT / "docs" / "PLAYER_GUIDE.pt-BR.md",
}


@router.get("/player-guide")
async def player_guide(lang: str = "pt-br") -> dict:
    """Player guide markdown by UI language, read from disk each call."""
    lang = lang.lower()
    primary = PLAYER_GUIDE_PATHS.get(lang, PLAYER_GUIDE_PATHS["pt-br"])
    for path in (primary, *PLAYER_GUIDE_PATHS.values()):
        try:
            return {"markdown": path.read_text(encoding="utf-8")}
        except OSError:
            continue
    raise HTTPException(status_code=404, detail="player_guide_not_found")


@router.get("/health")
async def health() -> dict:
    proxy = await check_proxy()
    # First-launch: surface Claude auth file + auto-spawn state so the title screen can show
    # an actionable error (no auth routes to the setup wizard).
    proxy["auth_present"] = proxy_spawn.auth_present()
    proxy["spawn_managed"] = proxy_spawn.managed.running
    proxy["binary_present"] = proxy_spawn.binary_exists()

    db_status: dict
    try:
        conn = await connection.connect()
        try:
            cur = await conn.execute("PRAGMA user_version;")
            row = await cur.fetchone()
            db_status = {
                "ok": True,
                "schema_version": int(row[0]) if row else 0,
                "path": str(config.DB_PATH),
            }
        finally:
            await conn.close()
    except Exception as exc:  # noqa: BLE001
        db_status = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    return {
        "ok": bool(proxy["reachable"] and db_status.get("ok")),
        "proxy": proxy,
        "db": db_status,
        "models": {
            "narrator": config.NARRATOR_MODEL,
            "agent": config.AGENT_MODEL,
            "crystallizer": config.CRYSTALLIZER_MODEL,
            "director": config.DIRECTOR_MODEL,
        },
    }
