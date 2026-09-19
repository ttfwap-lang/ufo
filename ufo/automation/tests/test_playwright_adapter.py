"""Unit tests for automation.playwright_adapter.

These tests mock out the underlying playwright calls entirely -- they do
not require the ``playwright`` package to be installed, nor a real
browser. Constructing a ``PlaywrightDesktop`` never imports playwright;
only calling ``launch`` does, so:

- Tests that only need to verify import-guarding use no mocks.
- Tests that exercise adapter behavior patch
  ``automation.playwright_adapter._import_playwright`` directly, so they
  work whether or not playwright is actually installed in this
  environment.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure the repo root (which contains this "ufo" package) is importable
# when tests are run directly via `pytest automation/tests/`.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT.parent))

from ufo.automation.desktop import Rect
from ufo.automation.playwright_adapter import ELECTRON_PROCESS_NAMES, PlaywrightDesktop


def test_import_guard_raises_clear_runtime_error_when_playwright_missing():
    """If playwright truly is not installed, instantiating the class must
    not fail, and calling launch() must raise a clear, actionable error."""
    with patch.dict(sys.modules, {"playwright": None, "playwright.async_api": None}):
        adapter = PlaywrightDesktop()
        import asyncio

        with pytest.raises(RuntimeError, match="playwright"):
            asyncio.run(adapter.launch("chrome.exe"))


@pytest.mark.asyncio
async def test_launch_connects_over_cdp_when_endpoint_given():
    mock_page = MagicMock()
    mock_context = MagicMock(pages=[mock_page])
    mock_browser = MagicMock(contexts=[mock_context], process=MagicMock(pid=4321))
    mock_browser.close = AsyncMock()

    mock_chromium = MagicMock()
    mock_chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)

    mock_playwright_obj = MagicMock(chromium=mock_chromium)

    mock_pw_cm = MagicMock()
    mock_pw_cm.start = AsyncMock(return_value=mock_playwright_obj)
    mock_pw_cm.__aexit__ = AsyncMock(return_value=None)

    fake_async_playwright = MagicMock(return_value=mock_pw_cm)

    with patch(
        "ufo.automation.playwright_adapter._import_playwright",
        return_value=fake_async_playwright,
    ):
        adapter = PlaywrightDesktop(cdp_endpoint="http://localhost:9222")
        pid = await adapter.launch("chrome.exe")

    assert pid == 4321
    mock_chromium.connect_over_cdp.assert_awaited_once_with("http://localhost:9222")


@pytest.mark.asyncio
async def test_launch_launches_new_browser_when_no_endpoint():
    mock_page = MagicMock()
    mock_context = MagicMock(pages=[])
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_browser = MagicMock(contexts=[], process=None)
    mock_browser.new_context = AsyncMock(return_value=mock_context)

    mock_chromium = MagicMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)

    mock_playwright_obj = MagicMock(chromium=mock_chromium)
    mock_pw_cm = MagicMock()
    mock_pw_cm.start = AsyncMock(return_value=mock_playwright_obj)

    fake_async_playwright = MagicMock(return_value=mock_pw_cm)

    with patch(
        "ufo.automation.playwright_adapter._import_playwright",
        return_value=fake_async_playwright,
    ):
        adapter = PlaywrightDesktop()
        pid = await adapter.launch("msedge.exe")

    mock_chromium.launch.assert_awaited_once()
    assert mock_chromium.launch.call_args.kwargs["channel"] == "msedge"
    assert pid == 0


@pytest.mark.asyncio
async def test_find_window_matches_title_regex():
    mock_page = MagicMock()
    mock_page.title = AsyncMock(return_value="Example Domain - Chrome")
    mock_context = MagicMock(pages=[mock_page])
    mock_browser = MagicMock(contexts=[mock_context])

    adapter = PlaywrightDesktop()
    adapter._browser = mock_browser

    element = await adapter.find_window(r"Example Domain")
    assert element.handle is mock_page
    assert element.name == "Example Domain - Chrome"


@pytest.mark.asyncio
async def test_find_window_raises_lookup_error_when_no_match():
    mock_page = MagicMock()
    mock_page.title = AsyncMock(return_value="Unrelated")
    mock_context = MagicMock(pages=[mock_page])
    mock_browser = MagicMock(contexts=[mock_context])

    adapter = PlaywrightDesktop()
    adapter._browser = mock_browser

    with pytest.raises(LookupError):
        await adapter.find_window(r"Nonexistent")


@pytest.mark.asyncio
async def test_click_and_type_text_delegate_to_locator():
    from ufo.automation.desktop import Element

    mock_locator = MagicMock()
    mock_locator.click = AsyncMock()
    mock_locator.fill = AsyncMock()
    mock_locator.text_content = AsyncMock(return_value="hello world")

    element = Element(handle=mock_locator, name="#input")
    adapter = PlaywrightDesktop()

    await adapter.click(element)
    mock_locator.click.assert_awaited_once()

    await adapter.type_text(element, "hello world")
    mock_locator.fill.assert_awaited_once_with("hello world")

    text = await adapter.get_text(element)
    assert text == "hello world"


@pytest.mark.asyncio
async def test_screenshot_applies_region_clip():
    mock_page = MagicMock()
    mock_page.screenshot = AsyncMock(return_value=b"PNGDATA")

    adapter = PlaywrightDesktop()
    adapter._page = mock_page

    region = Rect(left=0, top=0, right=100, bottom=50)
    result = await adapter.screenshot(region)

    assert result == b"PNGDATA"
    kwargs = mock_page.screenshot.call_args.kwargs
    assert kwargs["clip"] == {"x": 0, "y": 0, "width": 100, "height": 50}


@pytest.mark.asyncio
async def test_close_closes_browser_and_playwright_context():
    mock_browser = MagicMock()
    mock_browser.close = AsyncMock()
    mock_pw_cm = MagicMock()
    mock_pw_cm.__aexit__ = AsyncMock(return_value=None)

    adapter = PlaywrightDesktop()
    adapter._browser = mock_browser
    adapter._playwright_cm = mock_pw_cm

    await adapter.close()

    mock_browser.close.assert_awaited_once()
    mock_pw_cm.__aexit__.assert_awaited_once()
    assert adapter._browser is None
    assert adapter._playwright_cm is None


def test_electron_process_names_is_nonempty_set():
    assert isinstance(ELECTRON_PROCESS_NAMES, set)
    assert "code.exe" in ELECTRON_PROCESS_NAMES
