"""browser.py — Playwright manager, per skills/agent-spec.md §4.7.

One BrowserManager per process with its OWN session_dir. Never share a user_data_dir
between concurrent runs (spec §12.2).
"""
import asyncio
import logging
import random
from pathlib import Path
from typing import Optional

from playwright.async_api import BrowserContext, Page, async_playwright

from config import settings

logger = logging.getLogger(__name__)

# A real Chrome UA. investor.tsmc.com sits behind Cloudflare and 403s library
# defaults and bare "Mozilla/5.0" alike; only a full UA string gets through.
CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


class BrowserManager:
    def __init__(self, session_dir: Path, visible: bool = False):
        self.session_dir = session_dir
        self.visible = visible
        self._playwright = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    async def launch(self):
        self.session_dir.mkdir(parents=True, exist_ok=True)
        args = ["--disable-blink-features=AutomationControlled"]
        if not self.visible:
            args.append("--start-minimized")

        self._playwright = await async_playwright().start()
        self.context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.session_dir),
            headless=False,          # GPU rendering; minimized when not visible
            channel="chromium",
            args=args,
            user_agent=CHROME_UA,
            accept_downloads=True,
        )
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        await self.page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => false });"
        )
        logger.info("browser up (session=%s)", self.session_dir.name)

    async def navigate(self, url: str) -> str:
        """Navigate, settle, return body text. Rate-limited per config."""
        delay = random.uniform(settings.min_navigation_delay, settings.max_navigation_delay)
        if delay > 0:
            await asyncio.sleep(delay)
        await self.page.goto(url, timeout=settings.page_load_timeout)
        await self.page.wait_for_load_state("networkidle", timeout=settings.page_load_timeout)
        return await self.page.inner_text("body")

    async def close(self):
        try:
            if self.context:
                await self.context.close()
        finally:
            if self._playwright:
                await self._playwright.stop()
