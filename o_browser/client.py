"""
BrowserClient — Direct browser automation (launches Chrome locally or connects via CDP).

Usage:
    # Headless automation
    async with BrowserClient() as browser:
        await browser.goto("https://example.com")
        text = await browser.get_text()

    # Connect to existing Chrome (e.g. launched with --remote-debugging-port=9222)
    async with BrowserClient(cdp_url="http://127.0.0.1:9222") as browser:
        await browser.goto("https://example.com")
        text = await browser.get_text()

    # With recording + proxy
    async with BrowserClient(record=True, proxy={"server": "http://host:port"}) as browser:
        await browser.goto("https://example.com")
    # → recordings/ses_YYYYMMDD_HHMMSS/{network.har, video.webm, state.json}

    # Interactive (human navigates, we record)
    async with BrowserClient(interactive=True, record=True) as browser:
        await browser.wait_closed()
"""

import asyncio
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Callable

from ._mixin import PageMixin
from .har import HARRecorder


def _detect_channel() -> str:
    """Detect best available Chrome channel."""
    for channel, binary in [
        ("chrome-beta", "google-chrome-beta"),
        ("chrome", "google-chrome"),
    ]:
        if shutil.which(binary):
            return channel
    return "chromium"


class BrowserClient(PageMixin):
    """
    Async browser client — launches Chrome directly.

    Can be used standalone or inherited by domain-specific clients.
    """

    def __init__(
        self,
        profile_path: Optional[str] = None,
        headless: bool = True,
        channel: Optional[str] = None,
        viewport: tuple[int, int] = (1920, 1080),
        user_agent: str = None,
        cookies: List[Dict] = None,
        locale: str = None,
        timezone_id: str = None,
        browser_args: List[str] = None,
        proxy: Optional[Dict] = None,
        record: bool = False,
        record_dir: Optional[str] = None,
        interactive: bool = False,
        cdp_url: Optional[str] = None,
    ):
        self.cdp_url = cdp_url
        self.profile_path = Path(profile_path).expanduser() if profile_path else None
        self.headless = headless if not interactive else False
        self.channel = channel or os.environ.get("BROWSER_CHANNEL") or _detect_channel()
        self.viewport = {"width": viewport[0], "height": viewport[1]} if not interactive else None
        self.user_agent = user_agent
        self.cookies = cookies or []
        self.locale = locale
        self.timezone_id = timezone_id
        self.browser_args = browser_args or []
        self.proxy = proxy
        self.record = record
        self.record_dir = Path(record_dir) if record_dir else None
        self.interactive = interactive

        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._closed_event: Optional[asyncio.Event] = None
        self._cdp_owns_browser = False
        self._har: Optional[HARRecorder] = None

        self._response_handlers: List[Callable] = []

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    def _prepare_record_dir(self) -> Path:
        """Create and return the recording directory."""
        if self.record_dir:
            d = self.record_dir
        else:
            session_id = f"ses_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            d = Path("recordings") / session_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _build_context_options(self) -> dict:
        """Build shared context options for both persistent and ephemeral modes."""
        opts = {}
        if self.viewport:
            opts["viewport"] = self.viewport
        if self.user_agent:
            opts["user_agent"] = self.user_agent
        if self.locale:
            opts["locale"] = self.locale
        if self.timezone_id:
            opts["timezone_id"] = self.timezone_id
        if self.proxy:
            opts["proxy"] = self.proxy
        if self.record:
            rec_dir = self._prepare_record_dir()
            self.record_dir = rec_dir
            # HAR is captured Python-side (see HARRecorder) so it survives the user
            # closing the browser in interactive mode; only the video is left to Playwright.
            opts["record_video_dir"] = str(rec_dir)
        return opts

    async def start(self) -> "BrowserClient":
        """Start browser and return self."""
        from patchright.async_api import async_playwright

        self._playwright = await async_playwright().start()

        if self.cdp_url:
            self._browser = await self._playwright.chromium.connect_over_cdp(self.cdp_url)
            self._cdp_owns_browser = True
            contexts = self._browser.contexts
            self._context = contexts[0] if contexts else await self._browser.new_context()
            self._page = await self._context.new_page()
        elif self.profile_path:
            default_args = [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ]
            launch_args = list(set(default_args + self.browser_args))
            ctx_opts = self._build_context_options()

            if not self.profile_path.exists():
                self.profile_path.mkdir(parents=True, exist_ok=True)

            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_path),
                headless=self.headless,
                channel=self.channel,
                args=launch_args,
                **ctx_opts,
            )
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        else:
            default_args = [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ]
            launch_args = list(set(default_args + self.browser_args))
            ctx_opts = self._build_context_options()

            self._browser = await self._playwright.chromium.launch(
                headless=self.headless,
                channel=self.channel,
                args=launch_args,
            )
            self._context = await self._browser.new_context(**ctx_opts)
            self._page = await self._context.new_page()

        if self.cookies:
            await self.add_cookies(self.cookies)

        if self.record:
            self._har = HARRecorder()
            self._har.attach(self._context)

        if self._response_handlers:
            self._page.on("response", self._on_response)

        # Track browser close for interactive mode
        if self.interactive:
            self._closed_event = asyncio.Event()
            self._setup_close_detection()

        return self

    def _setup_close_detection(self):
        """Detect when user closes browser (all pages closed or browser disconnected)."""
        def on_page_close():
            # Check if any pages remain
            try:
                if not self._context.pages:
                    self._closed_event.set()
            except Exception:
                self._closed_event.set()

        # Watch existing pages
        for p in self._context.pages:
            p.on("close", lambda: on_page_close())

        # Watch new pages too
        self._context.on("page", lambda page: page.on("close", lambda: on_page_close()))

        # Browser disconnect (persistent context)
        self._context.on("close", lambda: self._closed_event.set())

        # Browser disconnect (ephemeral)
        if self._browser:
            self._browser.on("disconnected", lambda: self._closed_event.set())

    async def wait_closed(self):
        """Wait for the browser to be closed by the user (interactive mode)."""
        if not self._closed_event:
            self._closed_event = asyncio.Event()
            self._setup_close_detection()
        await self._closed_event.wait()

    async def close(self):
        """Close browser and cleanup. Saves recordings if enabled."""
        if self.record and self._context:
            try:
                state_path = self.record_dir / "state.json"
                await self._context.storage_state(path=str(state_path))
            except Exception:
                pass

        # Write the HAR from our Python-side buffer. This runs even when the browser was
        # already torn down by the user (interactive mode), unlike Playwright's native HAR.
        if self.record and self._har and self.record_dir:
            try:
                n = self._har.write(str(self.record_dir / "network.har"))
                print(f"HAR: {n} entries -> {self.record_dir / 'network.har'}")
            except Exception as e:
                print(f"HAR write failed: {e}")

        if self._cdp_owns_browser:
            # CDP mode: only close pages we opened, don't kill the browser
            if self._page:
                try:
                    await self._page.close()
                except Exception:
                    pass
        else:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()

        if self._playwright:
            await self._playwright.stop()
        if self.record and self.record_dir:
            print(f"Recordings saved: {self.record_dir}")

    # === Cookie Management ===

    async def add_cookies(self, cookies: List[Dict]):
        """Add cookies to browser context."""
        formatted = []
        for cookie in cookies:
            c = {
                "name": cookie["name"],
                "value": cookie["value"],
                "domain": cookie.get("domain", ""),
                "path": cookie.get("path", "/"),
            }
            if "httpOnly" in cookie:
                c["httpOnly"] = cookie["httpOnly"]
            if "secure" in cookie:
                c["secure"] = cookie["secure"]
            if "sameSite" in cookie:
                c["sameSite"] = cookie["sameSite"]
            formatted.append(c)

        await self._context.add_cookies(formatted)

    async def get_cookies(self) -> List[Dict]:
        """Get all cookies from context."""
        if not self._context:
            return []
        return await self._context.cookies()

    # === Response Interception ===

    def on_response(self, handler: Callable):
        """Register response handler for intercepting network responses."""
        self._response_handlers.append(handler)
        if self._page:
            self._page.on("response", self._on_response)

    async def _on_response(self, response):
        """Internal response handler dispatcher."""
        for handler in self._response_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(response)
                else:
                    handler(response)
            except Exception:
                pass
