"""run_agent.py — ONE agent, ONE process, per skills/agent-spec.md §3.4.

The spec is explicit (§3.2): the module globals in tools.py plus the browser refs make this
design single-agent-per-process. "For parallel runs, use multiprocessing — one process per
agent — not threads." panel.py spawns three of these concurrently, each with its own
session dir.

Usage:  python run_agent.py A          # or B, C
Prints one JSON object to stdout. Everything else goes to stderr.
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent import run_panel_agent, warmup          # noqa: E402
from browser import BrowserManager                 # noqa: E402
from config import REPO_ROOT                       # noqa: E402
from crawl_browser import CrawlBrowserManager      # noqa: E402
from prompts import CLAIM_TSMC, SEED_URLS           # noqa: E402
from tools import set_agent_key, set_browser, set_crawl_browser   # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,                              # stdout stays pure JSON
)
log = logging.getLogger("run_agent")


async def main(key: str) -> int:
    session_root = REPO_ROOT / "session" / key       # SEPARATE dir per agent — spec §12.2
    browser = BrowserManager(session_root / "playwright")
    crawl = CrawlBrowserManager(session_root / "crawl4ai")

    set_agent_key(key)                                # opens out/tools_<key>.jsonl
    log.info("agent %s starting", key)
    warmup()                                          # cold endpoint = 46s; warm = ~3s

    await browser.launch()
    await crawl.launch()
    set_browser(browser)                              # inject BEFORE Runner.run
    set_crawl_browser(crawl)

    try:
        result = await run_panel_agent(key, CLAIM_TSMC, SEED_URLS[key])

        # WRITE BEFORE TEARDOWN. crawl4ai writes banners to stdout so stdout is not a clean
        # channel, and the result file is the contract panel.py reads rather than the exit
        # code — because the Playwright/crawl4ai teardown segfaults on Windows *after* a
        # successful run. If this write sat after close(), a segfault would discard a
        # verdict the agent had already earned.
        out_dir = REPO_ROOT / "out"
        out_dir.mkdir(exist_ok=True)
        (out_dir / f"agent_{key}.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    finally:
        await crawl.close()
        await browser.close()

    log.info("agent %s -> verdict=%s in %ss -> out/agent_%s.json",
             key, result.get("verdict"), result.get("elapsed"), key)
    return 0


if __name__ == "__main__":
    agent_key = (sys.argv[1] if len(sys.argv) > 1 else "A").upper()
    if agent_key not in ("A", "B", "C"):
        print(json.dumps({"error": f"unknown agent {agent_key}"}))
        sys.exit(2)
    sys.exit(asyncio.run(main(agent_key)))
