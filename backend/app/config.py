"""Central backend config from env + .env (dotenv)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent

load_dotenv(BACKEND_DIR / ".env")


def _path_env(key: str, default: Path) -> Path:
    val = os.environ.get(key, "").strip()
    return Path(val) if val else default


# Paths
PROMPTS_DIR = _path_env("OPRPG_PROMPTS_DIR", REPO_ROOT / "prompts")
FRONTEND_DIST = _path_env("OPRPG_FRONTEND_DIST", REPO_ROOT / "frontend" / "dist")
DB_PATH = _path_env("OPRPG_DB_PATH", BACKEND_DIR / "data" / "campaign.db")
MIGRATIONS_DIR = BACKEND_DIR / "app" / "db" / "migrations"

# CLIProxyAPI
PROXY_URL = os.environ.get("ANTHROPIC_PROXY_URL", "http://127.0.0.1:8318").strip()
PROXY_KEY = os.environ.get("ANTHROPIC_PROXY_KEY", "onepiece-proxy-key").strip()

# Every role runs on Sonnet 5 (default adaptive thinking). Sonnet 5 rejects non-default
# sampling params (temperature/top_p/top_k → 400); the proxy client omits them per model.
NARRATOR_MODEL = os.environ.get("NARRATOR_MODEL", "claude-sonnet-5")
AGENT_MODEL = os.environ.get("AGENT_MODEL", "claude-sonnet-5")
CRYSTALLIZER_MODEL = os.environ.get("CRYSTALLIZER_MODEL", "claude-sonnet-5")
DIRECTOR_MODEL = os.environ.get("DIRECTOR_MODEL", "claude-sonnet-5")
META_ROUTER_MODEL = os.environ.get("META_ROUTER_MODEL", "claude-sonnet-5")
# Post-turn Auditor: final gate over the whole turn (prose + generated cards + deltas) before
# the player sees the prose. Opus like the narrator, since it may rewrite prose.
AUDITOR_MODEL = os.environ.get("AUDITOR_MODEL", NARRATOR_MODEL)
# Evolutive World (FASE 33): the departure-snapshot generator (freeze) and the return-reconciler
# both write factual card content, not player-facing prose, so Sonnet like the other generators.
DEPARTURE_MODEL = os.environ.get("DEPARTURE_MODEL", AGENT_MODEL)
RECONCILE_MODEL = os.environ.get("RECONCILE_MODEL", AGENT_MODEL)
AGENT_TEMPERATURE = float(os.environ.get("AGENT_TEMPERATURE", "0.7"))
DIRECTOR_TEMPERATURE = float(os.environ.get("DIRECTOR_TEMPERATURE", "0.7"))
# META router is a classifier/decisional path; 0.5 is the validated sweet spot.
META_ROUTER_TEMPERATURE = float(os.environ.get("META_ROUTER_TEMPERATURE", "0.5"))

# Tool-call reasoning. Forced tool_choice suppresses adaptive thinking (measured against the
# proxy: thinking_tokens=0 even with effort or explicit adaptive), so tool roles ran with zero
# reasoning. Setting TOOL_EFFORT switches the tool path to tool_choice=auto + adaptive thinking
# at this effort, with a forced-tool fallback when the model skips the call. Empty = legacy
# forced path (no thinking). Levels: low|medium|high|xhigh|max (xhigh/max need Sonnet 5 /
# Opus 4.7+ / Fable 5).
TOOL_EFFORT = os.environ.get("TOOL_EFFORT", "").strip()
# Thinking tokens count toward max_tokens; widen the ceiling on the reasoning path so thinking
# cannot starve the structured tool output. A per-call max_tokens above this is respected.
TOOL_THINKING_MAX_TOKENS = int(os.environ.get("TOOL_THINKING_MAX_TOKENS", "16000"))

# Canon research uses the Fandom MediaWiki API (HTML scraping returns 403; the api.php returns
# 200). Descriptive user-agent. `CANON_VERSION` keys the `canonical_briefings` cache; bump it
# when a new manga milestone invalidates everything.
FANDOM_API_URL = os.environ.get("FANDOM_API_URL", "https://onepiece.fandom.com/api.php").strip()
FANDOM_USER_AGENT = os.environ.get(
    "FANDOM_USER_AGENT",
    "OnePieceRPG/0.1 (local single-player TRPG; canon research; +https://github.com/)",
).strip()
CANON_VERSION = os.environ.get("CANON_VERSION", "post-egghead-2026-05").strip()

# Threshold (seconds) above which a 429 with a long `retry-after` is treated as a subscription
# quota window (pauses the turn) instead of an RPM burst. Default 5min.
QUOTA_RESET_THRESHOLD_S = int(os.environ.get("OPRPG_QUOTA_RESET_THRESHOLD_S", "300"))

# Post-turn Auditor wall-clock budget. On timeout/error the original prose is released
# untouched (best-effort gate).
AUDIT_TIMEOUT_S = float(os.environ.get("OPRPG_AUDIT_TIMEOUT_S", "90"))
