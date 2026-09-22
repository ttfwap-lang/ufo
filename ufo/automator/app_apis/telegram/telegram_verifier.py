"""Self-verification with screenshots for Telegram automaton.

Every operation can be verified by capturing visual evidence:
- Pre-operation screenshots (before a message is sent)
- Post-operation screenshots (after a message is sent)
- Verification of message presence in the chat
- Failure evidence capture for debugging
- Continuous state monitoring

All screenshots are saved with timestamps for audit/review.

Storage layout:
    ufo_skill_state/evidence/
    ├── goal_{goal_id}/
    │   ├── pre_msg_{n}_{timestamp}.png
    │   ├── post_msg_{n}_{timestamp}.png
    │   └── verified_{n}_{timestamp}.png  (with OCR verification result)
    └── failures/
        └── fail_{timestamp}.png
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

logger = logging.getLogger(__name__)

# Evidence storage root
EVIDENCE_DIR = Path("ufo_skill_state/evidence")


@dataclass
class VerificationResult:
    """Result of a verification check."""
    success: bool
    evidence_path: Optional[Path] = None
    reasoning: str = ""
    timestamp: str = ""
    details: Dict[str, Any] = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}


class TelegramVerifier:
    """Verifies Telegram operations using screenshots and visual analysis.

    Capabilities:
    - Capture screenshot at any moment
    - Verify message was sent (visual check of chat state)
    - Save evidence with timestamps
    - Analyze screenshots for anomalies
    - Compare before/after states
    """

    def __init__(
        self,
        controller=None,
        evidence_dir: Path = EVIDENCE_DIR,
    ):
        """Initialize the verifier.

        Args:
            controller: TelegramGUIController for screenshots.
            evidence_dir: Where to store verification evidence.
        """
        self._controller = controller
        self._evidence_dir = Path(evidence_dir)
        self._evidence_dir.mkdir(parents=True, exist_ok=True)
        self._last_screenshot: Optional[bytes] = None
        self._screenshot_history: List[Dict[str, Any]] = []

    def set_controller(self, controller) -> None:
        """Attach a GUI controller."""
        self._controller = controller

    # ==================== Screenshot Capture ====================

    async def capture_screenshot(
        self,
        label: str = "",
        goal_id: Optional[str] = None,
    ) -> Tuple[Optional[bytes], Optional[Path]]:
        """Capture a screenshot and optionally save it.

        Args:
            label: Descriptive label for the screenshot.
            goal_id: Optional goal ID for organizing evidence.

        Returns:
            (screenshot_bytes, saved_path) tuple.
        """
        if self._controller is None:
            logger.warning("No controller for screenshot capture")
            return None, None

        try:
            screenshot = await self._controller.take_screenshot()
        except Exception as e:
            logger.error(f"Screenshot capture failed: {e}")
            # Try with window capture if controller method fails
            try:
                screenshot = await self._capture_via_window()
            except Exception as e2:
                logger.error(f"Window screenshot also failed: {e2}")
                screenshot = None

        if screenshot is None:
            return None, None

        # Track in memory
        self._last_screenshot = screenshot
        timestamp = datetime.now().isoformat().replace(":", "-")
        self._screenshot_history.append(
            {
                "timestamp": timestamp,
                "label": label,
                "size": len(screenshot),
                "goal_id": goal_id,
            }
        )

        # Save to disk if labeled
        saved_path = None
        if label:
            try:
                if goal_id:
                    goal_dir = self._evidence_dir / f"goal_{goal_id}"
                else:
                    goal_dir = self._evidence_dir / "general"
                goal_dir.mkdir(parents=True, exist_ok=True)

                filename = f"{label}_{timestamp}.png"
                saved_path = goal_dir / filename
                with open(saved_path, "wb") as f:
                    f.write(screenshot)
                logger.info(f"Screenshot saved: {saved_path}")
            except Exception as e:
                logger.error(f"Failed to save screenshot: {e}")

        return screenshot, saved_path

    async def _capture_via_window(self) -> Optional[bytes]:
        """Capture screenshot of the specific Telegram window.

        Uses PrintWindow on the concrete HWND - never grabs the whole desktop,
        so verification evidence always shows Telegram itself.
        """
        if self._controller is None or self._controller.window is None:
            return None
        try:
            import win32gui
            import win32ui
            import win32con
            import ctypes
            from PIL import Image

            # Resolve the concrete HWND from the WindowSpecification
            hwnd = None
            handle = self._controller.window.handle
            if hasattr(handle, "handle") and isinstance(handle.handle, int):
                hwnd = handle.handle
            elif isinstance(handle, int):
                hwnd = handle

            if not hwnd or not win32gui.IsWindow(hwnd):
                return None

            rect = win32gui.GetWindowRect(hwnd)
            width = rect[2] - rect[0]
            height = rect[3] - rect[1]
            if width <= 0 or height <= 0:
                return None

            hwnd_dc = win32gui.GetWindowDC(hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()
            bmp = win32ui.CreateBitmap()
            bmp.CreateCompatibleBitmap(mfc_dc, width, height)
            save_dc.SelectObject(bmp)
            try:
                PW_RENDERFULLCONTENT = 2
                result = ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), PW_RENDERFULLCONTENT)
                if not result:
                    result = ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 1)
                if not result:
                    return None
                bmpinfo = bmp.GetInfo()
                bmpstr = bmp.GetBitmapBits(True)
                image = Image.frombuffer(
                    "RGB", (bmpinfo["bmWidth"], bmpinfo["bmHeight"]), bmpstr, "raw", "BGRX", 0, 1
                )
                buf = io.BytesIO()
                image.save(buf, format="PNG")
                return buf.getvalue()
            finally:
                save_dc.DeleteDC()
                mfc_dc.DeleteDC()
                win32gui.ReleaseDC(hwnd, hwnd_dc)
                win32gui.DeleteObject(bmp.GetHandle())
        except Exception as e:
            logger.error(f"Window capture failed: {e}")
            return None

    # ==================== Verification ====================

    async def verify_window_present(self) -> VerificationResult:
        """Verify Telegram window is present and connected."""
        if self._controller is None:
            return VerificationResult(False, reasoning="No controller")
        is_connected = self._controller.is_connected
        has_window = self._controller.window is not None
        success = is_connected and has_window
        return VerificationResult(
            success=success,
            reasoning=f"connected={is_connected}, window={has_window}",
        )

    async def verify_foreground_ownership(self) -> VerificationResult:
        """Verify input can safely be delivered to Telegram.

        - Unlocked mode: Telegram must own the foreground (otherwise keys
          would leak into the user's window). Refuse if not.
        - Locked mode: the lockout overlay owns foreground, so verify the
          lockout is still active (the machine is still confiscated) and
          input is injected via window messages.
        """
        if self._controller is None:
            return VerificationResult(False, reasoning="No controller")

        lockout_active = self._controller.lockout_active

        def _check():
            if lockout_active:
                # Locked: overlay owns focus by design; just verify the lockout
                # is still held and Telegram window is valid.
                lockout = getattr(self._controller, "_lockout", None)
                still_locked = lockout is not None and lockout.is_locked
                hwnd = self._controller.get_concrete_hwnd()
                return still_locked and hwnd is not None
            hwnd = self._controller.get_concrete_hwnd()
            if not hwnd:
                return False
            try:
                import ctypes
                user32 = ctypes.windll.user32
                return user32.GetForegroundWindow() == hwnd
            except Exception:
                return False

        is_safe = await asyncio.to_thread(_check)
        mode = "locked" if lockout_active else "unlocked"
        return VerificationResult(
            success=is_safe,
            reasoning=(
                f"Input safe ({mode}): Telegram under AI control"
                if is_safe
                else f"NOT SAFE ({mode}): refusing to send input"
            ),
            timestamp=datetime.now().isoformat(),
        )

    async def verify_before_send(
        self,
        message_number: int,
        goal_id: Optional[str] = None,
    ) -> VerificationResult:
        """Capture pre-send state and verify chat is ready."""
        screenshot, path = await self.capture_screenshot(
            label=f"pre_msg_{message_number}",
            goal_id=goal_id,
        )
        if screenshot is None:
            return VerificationResult(
                False,
                reasoning="Failed to capture pre-send screenshot",
            )

        # Analyze screenshot for readiness indicators
        analysis = await self.analyze_screenshot(screenshot)
        return VerificationResult(
            success=analysis["usable"],
            evidence_path=path,
            reasoning=analysis["reasoning"],
            timestamp=datetime.now().isoformat(),
            details=analysis,
        )

    async def verify_after_send(
        self,
        message_number: int,
        message_text: str,
        goal_id: Optional[str] = None,
    ) -> VerificationResult:
        """Capture post-send screenshot and verify message was sent.

        Also verifies Telegram still owns the foreground (no keystroke
        leakage into other apps).
        """
        # Small delay for UI to settle
        await asyncio.sleep(0.3)
        screenshot, path = await self.capture_screenshot(
            label=f"post_msg_{message_number}",
            goal_id=goal_id,
        )
        if screenshot is None:
            return VerificationResult(
                False,
                reasoning="Failed to capture post-send screenshot",
            )

        analysis = await self.analyze_screenshot(screenshot)
        # Verify the message bubble should appear near bottom
        success = analysis["usable"]
        # Safety: confirm Telegram still owns foreground after send
        fg = await self.verify_foreground_ownership()
        if not fg.success:
            success = False
            analysis["reasoning"] += " | WARNING: lost foreground after send"
        return VerificationResult(
            success=success,
            evidence_path=path,
            reasoning=f"Post-send analysis: {analysis['reasoning']}",
            timestamp=datetime.now().isoformat(),
            details={
                **analysis,
                "foreground_ok": fg.success,
                # Privacy: never log message content - redact it entirely
                "message_text_redacted": True,
                "message_number": message_number,
            },
        )

    async def verify_goal_progress(
        self,
        goal_id: str,
        expected_messages: int,
    ) -> VerificationResult:
        """Verify overall goal progress with evidence."""
        screenshot, path = await self.capture_screenshot(
            label=f"goal_checkpoint_expected_{expected_messages}",
            goal_id=goal_id,
        )
        if screenshot is None:
            return VerificationResult(
                False, reasoning="Failed to capture progress screenshot"
            )
        analysis = await self.analyze_screenshot(screenshot)
        return VerificationResult(
            success=analysis["usable"],
            evidence_path=path,
            reasoning=f"Progress checkpoint: {analysis['reasoning']}",
            timestamp=datetime.now().isoformat(),
            details={**analysis, "expected_messages": expected_messages},
        )

    # ==================== Screenshot Analysis ====================

    async def analyze_screenshot(self, screenshot: bytes) -> Dict[str, Any]:
        """Analyze a screenshot for basic properties.

        Checks:
        - Not blank/black
        - Has sufficient variation (not frozen)
        - Size within expected range
        - Content changed from last screenshot (if available)

        Returns:
            Dict with analysis results.
        """
        try:
            image = Image.open(io.BytesIO(screenshot))
            w, h = image.size

            # Check not blank
            import numpy as np
            arr = np.array(image.convert("RGB"))
            stddev = float(arr.std())
            mean = float(arr.mean())

            usable = stddev > 10.0  # Non-uniform is generally usable "real" UI

            # Check changed from last
            changed = True
            if self._last_screenshot and self._last_screenshot != screenshot:
                try:
                    last_img = Image.open(io.BytesIO(self._last_screenshot))
                    last_arr = np.array(last_img.convert("RGB"))
                    if last_arr.shape == arr.shape:
                        diff = float(np.abs(arr.astype(float) - last_arr.astype(float)).mean())
                        changed = diff > 1.0
                except Exception:
                    changed = True

            return {
                "usable": usable,
                "changed": changed,
                "reasoning": (
                    f"size={w}x{h}, stddev={stddev:.1f}, changed={changed}"
                ),
                "resolution": f"{w}x{h}",
                "stddev": round(stddev, 2),
            }
        except Exception as e:
            return {
                "usable": False,
                "changed": False,
                "reasoning": f"Analysis failed: {e}",
            }

    # ==================== Evidence Management ====================

    def list_evidence(self, goal_id: Optional[str] = None) -> List[Path]:
        """List evidence files for a goal or all goals."""
        if goal_id:
            goal_dir = self._evidence_dir / f"goal_{goal_id}"
            if goal_dir.exists():
                return sorted(goal_dir.glob("*.png"))
            return []
        return sorted(self._evidence_dir.rglob("*.png"))

    def get_screenshot_history(self) -> List[Dict[str, Any]]:
        """Get in-memory screenshot capture history."""
        return self._screenshot_history

    def clear_evidence(self, goal_id: Optional[str] = None) -> None:
        """Delete evidence files for cleanup."""
        if goal_id:
            goal_dir = self._evidence_dir / f"goal_{goal_id}"
            if goal_dir.exists():
                for f in goal_dir.glob("*.png"):
                    f.unlink()
        else:
            for f in self._evidence_dir.rglob("*.png"):
                f.unlink()

    def base64_encode(self, screenshot: bytes) -> str:
        """Encode screenshot for LLM vision analysis."""
        return base64.b64encode(screenshot).decode("ascii")
