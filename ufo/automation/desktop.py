"""Backend-agnostic desktop automation protocol and shared data types.

This module defines the ``DesktopAutomation`` protocol that both the
Playwright-backed adapter (``playwright_adapter.PlaywrightDesktop``, for
Chromium/Edge/Electron targets) and the UI Automation-backed adapter
(``uia_adapter.UIADesktop``, for native Win32 targets) implement.

Consumers should depend on this protocol (and the ``factory`` module to
obtain a concrete instance) rather than importing a specific adapter
directly, so that call sites are agnostic to which backend is actually
driving a given target.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class Rect:
    """A rectangle in screen coordinates."""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


@dataclass
class Element:
    """A handle to a UI element, valid for whichever backend produced it.

    ``handle`` is backend-specific (e.g. an HWND int for UIA, or an opaque
    Playwright locator/ElementHandle wrapper for the Playwright backend).
    Callers should treat it as an opaque token and pass it back into the
    same ``DesktopAutomation`` instance that produced it.
    """

    handle: Any
    name: Optional[str] = None
    class_name: Optional[str] = None
    rect: Optional[Rect] = None
    automation_id: Optional[str] = None


@runtime_checkable
class DesktopAutomation(Protocol):
    """Protocol implemented by every desktop automation backend."""

    async def launch(self, app: str, args: Optional[list] = None) -> int:
        """Launch an application, returning its process id."""
        ...

    async def find_window(
        self, title_re: str, class_name: Optional[str] = None
    ) -> Element:
        """Find a top-level window by title regex (and optional class name)."""
        ...

    async def find_element(self, window: Element, **criteria: Any) -> Element:
        """Find a descendant element within ``window`` matching ``criteria``."""
        ...

    async def click(self, element: Element) -> None:
        """Click the given element."""
        ...

    async def type_text(self, element: Element, text: str) -> None:
        """Type text into the given element."""
        ...

    async def get_text(self, element: Element) -> str:
        """Return the text content of the given element."""
        ...

    async def screenshot(self, region: Optional[Rect] = None) -> bytes:
        """Capture a screenshot, optionally limited to ``region``. Returns PNG bytes."""
        ...

    async def close(self) -> None:
        """Release any resources held by this backend instance."""
        ...
