"""
System Toolkit MCP Server.

Desktop capabilities that benchmark tasks (OSWorld, Windows Agent Arena)
need constantly but pure click/type UI automation does badly or slowly:
clipboard access, window management, global hotkeys, opening paths/URLs,
waiting for windows, system info, and a few common OS settings.
"""
import ctypes
import logging
import os
import re
import subprocess
import sys
import time
from typing import Annotated, Any, Dict, List, Optional

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from ufo.client.mcp.mcp_registry import MCPRegistry

logger = logging.getLogger(__name__)

_SAFE_URL = re.compile(r"^(https?://|file:///)", re.I)
_SW = {"hide": 0, "normal": 1, "minimize": 6, "maximize": 3, "restore": 9}


def _win32():
    if sys.platform != "win32":
        raise ToolError("This tool is only available on Windows.")
    import win32con
    import win32gui
    import win32process
    return win32con, win32gui, win32process


def _visible_windows() -> List[Dict[str, Any]]:
    _, win32gui, win32process = _win32()
    out: List[Dict[str, Any]] = []

    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if not title.strip():
            return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            l, t, r, b = win32gui.GetWindowRect(hwnd)
        except Exception:
            return
        out.append({"hwnd": hwnd, "title": title, "pid": pid, "rect": [l, t, r, b],
                    "minimized": bool(win32gui.IsIconic(hwnd))})

    win32gui.EnumWindows(cb, None)
    return out


def _find(title: str) -> Dict[str, Any]:
    needle = title.strip().lower()
    if not needle:
        raise ToolError("title must not be empty.")
    wins = _visible_windows()
    exact = [w for w in wins if w["title"].lower() == needle]
    hits = exact or [w for w in wins if needle in w["title"].lower()]
    if not hits:
        raise ToolError(f"No visible window matches '{title}'. Use list_windows to see what is open.")
    return hits[0]


