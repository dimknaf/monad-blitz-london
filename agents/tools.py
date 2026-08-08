"""tools.py — agent tools, per skills/agent-spec.md §4.

Tool behaviour is the skill's. The only addition is instrumentation: every call is logged
(name, arg, ok, bytes, elapsed) to out/tools_<agent>.jsonl. It records what already happens
and changes nothing — it is the audit trail and the feed the frontend streams.
"""
import asyncio
import json
import logging
import re
import time
from pathlib import Path

from agents import function_tool

from config import REPO_ROOT, settings

logger = logging.getLogger(__name__)

_browser = None
_crawl_browser = None
_agent_key = "X"
_fetches_ok = 0          # successful page fetches this run — the gate on submit_result
_log_path: Path | None = None


def set_browser(browser):
    global _browser
    _browser = browser


def set_crawl_browser(crawl_browser):
    global _crawl_browser
    _crawl_browser = crawl_browser


def set_agent_key(key: str):
    """Names the tool log so panel.py and the frontend can find it."""
    global _agent_key, _log_path, _fetches_ok
    _agent_key = key
    _fetches_ok = 0
    out = REPO_ROOT / "out"
    out.mkdir(exist_ok=True)
    _log_path = out / f"tools_{key}.jsonl"
    _log_path.write_text("", encoding="utf-8")


def fetches_ok() -> int:
    return _fetches_ok


def _record(tool: str, arg: str, ok: bool, size: int, elapsed: float, note: str = ""):
    entry = {
        "ts": round(time.time(), 3), "agent": _agent_key, "tool": tool,
        "arg": arg[:200], "ok": ok, "bytes": size, "elapsed": round(elapsed, 2), "note": note[:200],
    }
    logger.info("TOOL %-18s %-4s %6dB %5.1fs  %s", tool, "ok" if ok else "FAIL", size, elapsed, arg[:90])
    if _log_path:
        with _log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")


def _truncate(text: str, max_chars: int | None = None) -> str:
    cap = max_chars or settings.tool_output_max_chars
    return text if len(text) <= cap else text[:cap] + "\n... [truncated]"


# --------------------------------------------------------------- local path

@function_tool
async def search_google(query: str) -> str:
    """Search Google for a query and return the top results with titles, snippets, and URLs.

    Use this to find information about companies, products, or any external topic.

    Args:
        query: The search query string.
    """
    t = time.time()
    if not _browser:
        _record("search_google", query, False, 0, time.time() - t, "no browser")
        return "ERROR: Browser not initialized"
    url = f"https://www.google.com/search?q={query}&num=10"
    try:
        body_text = await _browser.navigate(url)
        page = _browser.page

        links = []
        anchors = await page.query_selector_all("a[href]")
        for anchor in anchors[:30]:
            href = await anchor.get_attribute("href")
            text = (await anchor.inner_text()).strip()
            if not href or not text:
                continue
            if href.startswith("http") and "google" not in href:
                links.append(f"{text[:80]} -> {href}")

        body_text = _truncate(body_text)
        out = f"=== Google Search Results for: {query} ===\n\n"
        if links:
            out += "Key Links:\n" + "\n".join(links[:10]) + "\n\n"
        out += "Page Content:\n" + body_text
        _record("search_google", query, True, len(out), time.time() - t, f"{len(links)} links")
        return out

    except Exception as e:
        logger.error("Google search failed for %r: %s", query, e)
        _record("search_google", query, False, 0, time.time() - t, str(e)[:150])
        return f"ERROR: Search failed - {e}"


@function_tool
async def visit_webpage(url: str) -> str:
    """Visit a webpage or PDF and extract its text. This is how you gather evidence.

    Args:
        url: The full URL to visit.
    """
    global _fetches_ok
    t = time.time()

    # PDF branch: crawl4ai renders HTML and returns 0 bytes on PDFs (verified: 6 empty
    # fetches on the TSMC transcripts). MUST be PyMuPDF — pypdf and pdfplumber silently
    # strip inter-word spaces on these files ("letmegiveyounotanumber").
    if url.lower().split("?")[0].endswith(".pdf"):
        try:
            import fitz
            import requests
            from browser import CHROME_UA
            r = requests.get(url, headers={"User-Agent": CHROME_UA}, timeout=60)
            r.raise_for_status()
            with fitz.open(stream=r.content, filetype="pdf") as doc:
                pages = doc.page_count          # read INSIDE the with — closed doc raises
                text = "\n".join(p.get_text() for p in doc)
            _fetches_ok += 1
            _record("visit_webpage", url, True, len(text), time.time() - t, f"pdf {pages}p")
            return f"=== PDF: {url} ===\n\n{_truncate(text)}"
        except Exception as e:
            _record("visit_webpage", url, False, 0, time.time() - t, f"pdf: {str(e)[:120]}")
            return f"ERROR: Failed to read PDF - {e}. Find an HTML version instead."

    if _crawl_browser:
        try:
            md = await _crawl_browser.fetch(url)
            if md and not md.startswith("ERROR"):
                _fetches_ok += 1
                _record("visit_webpage", url, True, len(md), time.time() - t, "crawl4ai")
                return f"=== Webpage: {url} ===\n\n{_truncate(md)}"
        except Exception as e:
            logger.error("crawl4ai failed for %s: %s", url, e)

    if not _browser:
        _record("visit_webpage", url, False, 0, time.time() - t, "no browser")
        return "ERROR: Browser not initialized"
    try:
        body = await _browser.navigate(url)
        body = re.sub(r"\n{3,}", "\n\n", re.sub(r" {2,}", " ", body))
        _fetches_ok += 1
        _record("visit_webpage", url, True, len(body), time.time() - t, "playwright")
        return f"=== Webpage: {url} ===\n\n{_truncate(body)}"
    except Exception as e:
        _record("visit_webpage", url, False, 0, time.time() - t, str(e)[:150])
        return f"ERROR: Failed to load page - {e}"


