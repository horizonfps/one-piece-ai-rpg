"""FastAPI entrypoint.

In production (web-local) serves the static Svelte build + the API in one process. In dev,
Vite serves the frontend on :5173 and proxies /api here; without a build, `/` is a JSON
placeholder.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import app_settings, config
from .api import campaigns, catalog as catalog_api, health, settings as settings_api, setup as setup_api
from .db import catalog, connection
from .db.migrate import run_migrations
from .proxy import mgmt as proxy_mgmt, spawn as proxy_spawn
from .proxy.health import check_proxy


@asynccontextmanager
async def lifespan(app: FastAPI):
    result = await run_migrations()
    print(f"[db] migrations: schema_version={result['schema_version']} applied={result['applied']}")
    # Creation catalogs: imported from canonical YAMLs at boot (idempotent upsert).
    conn = await connection.connect()
    try:
        counts = await catalog.import_catalogs(conn)
        print(f"[db] catálogos: {counts}")
    finally:
        await conn.close()

    # Apply persisted preferences (proxy url/key override env).
    app_state = app_settings.load()
    app_settings.apply_to_runtime(app_state)

    # Boot-flow: ensure the management key BEFORE auto-spawn so the wizard's "Open in Browser"
    # button works on first run.
    mgmt_key = proxy_mgmt.ensure_management_key()
    print(f"[proxy] management key: {'ok' if mgmt_key else 'ausente'}")

    # Auto-spawn CLIProxyAPI if not up and enabled. Best-effort: failure does not take down the
    # backend (the title screen shows the actionable error + retry, with no polling loop).
    probe = await check_proxy(timeout=2.0)
    if proxy_spawn.should_spawn(
        reachable=bool(probe.get("reachable")),
        enabled=bool(app_state.get("auto_spawn_proxy", True)),
        binary_ok=proxy_spawn.binary_exists(),
    ):
        started = proxy_spawn.managed.start()
        print(f"[proxy] auto-spawn: {'iniciado' if started else proxy_spawn.managed.error or 'já rodando'}")

    yield

    # Shutdown: tear down the proxy we started (if we did).
    proxy_spawn.managed.stop()


app = FastAPI(title="One Piece RPG", version="0.1.0", lifespan=lifespan)

# Dev: Vite (5173) -> backend (8400). In prod everything is same-origin; CORS is inert.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# /api/* registered BEFORE the SPA catch-all for match priority.
app.include_router(health.router)
app.include_router(settings_api.router)
app.include_router(setup_api.router)
app.include_router(catalog_api.router)
app.include_router(campaigns.router)


if config.FRONTEND_DIST.exists():
    _assets = config.FRONTEND_DIST / "assets"
    if _assets.exists():
        app.mount("/assets", StaticFiles(directory=_assets), name="assets")

    @app.get("/")
    async def index():
        return FileResponse(config.FRONTEND_DIST / "index.html")

    @app.get("/{path:path}")
    async def spa_fallback(path: str):
        candidate = config.FRONTEND_DIST / path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(config.FRONTEND_DIST / "index.html")
else:

    @app.get("/")
    async def index_placeholder():
        return JSONResponse(
            {
                "app": "One Piece RPG — backend",
                "frontend_build": (
                    "ausente — em dev rode `npm run dev` em frontend/ (Vite serve em :5173 "
                    "e faz proxy de /api). Pra servir daqui, `npm run build`."
                ),
                "health": "/api/health",
            }
        )