@MCPRegistry.register_factory_decorator("SystemToolkit")
@MCPRegistry.register_factory_decorator("system_toolkit_mcp_server")
def create_system_toolkit_mcp_server(*args, **kwargs) -> FastMCP:
    mcp = FastMCP("UFO System Toolkit MCP Server")

    @mcp.tool()
    def clipboard_get() -> str:
        """Return the current text on the Windows clipboard (empty string if none)."""
        import win32clipboard
        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            return ""
        finally:
            win32clipboard.CloseClipboard()

    @mcp.tool()
    def clipboard_set(text: Annotated[str, Field(description="Text to place on the clipboard.")]) -> str:
        """Put text on the Windows clipboard, e.g. before pasting with the hotkey ^v."""
        import win32clipboard
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
        finally:
            win32clipboard.CloseClipboard()
        return f"Clipboard set ({len(text)} characters)."

    @mcp.tool()
    def list_windows() -> List[Dict[str, Any]]:
        """List visible top-level windows: title, pid, rect [left, top, right, bottom], minimized."""
        return [{k: v for k, v in w.items() if k != "hwnd"} for w in _visible_windows()]

    @mcp.tool()
    def window_control(
        title: Annotated[str, Field(description="Window title, or a unique part of it (case-insensitive).")],
        action: Annotated[str, Field(description="One of: focus, minimize, maximize, restore, close, move_resize.")],
        x: Annotated[Optional[int], Field(description="Left edge in pixels (move_resize only).")] = None,
        y: Annotated[Optional[int], Field(description="Top edge in pixels (move_resize only).")] = None,
        width: Annotated[Optional[int], Field(description="Width in pixels (move_resize only).")] = None,
        height: Annotated[Optional[int], Field(description="Height in pixels (move_resize only).")] = None,
    ) -> str:
        """Focus, minimize, maximize, restore, close or move/resize a window found by title."""
        win32con, win32gui, _ = _win32()
        w = _find(title)
        hwnd, action = w["hwnd"], action.strip().lower()
        if action == "focus":
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            # Alt keypress lets SetForegroundWindow succeed from a background process.
            ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)
            ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)
            win32gui.SetForegroundWindow(hwnd)
        elif action in ("minimize", "maximize", "restore"):
            win32gui.ShowWindow(hwnd, _SW[action])
        elif action == "close":
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        elif action == "move_resize":
            if None in (x, y, width, height):
                raise ToolError("move_resize needs x, y, width and height.")
            win32gui.MoveWindow(hwnd, x, y, width, height, True)
        else:
            raise ToolError("action must be one of: focus, minimize, maximize, restore, close, move_resize.")
        return f"{action} applied to window '{w['title']}'."

    @mcp.tool()
    def wait_for_window(
        title: Annotated[str, Field(description="Window title, or a unique part of it.")],
        timeout: Annotated[float, Field(description="Seconds to wait (max 120).")] = 15.0,
    ) -> str:
        """Block until a window whose title contains `title` is visible, or fail after timeout."""
        deadline = time.time() + min(max(timeout, 0.5), 120.0)
        while time.time() < deadline:
            try:
                return f"Window found: '{_find(title)['title']}'."
            except ToolError:
                time.sleep(0.4)
        raise ToolError(f"Timed out waiting for a window matching '{title}'.")

    @mcp.tool()
    def press_hotkey(
        keys: Annotated[str, Field(description="pywinauto key string sent to the focused window, e.g. '^c' (Ctrl+C), '%{F4}' (Alt+F4), '#e' is NOT supported; '{VK_LWIN down}e{VK_LWIN up}' opens Explorer.")],
    ) -> str:
        """Send a keyboard shortcut to whatever window currently has focus (no control ID needed)."""
        from pywinauto.keyboard import send_keys
        send_keys(keys, pause=0.05)
        return f"Sent keys: {keys}"

    @mcp.tool()
    def open_target(
        target: Annotated[str, Field(description="An http(s) URL, or an absolute file/folder path to open with its default app.")],
    ) -> str:
        """Open a URL in the default browser, or a file/folder with its default application."""
        if _SAFE_URL.match(target):
            os.startfile(target)  # noqa: S606
            return f"Opened {target}"
        path = os.path.abspath(os.path.expandvars(target))
        if not os.path.exists(path):
            raise ToolError(f"Path does not exist: {path}")
        if os.path.splitext(path)[1].lower() in (".exe", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".msi", ".scr"):
            raise ToolError("Refusing to execute programs via open_target; launch applications with run_shell.")
        os.startfile(path)  # noqa: S606
        return f"Opened {path}"

    @mcp.tool()
    def get_system_info() -> Dict[str, Any]:
        """Screen size, OS version, current time, foreground window and battery state."""
        import platform
        info: Dict[str, Any] = {
            "os": platform.platform(),
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "screen": [ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1)],
        }
        try:
            _, win32gui, _ = _win32()
            info["foreground_window"] = win32gui.GetWindowText(win32gui.GetForegroundWindow())
        except Exception:
            pass
        try:
            import psutil
            b = psutil.sensors_battery()
            if b:
                info["battery"] = {"percent": b.percent, "plugged_in": b.power_plugged}
        except Exception:
            pass
        return info

    @mcp.tool()
    def set_system_setting(
        name: Annotated[str, Field(description="One of: dark_mode, wallpaper.")],
        value: Annotated[str, Field(description="dark_mode: 'on' or 'off'. wallpaper: absolute path to an image file.")],
    ) -> str:
        """Change a common Windows personalization setting directly (faster and more reliable than the Settings app)."""
        name = name.strip().lower()
        if name == "dark_mode":
            import winreg
            if value.strip().lower() not in ("on", "off"):
                raise ToolError("dark_mode value must be 'on' or 'off'.")
            light = 0 if value.strip().lower() == "on" else 1
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            try:
                winreg.SetValueEx(key, "AppsUseLightTheme", 0, winreg.REG_DWORD, light)
                winreg.SetValueEx(key, "SystemUsesLightTheme", 0, winreg.REG_DWORD, light)
            finally:
                winreg.CloseKey(key)
            return f"dark_mode set to {value}."
        if name == "wallpaper":
            path = os.path.abspath(value)
            if not os.path.isfile(path):
                raise ToolError(f"Image file not found: {path}")
            ok = ctypes.windll.user32.SystemParametersInfoW(20, 0, path, 3)
            if not ok:
                raise ToolError("Windows rejected the wallpaper change.")
            return f"Wallpaper set to {path}."
        raise ToolError("Unknown setting. Supported: dark_mode, wallpaper.")

    return mcp


if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)
    create_system_toolkit_mcp_server().run()
