"""firecrawl_rest.py — Firecrawl REST helpers.

Mirrors tasks/autorss-helper-tools/firecrawl_rest.py: plain requests.post to
api.firecrawl.dev with a Bearer key and defensive parsing. NO MCP server — its
teardown segfaults on Windows, and we are already fighting one of those.

Used only when WEB_BACKEND=firecrawl. Default backend is crawl4ai.
"""
import logging

import requests

from config import settings

logger = logging.getLogger(__name__)

_SEARCH_TIMEOUT = 30
_SCRAPE_TIMEOUT = 60
_MAX_RESULTS = 10
_TITLE_CAP = 200
_DESC_CAP = 300


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.firecrawl_api_key}",
        "Content-Type": "application/json",
    }


def search_web(query: str, limit: int = 10) -> list[dict]:
    """POST /v2/search -> [{url, title, description}]. Trimmed so results can't flood context."""
    limit = max(1, min(limit, _MAX_RESULTS))
    resp = requests.post(
        "https://api.firecrawl.dev/v2/search",
        headers=_headers(),
        json={"query": query, "limit": limit},
        timeout=_SEARCH_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json().get("data", {})
    rows = payload.get("web", payload) if isinstance(payload, dict) else payload
    out = []
    for r in (rows or [])[:limit]:
        if not isinstance(r, dict):
            continue
        out.append({
            "url": r.get("url", ""),
            "title": (r.get("title") or "")[:_TITLE_CAP],
            "description": (r.get("description") or "")[:_DESC_CAP],
        })
    return out


def scrape_markdown(url: str, max_chars: int) -> str:
    """POST /v2/scrape -> markdown, hard-capped."""
    resp = requests.post(
        "https://api.firecrawl.dev/v2/scrape",
        headers=_headers(),
        json={"url": url, "formats": ["markdown"]},
        timeout=_SCRAPE_TIMEOUT,
    )
    resp.raise_for_status()
    md = (resp.json().get("data") or {}).get("markdown", "") or ""
    return md if len(md) <= max_chars else md[:max_chars] + "\n... [truncated]"
