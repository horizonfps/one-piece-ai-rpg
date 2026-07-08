"""Async CLIProxyAPI client with the cloaking workaround.

OAuth mode drops the `system` param, so each component's prompt goes inside the first
user message between `<{tag}-instructions>...</{tag}-instructions>` tags. Never pass `system=`.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import AsyncIterator

from anthropic import AsyncAnthropic

from .. import config
from ..pipeline import trace
from . import errors

_client: AsyncAnthropic | None = None
_client_loop: asyncio.AbstractEventLoop | None = None


def get_client() -> AsyncAnthropic:
    """Async proxy client, keyed by the running event loop.

    httpx's TCP pool is bound to the loop that opened it; reusing the client on a
    different loop raises "Event loop is closed". Recreating per-loop gives each loop its
    own pool (fixes the pytest-asyncio flake) without affecting production or prompt
    caching, which lives in the request content.
    """
    global _client, _client_loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _client is None or _client_loop is not loop:
        # Drop only EMPTY inherited ANTHROPIC_AUTH_TOKEN/ANTHROPIC_BASE_URL; an empty
        # value makes the SDK send an invalid `Authorization: Bearer`. Real values kept.
        for _var in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
            if os.environ.get(_var, None) == "":
                os.environ.pop(_var, None)
        _client = AsyncAnthropic(api_key=config.PROXY_KEY, base_url=config.PROXY_URL)
        _client_loop = loop
    return _client


def _usage(response) -> dict | None:
    """Token usage from the API response (devtools); includes cache fields to show hits."""
    u = getattr(response, "usage", None)
    if u is None:
        return None
    return {
        "input": int(getattr(u, "input_tokens", 0) or 0),
        "output": int(getattr(u, "output_tokens", 0) or 0),
        "cache_read": int(getattr(u, "cache_read_input_tokens", 0) or 0),
        "cache_creation": int(getattr(u, "cache_creation_input_tokens", 0) or 0),
    }


# Prompt caching: the large STATIC prefix (cloaked prompt + tools) carries `cache_control`,
# so from turn 2 it is a cache read while only dynamic `sections` pay full price. TTL is 1h
# to survive the player's think time between turns; requires the beta header below.
_CACHE_CONTROL = {"type": "ephemeral", "ttl": "1h"}
_CACHE_HEADERS = {"anthropic-beta": "extended-cache-ttl-2025-04-11"}

# Models that 400 on non-default sampling params (temperature/top_p/top_k). Introduced with
# Opus 4.7; Sonnet 5 / Fable 5 / Opus 4.8 inherit it. For these the caller's temperature is
# dropped and behavior is steered by the prompt instead.
_NO_SAMPLING_MODELS = ("claude-sonnet-5", "claude-fable-5", "claude-opus-4-7", "claude-opus-4-8")


def _accepts_temperature(model: str) -> bool:
    return not any(model.startswith(p) for p in _NO_SAMPLING_MODELS)


def _extract_tool_use(response, tool_name: str) -> dict | None:
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == tool_name:
            return dict(block.input)
    return None


async def _messages_create(**create_kwargs):
    """`messages.create` with quota classification. The SDK retries transient 429/timeout;
    on exhaustion the Claude Max subscription limit is reclassified to QuotaExceededError."""
    try:
        return await get_client().messages.create(**create_kwargs)
    except Exception as exc:  # noqa: BLE001 reclassify only
        raise errors.classify_api_error(exc, threshold_s=config.QUOTA_RESET_THRESHOLD_S) from exc


def _refusal_guard(response, *, stage: str) -> None:
    """Raise ModelRefusalError if the model declined via safety filter; surfaced to the
    player to rephrase, with no retry or prose fallback."""
    if errors.is_refusal_stop_reason(getattr(response, "stop_reason", None)):
        raise errors.ModelRefusalError(stage=stage)


def _render_sections(sections: list[tuple[str, object]]) -> str:
    parts = []
    for title, body in sections:
        if isinstance(body, (dict, list)):
            rendered = "```json\n" + json.dumps(body, ensure_ascii=False, indent=2) + "\n```"
        else:
            rendered = str(body)
        parts.append(f"# {title}\n\n{rendered}")
    return "\n\n".join(parts)


def build_content(
    instructions: str,
    tag: str,
    sections: list[tuple[str, object]],
    cached_sections: list[tuple[str, object]] | None = None,
    volatile_instructions: str | None = None,
) -> list[dict]:
    """Cloaked + cached user-message blocks. Block 0 = static instructions with
    `cache_control` (breakpoint caches tools + this block). Optional block 1 = near-static
    `cached_sections` with its own breakpoint (large catalogs that rarely change; a change
    busts the cache once). Rendering must be byte-identical turn to turn (caller orders
    deterministically). Optional `volatile_instructions` = per-turn conditional addenda in
    their own block AFTER the breakpoints (inside block 0 they would bust the whole prefix
    every turn). Final block = dynamic `sections`, uncached."""
    blocks: list[dict] = [{
        "type": "text",
        "text": f"<{tag}-instructions>\n{instructions}\n</{tag}-instructions>",
        "cache_control": _CACHE_CONTROL,
    }]
    if cached_sections:
        blocks.append({
            "type": "text",
            "text": _render_sections(cached_sections),
            "cache_control": _CACHE_CONTROL,
        })
    if volatile_instructions:
        blocks.append({
            "type": "text",
            "text": f"<{tag}-instructions-addenda>\n{volatile_instructions}\n</{tag}-instructions-addenda>",
        })
    if sections:
        blocks.append({"type": "text", "text": _render_sections(sections)})
    return blocks


async def call_tool(
    *,
    model: str,
    instructions: str,
    tag: str,
    sections: list[tuple[str, object]],
    cached_sections: list[tuple[str, object]] | None = None,
    volatile_instructions: str | None = None,
    tool: dict,
    tool_name: str,
    temperature: float | None = None,
    max_tokens: int = 4096,
    trace_label: str | None = None,
    effort: str | None = None,
) -> dict:
    """Call the proxy with a tool; returns the tool_use `input`.

    Reasoning path (`effort` or `config.TOOL_EFFORT` set): tool_choice=auto so the model can
    think (forced tool_choice suppresses adaptive thinking), steered by `effort`, with a widened
    max_tokens so thinking does not starve the output. Falls back to the forced path if the
    model answers without calling the tool. Default path (no effort): forced tool, no thinking."""
    content = build_content(instructions, tag, sections, cached_sections, volatile_instructions)
    base: dict = dict(
        model=model,
        messages=[{"role": "user", "content": content}],
        tools=[tool],
        extra_headers=_CACHE_HEADERS,
    )
    if temperature is not None and _accepts_temperature(model):
        base["temperature"] = temperature

    effort = effort or config.TOOL_EFFORT or None
    response = None
    result = None
    if effort:
        response = await _messages_create(
            **base,
            max_tokens=max(max_tokens, config.TOOL_THINKING_MAX_TOKENS),
            tool_choice={"type": "auto"},
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
        )
        result = _extract_tool_use(response, tool_name)

    if result is None:
        # Default path, or reasoning fallback: force the tool to guarantee structured output.
        response = await _messages_create(
            **base, max_tokens=max_tokens, tool_choice={"type": "tool", "name": tool_name}
        )
        result = _extract_tool_use(response, tool_name)

    if result is not None:
        trace.record(
            tag=tag, model=model,
            sections=[*(cached_sections or []), *sections], output=result,
            label=trace_label,
            instructions_chars=len(instructions) + len(volatile_instructions or ""),
            usage=_usage(response),
        )
        return result

    # No tool_use: content refusal surfaces to the player; truncation/other stop_reason
    # raises RuntimeError (caller's retry covers it).
    _refusal_guard(response, stage=tag)
    raise RuntimeError(
        f"Resposta sem tool_use de {tool_name}. stop_reason={response.stop_reason}, "
        f"content types={[getattr(b, 'type', '?') for b in response.content]}"
    )


async def call_text(
    *,
    model: str,
    instructions: str,
    tag: str,
    sections: list[tuple[str, object]],
    max_tokens: int = 2500,
    temperature: float | None = None,
    trace_label: str | None = None,
) -> str:
    """Call the proxy expecting plain text (narrator path); returns the string."""
    content = build_content(instructions, tag, sections)
    create_kwargs: dict = dict(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": content}],
        extra_headers=_CACHE_HEADERS,
    )
    if temperature is not None and _accepts_temperature(model):
        create_kwargs["temperature"] = temperature
    response = await _messages_create(**create_kwargs)
    text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
    if not text:
        _refusal_guard(response, stage=tag)
    trace.record(
        tag=tag, model=model, sections=sections, output=text,
        label=trace_label, instructions_chars=len(instructions),
        usage=_usage(response),
    )
    return text


async def stream_text(
    *,
    model: str,
    instructions: str,
    tag: str,
    sections: list[tuple[str, object]],
    max_tokens: int = 2500,
    temperature: float | None = None,
    trace_label: str | None = None,
) -> AsyncIterator[str]:
    """Stream plain text deltas (narrator via WebSocket); yields text chunks."""
    content = build_content(instructions, tag, sections)
    create_kwargs: dict = dict(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": content}],
        extra_headers=_CACHE_HEADERS,
    )
    if temperature is not None and _accepts_temperature(model):
        create_kwargs["temperature"] = temperature
    chunks: list[str] = []
    usage: dict | None = None
    final = None
    try:
        async with get_client().messages.stream(**create_kwargs) as stream:
            async for text in stream.text_stream:
                chunks.append(text)
                yield text
            try:
                final = await stream.get_final_message()
                usage = _usage(final)
            except Exception:  # noqa: BLE001 best-effort devtools telemetry
                final = None
            if final is not None:
                _refusal_guard(final, stage=tag)  # mid-stream refusal surfaces to player
    except errors.ModelRefusalError:
        raise
    except Exception as exc:  # noqa: BLE001 reclassify quota
        raise errors.classify_api_error(exc, threshold_s=config.QUOTA_RESET_THRESHOLD_S) from exc
    trace.record(
        tag=tag, model=model, sections=sections, output="".join(chunks),
        label=trace_label, instructions_chars=len(instructions), usage=usage,
    )
