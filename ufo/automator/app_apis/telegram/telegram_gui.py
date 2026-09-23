"""Telegram Desktop GUI Controller - Hybrid UIA + Keyboard + Visual automation."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from ufo.automation.desktop import DesktopAutomation, Element, Rect
from ufo.automation.factory import get_desktop_automation
from ufo.automator.app_apis.telegram.telegram_privacy import PrivacyRedactor


@dataclass
class ChatItem:
    """Represents a chat in the Telegram sidebar."""
    name: str
    unread_count: int = 0
    is_muted: bool = False
    is_channel: bool = False
    is_group: bool = False
    is_bot: bool = False
    last_message_preview: str = ""
    element: Optional[Element] = None


@dataclass
class Message:
    """Represents a message in the chat history."""
    sender: str
    text: str
    timestamp: str
    is_outgoing: bool = False
    has_media: bool = False


class TelegramGUIController:
    """Hybrid controller for Telegram Desktop using UIA + Keyboard + Visual."""
    
    # Telegram Desktop window class name
    WINDOW_CLASS = "class MainWindow"
    PROCESS_NAME = "Telegram.exe"
    
    # Keyboard shortcuts
    SHORTCUTS = {
        "new_message": "^n",           # Ctrl+N
        "search": "^f",                # Ctrl+F
        "next_chat": "^{TAB}",         # Ctrl+Tab
        "prev_chat": "^+{TAB}",        # Ctrl+Shift+Tab
        "focus_input": "{TAB}",        # Tab
        "send": "{ENTER}",             # Enter
        "new_line": "+{ENTER}",        # Shift+Enter
        "escape": "{ESC}",             # Escape
        "select_all": "^a",            # Ctrl+A
        "copy": "^c",                  # Ctrl+C
        "paste": "^v",                 # Ctrl+V
        "settings": "^p",              # Ctrl+P (sometimes)
        "contacts": "^o",              # Ctrl+O
        "calls": "^l",                 # Ctrl+L
    }
    
    def __init__(self, desktop: Optional[DesktopAutomation] = None):
        """Initialize the Telegram GUI controller.
        
        Args:
            desktop: Optional DesktopAutomation instance. If not provided,
                     will be created based on process name.
        """
        self._desktop = desktop
        self._window: Optional[Element] = None
        self._chat_list: Optional[Element] = None
        self._connected = False
        self._lockout = None  # Optional ScreenLockout reference for locked input
        self._privacy_redactor: Optional[PrivacyRedactor] = None
        self._human_mouse = None  # cached HumanMouse engine
        # MANDATORY warning gate: near-opaque on-top 5s countdown with "*" to
        # cancel - shown before ANY automation input, even tests.
        self._warning_lockout = None
        self._automation_warning_armed = False
    
    async def connect(self) -> bool:
        """Connect to Telegram Desktop window.

        Finds the Telegram main window robustly (by process name, NOT by
        title - the title changes to the active chat name during use).

        Returns:
            True if connected successfully, False otherwise.
        """
        if self._desktop is None:
            self._desktop = get_desktop_automation(self.PROCESS_NAME)

        try:
            # Find the Telegram window by process name + class (title-agnostic)
            found = await self._find_telegram_window()
            if not found:
                print("Telegram window not found - is Telegram Desktop running?")
                self._connected = False
                return False

            hwnd, title, cls, pid = found
            # Connect pywinauto by window handle (title-independent)
            try:
                await self._desktop.connect_handle(hwnd)
            except Exception:
                # Fall back to PID connect
                await self._desktop.connect(pid)

            # Resolve the window Element directly from the HWND - avoids the
            # class-only window search (which could match other Qt windows).
            self._window = await self._desktop.window_from_handle(hwnd)
            if self._window is None:
                self._window = await self._desktop.find_window(
                    class_name=self.WINDOW_CLASS
                )

            # Find the chat list (Dialogs::InnerWidget)
            self._chat_list = await self._find_chat_list()

            self._connected = True
            return True

        except Exception as e:
            print(f"Failed to connect to Telegram: {e}")
            self._connected = False
            return False

    async def _find_telegram_window(self) -> Optional[Tuple[int, str, str, int]]:
        """Find Telegram's main window: (hwnd, title, class_name, pid).

        Title-independent: Telegram changes its window title to the active
        chat name (e.g. "whale cc 3 (3625)"), so we resolve by process name
        and prefer the main QWindowIcon class.

        Robustness (RULE 2): Telegram can leave a minimized "ghost" window
        (rect at -32000/-25600) next to a real, sane-geometry window. Binding
        to the ghost breaks every screen-region capture, so candidates are
        SCORED: non-minimized + visible + on-screen + QWindowIcon wins.
        """
        def _do_find():
            import win32gui
            import win32process
            try:
                import psutil
            except Exception:
                psutil = None

            results = []

            def callback(hwnd, res):
                try:
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    proc_name = psutil.Process(pid).name() if psutil else None
                except Exception:
                    return
                if not proc_name or proc_name.lower() != "telegram.exe":
                    return
                title = win32gui.GetWindowText(hwnd)
                cls = win32gui.GetClassName(hwnd)
                if not title and "QWindowIcon" not in cls:
                    return
                results.append((hwnd, title, cls, pid))

            try:
                win32gui.EnumWindows(callback, results)
            except Exception:
                pass

            if not results:
                return None

            def _score(r):
                hwnd, title, cls, _pid = r
                s = 0
                # The real main window is the Qt icon window. Tray/helper
                # windows (Qt51519TrayIconMessageWindowClass) must never win,
                # even when they are not minimized.
                if "QWindowIcon" in cls:
                    s += 500
                elif "Tray" in cls or "tray" in cls:
                    s -= 500
                try:
                    if not win32gui.IsIconic(hwnd):
                        s += 100          # not minimized
                    if win32gui.IsWindowVisible(hwnd):
                        s += 50
                    l, t, rr, b = win32gui.GetWindowRect(hwnd)
                    w, h = rr - l, b - t
                    if w > 200 and h > 200 and l > -1000 and t > -1000:
                        s += 30           # on-screen, sane size
                    if rr > 0 and b > 0:
                        s += 10
                except Exception:
                    pass
                if title:
                    s += 5
                return s

            # Highest score wins; keep the original tie-break (main icon window)
            best = max(results, key=_score)
            return best

        return await asyncio.to_thread(_do_find)
    
    async def _ensure_window_fresh(self) -> bool:
        """Ensure the window handle is still valid, re-find if needed.

        Title-independent: resolves via process name + class, since Telegram
        retitles its window with the active chat name.
        """
        if not self._window:
            return False
        try:
            # Try to access the window to check if it's still valid
            _ = self._window.rect
            return True
        except Exception:
            # Window handle is stale, re-find using the robust finder
            try:
                found = await self._find_telegram_window()
                if not found:
                    return False
                hwnd, title, cls, pid = found
                try:
                    await self._desktop.connect_handle(hwnd)
                except Exception:
                    await self._desktop.connect(pid)
                self._window = await self._desktop.window_from_handle(hwnd)
                self._chat_list = None  # re-resolve later (fresh)
                return True
            except Exception:
                return False
    
    def get_concrete_hwnd(self) -> Optional[int]:
        """Resolve the concrete HWND of the Telegram main window."""
        if not self._window:
            return None
        try:
            handle = self._window.handle
            hwnd = handle.handle if hasattr(handle, "handle") else handle
            if isinstance(hwnd, int) and hwnd > 0:
                return hwnd
        except Exception:
            pass
        return None

    def _ensure_sane_geometry(self, hwnd: int) -> bool:
        """RULE 2: keep Telegram visible, un-minimized and fully on-screen.

        A window restored to an off-screen / oversized geometry breaks
        screen-region screenshots ("Unable to capture the target window")
        and puts click targets outside the desktop. This clamps the window
        into the primary monitor's work area with a small margin.
        """
        try:
            import win32gui
            import win32con

            # Un-minimize / un-hide first (idempotent)
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                import time as _t
                _t.sleep(0.15)
            if not win32gui.IsWindowVisible(hwnd):
                # A hidden-but-real window must be shown, otherwise the
                # screen-region capture grabs whatever is painted on top.
                win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
                win32gui.SetWindowPos(hwnd, win32con.HWND_TOP, 0, 0, 0, 0,
                                      win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
                                      | win32con.SWP_SHOWWINDOW)
                import time as _t2
                _t2.sleep(0.2)

            import ctypes
            from ctypes import wintypes

            SPI_GETWORKAREA = 0x0030
            rect = wintypes.RECT()
            ctypes.windll.user32.SystemParametersInfoW(
                SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
            wa_w = rect.right - rect.left
            wa_h = rect.bottom - rect.top
            if wa_w <= 0 or wa_h <= 0:  # fallback if work area unavailable
                wa_w, wa_h = 1920, 1040

            l, t, r, b = win32gui.GetWindowRect(hwnd)
            w, h = r - l, b - t
            margin = 8
            max_w = max(640, wa_w - 2 * margin)
            max_h = max(480, wa_h - 2 * margin)

            need_fix = False
            # iconic leftovers put the rect at -32000
            if w <= 0 or h <= 0 or l < -1000 or t < -1000:
                need_fix = True
            # extends beyond the work area (bottom/right overflow is the
            # common failure after a display change or geometry restore)
            elif r > rect.right + 4 or b > rect.bottom + 4:
                need_fix = True
            elif w > max_w or h > max_h:
                need_fix = True

            if need_fix:
                nw = min(w if w > 0 else max_w, max_w)
                nh = min(h if h > 0 else max_h, max_h)
                nx = max(rect.left + margin,
                         min(l if l > -1000 else rect.left + margin,
                             rect.right - nw - margin))
                ny = max(rect.top + margin,
                         min(t if t > -1000 else rect.top + margin,
                             rect.bottom - nh - margin))
                win32gui.MoveWindow(hwnd, nx, ny, nw, nh, True)
                return True
            return False
        except Exception:
            return False

    def _ensure_foreground(self) -> bool:
        """Ensure the Telegram window is the foreground window.

        If Telegram is not in the foreground, brings it to front using
        multiple techniques (SetForegroundWindow + Alt-tap trick, minimize/
        restore, WScript.Shell AppActivate) and verifies ownership. Returns
        True ONLY if Telegram owns the foreground afterwards.

        This guarantees keystrokes are delivered to Telegram, never to the
        user's active window - the critical safety guard for autonomous input.
        """
        hwnd = self.get_concrete_hwnd()
        if not hwnd:
            return False
        try:
            import win32gui
            import win32con
            import ctypes
            import time

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            def _is_foreground() -> bool:
                return user32.GetForegroundWindow() == hwnd

            if not win32gui.IsWindow(hwnd):
                return False

            # Fast path: already foreground
            if _is_foreground():
                return True

            # Restore if minimized/hidden
            if win32gui.IsIconic(hwnd) or not win32gui.IsWindowVisible(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.ShowWindow(hwnd, win32con.SW_SHOW)

            # RULE 2: sane size/position - clamp into the work area so
            # screen-region captures can never fail on an off-screen window
            self._ensure_sane_geometry(hwnd)

            # Unlock foreground permission
            user32.LockSetForegroundWindow(1)  # LSFW_UNLOCK

            attempts = [
                # A) Thread-attach + Alt-tap + SetForegroundWindow
                lambda: self._focus_via_attach(hwnd, user32, kernel32),
                # B) Minimize & restore (grant foreground permission)
                lambda: self._focus_via_minimize_restore(hwnd, win32gui, win32con),
                # C) WScript.Shell AppActivate (shell-level focus steal)
                lambda: self._focus_via_appactivate(),
            ]

            for attempt in attempts:
                try:
                    if attempt():
                        if _is_foreground():
                            return True
                except Exception:
                    pass
                time.sleep(0.25)

            return _is_foreground()
        except Exception:
            return False

    def _focus_via_attach(self, hwnd: int, user32, kernel32) -> bool:
        """Focus using thread-input attachment + Alt-tap + SetForegroundWindow."""
        import win32gui
        cur_fore = user32.GetForegroundWindow()
        cur_tid = kernel32.GetCurrentThreadId()
        fore_tid = user32.GetWindowThreadProcessId(cur_fore, None) if cur_fore else 0
        target_tid = user32.GetWindowThreadProcessId(hwnd, None)
        attached = False
        if fore_tid and fore_tid != cur_tid:
            attached = bool(user32.AttachThreadInput(fore_tid, cur_tid, True))
        if target_tid and target_tid != cur_tid:
            user32.AttachThreadInput(target_tid, cur_tid, True)

        # Alt-tap clears Windows foreground lock
        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(0x12, 0, 2, 0)

        try:
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass

        time.sleep(0.3)

        if attached:
            user32.AttachThreadInput(fore_tid, cur_tid, False)
        return user32.GetForegroundWindow() == hwnd

    def _focus_via_minimize_restore(self, hwnd: int, win32gui, win32con) -> bool:
        """Focus by minimizing then restoring (grants foreground permission)."""
        win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
        time.sleep(0.1)
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.3)
        return True

    def _focus_via_appactivate(self) -> bool:
        """Focus using WScript.Shell AppActivate (very reliable focus steal)."""
        try:
            import win32com.client
            shell = win32com.client.Dispatch("WScript.Shell")
            window_title = None
            try:
                import win32gui
                window_title = win32gui.GetWindowText(self.get_concrete_hwnd())
            except Exception:
                pass
            if window_title:
                shell.AppActivate(window_title)
            else:
                shell.AppActivate("Telegram")
            time.sleep(0.3)
            return True
        except Exception:
            return False

    def set_lockout(self, lockout) -> None:
        """Attach an optional ScreenLockout for locked-mode input injection."""
        self._lockout = lockout

    @property
    def lockout_active(self) -> bool:
        """True if a lockout is attached and currently locked."""
        return self._lockout is not None and self._lockout.is_locked

    # ==================== MANDATORY WARNING GATE ====================

    def _build_human_mouse(self):
        """Create/cache the HumanMouse engine with the mandatory warning hook."""
        if self._human_mouse is None:
            from ufo.automator.app_apis.telegram.telegram_human_mouse import (
                HumanMouse,
            )
            self._human_mouse = HumanMouse(
                first_move_hook=self._sync_warning_hook
            )
        return self._human_mouse

    def _sync_warning_hook(self) -> None:
        """Synchronous wrapper: show the 5s countdown before the first move.

        Called from a worker thread (HumanMouse moves are thread-offloaded),
        so it runs its own event loop here.
        """
        import asyncio as _asyncio
        loop = _asyncio.new_event_loop()
        try:
            ok = loop.run_until_complete(self._ensure_automation_warning())
            if not ok:
                raise RuntimeError(
                    "AUTOMATION CANCELLED BY USER (countdown aborted) - refusing to move cursor"
                )
        finally:
            loop.close()

    async def _ensure_automation_warning(
        self, countdown: int = 8, message: str = "AUTOMATION STARTING"
    ) -> bool:
        """MANDATORY near-opaque on-top 5s countdown before automation.

        No input (mouse or keyboard) may ever be injected without first
        showing this message. Cancel keys are verified (Ctrl+Shift+Q primary,
        ESC backup); P = pause. Returns True when the countdown completed.
        """
        if self._automation_warning_armed:
            return True
        from ufo.automator.app_apis.telegram.telegram_lockout import ScreenLockout

        if self._warning_lockout is None:
            self._warning_lockout = ScreenLockout()
            self._warning_lockout._on_stop = self._on_warning_cancel

        armed = await self._warning_lockout.acquire(
            message=message, countdown=countdown
        )
        if not armed:
            # Cancelled during countdown - keep it unarmed; callers must abort
            return False
        self._automation_warning_armed = True
        return True

    def _on_warning_cancel(self) -> None:
        """Cancel pressed on the mandatory warning gate."""
        print("WARNING-GATE: cancel pressed - automation will not take control")
        self._automation_warning_armed = False

    @property
    def warning_armed(self) -> bool:
        return self._automation_warning_armed

    # ==================== RULE 2: FORCE TELEGRAM ON TOP ====================

    async def force_telegram_top(self) -> bool:
        """GLOBAL RULE 2: Telegram must be foreground, visible, sane size.

        1) best-effort in-process (restore/bring/focus)
        2) if UIPI-blocked (elevated Telegram), run the elevated fixer
           (elev_fix_window.py via Start-Process -Verb RunAs) and re-verify
        3) only then return True
        """
        found = await self._find_telegram_window()
        if not found:
            print("force_telegram_top: no Telegram window found")
            return False
        hwnd, title, cls, pid = found

        import win32gui
        if win32gui.IsIconic(hwnd) or not win32gui.IsWindowVisible(hwnd):
            try:
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            except Exception:
                pass

        # In-process attempt
        ok = await asyncio.to_thread(self._ensure_foreground)
        if ok:
            return True

        # UIPI path: elevated fixer (operator approves UAC once)
        print("force_telegram_top: UIPI-blocked - requesting elevated fix (approve UAC)")
        try:
            import subprocess
            proc = subprocess.run(
                [
                    "powershell", "-NoProfile", "-Command",
                    "Start-Process -FilePath "
                    "'C:\\Users\\lnxzf\\Desktop\\projects\\ufo\\ufo\\.venv\\Scripts\\python.exe' "
                    "-ArgumentList 'C:\\Users\\lnxzf\\Desktop\\projects\\ufo\\ufo\\elev_fix_window.py' "
                    "-Verb RunAs -Wait",
                ],
                capture_output=True, text=True, timeout=120,
            )
        except Exception as e:
            print(f"force_telegram_top: elevated fix launch failed: {e}")
        await asyncio.sleep(1.0)
        ok = await asyncio.to_thread(self._ensure_foreground)
        return ok

    # ==================== RULE 3: VISUAL TROUBLESHOOTING ====================

    async def troubleshoot_screenshot(self, label: str = "troubleshoot") -> Optional[str]:
        """GLOBAL RULE 3: capture a screenshot to diagnose any stuck state.

        Saves to ufo_skill_state/evidence/debug/<label>_<ts>.png and returns
        the path. Always called before blind retries.
        """
        try:
            from datetime import datetime
            from pathlib import Path
            shot = await self.take_screenshot()
            if not shot:
                return None
            d = Path("ufo_skill_state/evidence/debug")
            d.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().isoformat().replace(":", "-")
            path = d / f"{label}_{ts}.png"
            with open(path, "wb") as f:
                f.write(shot)
            print(f"[troubleshoot] screenshot -> {path}")
            return str(path)
        except Exception as e:
            print(f"[troubleshoot] failed: {e}")
            return None

    def _type_keys_locked(self, keys: str) -> bool:
        """Type keys while the lockout overlay is active.

        The overlay stays TOPMOST (screen dimmed, user blocked). For each
        keystroke batch:
        1. Pause the overlay's foreground ownership (input burst)
        2. Bring Telegram to the foreground
        3. SendInput reaches Telegram (Qt accepts real keyboard events)
        4. Overlay re-grabs foreground

        The screen never uncovers because the overlay remains topmost.
        """
        if self._lockout is None:
            return False

        try:
            self._lockout.begin_input_burst()
            try:
                if not self._ensure_foreground():
                    return False
                import pywinauto.keyboard as keyboard
                keyboard.send_keys(keys)
                return True
            finally:
                # ALWAYS release the burst - otherwise the focus keeper
                # permanently yields foreground (user could type into Telegram)
                self._lockout.end_input_burst()
        except Exception as e:
            print(f"Locked type keys failed: {e}")
            try:
                self._lockout.end_input_burst()
            except Exception:
                pass
            return False

    async def _type_keys_safe(self, keys: str) -> bool:
        """Type keys ONLY into the Telegram window, respecting lockout mode.

        MANDATORY WARNING: the 5s on-top countdown must be shown before any
        input (even typing). While typing, the warning gate's input burst is
        active so the AI's own keys never trigger the cancel/pause hotkeys.
        """
        import asyncio as _asyncio

        # Locked mode: overlay owns foreground -> burst injection
        if self.lockout_active and self._lockout is not None:
            return await _asyncio.to_thread(self._type_keys_locked, keys)

        # Unlocked mode: MANDATORY warning gate first
        if not self._automation_warning_armed:
            ok = await self._ensure_automation_warning()
            if not ok:
                print("SAFETY: cancelled at countdown - refusing to type")
                return False

        # Burst-suppress while we inject our own keys (never self-cancel/pause)
        burst = None
        if self._warning_lockout is not None:
            self._warning_lockout.begin_input_burst()
            burst = self._warning_lockout
        try:
            if not await _asyncio.to_thread(self._ensure_foreground):
                print("SAFETY: Telegram is not the foreground window - refusing to type")
                return False
            try:
                import pywinauto.keyboard as keyboard
                await _asyncio.to_thread(keyboard.send_keys, keys)
                return True
            except Exception as e:
                print(f"Global type keys failed: {e}")
                if not await self._ensure_window_fresh():
                    return False
                try:
                    await self._desktop.type_text(self._window, keys)
                    return True
                except Exception as e2:
                    print(f"Window type keys failed: {e2}")
                    return False
        finally:
            if burst is not None:
                try:
                    burst.end_input_burst()
                except Exception:
                    pass
    
    async def _dismiss_overlays(self) -> bool:
        """Close stray overlays (search panel, context menus) before work.

        ROOT CAUSE FIX: leaving a Ctrl+F search overlay open hides the
        sidebar chat list - UIA then exposes ZERO ListItems. Pressing ESC
        dismisses it and restores the normal chat list view.

        Returns: True if the overlay was dismissed (state may have changed).
        """
        try:
            # Press Escape via global input (safe: only when we own foreground
            # or a lockout is active; ESC never sends user text to Telegram).
            ok = await self._type_keys_safe(self.SHORTCUTS["escape"])
            await asyncio.sleep(0.4)
            return ok
        except Exception:
            return False

    async def _ensure_sidebar_visible(self) -> bool:
        """Ensure the sidebar chat list is in normal view (no search overlay).

        Called before sidebar enumeration: dismisses any open overlay, then
        re-resolves the chat list. Retries a few times.
        """
        for attempt in range(3):
            # If we already have a chat list with items, we're good
            if self._chat_list is not None and await self._chat_items_exist():
                return True
            # Close any search/overlay that may be hiding the sidebar
            await self._dismiss_overlays()
            self._chat_list = await self._find_chat_list()
            await asyncio.sleep(0.3)
        return self._chat_list is not None

    async def _chat_items_exist(self) -> bool:
        """Quick check whether the chat list currently exposes rows."""
        if self._chat_list is None:
            return False

        def _check():
            try:
                spec = self._chat_list.handle
                return len(spec.children(control_type="ListItem")) > 0
            except Exception:
                return False

        return await asyncio.to_thread(_check)

    async def _find_chat_list(self) -> Optional[Element]:
        """Find the chat list element (Dialogs::InnerWidget) robustly.

        Resolves fresh each call (window handles go stale). Searches the
        Telegram window for the List control whose class is
        'Dialogs::InnerWidget' (the sidebar chat list).
        """
        if not self._window:
            return None

        def _do_find():
            try:
                handle = self._window.handle  # WindowSpecification
                # Note: descendants() is expensive; search for the List control
                # whose UIA class is Dialogs::InnerWidget.
                lists = handle.descendants(control_type="List")
                for lst in lists:
                    try:
                        cls = lst.element_info.class_name
                        if "Dialogs::InnerWidget" in cls:
                            rect_obj = lst.element_info.rectangle
                            rect = None
                            if rect_obj is not None:
                                rect = Rect(
                                    left=rect_obj.left,
                                    top=rect_obj.top,
                                    right=rect_obj.right,
                                    bottom=rect_obj.bottom,
                                )
                            return Element(
                                handle=lst,
                                name="Chats",
                                class_name=cls,
                                rect=rect,
                            )
                    except Exception:
                        continue
                return None
            except Exception:
                return None

        return await asyncio.to_thread(_do_find)

    async def _find_chat_by_name(self, name: str) -> Optional[Element]:
        """Find a chat row (ListItem) in the sidebar by its display name.

        Walks the real chat list - each chat is a ListItem whose window text
        starts with the chat name (e.g. "Saved Messages, ..."). Returns an
        Element whose handle supports click_input() (real conversation click).
        """
        if not self._connected:
            await self.connect()
        if not self._chat_list:
            self._chat_list = await self._find_chat_list()
        if not self._chat_list:
            return None
        # Sidebar may be hidden behind a search overlay - dismiss it first
        if not await self._chat_items_exist():
            await self._ensure_sidebar_visible()
            if not self._chat_list:
                return None

        normalized = name.strip().lower()

        def _do_find():
            try:
                list_spec = self._chat_list.handle  # WindowSpecification
                items = list_spec.children(control_type="ListItem")
                # First pass: exact prefix/name match
                for item in items:
                    try:
                        text = (item.window_text() or "").strip()
                    except Exception:
                        continue
                    if not text:
                        continue
                    first_token = text.split(",")[0].strip().lower()
                    if first_token == normalized:
                        return item
                # Second pass: contains match
                for item in items:
                    try:
                        text = (item.window_text() or "").strip()
                    except Exception:
                        continue
                    if normalized in text.lower():
                        return item
                return None
            except Exception:
                return None

        item = await asyncio.to_thread(_do_find)
        if item is None:
            return None

        # Build Element with rect for potential scroll/click verification
        rect = None
        try:
            info = item.element_info
            rect_obj = getattr(info, "rectangle", None)
            if rect_obj is not None:
                rect = Rect(
                    left=rect_obj.left,
                    top=rect_obj.top,
                    right=rect_obj.right,
                    bottom=rect_obj.bottom,
                )
        except Exception:
            pass
        return Element(handle=item, name=name, class_name="ListItem", rect=rect)

    async def _scroll_chat_list(self, direction: int = -1, steps: int = 1) -> bool:
        """Scroll the sidebar chat list with real mouse wheel events.

        :param direction: -1 scroll down (lower chats), +1 scroll up.
        :param steps: Number of wheel notches.
        :return: True if scrolled, False otherwise.
        """
        if not self._chat_list:
            self._chat_list = await self._find_chat_list()
        if not self._chat_list or not self._chat_list.rect:
            return False

        rect = self._chat_list.rect
        cx = (rect.left + rect.right) // 2
        cy = (rect.top + rect.bottom) // 2

        def _do_scroll():
            try:
                mouse = self._build_human_mouse()
                # Move cursor onto the list with human motion, then wheel with
                # human timing - NO click (a click could open a random chat).
                mouse.scroll(-1 if direction < 0 else 1, x=cx, y=cy)
                for _ in range(max(0, steps - 1)):
                    mouse.scroll(-1 if direction < 0 else 1, x=cx, y=cy)
                return True
            except Exception:
                return False

        return await asyncio.to_thread(_do_scroll)
    
    def _parse_chat_element(self, element: Element) -> Optional[ChatItem]:
        """Parse a chat list item element into ChatItem.

        Privacy: the message preview is ALWAYS redacted - only the chat name
        (navigation metadata) is retained.
        """
        try:
            name = element.window_text() or ""
            # Escape any unicode issues, keep chat name (first token) only
            chat_name = name.split(",")[0].strip() if name else ""
            return ChatItem(
                name=chat_name[:100],
                last_message_preview=PrivacyRedactor.REDACTED,
                element=element
            )
        except Exception:
            return None

    async def get_chats(self, max_chats: int = 50) -> List[ChatItem]:
        """Get the visible chats from the sidebar (real list walk).

        Args:
            max_chats: Maximum number of chats to retrieve.

        Returns:
            List of ChatItem objects (name + element handle for clicking).
        """
        if not self._connected:
            await self.connect()

        # Ensure the sidebar is in normal view (dismiss search overlays that
        # hide the chat list - the root cause of empty enumeration). Retry the
        # walk a few times: the list can lag behind the overlay dismissal.
        for attempt in range(3):
            await self._ensure_sidebar_visible()
            if not self._chat_list:
                return []
            results = await self._walk_chat_items(max_chats)
            if results:
                return results
            await asyncio.sleep(0.5)
        return []

    async def _walk_chat_items(self, max_chats: int) -> List[ChatItem]:
        """Enum the sidebar rows and build privacy-safe ChatItems."""
        if not self._chat_list:
            return []

        def _do_walk():
            results = []
            try:
                list_spec = self._chat_list.handle
                items = list_spec.children(control_type="ListItem")
                for item in items[:max_chats]:
                    try:
                        text = (item.window_text() or "").strip()
                    except Exception:
                        continue
                    if not text:
                        continue
                    # PRIVACY: only the chat name (first token) is retained;
                    # the message preview portion is NEVER stored.
                    chat_name = text.split(",")[0].strip()[:100]
                    if not chat_name:
                        continue
                    try:
                        info = item.element_info
                        rect_obj = getattr(info, "rectangle", None)
                        rect = None
                        if rect_obj is not None:
                            rect = Rect(
                                left=rect_obj.left,
                                top=rect_obj.top,
                                right=rect_obj.right,
                                bottom=rect_obj.bottom,
                            )
                        results.append(
                            ChatItem(
                                name=chat_name,
                                last_message_preview=PrivacyRedactor.REDACTED,
                                element=Element(
                                    handle=item,
                                    name=chat_name,
                                    class_name=info.class_name,
                                    rect=rect,
                                ),
                            )
                        )
                    except Exception:
                        continue
            except Exception:
                pass
            return results

        return await asyncio.to_thread(_do_walk)
    
    async def open_chat(self, chat_name: str) -> bool:
        """Open a chat the way a human does: CLICK its real row in the sidebar.

        Strategy (bulletproof):
        1. Resolve the sidebar chat list fresh each attempt
        2. Search visible rows for the chat name (exact first-token, then contains)
        3. Click the real row (click_input) - no search box involved
        4. Scroll the list and repeat when the chat is not visible
        5. Fall back to the Ctrl+F search only if clicking fails everywhere

        Args:
            chat_name: Name of the chat to open.

        Returns:
            True if the chat was opened (click landed + state changed).
        """
        if not self._connected:
            await self.connect()

        # Snapshot the window state to verify the click actually changed UI
        before = await self._capture_window_state_hash()

        # Ensure Telegram is usable/foreground (best-effort; click_input is
        # window-targeted so it works even behind other windows)
        await self._ensure_window_fresh()

        # Ensure sidebar is visible (dismiss any search overlay left open)
        await self._ensure_sidebar_visible()

        max_scrolls = 10
        chat_elem = None

        # Attempt: search visible, then scroll UP (frequent chats near top),
        # then DOWN - re-resolving fresh each position.
        scroll_pattern = [0] + [+1] * (max_scrolls // 2) + [-1] * (max_scrolls // 2 + 2)
        for action in scroll_pattern:
            if action != 0:
                ok_scroll = await self._scroll_chat_list(action, steps=2)
                await asyncio.sleep(0.25)
                if not ok_scroll:
                    break
            chat_elem = await self._find_chat_by_name(chat_name)
            if chat_elem is not None:
                break

        if chat_elem is None:
            # Last resort: type in search box (human equivalent of Ctrl+F)
            print(f"[open_chat] '{chat_name}' not visible in sidebar - using search")
            return await self._open_chat_by_keyboard(chat_name)

        # Click the real chat row with retries - coordinate click + title verify
        # UIA click_input() resolves Qt custom list items unreliably; we click
        # at the EXACT visual rect of the row and verify the window title
        # changed to "<chat name> - (n)" (Telegram retitles with active chat).
        for attempt in range(4):
            try:
                # Re-resolve fresh element + rect each attempt
                chat_elem = await self._find_chat_by_name(chat_name)
                if chat_elem is None or chat_elem.rect is None:
                    await asyncio.sleep(0.3)
                    continue

                await self._click_at_rect(chat_elem.rect)
                await asyncio.sleep(0.8)

                # Verify: Telegram retitles the window to "<chat name> - (n)"
                await self._ensure_window_fresh()
                title = (self._window.name or "") if self._window else ""
                if self._title_matches_chat(title, chat_name):
                    return True

                # Fallback verification: window state changed
                after = await self._capture_window_state_hash()
                if after is not None and before is not None and after != before:
                    # Something changed - confirm by checking title once more
                    await self._ensure_window_fresh()
                    title = (self._window.name or "") if self._window else ""
                    if self._title_matches_chat(title, chat_name):
                        return True
                # Didn't land - scroll a bit and retry
                await self._scroll_chat_list(1, steps=1)
            except Exception as e:
                print(f"[open_chat] click attempt {attempt + 1} failed: {e}")
                await asyncio.sleep(0.5)

        # Last resort
        return await self._open_chat_by_keyboard(chat_name)

    def _title_matches_chat(self, title: str, chat_name: str) -> bool:
        """True if the window title contains the chat name (active chat)."""
        if not title or not chat_name:
            return False
        t = title.lower()
        n = chat_name.lower().strip()
        return n in t or n.split("(")[0].strip() in t

    async def _click_at_rect(self, rect: Rect) -> bool:
        """Click at exact screen coordinates with HUMAN-like movement.

        Uses the HumanMouse engine (fastest human mover minus 20%): bezier
        path, submovements, overshoot-then-correct, tremor - then a human
        click. Falls back to precise fixed-point click if unavailable.

        During a lockout, the backdrop is click-through for the duration of
        the click (click burst) so the click reaches Telegram, not the overlay.
        """
        if rect is None:
            return False

        click_burst = False
        if self.lockout_active and self._lockout is not None:
            self._lockout.begin_click_burst()
            click_burst = True

        try:
            # Ensure the window is foreground so the click targets the real window
            await asyncio.to_thread(self._ensure_foreground)

            cx = (rect.left + rect.right) // 2
            cy = (rect.top + rect.bottom) // 2

            def _do_click():
                mouse = self._build_human_mouse()
                mouse.click(cx, cy)
                return True

            return await asyncio.to_thread(_do_click)
        finally:
            if click_burst:
                try:
                    self._lockout.end_click_burst()
                except Exception:
                    pass

    async def _capture_window_state_hash(self) -> Optional[str]:
        """Capture a stable window-state signature (post-click verification)."""
        try:
            screenshot = await self.take_screenshot()
            if not screenshot:
                return None
            import hashlib
            # Downsample for stability against minor rendering jitter
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(screenshot)).convert("L").resize((64, 48))
            return hashlib.md5(img.tobytes()).hexdigest()
        except Exception:
            return None
    
    async def _open_chat_by_keyboard(self, chat_name: str) -> bool:
        """Fallback: open chat using Ctrl+F search + enter."""
        if not self._window:
            return False
        
        try:
            # Press Ctrl+F to focus search
            await self._type_keys_safe(self.SHORTCUTS["search"])
            await asyncio.sleep(0.3)
            
            # Type chat name
            await self._type_keys_safe(chat_name)
            await asyncio.sleep(0.5)
            
            # Press Enter to open first result
            await self._type_keys_safe(self.SHORTCUTS["send"])
            await asyncio.sleep(0.5)
            
            # Escape to clear search
            await self._type_keys_safe(self.SHORTCUTS["escape"])
            
            return True
        except Exception as e:
            print(f"Keyboard navigation failed: {e}")
            return False
    
    async def search_chats(self, query: str) -> List[ChatItem]:
        """Search for chats.
        
        Args:
            query: Search query.
            
        Returns:
            List of matching chats.
        """
        # Use keyboard shortcut to search
        await self._open_chat_by_keyboard(query)
        # Then parse results (would need visual/UIA)
        return []
    
    # ==================== Message Operations ====================
    
    async def send_message(self, text: str, chat_name: Optional[str] = None) -> bool:
        """Send a message to the current (or specified) chat.
        
        Args:
            text: Message text to send.
            chat_name: Optional chat name to switch to first.
            
        Returns:
            True if message was sent, False otherwise.
        """
        if not self._connected:
            await self.connect()
        
        # Switch chat if needed
        if chat_name:
            success = await self.open_chat(chat_name)
            if not success:
                return False
        
        # Focus message input and send
        return await self._send_message_to_current_chat(text)
    
    async def _send_message_to_current_chat(self, text: str) -> bool:
        """Send message to currently open chat using keyboard."""
        if not self._window:
            return False
        
        try:
            # Method 1: Ctrl+N for new message (works in some versions)
            # await self._type_keys_safe(self.SHORTCUTS["new_message"])
            
            # Method 2: Tab to focus input (most reliable)
            await self._type_keys_safe(self.SHORTCUTS["focus_input"])
            await asyncio.sleep(0.2)
            
            # Type the message
            await self._type_keys_safe(text)
            await asyncio.sleep(0.2)
            
            # Press Enter to send
            await self._type_keys_safe(self.SHORTCUTS["send"])
            await asyncio.sleep(0.3)
            
            return True
        except Exception as e:
            print(f"Failed to send message: {e}")
            return False
    
    async def send_multiline_message(self, lines: List[str]) -> bool:
        """Send a multi-line message (Shift+Enter for new lines)."""
        if not self._window:
            return False
        
        try:
            await self._type_keys_safe(self.SHORTCUTS["focus_input"])
            await asyncio.sleep(0.2)
            
            for i, line in enumerate(lines):
                await self._type_keys_safe(line)
                if i < len(lines) - 1:
                    await self._type_keys_safe(self.SHORTCUTS["new_line"])
                    await asyncio.sleep(0.1)
            
            await self._type_keys_safe(self.SHORTCUTS["send"])
            await asyncio.sleep(0.3)
            
            return True
        except Exception as e:
            print(f"Failed to send multiline message: {e}")
            return False
    
    async def read_recent_messages(self, count: int = 10) -> List[Message]:
        """Read recent messages from current chat.

        PRIVACY POLICY: the message area content is NEVER read for context.
        Only messages that classify as errors may be returned (with the
        error phrase), everything else returns a redacted placeholder.
        """
        # Message area (HistoryWidget) has no UIA children. Any future
        # reading must go through PrivacyRedactor - non-error content is
        # never returned. Error phrases MAY be returned for recovery.
        try:
            self._privacy_redactor = self._privacy_redactor or PrivacyRedactor()
        except Exception:
            pass
        return []
    
    # ==================== Visual Grounding Fallback ====================
    
    async def find_element_visual(self, element_type: str) -> Optional[Tuple[int, int]]:
        """Find element coordinates using visual grounding.

        NOT IMPLEMENTED: returning None (no vision model attached here).
        A future integration would feed the screenshot to
        ufo.automator.ui_control.grounding (OMNIParser/Venus) to detect
        element coordinates for clicking.
        """
        return None

    async def click_visual(self, element_type: str) -> bool:
        """Click an element using visual coordinates.

        NOT IMPLEMENTED: returns False (no detection pipeline attached).
        Use the UIA/keyboard paths which are fully implemented.
        """
        return False
    
    # ==================== Utility Methods ====================
    
    async def take_screenshot(self, region: Optional[Rect] = None) -> bytes:
        """Take screenshot of the Telegram window (targets the specific window).

        Self-healing: a minimized / off-screen window (rect at -25600 after a
        minimize-restore cycle or a geometry restore) makes the screen-region
        capture fail. RULE 2 requires a sane visible window, so force it back
        and retry once instead of aborting the step.
        """
        if not self._desktop:
            return b""
        # Ensure window is fresh so we capture the real, current Telegram window
        await self._ensure_window_fresh()
        try:
            return await self._desktop.screenshot(window=self._window, region=region)
        except Exception as first_err:
            hwnd = self.get_concrete_hwnd()
            if hwnd:
                # Restore + clamp into the work area, then retry once
                self._ensure_sane_geometry(hwnd)
                await asyncio.sleep(0.4)
                try:
                    return await self._desktop.screenshot(window=self._window, region=region)
                except Exception:
                    pass
            raise first_err
    
    async def close(self) -> None:
        """Close the desktop automation connection."""
        if self._desktop:
            await self._desktop.close()
            self._connected = False
    
    @property
    def is_connected(self) -> bool:
        return self._connected
    
    @property
    def window(self) -> Optional[Element]:
        return self._window
    
    @property
    def desktop(self) -> Optional[DesktopAutomation]:
        return self._desktop
