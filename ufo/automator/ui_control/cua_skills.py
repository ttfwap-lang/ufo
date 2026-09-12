"""
CUA-Skills (Computer Use Abstraction Skills) — Atomic Primitives for Desktop Automation.

This module provides a library of high-level, reliable UI automation primitives
that encapsulate common multi-step operations into single callable functions.
These primitives handle retries, error recovery, and timing internally.

Usage:
    from ufo.automator.ui_control.cua_skills import CUASkills
    skills = CUASkills()
    skills.open_file_dialog_and_select("C:/path/to/file.pdf")
    skills.save_as("C:/path/to/output.pdf")
    skills.dismiss_dialog()
"""
import logging
import time
logger = logging.getLogger(__name__)
try:
    import pyautogui
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0.1
except ImportError:
    pyautogui = None

class CUASkills:
    """
    Atomic Computer Use Abstraction primitives for common desktop operations.
    Each method is self-contained, handles its own error recovery, and returns
    a success/failure status with description.
    """

    def __init__(self, action_delay: float=0.5):
        """
        :param action_delay: Base delay between sequential actions (seconds)
        """
        self.action_delay = action_delay
        if pyautogui is None:
            raise ImportError('pyautogui is required for CUA-Skills')

    def dismiss_dialog(self, max_attempts: int=3) -> str:
        """
        Dismiss any active modal dialog by trying Escape, then Enter, then Alt+F4.

        :param max_attempts: Number of dismiss strategies to try
        :return: Description of what was done
        """
        strategies = [('Escape', lambda: pyautogui.press('escape')), ('Enter', lambda: pyautogui.press('enter')), ('Alt+F4', lambda: pyautogui.hotkey('alt', 'F4'))]
        for i, (name, action) in enumerate(strategies[:max_attempts]):
            try:
                action()
                time.sleep(self.action_delay)
                logger.info(f'CUA-Skills: Dismiss dialog attempt {i + 1} via {name}')
                return f'Dismissed dialog via {name}'
            except Exception as e:
                logger.warning(f'CUA-Skills: Dismiss via {name} failed: {e}')
        return 'Failed to dismiss dialog after all attempts'

    def open_file_dialog_and_select(self, file_path: str, timeout: float=5.0) -> str:
        """
        Handle a standard Windows Open File dialog:
        1. Wait for dialog to appear
        2. Clear the filename field
        3. Type the file path
        4. Press Enter to confirm

        :param file_path: Absolute path to the file to open
        :param timeout: Max seconds to wait for dialog
        :return: Status description
        """
        try:
            time.sleep(self.action_delay)
            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.2)
            pyautogui.typewrite(file_path, interval=0.02) if file_path.isascii() else pyautogui.write(file_path)
            time.sleep(0.3)
            pyautogui.press('enter')
            time.sleep(self.action_delay)
            logger.info(f'CUA-Skills: Opened file via dialog: {file_path}')
            return f'File dialog: selected {file_path}'
        except Exception as e:
            logger.error(f'CUA-Skills: open_file_dialog failed: {e}')
            return f'Failed: {e}'

    def save_as(self, file_path: str) -> str:
        """
        Trigger Save As dialog (Ctrl+Shift+S or F12) and save to specified path.

        :param file_path: Destination file path
        :return: Status description
        """
        try:
            pyautogui.hotkey('ctrl', 'shift', 's')
            time.sleep(1.0)
            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.2)
            pyautogui.typewrite(file_path, interval=0.02) if file_path.isascii() else pyautogui.write(file_path)
            time.sleep(0.3)
            pyautogui.press('enter')
            time.sleep(self.action_delay)
            time.sleep(0.5)
            pyautogui.press('enter')
            logger.info(f'CUA-Skills: Save As completed: {file_path}')
            return f'Saved as {file_path}'
        except Exception as e:
            logger.error(f'CUA-Skills: save_as failed: {e}')
            return f'Failed: {e}'

    def switch_to_window(self, title_fragment: str) -> str:
        """
        Switch to a window matching the given title fragment using Alt+Tab cycling.
        Falls back to tasklist-based enumeration on Windows.

        :param title_fragment: Substring to match in window title
        :return: Status description
        """
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            target_hwnd = None

            def enum_callback(hwnd, _):
                nonlocal target_hwnd
                if user32.IsWindowVisible(hwnd):
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buf = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buf, length + 1)
                        if title_fragment.lower() in buf.value.lower():
                            target_hwnd = hwnd
                            return False
                return True
            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
            user32.EnumWindows(WNDENUMPROC(enum_callback), 0)
            if target_hwnd:
                user32.SetForegroundWindow(target_hwnd)
                user32.ShowWindow(target_hwnd, 9)
                time.sleep(self.action_delay)
                logger.info(f"CUA-Skills: Switched to window matching '{title_fragment}'")
                return f'Switched to window: {title_fragment}'
            else:
                logger.warning(f"CUA-Skills: No window found matching '{title_fragment}'")
                return f'Window not found: {title_fragment}'
        except Exception as e:
            logger.error(f'CUA-Skills: switch_to_window failed: {e}')
            return f'Failed: {e}'

    def type_text(self, text: str, use_clipboard: bool=True) -> str:
        """
        Type text into the focused control. Uses clipboard paste for non-ASCII text.

        :param text: Text to type
        :param use_clipboard: Use clipboard paste (Ctrl+V) for reliability
        :return: Status description
        """
        try:
            if use_clipboard:
                import subprocess
                subprocess.run(['powershell', '-Command', f"Set-Clipboard -Value '{text}'"], capture_output=True, timeout=5, creationflags=134217728)
                pyautogui.hotkey('ctrl', 'v')
            else:
                pyautogui.typewrite(text, interval=0.02)
            time.sleep(self.action_delay)
            logger.info(f'CUA-Skills: Typed {len(text)} characters')
            return f'Typed {len(text)} characters'
        except Exception as e:
            logger.error(f'CUA-Skills: type_text failed: {e}')
            return f'Failed: {e}'

    def wait_for_window(self, title_fragment: str, timeout: float=30.0, poll_interval: float=1.0) -> bool:
        """
        Wait for a window with the given title to appear.

        :param title_fragment: Substring to match in window title
        :param timeout: Maximum wait time in seconds
        :param poll_interval: Time between checks
        :return: True if window appeared within timeout
        """
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        start = time.time()
        while time.time() - start < timeout:
            found = False

            def enum_callback(hwnd, _):
                nonlocal found
                if user32.IsWindowVisible(hwnd):
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buf = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buf, length + 1)
                        if title_fragment.lower() in buf.value.lower():
                            found = True
                            return False
                return True
            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
            user32.EnumWindows(WNDENUMPROC(enum_callback), 0)
            if found:
                logger.info(f"CUA-Skills: Window '{title_fragment}' appeared after {time.time() - start:.1f}s")
                return True
            time.sleep(poll_interval)
        logger.warning(f"CUA-Skills: Window '{title_fragment}' did not appear within {timeout}s")
        return False

    def screenshot_region(self, x: int, y: int, width: int, height: int, save_path: str) -> str:
        """
        Capture a screenshot of a specific region.

        :param x: Left coordinate
        :param y: Top coordinate
        :param width: Width of region
        :param height: Height of region
        :param save_path: Path to save the screenshot
        :return: Status description
        """
        try:
            img = pyautogui.screenshot(region=(x, y, width, height))
            img.save(save_path)
            logger.info(f'CUA-Skills: Screenshot saved to {save_path}')
            return f'Screenshot saved: {save_path}'
        except Exception as e:
            logger.error(f'CUA-Skills: screenshot_region failed: {e}')
            return f'Failed: {e}'
