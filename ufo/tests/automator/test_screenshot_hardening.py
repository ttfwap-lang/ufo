# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Unit tests for screenshot system hardening and visual screenshot verification script.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from PIL import Image

from ufo.automator.ui_control.screenshot import (
    is_valid_capture_image,
    _ensure_window_restored,
    _crop_desktop_rect,
    _create_diagnostic_error_frame,
    ControlPhotographer,
    DesktopPhotographer,
)
from tests.verify_screenshots import (
    is_valid_step_image,
    scan_and_verify_screenshots,
    verify_task_screenshots,
    main,
)


class TestScreenshotHardening(unittest.TestCase):

    def test_is_valid_capture_image_rejections(self):
        # 1. None image
        self.assertFalse(is_valid_capture_image(None))

        # 2. 1x1 tiny image
        tiny_img = Image.new("RGB", (1, 1), (0, 0, 0))
        self.assertFalse(is_valid_capture_image(tiny_img))

        # 3. All-black image (getbbox is None)
        black_img = Image.new("RGB", (200, 200), (0, 0, 0))
        self.assertFalse(is_valid_capture_image(black_img))

        # 4. Solid color image (pixel stddev is 0.0 <= 5.0)
        white_img = Image.new("RGB", (200, 200), (255, 255, 255))
        self.assertFalse(is_valid_capture_image(white_img))

        gray_img = Image.new("RGB", (200, 200), (128, 128, 128))
        self.assertFalse(is_valid_capture_image(gray_img))

    def test_is_valid_capture_image_acceptances(self):
        # Image with high contrast UI pattern
        img = Image.new("RGB", (200, 200), (255, 255, 255))
        # Draw a black box and text pattern
        for x in range(50, 150):
            for y in range(50, 150):
                img.putpixel((x, y), (0, 0, 0))
        self.assertTrue(is_valid_capture_image(img))

        # Diagnostic error frame banner — correctly detected as invalid
        diag_frame = _create_diagnostic_error_frame()
        self.assertFalse(is_valid_capture_image(diag_frame))

    @patch("win32gui.IsWindow", return_value=True)
    @patch("win32gui.IsIconic", return_value=True)
    @patch("win32gui.IsWindowVisible", return_value=False)
    @patch("win32gui.ShowWindow")
    @patch("win32gui.BringWindowToTop")
    @patch("win32gui.RedrawWindow")
    def test_ensure_window_restored_minimized(
        self, mock_redraw, mock_top, mock_show, mock_visible, mock_iconic, mock_iswin
    ):
        result = _ensure_window_restored(12345)
        self.assertTrue(result)
        mock_show.assert_called()
        mock_redraw.assert_called()

    @patch("win32gui.ShowWindow")
    @patch("win32gui.IsWindow", return_value=True)
    @patch("ufo.automator.ui_control.screenshot.DesktopPhotographer.capture")
    def test_crop_desktop_rect(self, mock_desktop_capture, mock_iswin, mock_show):
        # Create a valid desktop image
        desktop_img = Image.new("RGB", (1000, 800), (255, 255, 255))
        for x in range(100, 300):
            for y in range(100, 300):
                desktop_img.putpixel((x, y), (0, 128, 255))
        mock_desktop_capture.return_value = desktop_img

        cropped = _crop_desktop_rect(12345, (50, 50, 400, 400))
        self.assertIsNotNone(cropped)
        self.assertGreater(cropped.width, 1)
        self.assertGreater(cropped.height, 1)

    def test_desktop_photographer_diagnostic_fallback(self):
        photographer = DesktopPhotographer(all_screens=False)
        with patch("ufo.automator.ui_control.screenshot.ImageGrab.grab", return_value=None), \
             patch("ufo.automator.ui_control.screenshot._win32_grab_screen", return_value=None), \
             patch("urllib.request.urlopen", side_effect=Exception("Relay server offline")):
            captured = photographer.capture()
            self.assertIsNotNone(captured)
            self.assertEqual(captured.size, (800, 600))
            # Diagnostic error frames are intentionally detected as invalid
            # by is_diagnostic_warning_frame() to trigger retry logic upstream
            self.assertFalse(is_valid_capture_image(captured))

    def test_control_photographer_fallback_chain(self):
        mock_control = MagicMock()
        mock_control.handle = 12345
        mock_control.capture_as_image.return_value = Image.new("RGB", (100, 100), (0, 0, 0)) # invalid black

        photographer = ControlPhotographer(mock_control)
        
        valid_img = Image.new("RGB", (300, 200), (255, 255, 255))
        for x in range(20, 80):
            valid_img.putpixel((x, x), (255, 0, 0))

        with patch("ufo.automator.ui_control.screenshot._ensure_window_restored", return_value=True), \
             patch("ufo.automator.ui_control.screenshot._win32_print_window", return_value=valid_img):
            captured = photographer.capture()
            self.assertIsNotNone(captured)
            self.assertTrue(is_valid_capture_image(captured))


