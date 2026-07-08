"""CLIProxyAPI management API (boot-flow).

The management key authenticates the backend to the proxy's `/v0/management/*` endpoints
(`Authorization: Bearer <key>`). The proxy hashes the plaintext secret-key in its config.yaml
at startup, so the canonical plaintext lives in app_settings.json (`proxy_mgmt_key`, never in
the public view). At boot, before auto-spawn, `ensure_management_key()` generates the key if
missing and seeds config.yaml only when its secret-key is empty (a non-empty value may be the
hash of ours, so it is left alone). Override via env PROXY_MGMT_KEY.
"""
from __future__ import annotations

import os
import re
import secrets
from pathlib import Path

import httpx

from .. import app_settings, config
from . import spawn

CONFIG_PATH: Path = spawn.PROXY_DIR / spawn.CONFIG_NAME


def management_key() -> str:
    """Plaintext key: env > app_settings. Empty = not initialized yet."""
    env = os.environ.get("PROXY_MGMT_KEY", "").strip()
    if env:
        return env
    return app_settings.load().get("proxy_mgmt_key", "")


def ensure_management_key() -> str:
    """Idempotent, called in the lifespan BEFORE auto-spawn: ensures the key is generated and
    seeded into config.yaml (when the file exists and its secret is empty)."""
    env = os.environ.get("PROXY_MGMT_KEY", "").strip()
    if env:
        return env
    key = app_settings.load().get("proxy_mgmt_key", "")
    if not key:
        key = "oprpg-mgmt-" + secrets.token_urlsafe(24)
        app_settings.update({"proxy_mgmt_key": key})
    _seed_config(key)
    return key


def _seed_config(key: str) -> None:
    """Write the key into config.yaml only when its secret-key is empty/absent. Surgical text
    edit to preserve comments (PyYAML would rewrite the file)."""
    if not CONFIG_PATH.is_file():
        return
    text = CONFIG_PATH.read_text(encoding="utf-8")
    empty = re.search(r"(?m)^(\s*)secret-key:\s*(?:\"\"|'')?\s*$", text)
    if empty:
        text = text[: empty.start()] + f'{empty.group(1)}secret-key: "{key}"' + text[empty.end():]
    elif re.search(r"(?m)^\s*secret-key:", text):
        return  # already has a value (possibly the hash of ours); do not overwrite
    elif re.search(r"(?m)^remote-management:", text):
        text = re.sub(
            r"(?m)^remote-management:\s*$",
            f'remote-management:\n  secret-key: "{key}"',
            text,
            count=1,
        )
    else:
        text += f'\nremote-management:\n  secret-key: "{key}"\n'
    CONFIG_PATH.write_text(text, encoding="utf-8")


async def request_auth_url(key: str, timeout: float = 15.0) -> dict:
    """GET /v0/management/anthropic-auth-url on the proxy; returns the proxy JSON. Raises
    HTTPStatusError on non-2xx (caller maps it to an actionable error).

    `is_webui=1` is required: without it the proxy assumes its own TUI/CLI login and does not
    open the port 54545 forwarder, so the OAuth redirect dies with ERR_CONNECTION_REFUSED."""
    url = config.PROXY_URL.rstrip("/") + "/v0/management/anthropic-auth-url"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(
            url,
            params={"is_webui": "1"},
            headers={"Authorization": f"Bearer {key}"},
        )
    resp.raise_for_status()
    return resp.json()
