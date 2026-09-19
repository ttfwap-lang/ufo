"""Playwright-backed desktop automation adapter.

Handles Chromium/Edge and Electron targets by attaching to their Chrome
DevTools Protocol (CDP) endpoint. This backend has NO ability to drive
arbitrary native Win32 windows (Notepad, Office's native ribbon UI, etc.)
-- those must go through ``uia_adapter.UIADesktop`` instead. See
``factory.get_desktop_automation`` for routing logic.

The ``playwright`` package is an optional dependency (the ``windows``
extra in pyproject.toml). Importing this module must never fail even if
``playwright`` is not installed -- the import is deferred until a
``PlaywrightDesktop`` instance actually needs it, at which point a clear
``RuntimeError`` is raised if the package is missing.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from ufo.automation.desktop import Element, Rect

# Known Electron-based application process names. This is intentionally a
# small, explicit allowlist rather than a heuristic -- extend as needed.
ELECTRON_PROCESS_NAMES = {
    "electron.exe",
    "code.exe",  # VS Code
    "slack.exe",
    "discord.exe",
    "teams.exe",
    "figma.exe",
}


def _import_playwright() -> Any:
    """Lazily import playwright's async API, raising a clear error if absent."""
    try:
        from playwright.async_api import async_playwright  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised via mocked tests
        raise RuntimeError(
            "The 'playwright' package is required for PlaywrightDesktop but is "
            "not installed. Install it via the 'windows' extra, e.g. "
            "`pip install ufo[windows]` followed by `playwright install chromium`."
        ) from exc
    return async_playwright


class PlaywrightDesktop:
    """DesktopAutomation implementation for Chromium/Edge/Electron via CDP.

    This class satisfies the ``DesktopAutomation`` protocol structurally
    (see ``automation.desktop.DesktopAutomation``); it does not need to
    subclass it because the protocol is runtime-checkable and duck-typed.
    """

    def __init__(self, cdp_endpoint: Optional[str] = None) -> None:
        """
        :param cdp_endpoint: Optional existing CDP endpoint (e.g.
            "http://localhost:9222") to attach to. If not provided, a new
            browser is launched on demand by ``launch``.
        """
        self._cdp_endpoint = cdp_endpoint
        self._playwright_cm = None
        self._playwright = None
        self._browser = None
        self._page = None

    async def launch(self, app: str, args: Optional[list] = None) -> int:
        """Launch or attach to a Chromium/Edge/Electron target.

        :param app: executable name (e.g. "chrome.exe", "msedge.exe") or a
            path to an Electron app's executable.
        :param args: extra command-line args, e.g. ["--remote-debugging-port=9222"].
        :return: the browser process id, if available (0 if unknown).
        """
        async_playwright = _import_playwright()
        self._playwright_cm = async_playwright()
        self._playwright = await self._playwright_cm.start()

        if self._cdp_endpoint:
            self._browser = await self._playwright.chromium.connect_over_cdp(
                self._cdp_endpoint
            )
        else:
            channel = "msedge" if "edge" in app.lower() else "chrome"
            self._browser = await self._playwright.chromium.launch(
                channel=channel, args=args or []
            )

        contexts = self._browser.contexts
        context = contexts[0] if contexts else await self._browser.new_context()
        pages = context.pages
        self._page = pages[0] if pages else await context.new_page()

        proc = getattr(self._browser, "process", None)
        pid = getattr(proc, "pid", 0) if proc else 0
        return pid or 0

    async def find_window(
        self, title_re: str, class_name: Optional[str] = None
    ) -> Element:
        """Find a browser page/window whose title matches ``title_re``."""
        if self._browser is None:
            raise RuntimeError("PlaywrightDesktop.launch() must be called first")

        pattern = re.compile(title_re)
        for context in self._browser.contexts:
            for page in context.pages:
                title = await page.title()
                if pattern.search(title or ""):
                    self._page = page
                    return Element(handle=page, name=title, class_name=class_name)

        raise LookupError(f"No page found matching title regex: {title_re!r}")

    async def find_element(self, window: Element, **criteria: Any) -> Element:
        """Find an element on the page via a CSS/text selector.

        Expected criteria: ``selector`` (CSS selector string) or ``text``.
        """
        page = window.handle
        selector = criteria.get("selector")
        if not selector and "text" in criteria:
            selector = f"text={criteria['text']}"
        if not selector:
            raise ValueError(
                "find_element requires a 'selector' or 'text' criterion"
            )

        locator = page.locator(selector).first
        box = await locator.bounding_box()
        rect = (
            Rect(
                left=int(box["x"]),
                top=int(box["y"]),
                right=int(box["x"] + box["width"]),
                bottom=int(box["y"] + box["height"]),
            )
            if box
            else None
        )
        return Element(handle=locator, name=selector, rect=rect)

    async def click(self, element: Element) -> None:
        await element.handle.click()

    async def type_text(self, element: Element, text: str) -> None:
        await element.handle.fill(text)

    async def get_text(self, element: Element) -> str:
        return await element.handle.text_content() or ""

    async def screenshot(self, region: Optional[Rect] = None) -> bytes:
        if self._page is None:
            raise RuntimeError("PlaywrightDesktop.launch() must be called first")

        clip = None
        if region is not None:
            clip = {
                "x": region.left,
                "y": region.top,
                "width": region.width,
                "height": region.height,
            }
        return await self._page.screenshot(clip=clip)

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright_cm is not None:
            await self._playwright_cm.__aexit__(None, None, None)
            self._playwright_cm = None
            self._playwright = None
