"""POST /api/setup/connect-claude: Claude OAuth broker. The frontend never talks to the proxy
nor sees the management key; it requests the auth URL here and polls /api/health for completion.
Structured errors {"error", "detail"} for actionable UI."""
from __future__ import annotations

import asyncio

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..proxy import mgmt, spawn as proxy_spawn
from ..proxy.health import check_proxy

router = APIRouter(prefix="/api/setup", tags=["setup"])


def _err(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "detail": detail})


@router.post("/connect-claude")
async def connect_claude():
    key = mgmt.management_key()
    if not key:
        return _err(
            409,
            "mgmt_key_missing",
            "Management key ausente: config do proxy não inicializada (reinicie o jogo).",
        )

    probe = await check_proxy(timeout=2.0)
    if not probe.get("reachable"):
        if not proxy_spawn.binary_exists():
            return _err(
                409,
                "binary_missing",
                f"Binário do CLIProxyAPI ausente em {proxy_spawn.BINARY_PATH}.",
            )
        proxy_spawn.managed.start()
        for _ in range(10):  # up to ~5s for the proxy to open the port
            await asyncio.sleep(0.5)
            probe = await check_proxy(timeout=1.0)
            if probe.get("reachable"):
                break
        if not probe.get("reachable"):
            return _err(
                502,
                "proxy_unreachable",
                proxy_spawn.managed.error or probe.get("error", "proxy não respondeu"),
            )

    try:
        data = await mgmt.request_auth_url(key)
    except httpx.HTTPStatusError as exc:
        return _err(502, "mgmt_error", f"management API respondeu {exc.response.status_code}")
    except Exception as exc:  # noqa: BLE001 network/timeout becomes an actionable error
        return _err(502, "proxy_unreachable", f"{type(exc).__name__}: {exc}")
    return {"auth_url": data["url"], "state": data.get("state")}