@function_tool
async def wait_for_human(reason: str) -> str:
    """Pause and ask the human operator to intervene in the browser.

    ONLY for a CAPTCHA, login wall, cookie consent, or a page that genuinely will not load.

    Args:
        reason: Short explanation of why human help is needed.
    """
    t = time.time()
    if not _browser:
        return "ERROR: Browser not initialized"
    logger.info("HUMAN INTERVENTION REQUESTED: %s", reason)
    await asyncio.get_event_loop().run_in_executor(
        None, input, f"\n>>> Agent needs help: {reason}\n>>> Press Enter when done... "
    )
    _record("wait_for_human", reason, True, 0, time.time() - t)
    try:
        return "Human intervention complete. Current page:\n\n" + _truncate(
            await _browser.page.inner_text("body")
        )
    except Exception:
        return "Human intervention complete. Could not read page."


# ----------------------------------------------------------- firecrawl path

@function_tool
async def firecrawl_search(query: str, limit: int = 10) -> str:
    """Search the web. Returns JSON {url, title, description} — LINKS ONLY.

    You must open a result with firecrawl_scrape before you can cite it.

    Args:
        query: The search query string.
        limit: How many results (max 10).
    """
    from firecrawl_rest import search_web
    t = time.time()
    try:
        rows = search_web(query, limit=limit)
        out = json.dumps(rows)
        _record("firecrawl_search", query, True, len(out), time.time() - t, f"{len(rows)} results")
        return out
    except Exception as e:
        _record("firecrawl_search", query, False, 0, time.time() - t, str(e)[:150])
        return f"ERROR: search failed ({e})"


@function_tool
async def firecrawl_scrape(url: str) -> str:
    """Fetch a page or PDF as clean markdown. This is how you gather evidence.

    Args:
        url: The full URL to fetch.
    """
    global _fetches_ok
    from firecrawl_rest import scrape_markdown
    t = time.time()
    try:
        md = scrape_markdown(url, settings.tool_output_max_chars)
    except Exception as e:
        _record("firecrawl_scrape", url, False, 0, time.time() - t, str(e)[:150])
        return f"ERROR: scrape failed ({e})"
    if not md:
        _record("firecrawl_scrape", url, False, 0, time.time() - t, "empty")
        return f"No content scraped from {url}."
    _fetches_ok += 1
    _record("firecrawl_scrape", url, True, len(md), time.time() - t)
    return md


# ------------------------------------------------------------- delegation

_call_depth = 0
_MAX_DEPTH = 1
_parent_spec: tuple[str, str] | None = None


def set_parent_spec(name: str, instructions: str):
    """Subagents reuse the parent's prompt (spec §5.2)."""
    global _parent_spec
    _parent_spec = (name, instructions)


@function_tool
async def delegate_to_subagent(task: str) -> str:
    """Delegate a focused task to a fresh subagent in its own context.

    Avoid this — the task is narrow enough to do yourself. Never delegate the verdict.

    Args:
        task: A self-contained task description for the subagent.
    """
    global _call_depth
    t = time.time()
    if _call_depth >= _MAX_DEPTH:
        return "ERROR: max delegation depth reached. Do the task yourself."
    if _parent_spec is None:
        return "ERROR: no parent spec registered."
    _call_depth += 1
    try:
        from agents import Runner
        from agent import create_agent

        result = await Runner.run(
            starting_agent=create_agent(*_parent_spec),
            input=task,
            max_turns=settings.agent_max_turns,
        )
        out = _truncate(str(result.final_output))
        _record("delegate_to_subagent", task, True, len(out), time.time() - t)
        return out
    except Exception as e:
        _record("delegate_to_subagent", task, False, 0, time.time() - t, str(e)[:150])
        return f"ERROR: subagent failed - {e}"
    finally:
        _call_depth -= 1


# ---------------------------------------------------------------- terminal

@function_tool
async def submit_result(
    verdict: bool,
    confidence: float,
    reasoning: str,
    citations: list[str],
) -> str:
    """Submit your structured findings. Call this exactly once when done.

    Args:
        verdict: True if the claim holds, False if it does not.
        confidence: 0.0 to 1.0.
        reasoning: One paragraph explaining how you reached the verdict.
        citations: URLs of documents you actually opened, with short quotes.
    """
    payload = {
        "verdict": bool(verdict),
        "confidence": float(confidence),
        "reasoning": reasoning,
        "citations": list(citations or []),
        "fetches": _fetches_ok,
    }
    _record("submit_result", f"verdict={verdict}", True, len(json.dumps(payload)), 0.0,
            f"{_fetches_ok} fetches")
    return json.dumps(payload)
