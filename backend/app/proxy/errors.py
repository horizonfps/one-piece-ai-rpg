"""Runtime errors for the inference path.

Two failure modes need a policy distinct from the SDK's transient backoff (which covers
429/RPM and timeout):
- Quota exhausted: the Claude Max subscription window is empty (resets in hours). The turn
  pauses and resumes when the player returns; the engine never degrades or invents prose.
  Classified as QuotaExceededError.
- Model refusal: the model declined via safety filter (stop_reason). Surfaced to the player
  to rephrase, with no masked retry or guardrail evasion. Classified as ModelRefusalError.

`classify_api_error` inspects the SDK exception and returns the structured version when it
recognizes the signal, else the original exception. Classification is defensive: it pauses
only on a strong signal (text marker OR long `retry-after`); ambiguous 429s stay transient.
Markers and threshold are tunable without touching the pipeline.
"""
from __future__ import annotations


class QuotaExceededError(Exception):
    """Claude Max subscription quota exhausted (hours-long window), distinct from transient
    429/RPM. The runner pauses the turn without partial persistence and the UI asks the player
    to return later. `retry_after_seconds` and `reset_hint` feed the UI message."""

    def __init__(
        self,
        message: str = "assinatura Claude Max no limite",
        *,
        retry_after_seconds: int | None = None,
        reset_hint: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
        self.reset_hint = reset_hint
        self.status_code = status_code


class ModelRefusalError(Exception):
    """The model refused to produce content (safety-filter stop_reason). Surfaced to the
    player to rephrase, with no retry or prose fallback. The campaign stays intact (refusal
    happens in the Narrator call before any turn persistence). `stage` marks where it
    occurred, for telemetry."""

    def __init__(
        self,
        message: str = "o modelo recusou renderizar este input",
        *,
        stage: str | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage


# Text markers that indicate subscription exhaustion, absent from a transient burst 429.
# Case-insensitive.
QUOTA_TEXT_MARKERS = (
    "usage limit",
    "usage_limit",
    "quota",
    "exceeded your",
    "reached your",
    "plan limit",
    "monthly limit",
    "spending limit",
    "credit balance",
    "out of credit",
    "limit will reset",
    "upgrade your plan",
    "subscription limit",
)

# stop_reason the API returns when the model declines for safety.
REFUSAL_STOP_REASONS = ("refusal",)

# Threshold (seconds) above which a 429 `retry-after` is treated as a quota window. RPM resets
# in seconds; subscription quota in minutes/hours. Conservative 5min default.
DEFAULT_QUOTA_RESET_THRESHOLD_S = 300


def is_refusal_stop_reason(stop_reason: str | None) -> bool:
    """True when the response `stop_reason` indicates a model content refusal."""
    return (stop_reason or "").strip().lower() in REFUSAL_STOP_REASONS


def is_quota_exhaustion(
    *,
    status_code: int | None,
    text: str,
    retry_after_seconds: int | None,
    threshold_s: int = DEFAULT_QUOTA_RESET_THRESHOLD_S,
) -> bool:
    """Defensive heuristic: quota exhausted if the error text carries a subscription marker
    or it is a 429 with a long `retry-after` (>= threshold). Ambiguous returns False."""
    low = (text or "").lower()
    if any(m in low for m in QUOTA_TEXT_MARKERS):
        return True
    if status_code == 429 and retry_after_seconds is not None and retry_after_seconds >= threshold_s:
        return True
    return False


def _retry_after_seconds(headers) -> int | None:
    """Integer `retry-after` seconds from headers, if present and numeric."""
    if headers is None:
        return None
    try:
        raw = headers.get("retry-after")
    except AttributeError:
        raw = None
    if raw is None:
        return None
    try:
        return int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return None


def _reset_hint(headers) -> str | None:
    """Raw reset timestamp from rate-limit headers (UI hint only)."""
    if headers is None:
        return None
    for key in (
        "anthropic-ratelimit-unified-reset",
        "anthropic-ratelimit-tokens-reset",
        "anthropic-ratelimit-requests-reset",
    ):
        try:
            val = headers.get(key)
        except AttributeError:
            val = None
        if val:
            return str(val)
    return None


def _error_text(exc) -> str:
    """Join the exception message with the nested API error-body message."""
    parts = [str(getattr(exc, "message", "") or "")]
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            parts.append(str(err.get("message", "") or ""))
            parts.append(str(err.get("type", "") or ""))
        elif isinstance(err, str):
            parts.append(err)
    if not any(parts):
        parts.append(str(exc))
    return " ".join(p for p in parts if p)


def classify_api_error(
    exc: BaseException,
    *,
    threshold_s: int = DEFAULT_QUOTA_RESET_THRESHOLD_S,
) -> BaseException:
    """Inspect the Anthropic SDK exception. Return QuotaExceededError on recognized
    subscription exhaustion, else the original `exc`. Does not raise; the caller decides."""
    status_code = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    retry_after = _retry_after_seconds(headers)
    text = _error_text(exc)
    if is_quota_exhaustion(
        status_code=status_code, text=text, retry_after_seconds=retry_after, threshold_s=threshold_s
    ):
        return QuotaExceededError(
            "assinatura Claude Max no limite — volte mais tarde",
            retry_after_seconds=retry_after,
            reset_hint=_reset_hint(headers),
            status_code=status_code,
        )
    return exc
