"""
RemoteBrowser — Connect to a running browser service via CDP.

Usage:
    async with RemoteBrowser("http://host:8080") as browser:
        await browser.goto("https://example.com")
        text = await browser.get_text()

When pointed at an o-browser-full service, RemoteBrowser auto-creates a session
(POST /api/sessions) if none is currently active, so callers don't need to do it
manually. Disable via `auto_session=False` if you manage sessions yourself.
"""

import re
from typing import Optional

from ._mixin import PageMixin


class RemoteBrowser(PageMixin):
    """
    Connects to a remote Chrome instance via CDP WebSocket.

    Does NOT launch or kill the browser — only connects/disconnects.
    """

    def __init__(
        self,
        endpoint: str,
        workflow: str = "o-browser-client",
        auto_session: bool = True,
    ):
        """
        Args:
            endpoint: HTTP base URL (http://host:8080) or direct WS URL (ws://host:9222/devtools/...)
            workflow: name passed when auto-creating a session on o-browser-full
            auto_session: POST /api/sessions if no current session (o-browser-full only)
        """
        self.endpoint = endpoint
        self.workflow = workflow
        self.auto_session = auto_session
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def _discover_ws_url(self) -> str:
        """Auto-discover WebSocket URL from HTTP endpoint.

        On o-browser-full, the CDP port (9222) is only exposed once a session is
        running — so if there's no current session and `auto_session` is True we
        POST /api/sessions to start one.
        """
        import urllib.request
        import json

        base = self.endpoint.rstrip("/")

        # 1. Existing session on o-browser-full
        ws_url = self._fetch_current_session_ws(base)
        if ws_url:
            return ws_url

        # 2. Auto-create a session (o-browser-full)
        if self.auto_session:
            ws_url = self._create_session_and_get_ws(base)
            if ws_url:
                return ws_url

        # 3. Fallback: direct CDP /json/version (raw Chrome remote-debugging)
        cdp_base = re.sub(r":\d+", ":9222", base)
        with urllib.request.urlopen(f"{cdp_base}/json/version", timeout=5) as resp:
            data = json.loads(resp.read())
            return data["webSocketDebuggerUrl"]

    @staticmethod
    def _fetch_current_session_ws(base: str) -> Optional[str]:
        import urllib.request
        import json

        try:
            with urllib.request.urlopen(f"{base}/api/sessions/current", timeout=5) as resp:
                data = json.loads(resp.read())
                return data.get("cdp", {}).get("ws_url")
        except Exception:
            return None

    def _create_session_and_get_ws(self, base: str) -> Optional[str]:
        import urllib.request
        import json

        try:
            req = urllib.request.Request(
                f"{base}/api/sessions",
                data=json.dumps({"workflow": self.workflow}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read())
                return data.get("cdp", {}).get("ws_url")
        except Exception:
            return None

    async def start(self) -> "RemoteBrowser":
        """Connect to remote browser."""
        from patchright.async_api import async_playwright

        self._playwright = await async_playwright().start()

        if self.endpoint.startswith("ws://") or self.endpoint.startswith("wss://"):
            ws_url = self.endpoint
        else:
            ws_url = await self._discover_ws_url()

        self._browser = await self._playwright.chromium.connect_over_cdp(ws_url)
        contexts = self._browser.contexts
        self._context = contexts[0] if contexts else await self._browser.new_context()
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()

        return self

    async def close(self):
        """Disconnect (does NOT kill the remote browser)."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
