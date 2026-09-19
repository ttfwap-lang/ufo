"""UI Automation-backed desktop automation adapter.

Handles native Win32 targets that have no CDP surface for Playwright to
attach to: Notepad, Office's native ribbon UI, third-party native
binaries (e.g. a Rust "BankFidelity" app), and everything else that is
not Chrome/Edge/Electron. See ``factory.get_desktop_automation`` for
routing logic and ``playwright_adapter.PlaywrightDesktop`` for the
CDP-based counterpart.

``pywinauto`` (and optionally ``uiautomation``) are optional dependencies
(the ``native-win32`` extra in pyproject.toml). Importing this module
must never fail even if those packages are not installed on the current
platform -- the import is deferred until a ``UIADesktop`` instance
actually needs it, at which point a clear ``RuntimeError`` is raised if
the package is missing.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from ufo.automation.desktop import Element, Rect


def _import_pywinauto() -> Any:
    """Lazily import pywinauto, raising a clear error if absent."""
    try:
        import pywinauto  # type: ignore
        from pywinauto import Application  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised via mocked tests
        raise RuntimeError(
            "The 'pywinauto' package is required for UIADesktop but is not "
            "installed. Install it via the 'native-win32' extra, e.g. "
            "`pip install ufo[native-win32]`."
        ) from exc
    return pywinauto, Application


class UIADesktop:
    """DesktopAutomation implementation for native Win32 apps via UIA.

    Blocking pywinauto calls are offloaded to a thread via
    ``asyncio.to_thread`` so this class can satisfy the async
    ``DesktopAutomation`` protocol without blocking the event loop.
    """

    def __init__(self) -> None:
        self._pywinauto = None
        self._application_cls = None
        self._app = None
        self._pid: Optional[int] = None

    def _ensure_imported(self) -> None:
        if self._pywinauto is None:
            self._pywinauto, self._application_cls = _import_pywinauto()

    async def launch(self, app: str, args: Optional[list] = None) -> int:
        """Launch a native application by executable path/name."""
        self._ensure_imported()
        cmd_line = app if not args else " ".join([app, *args])

        def _do_launch():
            application = self._application_cls(backend="uia").start(cmd_line)
            return application

        self._app = await asyncio.to_thread(_do_launch)
        self._pid = getattr(self._app.process, "pid", None) if hasattr(
            self._app, "process"
        ) else None
        return self._pid or 0

    async def find_window(
        self, title_re: str, class_name: Optional[str] = None
    ) -> Element:
        """Find a top-level window by title regex (and optional class name)."""
        self._ensure_imported()
        if self._app is None:
            raise RuntimeError("UIADesktop.launch() must be called first")

        kwargs = {"title_re": title_re}
        if class_name:
            kwargs["class_name"] = class_name

        def _do_find():
            window = self._app.window(**kwargs)
            window.wait("exists", timeout=10)
            info = window.element_info
            rect_obj = getattr(info, "rectangle", None)
            rect = None
            if rect_obj is not None:
                rect = Rect(
                    left=rect_obj.left,
                    top=rect_obj.top,
                    right=rect_obj.right,
                    bottom=rect_obj.bottom,
                )
            return window, info, rect

        window, info, rect = await asyncio.to_thread(_do_find)
        return Element(
            handle=window,
            name=getattr(info, "name", None),
            class_name=getattr(info, "class_name", None),
            rect=rect,
            automation_id=getattr(info, "automation_id", None),
        )

    async def find_element(self, window: Element, **criteria: Any) -> Element:
        """Find a descendant control within ``window`` matching ``criteria``.

        Criteria are passed through to pywinauto's ``.child_window(**criteria)``,
        e.g. ``title="OK"``, ``control_type="Button"``, ``auto_id="submitBtn"``.
        """
        self._ensure_imported()
        parent = window.handle

        def _do_find():
            control = parent.child_window(**criteria)
            control.wait("exists", timeout=10)
            info = control.element_info
            rect_obj = getattr(info, "rectangle", None)
            rect = None
            if rect_obj is not None:
                rect = Rect(
                    left=rect_obj.left,
                    top=rect_obj.top,
                    right=rect_obj.right,
                    bottom=rect_obj.bottom,
                )
            return control, info, rect

        control, info, rect = await asyncio.to_thread(_do_find)
        return Element(
            handle=control,
            name=getattr(info, "name", None),
            class_name=getattr(info, "class_name", None),
            rect=rect,
            automation_id=getattr(info, "automation_id", None),
        )

    async def click(self, element: Element) -> None:
        await asyncio.to_thread(element.handle.click_input)

    async def type_text(self, element: Element, text: str) -> None:
        await asyncio.to_thread(element.handle.type_keys, text, with_spaces=True)

    async def get_text(self, element: Element) -> str:
        def _do_get():
            try:
                return element.handle.window_text()
            except AttributeError:
                return element.handle.get_value()

        return await asyncio.to_thread(_do_get)

    async def screenshot(self, region: Optional[Rect] = None) -> bytes:
        if self._app is None:
            raise RuntimeError("UIADesktop.launch() must be called first")

        def _do_screenshot():
            import io

            top_window = self._app.top_window()
            image = top_window.capture_as_image()
            if region is not None:
                image = image.crop(
                    (region.left, region.top, region.right, region.bottom)
                )
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            return buf.getvalue()

        return await asyncio.to_thread(_do_screenshot)

    async def close(self) -> None:
        if self._app is not None:

            def _do_close():
                try:
                    self._app.kill()
                except Exception:
                    pass

            await asyncio.to_thread(_do_close)
            self._app = None
