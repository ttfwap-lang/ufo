"""Hybrid desktop automation package.

This package provides a unified, backend-agnostic protocol for driving
Windows desktop UIs. Two backends are provided:

- ``playwright_adapter.PlaywrightDesktop``: drives Chromium/Edge and
  Electron apps via Chrome DevTools Protocol (CDP), using Playwright.
- ``uia_adapter.UIADesktop``: drives arbitrary native Win32 windows
  (Notepad, Office's native ribbon UI, third-party native binaries, etc.)
  via UI Automation (pywinauto/uiautomation), since Playwright has no CDP
  surface to attach to for those targets.

Use ``factory.get_desktop_automation(process_name)`` to select the
appropriate backend for a given target process.
"""

from ufo.automation.desktop import DesktopAutomation, Element, Rect
from ufo.automation.factory import get_desktop_automation

__all__ = [
    "DesktopAutomation",
    "Element",
    "Rect",
    "get_desktop_automation",
]
