"""App preferences — app config, not the save.

Lives in a JSON file separate from the character SQLite (`data/app_settings.json`) so
switching or deleting a campaign does not reset preferences. `proxy_url`/`proxy_key` here
override the env default and survive restart; `apply_to_runtime()` reflects changes at runtime
without a restart (settings are data, and uvicorn runs without --reload, which only reloads code).
"""
from __future__ import annotations

import json
from pathlib import Path

from . import config

SETTINGS_PATH: Path = config.DB_PATH.parent / "app_settings.json"

# Language here is the default for NEW campaigns; each campaign freezes its own at creation.
_ALLOWED_THEMES = ("dark", "light")
_ALLOWED_LANGUAGES = ("pt-br", "en")


def defaults() -> dict:
    """Defaults from env/`config` (proxy) + chrome preferences."""
    return {
        "theme": "dark",
        "language": "pt-br",
        "proxy_url": config.PROXY_URL,
        "proxy_key": config.PROXY_KEY,
        "auto_spawn_proxy": True,
        "setup_completed": False,
        # CLIProxyAPI management key plaintext (the proxy hashes its own copy in config.yaml
        # at boot; this is canonical). Never exposed in the public view.
        "proxy_mgmt_key": "",
    }


def _coerce(raw: dict) -> dict:
    """Merge raw over defaults and validate enums (invalid value falls back to default)."""
    out = defaults()
    if isinstance(raw, dict):
        if raw.get("theme") in _ALLOWED_THEMES:
            out["theme"] = raw["theme"]
        if raw.get("language") in _ALLOWED_LANGUAGES:
            out["language"] = raw["language"]
        if isinstance(raw.get("proxy_url"), str) and raw["proxy_url"].strip():
            out["proxy_url"] = raw["proxy_url"].strip()
        if isinstance(raw.get("proxy_key"), str) and raw["proxy_key"].strip():
            out["proxy_key"] = raw["proxy_key"].strip()
        if isinstance(raw.get("auto_spawn_proxy"), bool):
            out["auto_spawn_proxy"] = raw["auto_spawn_proxy"]
        if isinstance(raw.get("setup_completed"), bool):
            out["setup_completed"] = raw["setup_completed"]
        if isinstance(raw.get("proxy_mgmt_key"), str):
            out["proxy_mgmt_key"] = raw["proxy_mgmt_key"].strip()
    return out


def load() -> dict:
    """Read the file, or return defaults if missing/corrupt."""
    try:
        raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        raw = {}
    return _coerce(raw)


def save(settings: dict) -> dict:
    """Write the coerced JSON and return the final state."""
    final = _coerce(settings)
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return final


def update(patch: dict) -> dict:
    """Apply a partial patch over current state, persist, and reflect at runtime."""
    merged = load()
    if isinstance(patch, dict):
        # patch overwrites only present keys (an empty proxy_key does not erase the saved key).
        for k in ("theme", "language", "proxy_url", "proxy_key", "auto_spawn_proxy",
                  "setup_completed", "proxy_mgmt_key"):
            if k in patch and patch[k] not in (None, ""):
                merged[k] = patch[k]
            elif k in patch and patch[k] == "" and k in ("proxy_url",):
                # empty url resets to default (disallowed for proxy_key, for safety)
                merged[k] = defaults()[k]
    final = save(merged)
    apply_to_runtime(final)
    return final


def _mask_key(key: str) -> str:
    """Mask the key for display (show only the suffix)."""
    if not key:
        return ""
    return ("•" * max(0, len(key) - 4)) + key[-4:] if len(key) > 4 else "••••"


def public_view(settings: dict | None = None) -> dict:
    """UI view: never returns the raw `proxy_key`, only masked + a presence flag."""
    s = settings or load()
    return {
        "theme": s["theme"],
        "language": s["language"],
        "proxy_url": s["proxy_url"],
        "proxy_key_masked": _mask_key(s.get("proxy_key", "")),
        "proxy_key_set": bool(s.get("proxy_key")),
        "auto_spawn_proxy": s["auto_spawn_proxy"],
        "setup_completed": s["setup_completed"],
        "allowed_themes": list(_ALLOWED_THEMES),
        "allowed_languages": list(_ALLOWED_LANGUAGES),
    }


def apply_to_runtime(settings: dict | None = None) -> None:
    """Override `config.PROXY_URL`/`PROXY_KEY` with the saved values and force the proxy client
    to be recreated (picks up the new credential on next use). Idempotent; called at boot and on
    each settings PUT. Late client import avoids a cycle."""
    s = settings or load()
    config.PROXY_URL = s["proxy_url"]
    config.PROXY_KEY = s["proxy_key"]
    try:
        from .proxy import client as _client

        _client._client = None  # recreate with the new base_url/api_key on next get_client()
    except Exception:  # noqa: BLE001 best-effort; no client yet at boot is fine
        pass
