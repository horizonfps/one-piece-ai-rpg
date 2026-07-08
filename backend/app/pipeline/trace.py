"""Devtools trace: captures each turn's LLM call input/output. One per-turn buffer lives in
a `ContextVar`; the proxy client records after each call and the runner injects the buffer
into the terminal event. Not persisted; live WebSocket only, no-op when no buffer is active.

The buffer is a shared mutable list held by reference: tasks spawned via `asyncio.gather`
copy the context (already holding the buffer) at creation, so they all append to the SAME list."""
from __future__ import annotations

import contextvars
import json

_buf: contextvars.ContextVar[list | None] = contextvars.ContextVar("llm_trace", default=None)

# Per-INPUT-section cap; OUTPUT (the LLM decision) is never truncated.
MAX_INPUT_CHARS = 14000


def start() -> list:
    """Start a fresh buffer for the current turn and return the reference."""
    buf: list = []
    _buf.set(buf)
    return buf


def current() -> list | None:
    """Active buffer, or None if no turn started a trace."""
    return _buf.get()


def _safe(obj):
    """Ensure JSON-serializable, falling back to str() for exotic objects."""
    try:
        json.dumps(obj, ensure_ascii=False)
        return obj
    except (TypeError, ValueError):
        return str(obj)


def _render_sections(sections) -> list[dict]:
    """Render the call's dynamic input `sections` into readable title/body blocks."""
    out: list[dict] = []
    for title, body in sections or []:
        if isinstance(body, (dict, list)):
            text = json.dumps(_safe(body), ensure_ascii=False, indent=2)
        else:
            text = str(body)
        truncated = len(text) > MAX_INPUT_CHARS
        if truncated:
            text = text[:MAX_INPUT_CHARS] + "\n… (truncado)"
        out.append({"title": str(title), "body": text, "truncated": truncated})
    return out


def record(*, tag, model, sections, output, label=None, instructions_chars=0, usage=None) -> None:
    """Append a trace entry to the active buffer; no-op if none. `usage` = real API tokens."""
    buf = _buf.get()
    if buf is None:
        return
    buf.append({
        "seq": len(buf) + 1,
        "tag": tag,
        "label": label or tag,
        "model": model,
        "instructions_chars": instructions_chars,
        "usage": usage,
        "input": _render_sections(sections),
        "output": _safe(output),
    })
