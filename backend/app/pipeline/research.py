"""Canonical-island research pipeline (FASE 10.2): Query Planner -> Fandom -> Synthesizer.

Produces briefing_md (becomes canonical_context.post_arc_summary_hint for the arc_generator).
All three steps are best-effort: failure degrades the briefing, it does not block the plot.

  1. Query Planner (Sonnet) emits EN queries specific to the island.
  2. Executor runs them against the Fandom MediaWiki API (HTML scraping returns 403; api.php is
     the legitimate channel). Descriptive user-agent, no spoof. Page dedup across queries.
  3. Synthesizer (Sonnet, markdown, no tool) consolidates the dumps.
"""
from __future__ import annotations

import asyncio
import re

import httpx

from .. import config
from ..proxy import client

_PLANNER_PROMPT = "research_query_planner.pt-br.md"
_SYNTH_PROMPT = "research_synthesizer.pt-br.md"

_COVERAGE_ENUM = ["npc_status", "post_arc_events", "terminology", "canonical_conflicts"]

# Executor limits (rare call, once per canonical island): top-N search hits per query, lead
# (section 0) per hit. Page dedup across queries.
_HITS_PER_QUERY = 2
_HTTP_TIMEOUT = 20.0
_LEAD_MAX_CHARS = 1400  # cleaned lead cut per page

# --------------------------------------------------------------------------------------
# Query Planner: emit_queries
# --------------------------------------------------------------------------------------
EMIT_QUERIES_TOOL = {
    "name": "emit_queries",
    "description": (
        "Emite 4-8 queries WebSearch EN que cercam o estado canonico ATUAL da ilha a "
        "partir do timeline_anchor. Uma chamada, nenhum texto fora."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "queries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "EN, 3-10 palavras, especifica."},
                        "coverage_area": {"type": "string", "enum": _COVERAGE_ENUM},
                        "rationale": {"type": "string", "description": "1 frase PT-BR."},
                    },
                    "required": ["query", "coverage_area"],
                },
            },
        },
        "required": ["queries"],
    },
}


def _planner_instructions() -> str:
    return (config.PROMPTS_DIR / _PLANNER_PROMPT).read_text(encoding="utf-8")


def _synth_instructions() -> str:
    return (config.PROMPTS_DIR / _SYNTH_PROMPT).read_text(encoding="utf-8")


def parse_queries(emitted: dict | None) -> list[dict]:
    """Normalize emit_queries: only entries with a string query, sanitized coverage_area."""
    raw = (emitted or {}).get("queries")
    out: list[dict] = []
    if not isinstance(raw, list):
        return out
    for q in raw:
        if not isinstance(q, dict):
            continue
        query = (q.get("query") or "").strip()
        if not query:
            continue
        area = q.get("coverage_area")
        out.append({
            "query": query,
            "coverage_area": area if area in _COVERAGE_ENUM else "post_arc_events",
            "rationale": q.get("rationale", ""),
        })
    return out


async def plan_queries(planner_input: dict, *, retries: int = 1) -> list[dict]:
    """Run the Query Planner and return the parsed query list (empty on failure)."""
    last_exc: Exception | None = None
    for _attempt in range(retries + 1):
        try:
            emitted = await client.call_tool(
                model=config.AGENT_MODEL,
                instructions=_planner_instructions(),
                tag="research-planner",
                sections=[("ISLAND-RESEARCH-INPUT", planner_input)],
                tool=EMIT_QUERIES_TOOL,
                tool_name="emit_queries",
                temperature=config.AGENT_TEMPERATURE,
                max_tokens=1500,
                trace_label="Research · query planner",
            )
            queries = parse_queries(emitted)
            if queries:
                return queries
        except Exception as e:  # noqa: BLE001  retry covers truncation/parse
            last_exc = e
    if last_exc is not None and not isinstance(last_exc, (KeyError, ValueError)):
        # Network/proxy failure: research is best-effort, so swallow.
        return []
    return []


# --------------------------------------------------------------------------------------
# Executor: Fandom MediaWiki API
# --------------------------------------------------------------------------------------
_TAG_RE = re.compile(r"<(script|style|table|sup)[^>]*>.*?</\1>", re.S | re.I)
_ANY_TAG_RE = re.compile(r"<[^>]+>")
_ENTITY_RE = re.compile(r"&#?\w+;")
_REF_RE = re.compile(r"\[\s*\d+\s*\]")
_WS_RE = re.compile(r"\s+")


def clean_html(html: str) -> str:
    """Strip Fandom HTML to plain text: remove script/style/table/sup, tags, entities, reference
    markers, and collapse whitespace. Pure."""
    s = _TAG_RE.sub(" ", html or "")
    s = _ANY_TAG_RE.sub(" ", s)
    s = _ENTITY_RE.sub(" ", s)
    s = _REF_RE.sub(" ", s)
    return _WS_RE.sub(" ", s).strip()


