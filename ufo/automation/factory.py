"""Backend selection for desktop automation.

Routes a target by process/executable name to the appropriate
``DesktopAutomation`` implementation:

- Chrome, Edge, and known Electron apps -> ``PlaywrightDesktop`` (CDP).
- Everything else (Notepad, Office native UI, third-party native
  binaries such as "BankFidelity", etc.) -> ``UIADesktop``.

Playwright cannot attach to arbitrary native Win32 windows, so this is a
two-backend hybrid, not a full replacement of one by the other. See
``docs/plans/E2E_REMEDIATION_PLAN.md`` Phase 2 for the rationale.
"""

from __future__ import annotations

from ufo.automation.desktop import DesktopAutomation
from ufo.automation.playwright_adapter import ELECTRON_PROCESS_NAMES, PlaywrightDesktop
from ufo.automation.uia_adapter import UIADesktop

# Process names that Playwright can drive directly via CDP.
_PLAYWRIGHT_PROCESS_NAMES = {"chrome.exe", "msedge.exe"} | ELECTRON_PROCESS_NAMES


def is_electron_app(process_name: str) -> bool:
    """Return True if ``process_name`` is a known Electron-based app."""
    return process_name.lower() in ELECTRON_PROCESS_NAMES


def get_desktop_automation(process_name: str) -> DesktopAutomation:
    """Select the appropriate desktop automation backend for ``process_name``.

    :param process_name: the target executable's name, e.g. "chrome.exe",
        "notepad.exe", "BankFidelity.exe". Matching is case-insensitive.
    :return: a ``PlaywrightDesktop`` instance for Chrome/Edge/Electron
        targets, or a ``UIADesktop`` instance for everything else.
    """
    normalized = (process_name or "").strip().lower()
    if normalized in _PLAYWRIGHT_PROCESS_NAMES:
        return PlaywrightDesktop()
    return UIADesktop()
