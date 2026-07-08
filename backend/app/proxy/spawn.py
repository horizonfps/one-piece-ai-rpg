"""Auto-spawn CLIProxyAPI as a backend subprocess.

At boot, if the proxy is not reachable and auto-spawn is enabled, the backend launches the
`cli-proxy-api` binary (cwd at the proxy dir to resolve `./auths` and config.yaml) and tears
it down at shutdown. `should_spawn` is a pure decision; `ProxyProcess` owns the lifecycle
(start/stop best-effort)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .. import config

# CLIProxyAPI directory in the repo (binary + config.yaml + auths/).
PROXY_DIR: Path = config.REPO_ROOT / "cliproxyapi"
_BINARY_NAME = "cli-proxy-api.exe" if sys.platform == "win32" else "cli-proxy-api"
BINARY_PATH: Path = PROXY_DIR / "bin" / _BINARY_NAME
CONFIG_NAME = "config.yaml"
AUTHS_DIR: Path = PROXY_DIR / "auths"


def binary_exists() -> bool:
    return BINARY_PATH.is_file()


def auth_present() -> bool:
    """Auto-detect the Claude auth file: is there a `claude-*.json` in `cliproxyapi/auths/`?
    Without it the proxy starts but does not authenticate."""
    try:
        return any(AUTHS_DIR.glob("claude-*.json"))
    except OSError:
        return False


def should_spawn(*, reachable: bool, enabled: bool, binary_ok: bool) -> bool:
    """Spawn only when the proxy is not already up (`reachable=False`), auto-spawn is enabled,
    and the binary exists in the repo. Pure function (no I/O)."""
    return (not reachable) and enabled and binary_ok


class ProxyProcess:
    """Manages the CLIProxyAPI subprocess. Best-effort: a spawn failure does not take down the
    backend (the title screen still shows the actionable error)."""

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.error: str | None = None

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> bool:
        """Start the binary if not already running. Returns True if it started."""
        if self.running:
            return False
        if not binary_exists():
            self.error = f"binário ausente: {BINARY_PATH}"
            return False
        try:
            self.proc = subprocess.Popen(
                [str(BINARY_PATH), "-config", CONFIG_NAME],
                cwd=str(PROXY_DIR),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.error = None
            return True
        except Exception as exc:  # noqa: BLE001 best-effort
            self.error = f"{type(exc).__name__}: {exc}"
            self.proc = None
            return False

    def stop(self) -> None:
        """Tear down the subprocess at shutdown (terminate then kill on a short timeout)."""
        if self.proc is None:
            return
        if self.proc.poll() is None:
            try:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            except Exception:  # noqa: BLE001 best-effort on shutdown
                pass
        self.proc = None


# Managed-process singleton (1 backend = 1 proxy), used by the FastAPI lifespan.
managed = ProxyProcess()
