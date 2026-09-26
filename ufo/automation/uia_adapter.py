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
        # Ownership flag: did WE start this process, or merely attach to one that
        # was already running? close() only kills what we started.
        self._launched = False

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
        self._launched = True   # we started it, so closing may stop it
        # pywinauto's Application.process IS the int PID (application.py sets
        # `self.process = dw_process_id`); getattr(..., "pid") was always None,
        # so launch() returned 0 and the pid could never be used to reconnect.
        proc = getattr(self._app, "process", None)
        self._pid = proc if isinstance(proc, int) else getattr(proc, "pid", None)
        return self._pid or 0

    async def connect(self, process_id: int) -> None:
        """Connect to an existing application by process id."""
        self._ensure_imported()

        def _do_connect():
            application = self._application_cls(backend="uia").connect(process=process_id)
            return application

        self._app = await asyncio.to_thread(_do_connect)
        self._launched = False  # attached to a running app - NOT ours to kill
        self._pid = process_id

    async def connect_handle(self, hwnd: int) -> None:
        """Connect to an application by window handle (title-independent)."""
        self._ensure_imported()

        def _do_connect():
            application = self._application_cls(backend="uia").connect(handle=hwnd)
            return application

        self._app = await asyncio.to_thread(_do_connect)
        self._launched = False  # attached to a running app - NOT ours to kill
        self._pid = None

    async def window_from_handle(self, hwnd: int) -> Element:
        """Build an Element for a window handle (title-independent)."""
        self._ensure_imported()

        def _do_build():
            from pywinauto import Desktop
            desktop = Desktop(backend="uia")
            window = desktop.window(handle=hwnd)
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

        window, info, rect = await asyncio.to_thread(_do_build)
        return Element(
            handle=window,
            name=getattr(info, "name", None),
            class_name=getattr(info, "class_name", None),
            rect=rect,
            automation_id=getattr(info, "automation_id", None),
        )

    async def find_window(
        self, title_re: str = ".*", class_name: Optional[str] = None
    ) -> Element:
        """Find a top-level window by title regex (and optional class name).

        ``title_re`` defaults to ``.*`` so class-only searches work - many
        apps (e.g. Telegram) change their window title to reflect the active
        document/chat.
        
        If connected to an application (via launch() or connect()), searches within that app.
        Otherwise, searches all top-level windows using pywinauto's Desktop class.
        """
        self._ensure_imported()

        kwargs = {"title_re": title_re}
        if class_name:
            kwargs["class_name"] = class_name
        elif title_re == ".*":
            # A bare default search could match the first arbitrary window on
            # the desktop - require an explicit discriminator.
            raise ValueError(
                "find_window requires a class_name (or a specific title_re) "
                "when title_re is left as the default '.*'"
            )

        def _do_find():
            if self._app is not None:
                # Search within connected application
                window = self._app.window(**kwargs)
            else:
                # Search all top-level windows using Desktop
                from pywinauto import Desktop
                desktop = Desktop(backend="uia")
                window = desktop.window(**kwargs)
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

    async def screenshot(self, window: Optional[Element] = None, region: Optional[Rect] = None) -> bytes:
        """Capture a screenshot of a specific window (or the app's top window).

        Uses the window's own HWND with PrintWindow for reliability - works even
        when the target window is behind other windows. Falls back to
        capture_as_image() only for the exact window, never a full desktop grab.

        :param window: Optional specific window Element to capture.
        :param region: Optional region to crop.
        :return: PNG bytes.
        """
        if self._app is None and window is None:
            raise RuntimeError("UIADesktop.launch() or connect() must be called first")

        def _do_screenshot():
            import io
            from PIL import Image

            target = window.handle if window is not None else self._app.top_window()
            # Resolve concrete HWND first
            hwnd = None
            try:
                hwnd = target.handle if hasattr(target, "handle") else None
                if isinstance(hwnd, bool) or not isinstance(hwnd, int):
                    hwnd = None
            except Exception:
                hwnd = None

            image = None
            # 1) Preferred: raw win32 PrintWindow on the specific HWND (captures the
            #    exact window - works even when behind other windows).
            if hwnd:
                try:
                    import win32gui
                    import win32ui
                    import ctypes

                    if win32gui.IsWindow(hwnd):
                        rect = win32gui.GetWindowRect(hwnd)
                        width = rect[2] - rect[0]
                        height = rect[3] - rect[1]
                        if width > 0 and height > 0:
                            hwnd_dc = win32gui.GetWindowDC(hwnd)
                            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
                            save_dc = mfc_dc.CreateCompatibleDC()
                            bmp = win32ui.CreateBitmap()
                            bmp.CreateCompatibleBitmap(mfc_dc, width, height)
                            save_dc.SelectObject(bmp)
                            try:
                                PW_RENDERFULLCONTENT = 2
                                result = ctypes.windll.user32.PrintWindow(
                                    hwnd, save_dc.GetSafeHdc(), PW_RENDERFULLCONTENT
                                )
                                if not result:
                                    result = ctypes.windll.user32.PrintWindow(
                                        hwnd, save_dc.GetSafeHdc(), 1
                                    )
                                if result:
                                    bmpinfo = bmp.GetInfo()
                                    bmpstr = bmp.GetBitmapBits(True)
                                    image = Image.frombuffer(
                                        "RGB",
                                        (bmpinfo["bmWidth"], bmpinfo["bmHeight"]),
                                        bmpstr,
                                        "raw",
                                        "BGRX",
                                        0,
                                        1,
                                    )
                            finally:
                                save_dc.DeleteDC()
                                mfc_dc.DeleteDC()
                                win32gui.ReleaseDC(hwnd, hwnd_dc)
                                win32gui.DeleteObject(bmp.GetHandle())
                except Exception:
                    image = None

            # 2) Fallback: pywinauto control capture (may fail for custom Qt UIA)
            if image is None:
                try:
                    image = target.capture_as_image()
                    if image is None or image.size == (0, 0):
                        image = None
                except Exception:
                    image = None

            # 3) Last resort: PrintWindow via ui_control helper on the HWND
            if image is None and hwnd:
                try:
                    from ufo.automator.ui_control.screenshot import _win32_print_window
                    image = _win32_print_window(hwnd)
                except Exception:
                    image = None

            if image is None:
                raise RuntimeError("Unable to capture the target window")

            if region is not None:
                image = image.crop(
                    (region.left, region.top, region.right, region.bottom)
                )
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            return buf.getvalue()

        return await asyncio.to_thread(_do_screenshot)

    async def close(self) -> None:
        """Release the connection - stop the process ONLY if we started it.

        This distinction is the whole point of the method, and it was missing:
        launch() does Application().start() (a process we own) while connect()
        and connect_handle() do Application().connect() (a process that was
        already running and merely attached to). close() killed the app in both
        cases, so any caller that attached to the operator's running Telegram
        and then tidied up after itself TERMINATED TELEGRAM DESKTOP. That is
        what TelegramGUIController.close() does - and its own docstring says it
        closes "the desktop automation connection", not the application.

        Callers include ufo_bridge.py (5 sites) and telegram_receiver.py, so the
        kill reached production. Observed live: a script that connected, took a
        screenshot and called close() left Telegram gone a minute later, with no
        error anywhere, because kill() failures are swallowed.

        A launched process is still cleaned up - leaving a spawned app behind
        after teardown would leak a session nobody asked for.
        """
        if self._app is None:
            return
        if self._launched:

            def _do_close():
                try:
                    self._app.kill()
                except Exception:
                    pass

            await asyncio.to_thread(_do_close)
        # Attached-only: drop our reference and leave the running app alone.
        self._app = None
        self._launched = False