async def _search(http: httpx.AsyncClient, query: str, limit: int) -> list[str]:
    r = await http.get(config.FANDOM_API_URL, params={
        "action": "query", "list": "search", "srsearch": query,
        "srlimit": limit, "srnamespace": 0, "format": "json",
    })
    r.raise_for_status()
    return [h.get("title", "") for h in r.json().get("query", {}).get("search", []) if h.get("title")]


async def _page_lead(http: httpx.AsyncClient, title: str) -> str:
    r = await http.get(config.FANDOM_API_URL, params={
        "action": "parse", "page": title, "prop": "text", "section": 0,
        "disabletoc": 1, "redirects": 1, "format": "json",
    })
    r.raise_for_status()
    html = r.json().get("parse", {}).get("text", {}).get("*", "")
    return clean_html(html)[:_LEAD_MAX_CHARS]


async def execute_queries(queries: list[dict]) -> tuple[list[dict], bool]:
    """Run the queries against Fandom. Returns (raw_dumps, ok); ok=False when no snippet was
    gathered. Pages are deduped across queries (fetched once, reused)."""
    if not queries:
        return [], False
    headers = {"User-Agent": config.FANDOM_USER_AGENT}
    page_cache: dict[str, str] = {}
    any_hit = False
    raw_dumps: list[dict] = []
    try:
        async with httpx.AsyncClient(headers=headers, timeout=_HTTP_TIMEOUT) as http:
            async def _one(q: dict) -> dict:
                nonlocal any_hit
                snippets: list[str] = []
                try:
                    titles = await _search(http, q["query"], _HITS_PER_QUERY)
                except Exception:  # noqa: BLE001  best-effort per query
                    titles = []
                for title in titles:
                    if title in page_cache:
                        lead = page_cache[title]
                    else:
                        try:
                            lead = await _page_lead(http, title)
                        except Exception:  # noqa: BLE001
                            lead = ""
                        page_cache[title] = lead
                    if lead:
                        any_hit = True
                        snippets.append(f"[{title}] {lead}")
                return {"query": q["query"], "coverage_area": q["coverage_area"], "snippets": snippets}

            raw_dumps = list(await asyncio.gather(*[_one(q) for q in queries]))
    except Exception:  # noqa: BLE001  global failure (DNS/proxy) degrades
        return raw_dumps, False
    return raw_dumps, any_hit


# --------------------------------------------------------------------------------------
# Synthesizer: direct markdown, no tool
# --------------------------------------------------------------------------------------
async def synthesize(synth_input: dict) -> str:
    """Consolidate the raw_dumps into the markdown briefing. Plain text, no tool call."""
    return await client.call_text(
        model=config.AGENT_MODEL,
        instructions=_synth_instructions(),
        tag="research-synthesizer",
        sections=[("SYNTHESIS-INPUT", synth_input)],
        max_tokens=2200,
        temperature=config.AGENT_TEMPERATURE,
        trace_label="Research · synthesizer",
    )


# --------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------
async def run_research(island_meta: dict) -> dict:
    """Full pipeline: planner -> executor (Fandom) -> synthesizer. Returns {briefing_md, quality}
    (ok|degraded). Best-effort at every layer: missing queries/snippets/synth yields degraded.

    island_meta is the query planner contract."""
    planner_input = {
        "island_slug": island_meta.get("island_slug", ""),
        "canonical_name": island_meta.get("canonical_name", ""),
        "sea_cluster": island_meta.get("sea_cluster", ""),
        "canonical_mode": island_meta.get("canonical_mode", "remnants"),
        "canon_arc_name": island_meta.get("canon_arc_name", ""),
        "timeline_anchor": island_meta.get("timeline_anchor", config.CANON_VERSION),
        "known_canonical_npcs": island_meta.get("known_canonical_npcs") or [],
    }
    try:
        queries = await plan_queries(planner_input)
    except Exception:  # noqa: BLE001  best-effort
        queries = []
    raw_dumps, ok = await execute_queries(queries)
    if not raw_dumps or not ok:
        return {"briefing_md": "", "quality": "degraded"}

    synth_input = {
        "island_slug": planner_input["island_slug"],
        "canonical_name": planner_input["canonical_name"],
        "sea_cluster": planner_input["sea_cluster"],
        "canonical_mode": planner_input["canonical_mode"],
        "canon_arc_name": planner_input["canon_arc_name"],
        "timeline_anchor": planner_input["timeline_anchor"],
        "raw_dumps": raw_dumps,
    }
    try:
        briefing = (await synthesize(synth_input) or "").strip()
    except Exception:  # noqa: BLE001  synth failed, degrade; the plot still generates
        return {"briefing_md": "", "quality": "degraded"}
    if not briefing:
        return {"briefing_md": "", "quality": "degraded"}
    # Degradation marker the synth emits when the dumps are thin.
    quality = "degraded" if "(sem material relevante" in briefing.lower() else "ok"
    return {"briefing_md": briefing, "quality": quality}
