"""CLIProxyAPI healthcheck. Any HTTP response counts as reachable, including 401/404;
this checks reachability, not authentication.
"""
from __future__ import annotations

import httpx

from .. import config


async def check_proxy(timeout: float = 3.0) -> dict:
    url = config.PROXY_URL.rstrip("/") + "/v1/models"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers={"x-api-key": config.PROXY_KEY})
        return {"reachable": True, "status": resp.status_code, "url": config.PROXY_URL}
    except Exception as exc:  # noqa: BLE001 any network failure = proxy down
        return {
            "reachable": False,
            "error": f"{type(exc).__name__}: {exc}",
            "url": config.PROXY_URL,
        }