class TestVerifyScreenshotsScript(unittest.TestCase):

    def test_is_valid_step_image_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            # 1. Non-existent file
            valid, msg = is_valid_step_image(os.path.join(temp_dir, "nonexistent.png"))
            self.assertFalse(valid)

            # 2. Black image file
            black_path = os.path.join(temp_dir, "black.png")
            black_img = Image.new("RGB", (100, 100), (0, 0, 0))
            black_img.save(black_path)
            valid, msg = is_valid_step_image(black_path)
            self.assertFalse(valid)

            # 3. Valid UI screenshot file
            valid_path = os.path.join(temp_dir, "valid.png")
            valid_img = Image.new("RGB", (400, 300), (240, 240, 240))
            for x in range(50, 150):
                for y in range(50, 150):
                    valid_img.putpixel((x, y), (10, 50, 200))
            valid_img.save(valid_path)
            valid, msg = is_valid_step_image(valid_path)
            self.assertTrue(valid)

    def test_scan_and_verify_screenshots(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            valid_path = os.path.join(temp_dir, "step1.png")
            valid_img = Image.new("RGB", (400, 300), (240, 240, 240))
            for x in range(50, 150):
                for y in range(50, 150):
                    valid_img.putpixel((x, y), (10, 50, 200))
            valid_img.save(valid_path)

            results = scan_and_verify_screenshots(temp_dir)
            self.assertEqual(results["total_scanned"], 1)
            self.assertEqual(results["passed"], 1)
            self.assertEqual(results["failed"], 0)

            success = verify_task_screenshots(temp_dir)
            self.assertTrue(success)

    def test_is_valid_step_image_edge_cases(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            # 1. 0-byte file
            empty_path = os.path.join(temp_dir, "empty.png")
            open(empty_path, "wb").close()
            valid, msg = is_valid_step_image(empty_path)
            self.assertFalse(valid)
            self.assertIn("0 bytes", msg)

            # 2. 1x1 tiny image file
            tiny_path = os.path.join(temp_dir, "tiny_1x1.png")
            tiny_img = Image.new("RGB", (1, 1), (255, 255, 255))
            tiny_img.save(tiny_path)
            valid, msg = is_valid_step_image(tiny_path)
            self.assertFalse(valid)
            self.assertIn("Invalid dimensions", msg)

    def test_verify_task_screenshots_missing_and_empty_directories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            # Missing directory
            missing_dir = os.path.join(temp_dir, "non_existent_dir")
            self.assertFalse(verify_task_screenshots(missing_dir))

            # Empty directory
            empty_dir = os.path.join(temp_dir, "empty_dir")
            os.makedirs(empty_dir)
            self.assertFalse(verify_task_screenshots(empty_dir))

    def test_main_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            # 1. Missing directory -> exit code 1
            missing_dir = os.path.join(temp_dir, "non_existent_dir")
            with patch.object(sys, "argv", ["verify_screenshots.py", missing_dir]):
                with self.assertRaises(SystemExit) as cm:
                    main()
                self.assertEqual(cm.exception.code, 1)

            # 2. Empty directory -> exit code 1
            empty_dir = os.path.join(temp_dir, "empty_dir")
            os.makedirs(empty_dir)
            with patch.object(sys, "argv", ["verify_screenshots.py", empty_dir]):
                with self.assertRaises(SystemExit) as cm:
                    main()
                self.assertEqual(cm.exception.code, 1)

            # 3. Valid PNG directory -> exit code 0
            valid_dir = os.path.join(temp_dir, "valid_dir")
            os.makedirs(valid_dir)
            valid_img_path = os.path.join(valid_dir, "step1.png")
            valid_img = Image.new("RGB", (400, 300), (240, 240, 240))
            for x in range(50, 150):
                for y in range(50, 150):
                    valid_img.putpixel((x, y), (10, 50, 200))
            valid_img.save(valid_img_path)

            with patch.object(sys, "argv", ["verify_screenshots.py", valid_dir]):
                with self.assertRaises(SystemExit) as cm:
                    main()
                self.assertEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
