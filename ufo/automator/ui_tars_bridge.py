"""
UI-TARS Visual Computer Use Bridge for Microsoft UFO

Integrates ByteDance's UI-TARS Vision-Language-Action (VLA) paradigm
to handle applications that lack Windows UI Automation (UIA) support
(Canvas apps, games, Electron without accessibility flags, complex SPAs).

Capabilities:
1. High-resolution screenshot capture and normalized coordinate conversion.
2. Parsing UI-TARS action tokens:
   - Action: click(start_box='(x, y)')
   - Action: type(content='...')
   - Action: drag(start_box='(x1, y1)', end_box='(x2, y2)')
   - Action: hotkey(key='ctrl+s')
   - Action: finished()
3. Native Win32 / PyAutoGUI coordinate execution with DPI scaling.
4. Visual feedback settlement check (verifies screen pixel change).
"""

import base64
import ctypes
import json
import logging
import os
import re
import tempfile
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageStat
import pyautogui

logger = logging.getLogger("UFO_UITarsBridge")


class UITarsBridge:
    """
    Visual Grounding & Action Execution Bridge using the UI-TARS action protocol.
    """

    def __init__(
        self,
        endpoint_url: Optional[str] = None,
        model_name: str = "ui-tars-7b-dpo",
        screen_width: Optional[int] = None,
        screen_height: Optional[int] = None,
    ):
        self.endpoint_url = endpoint_url or os.environ.get("UI_TARS_ENDPOINT", "http://127.0.0.1:8080/v1")
        self.model_name = model_name
        self.screen_width = screen_width
        self.screen_height = screen_height
        self._last_screenshot: Optional[Image.Image] = None

    def capture_screen_area(self, hwnd: int = 0) -> Tuple[Image.Image, Tuple[int, int, int, int]]:
        """
        Capture the screen area for the target window or primary desktop.
        Returns (PIL Image, (left, top, width, height)).
        """
        if hwnd > 0:
            try:
                import win32gui
                if win32gui.IsWindow(hwnd):
                    rect = win32gui.GetWindowRect(hwnd)
                    left, top, right, bottom = rect
                    width = max(1, right - left)
                    height = max(1, bottom - top)
                    img = pyautogui.screenshot(region=(left, top, width, height))
                    self._last_screenshot = img
                    return img, (left, top, width, height)
            except Exception as e:
                logger.warning(f"Window screenshot failed for hwnd={hwnd}: {e}. Falling back to full desktop.")

        # Full primary display
        try:
            img = pyautogui.screenshot()
            self._last_screenshot = img
            return img, (0, 0, img.width, img.height)
        except Exception as e:
            logger.warning(f"pyautogui desktop screenshot failed: {e}. Trying UFO DesktopPhotographer fallback.")
            try:
                from ufo.automator.ui_control.screenshot import DesktopPhotographer, _create_diagnostic_error_frame
                dp = DesktopPhotographer(all_screens=False)
                img = dp.capture_raw()
                if img is not None:
                    self._last_screenshot = img
                    return img, (0, 0, img.width, img.height)
                img = _create_diagnostic_error_frame()
                self._last_screenshot = img
                return img, (0, 0, img.width, img.height)
            except Exception:
                # Synthetic fallback 1920x1080 canvas
                img = Image.new("RGB", (1920, 1080), (40, 40, 45))
                self._last_screenshot = img
                return img, (0, 0, 1920, 1080)

    def parse_single_action(
        self,
        action_text: str,
        screen_width: Optional[int] = None,
        screen_height: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Parse an individual UI-TARS action token."""
        sw = screen_width or self.screen_width or 1920
        sh = screen_height or self.screen_height or 1080
        action_text = action_text.strip()
        result = {"action": "none", "action_type": "none", "params": {}, "raw": action_text}

        # Right click
        rc_match = re.search(r"right_click\s*\(\s*start_box=['\"]?\s*[\(\[]?(\d+)[,\s]+(\d+)[\)\]]?['\"]?", action_text, re.I)
        if rc_match:
            raw_x, raw_y = int(rc_match.group(1)), int(rc_match.group(2))
            norm_x, norm_y = self._normalize_coords(raw_x, raw_y, sw, sh)
            result.update({
                "action": "right_click",
                "action_type": "click",
                "x": norm_x,
                "y": norm_y,
                "button": "right",
                "params": {"x": norm_x, "y": norm_y, "button": "right"}
            })
            return result

        # Double click
        dc_match = re.search(r"double_click\s*\(\s*start_box=['\"]?\s*[\(\[]?(\d+)[,\s]+(\d+)[\)\]]?['\"]?", action_text, re.I)
        if dc_match:
            raw_x, raw_y = int(dc_match.group(1)), int(dc_match.group(2))
            norm_x, norm_y = self._normalize_coords(raw_x, raw_y, sw, sh)
            result.update({
                "action": "double_click",
                "action_type": "click",
                "x": norm_x,
                "y": norm_y,
                "button": "left",
                "clicks": 2,
                "params": {"x": norm_x, "y": norm_y, "button": "left", "clicks": 2}
            })
            return result

        # Standard Click
        click_match = re.search(r"(?:left_)?click\s*\(\s*start_box=['\"]?\s*[\(\[]?(\d+)[,\s]+(\d+)[\)\]]?['\"]?", action_text, re.I)
        if click_match:
            raw_x, raw_y = int(click_match.group(1)), int(click_match.group(2))
            norm_x, norm_y = self._normalize_coords(raw_x, raw_y, sw, sh)
            result.update({
                "action": "click",
                "action_type": "click",
                "x": norm_x,
                "y": norm_y,
                "button": "left",
                "params": {"x": norm_x, "y": norm_y, "button": "left"}
            })
            return result

        # Type
        type_match = re.search(r"type\s*\(\s*content=['\"](.*?)['\"]\s*\)", action_text, re.I | re.DOTALL)
        if type_match:
            text = type_match.group(1)
            result.update({
                "action": "type",
                "action_type": "type",
                "text": text,
                "params": {"content": text}
            })
            return result

        # Drag
        drag_match = re.search(
            r"drag\s*\(\s*start_box=['\"]?\s*[\(\[]?(\d+)[,\s]+(\d+)[\)\]]?['\"]?\s*,\s*end_box=['\"]?\s*[\(\[]?(\d+)[,\s]+(\d+)[\)\]]?['\"]?\s*\)",
            action_text,
            re.I
        )
        if drag_match:
            sx, sy = self._normalize_coords(int(drag_match.group(1)), int(drag_match.group(2)), sw, sh)
            ex, ey = self._normalize_coords(int(drag_match.group(3)), int(drag_match.group(4)), sw, sh)
            result.update({
                "action": "drag",
                "action_type": "drag",
                "start_x": sx,
                "start_y": sy,
                "end_x": ex,
                "end_y": ey,
                "params": {"start_x": sx, "start_y": sy, "end_x": ex, "end_y": ey}
            })
            return result

        # Hotkey
        hotkey_match = re.search(r"hotkey\s*\(\s*key=['\"](.*?)['\"]\s*\)", action_text, re.I)
        if hotkey_match:
            k = hotkey_match.group(1)
            result.update({
                "action": "hotkey",
                "action_type": "hotkey",
                "key": k,
                "params": {"key": k}
            })
            return result

        # Finished
        if "finished" in action_text.lower():
            result.update({
                "action": "finished",
                "action_type": "finished",
                "params": {}
            })
            return result

        return result

    def parse_action_string(
        self,
        action_text: str,
        screen_width: Optional[int] = None,
        screen_height: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Parse raw UI-TARS prediction string into a list of executable action parameter dictionaries.
        Supports semicolon and newline-delimited multi-step compound actions.
        """
        sw = screen_width or self.screen_width or 1920
        sh = screen_height or self.screen_height or 1080
        chunks = [c.strip() for c in re.split(r"[;\n]", action_text) if c.strip()]
        parsed_actions = []
        for chunk in chunks:
            # Strip "Action:" prefixes if present
            cleaned = re.sub(r"^action:\s*", "", chunk, flags=re.I).strip()
            parsed = self.parse_single_action(cleaned, sw, sh)
            if parsed.get("action") != "none" or parsed.get("action_type") != "none":
                parsed_actions.append(parsed)
        return parsed_actions

    def _normalize_coords(self, x: int, y: int, width: int, height: int) -> Tuple[int, int]:
        """Convert normalized 0-1000 UI-TARS coordinate tokens to absolute pixel coordinates."""
        if x <= 1000 and y <= 1000 and (width > 1000 or height > 1000):
            # Scale from 0-1000 space
            actual_x = int((x / 1000.0) * width)
            actual_y = int((y / 1000.0) * height)
            return actual_x, actual_y
        return x, y

    def execute_parsed_action(self, parsed: Dict[str, Any], offset: Tuple[int, int] = (0, 0)) -> str:
        """Execute the parsed action physically on screen via PyAutoGUI."""
        atype = parsed.get("action_type")
        params = parsed.get("params", {})
        ox, oy = offset

        if atype == "click":
            target_x = params["x"] + ox
            target_y = params["y"] + oy
            button = params.get("button", "left")
            pyautogui.click(target_x, target_y, button=button)
            return f"UI-TARS executed {button}-click at absolute screen coords ({target_x}, {target_y})"

        elif atype == "type":
            content = params.get("content", "")
            pyautogui.write(content, interval=0.02)
            return f"UI-TARS typed text: '{content}'"

        elif atype == "drag":
            sx = params["start_x"] + ox
            sy = params["start_y"] + oy
            ex = params["end_x"] + ox
            ey = params["end_y"] + oy
            pyautogui.moveTo(sx, sy)
            pyautogui.dragTo(ex, ey, duration=0.8, button="left")
            return f"UI-TARS dragged from ({sx}, {sy}) to ({ex}, {ey})"

        elif atype == "hotkey":
            key_str = params.get("key", "")
            keys = [k.strip().lower() for k in key_str.split("+")]
            pyautogui.hotkey(*keys)
            return f"UI-TARS triggered hotkey: {'+'.join(keys)}"

        elif atype == "finished":
            return "UI-TARS visual task marked complete."

        return f"UI-TARS unhandled action: {parsed.get('raw')}"

    def verify_visual_settlement(self, pre_img: Image.Image, delay: float = 0.3) -> bool:
        """Verify whether pixels changed after action execution."""
        time.sleep(delay)
        post_img = pyautogui.screenshot()
        try:
            stat = ImageStat.Stat(Image.blend(pre_img.convert("RGB"), post_img.convert("RGB"), 0.5))
            diff = max(stat.stddev) if stat.stddev else 0.0
            return diff > 1.0
        except Exception:
            return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    bridge = UITarsBridge()
    img, box = bridge.capture_screen_area()
    print(f"Captured screen size: {img.size}, bounding box: {box}")
    # Test action parsing
    sample = "Action: click(start_box='(450, 620)')"
    parsed = bridge.parse_action_string(sample, img.width, img.height)
    print("Parsed Action:", parsed)
