"""Modal screen lockout for safe autonomous automation.

Displays a MODAL overlay:
- The rest of the screen stays visible but slightly greyed out (dimmed)
- A centered message card shows automation status / countdown
- Clicks and keys are captured by the overlay (machine unusable)
- ESC = STOP automation | P = PAUSE/RESUME (reliable global polling)

While locked, the AI injects input into Telegram via short "input bursts":
the overlay momentarily yields foreground so SendInput reaches Telegram,
while staying TOPMOST - so the screen remains dimmed and nothing leaks.
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class ScreenLockout:
    """Modal dim overlay with countdown, ESC-stop and P-pause.

    Usage:
        lockout = ScreenLockout()
        if await lockout.acquire(countdown=5):
            try:
                await agent.run_autonomous_goal(...)  # locked-mode input
            finally:
                await lockout.release()
    """

    def __init__(
        self,
        on_stop: Optional[Callable] = None,
        on_pause: Optional[Callable] = None,
        stop_key: int = None,
        pause_key: int = None,
        stop_key_label: str = "ESC",
        pause_key_label: str = "P",
    ):
        """Initialize.

        :param on_stop: Called once when user presses the stop hotkey.
        :param on_pause: Called with paused=True/False on pause-key toggles.
        :param stop_key: Virtual key code for STOP (default ESC 0x1B).
            Any key may be used, e.g. F1=0x70, F2=0x71.
        :param pause_key: Virtual key code for PAUSE/RESUME (default P 0x50).
        :param stop_key_label: Display label for the stop key on the card.
        :param pause_key_label: Display label for the pause key on the card.
        """
        self._on_stop = on_stop
        self._on_pause = on_pause
        self._stop_vk = stop_key if stop_key is not None else 0x1B  # ESC
        self._pause_vk = pause_key if pause_key is not None else 0x50  # P
        self._stop_label = stop_key_label
        self._pause_label = pause_key_label
        self._state = "idle"  # idle | countdown | locked | paused | stopping | released
        self._tk_thread: Optional[threading.Thread] = None
        self._root = None
        self._card = None
        self._title = None
        self._subtitle = None
        self._footer = None
        self._focus_keeper: Optional[threading.Thread] = None
        self._hotkey_thread: Optional[threading.Thread] = None
        self._keep_running = False
        self._in_input_burst = False
        # Edge-detection state for keys
        self._prev_stop = False
        self._prev_pause = False

    # ==================== Public API ====================

    async def acquire(self, message: str = "AUTOMATION IN PROGRESS", countdown: int = 5) -> bool:
        """Show the modal lockout and run the countdown.

        :param message: Main message to display once locked.
        :param countdown: Seconds to count down before locking.
        :return: True if acquired, False if user pressed ESC during countdown
            or the overlay failed to start.
        """
        self._state = "countdown"
        self._keep_running = True

        self._tk_thread = threading.Thread(
            target=self._run_overlay, args=(message, countdown), daemon=True
        )
        self._tk_thread.start()

        # Wait for overlay to appear
        deadline = time.time() + 5
        while self._root is None and time.time() < deadline:
            time.sleep(0.05)
        if self._root is None:
            logger.error("Lockout overlay failed to start")
            self._state = "released"
            return False

        # Global hotkeys (RegisterHotKey) - the ONLY key handler (no double toggles)
        self._start_hotkeys()
        # Focus keeper: overlay stays topmost-dim and owns foreground normally
        self._focus_keeper = threading.Thread(target=self._keep_focus, daemon=True)
        self._focus_keeper.start()

        # Run countdown
        for i in range(countdown, 0, -1):
            if self._state in ("stopping", "released"):
                break
            self._update_countdown(i)
            time.sleep(1)

        if self._state == "stopping":
            # User opted out during countdown - fully tear down the overlay
            # so the machine is not left locked.
            await self.release()
            return False
        if self._state == "released":
            return False

        self._state = "locked"
        self._update_locked(message)
        logger.info("Lockout active - automation may proceed safely")
        return True

    async def release(self) -> None:
        """Release the overlay."""
        if self._state == "released":
            return
        self._keep_running = False
        if self._root is not None:
            try:
                self._root.after(0, self._destroy)
            except Exception:
                pass
            # Wait for the tk thread to exit cleanly (avoids Tcl_AsyncDelete
            # errors from destroying a Tk window owned by another thread)
            if self._tk_thread is not None and self._tk_thread.is_alive():
                try:
                    await asyncio.to_thread(self._tk_thread.join, 2.0)
                except Exception:
                    pass
        self._state = "released"
        logger.info("Lockout released - control returned to user")

    async def pause(self) -> None:
        """Visual pause state."""
        if self._state == "locked":
            self._state = "paused"
            self._update_locked("AUTOMATION PAUSED - press P to resume")

    async def resume(self) -> None:
        """Resume after pause."""
        if self._state == "paused":
            self._state = "locked"
            self._update_locked("AUTOMATION IN PROGRESS")

    # ==================== State ====================

    @property
    def is_locked(self) -> bool:
        return self._state in ("locked", "paused", "countdown")

    @property
    def is_paused(self) -> bool:
        return self._state == "paused"

    @property
    def stopped(self) -> bool:
        return self._state == "stopping"

    # ==================== Input bursts (for AI typing) ====================

    def begin_input_burst(self) -> None:
        """Mark AI input injection: focus keeper yields foreground to Telegram."""
        self._in_input_burst = True

    def end_input_burst(self) -> None:
        """Mark input injection finished: overlay re-owns foreground."""
        self._in_input_burst = False

    # ==================== Overlay UI (tkinter thread) ====================

    def _run_overlay(self, message: str, countdown: int) -> None:
        """Run the modal overlay (dedicated thread).

        The overlay is a fullscreen, ALMOST-TRANSPARENT input blocker:
        - The automation stays fully visible on screen (user can watch it)
        - Clicks/keyboard are swallowed (machine unusable to the user)
        - A small centered card shows status/countdown and ESC/P hints
        """
        try:
            import tkinter as tk

            # ---------- Window 1: DIM BACKDROP (full screen, translucent grey) ----------
            root = tk.Tk()
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            root.attributes("-toolwindow", True)
            # Slightly MORE grey: visible dim over the automation, still see it run
            root.attributes("-alpha", 0.35)
            root.configure(bg="#18181f")

            sw = root.winfo_screenwidth()
            sh = root.winfo_screenheight()
            root.geometry(f"{sw}x{sh}+0+0")
            root.focus_force()
            root.grab_set()

            # ---------- Window 2: OPAQUE CARD (separate topmost, alpha 1.0) ----------
            card_w = min(560, sw - 120)
            card_h = 200
            card_root = tk.Toplevel(root)
            card_root.overrideredirect(True)
            card_root.attributes("-topmost", True)
            card_root.attributes("-toolwindow", True)
            # ~90% opaque - the message reads clearly (slight translucency,
            # but never washed out by the backdrop dim)
            card_root.attributes("-alpha", 0.9)
            cx = (sw - card_w) // 2
            cy = (sh - card_h) // 2
            card_root.geometry(f"{card_w}x{card_h}+{cx}+{cy}")
            card_root.configure(bg="#1e1e2e")

            card = tk.Frame(card_root, bg="#1e1e2e")
            card.pack(fill="both", expand=True)
            card.configure(highlightbackground="#3a3a55", highlightthickness=2)

            title = tk.Label(
                card,
                text="",
                font=("Segoe UI", 20, "bold"),
                fg="#ffd166",
                bg="#1e1e2e",
                wraplength=card_w - 40,
                justify="center",
            )
            title.pack(pady=(26, 0))

            subtitle = tk.Label(
                card,
                text="",
                font=("Segoe UI", 13),
                fg="#e0e0e8",
                bg="#1e1e2e",
                wraplength=card_w - 40,
                justify="center",
            )
            subtitle.pack(pady=(14, 0))

            footer = tk.Label(
                card,
                text=f"{self._stop_label} = STOP    |    {self._pause_label} = PAUSE / RESUME",
                font=("Segoe UI", 12, "bold"),
                fg="#ff6b6b",
                bg="#1e1e2e",
            )
            footer.pack(side="bottom", pady=18)

            # NOTE: no tk key bindings - ESC/P handled ONLY by global polling

            root.update_idletasks()
            card_root.update_idletasks()

            self._root = root
            self._card_root = card_root
            self._card = card
            self._title = title
            self._subtitle = subtitle
            self._footer = footer

            # Card window must stay topmost too - keep both in the keeper
            self._card_hwnd = None
            try:
                import win32gui, win32con
                # Bring card above the backdrop
                card_root.update()
                h = card_root.winfo_id()
                # Use the Tk window handle (winfo_id is the child widget; the
                # toplevel HWND is found via the parent)
                win32gui.SetWindowPos(
                    self._get_toplevel_hwnd(card_root),
                    win32con.HWND_TOPMOST, cx, cy, card_w, card_h,
                    win32con.SWP_SHOWWINDOW,
                )
            except Exception:
                pass

            root.mainloop()
        except Exception as e:
            logger.error(f"Overlay thread failed: {e}")
            self._state = "released"

    def _get_toplevel_hwnd(self, tk_root) -> int:
        """Resolve the HWND of a Tk toplevel window.

        For a tk.Toplevel, ``winfo_id()`` already returns the top-level HWND.
        Only walk to the parent when it is a child widget (frames etc).
        """
        try:
            import tkinter as tk
            hwnd = tk_root.winfo_id()
            # If this is a Toplevel, winfo_id is the toplevel HWND itself
            if isinstance(tk_root, tk.Toplevel):
                return int(hwnd)
            # Otherwise walk up (borderless overrideredirect frames wrap
            # the real window in a child HWND)
            import ctypes
            user32 = ctypes.windll.user32
            parent = user32.GetParent(int(hwnd))
            return int(parent) if parent else int(hwnd)
        except Exception:
            return 0

    def update_status(self, status_line: str) -> None:
        """Update the card subtitle with live progress (thread-safe).

        Lets the user watch automation progress live on screen.
        """
        if self._root is None:
            return

        def _set():
            try:
                self._subtitle.config(text=status_line)
            except Exception:
                pass

        try:
            self._root.after(0, _set)
        except Exception:
            pass

    def _update_countdown(self, seconds: int) -> None:
        """Update countdown text (thread-safe).

        Strict 5-second warning: shows the remaining time and the OPT OUT
        hotkey (STOP key) - pressing it during the countdown aborts the
        automation cleanly and returns control.
        """
        if self._root is None:
            return

        def _set():
            try:
                self._title.config(
                    text=f"\u26a0  AUTOMATION STARTS IN {seconds}  \u26a0",
                    fg="#ffd166",
                )
                self._subtitle.config(
                    text="Keep your hands off the keyboard and mouse.\n"
                    f"Press {self._stop_label} NOW to OPT OUT and cancel this run.",
                    fg="#e0e0e8",
                )
            except Exception:
                pass

        try:
            self._root.after(0, _set)
        except Exception:
            pass

    def _update_locked(self, message: str) -> None:
        """Update main card text (thread-safe)."""
        if self._root is None:
            return

        def _set():
            try:
                self._title.config(text=f"🔒  {message}  🔒", fg="#ff6b6b")
                # Keep showing potential live status (progress callback updates it)
                current = ""
                try:
                    current = self._subtitle.cget("text")
                except Exception:
                    current = ""
                if not current or "AI control" in current:
                    self._subtitle.config(
                        text="Automation in progress - watch it run on screen.",
                        fg="#e0e0e8",
                    )
            except Exception:
                pass

        try:
            self._root.after(0, _set)
        except Exception:
            pass

    def _destroy(self) -> None:
        try:
            if self._root is not None:
                try:
                    self._root.quit()
                except Exception:
                    pass
                try:
                    self._root.destroy()
                except Exception:
                    pass
            if self._card_root is not None:
                try:
                    self._card_root.destroy()
                except Exception:
                    pass
        except Exception:
            pass

    # ==================== Focus keeper ====================

    def _keep_focus(self) -> None:
        """Keep overlay topmost-dim; own foreground except during AI bursts."""
        import win32gui
        import win32con

        while self._keep_running and self._state != "released":
            try:
                hwnd = self._get_toplevel_hwnd(self._root) if self._root is not None else 0
                if hwnd:
                    # Always on top - the screen stays dimmed/covered
                    win32gui.SetWindowPos(
                        hwnd,
                        win32con.HWND_TOPMOST,
                        0, 0, 0, 0,
                        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW,
                    )
                    # Keep the opaque card above the backdrop
                    if self._card_root is not None:
                        try:
                            card_hwnd = self._get_toplevel_hwnd(self._card_root)
                            if card_hwnd:
                                win32gui.SetWindowPos(
                                    card_hwnd,
                                    win32con.HWND_TOPMOST,
                                    0, 0, 0, 0,
                                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW,
                                )
                        except Exception:
                            pass
                    # Own foreground (grab user keys) unless AI is injecting
                    if not self._in_input_burst and self._state not in ("stopping", "released"):
                        import ctypes
                        fg = ctypes.windll.user32.GetForegroundWindow()
                        if fg != hwnd:
                            try:
                                win32gui.SetForegroundWindow(hwnd)
                            except Exception:
                                pass
            except Exception:
                pass
            time.sleep(0.35)

    # ==================== Global hotkeys (RegisterHotKey - reliable) ====================

    def _start_hotkeys(self) -> None:
        """Start the RegisterHotKey message loop (reliable global hotkeys).

        RegisterHotKey is the OS-native mechanism: it delivers WM_HOTKEY
        messages for real AND synthesized key presses, unlike
        GetAsyncKeyState polling which can miss fast taps and did not detect
        synthesized input in verification tests.
        """
        self._hotkey_thread = threading.Thread(
            target=self._hotkey_message_loop, daemon=True
        )
        self._hotkey_thread.start()
        logger.info(
            f"Global hotkeys registered (stop={self._stop_label}, "
            f"pause={self._pause_label})"
        )

    def _hotkey_message_loop(self) -> None:
        """Message loop with a message-only window that receives WM_HOTKEY."""
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        WM_HOTKEY = 0x0312
        PM_REMOVE = 0x0001
        HWND_MESSAGE = -3

        # LRESULT CALLBACK(HWND, UINT, WPARAM, LPARAM) - LRESULT is pointer-sized
        WNDPROC = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wintypes.HWND, ctypes.c_uint,
            wintypes.WPARAM, wintypes.LPARAM,
        )

        class WNDCLASS(ctypes.Structure):
            _fields_ = [
                ("style", ctypes.c_uint),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        def wnd_proc(hwnd, msg, wparam, lparam):
            try:
                if msg == WM_HOTKEY:
                    hotkey_id = wparam & 0xFFFF
                    # Ignore hotkeys while the AI is injecting input (a burst
                    # sends ESC/other keys itself; they must not self-cancel).
                    if not self._in_input_burst:
                        if hotkey_id == 1:
                            self._set_stopped()
                        elif hotkey_id == 2:
                            self._toggle_pause()
                    return 0
                return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
            except Exception:
                return 0

        # Keep the callback object alive for the lifetime of the loop
        self._wnd_proc_ref = WNDPROC(wnd_proc)

        cls_name = f"UFO_HotkeyWnd_{id(self)}"
        wc = WNDCLASS()
        wc.lpfnWndProc = self._wnd_proc_ref
        wc.hInstance = kernel32.GetModuleHandleW(None)
        wc.lpszClassName = cls_name
        registered = user32.RegisterClassW(ctypes.byref(wc))
        if not registered:
            # Class may already exist from a previous instance - skip
            pass

        hwnd = user32.CreateWindowExW(
            0, cls_name, "ufo_hotkeys", 0, 0, 0, 0, 0,
            HWND_MESSAGE, None, wc.hInstance, None,
        )
        if not hwnd:
            logger.warning("Hotkey message window creation failed")
            return

        ok_stop = user32.RegisterHotKey(hwnd, 1, 0, self._stop_vk)
        ok_pause = user32.RegisterHotKey(hwnd, 2, 0, self._pause_vk)
        logger.info(f"RegisterHotKey result: stop={bool(ok_stop)}, pause={bool(ok_pause)}")

        msg = wintypes.MSG()
        while self._keep_running and self._state != "released":
            r = user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE)
            if r != 0:
                try:
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
                except Exception:
                    pass
            else:
                time.sleep(0.01)

        user32.UnregisterHotKey(hwnd, 1)
        user32.UnregisterHotKey(hwnd, 2)
        user32.DestroyWindow(hwnd)

    # ==================== Input/click bursts ====================

    def begin_input_burst(self) -> None:
        """Mark AI input injection: focus keeper yields foreground + hotkeys ignored."""
        self._in_input_burst = True

    def end_input_burst(self) -> None:
        """Mark input injection finished: overlay re-owns foreground."""
        self._in_input_burst = False

    def begin_click_burst(self) -> None:
        """Prepare for a real mouse click during lockout.

        Makes the backdrop click-through (WS_EX_TRANSPARENT) and suppresses
        hotkeys while the click is delivered to Telegram - otherwise the
        topmost backdrop intercepts the mouse events.
        """
        self._in_input_burst = True
        self._set_backdrop_click_through(True)

    def end_click_burst(self) -> None:
        """Restore the backdrop after a click burst."""
        self._in_input_burst = False
        self._set_backdrop_click_through(False)

    def _set_backdrop_click_through(self, enabled: bool) -> None:
        """Toggle WS_EX_TRANSPARENT on the backdrop so clicks pass through."""
        if self._root is None:
            return
        try:
            import ctypes
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_LAYERED = 0x00080000
            user32 = ctypes.windll.user32
            hwnd = self._get_toplevel_hwnd(self._root)
            if not hwnd:
                return
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if enabled:
                style |= WS_EX_TRANSPARENT | WS_EX_LAYERED
            else:
                style &= ~WS_EX_TRANSPARENT
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

    # ==================== State transitions ====================

    def _set_stopped(self) -> None:
        if self._state not in ("stopping", "released"):
            logger.info(f"{self._stop_label} pressed - STOPPING automation")
            self._state = "stopping"
            if self._on_stop:
                try:
                    self._on_stop()
                except Exception:
                    pass

    def _toggle_pause(self) -> None:
        if self._state == "locked":
            self._state = "paused"
            self._update_locked("AUTOMATION PAUSED - press P to resume")
            if self._on_pause:
                try:
                    self._on_pause(True)
                except Exception:
                    pass
        elif self._state == "paused":
            self._state = "locked"
            self._update_locked("AUTOMATION IN PROGRESS")
            if self._on_pause:
                try:
                    self._on_pause(False)
                except Exception:
                    pass
