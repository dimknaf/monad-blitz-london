"""crawl_browser.py — crawl4ai for clean markdown, per skills/agent-spec.md §4.8."""
import logging
from pathlib import Path
from typing import Optional

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

from browser import CHROME_UA

logger = logging.getLogger(__name__)


class CrawlBrowserManager:
    def __init__(self, session_dir: Path, visible: bool = False):
        self.session_dir = session_dir
        self.visible = visible
        self._crawler: Optional[AsyncWebCrawler] = None

    async def launch(self):
        self.session_dir.mkdir(parents=True, exist_ok=True)
        cfg = BrowserConfig(
            headless=not self.visible,
            browser_type="chromium",
            enable_stealth=True,         # spec §4.8
            user_agent=CHROME_UA,        # DEVIATION: Cloudflare on investor.tsmc.com 403s defaults
            use_persistent_context=True,
            user_data_dir=str(self.session_dir),
        )
        self._crawler = AsyncWebCrawler(config=cfg, verbose=False)
        await self._crawler.start()
        logger.info("crawl4ai up (session=%s)", self.session_dir.name)

    async def fetch(self, url: str) -> str:
        if not self._crawler:
            raise RuntimeError("crawl4ai not launched")
        result = await self._crawler.arun(url, config=CrawlerRunConfig(wait_until="networkidle"))
        if not result.success:
            return f"ERROR: Failed to fetch (status {result.status_code})"
        if result.markdown:
            return result.markdown.fit_markdown or result.markdown.raw_markdown or ""
        return ""

    async def close(self):
        if self._crawler:
            try:
                await self._crawler.close()
            finally:
                self._crawler = None
