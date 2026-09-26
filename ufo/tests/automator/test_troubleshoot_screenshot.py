"""Rule 3 screenshots must contain something, or they must not claim to.

troubleshoot_screenshot() is what the controller reaches for whenever the
automation gets stuck, and its output is treated as ground truth. On 2026-09-26
that ground truth was silently worthless: the saved debug PNG for
`search_field_missing` was 1073x1000 with exactly two grey levels in it - 97.44%
pure white inside a ~6px black frame - while a whole-desktop capture of the very
same screen, on the same unlocked session with Telegram running, returned 223 KB
of real content.

It was not an error and nothing reported it. take_screenshot() only retries when
the capture RAISES, and PrintWindow on Telegram's GPU-composited window returns
a white image while reporting success. So the blank bytes were written to disk
and logged with a confident `screenshot -> <path>`, and the one thing meant to
unstick the investigation becomes the thing that ends it.

These tests pin the detector, including the case that fooled the first version:
a border drags the whole-frame white fraction to 95.2%, so sampling across it
reads as content. The interior is what has to be checked.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw

from ufo.automator.app_apis.telegram.telegram_gui import TelegramGUIController

_looks_blank = TelegramGUIController._looks_blank


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _framed(w: int = 1073, h: int = 1000, frame: int = 6) -> bytes:
    """Reproduce the real failure: a thin dark frame around an empty white body.

    Dimensions and frame thickness match the captured file, because the whole
    point is that this specific shape is not detectable by whole-frame means.
    """
    img = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w - 1, h - 1], outline=(0, 0, 0), width=frame)
    return _png(img)


def _ui_like() -> bytes:
    """Something that actually looks rendered: a sidebar, a bar, text blocks."""
    img = Image.new("RGB", (900, 700), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 260, 700], fill=(40, 44, 52))
    d.rectangle([0, 0, 900, 52], fill=(58, 96, 168))
    for i in range(10):
        d.rectangle([16, 70 + i * 54, 244, 114 + i * 54], fill=(70, 76, 88))
    for i in range(14):
        d.rectangle([300, 80 + i * 44, 300 + (i * 37) % 560, 96 + i * 44], fill=(60, 60, 60))
    return _png(img)


def test_real_blank_debug_capture_is_rejected() -> None:
    """The actual file that shipped as evidence, if it is still on disk.

    Skipped when absent (ufo_skill_state is not tracked) so a clean clone still
    runs the rest of the suite.
    """
    here = Path(__file__).resolve().parents[2]
    hits = sorted((here / "ufo_skill_state/evidence/debug").glob("search_field_missing_*.png"))
    if not hits:
        import pytest
        pytest.skip("no captured debug PNG on disk")
    for p in hits:
        assert _looks_blank(p.read_bytes()) is True, f"{p.name} was blank but not detected"


def test_framed_but_empty_interior_is_blank() -> None:
    """The case that fooled the first version of the detector.

    Whole-frame white fraction is 95.2%, under a naive 98% cut-off, so a border
    must not be allowed to vote as content.
    """
    assert _looks_blank(_framed()) is True


def test_pure_white_without_border_is_blank() -> None:
    assert _looks_blank(_png(Image.new("RGB", (800, 600), (255, 255, 255)))) is True


def test_rendered_ui_is_not_blank() -> None:
    """The detector must not swing the other way and reject real evidence."""
    assert _looks_blank(_ui_like()) is False


def test_low_contrast_is_blank() -> None:
    """Near-uniform grey (a capture of a dead or obscured surface)."""
    assert _looks_blank(_png(Image.new("RGB", (640, 480), (252, 252, 252)))) is True


def test_unreadable_bytes_are_kept_not_discarded() -> None:
    """Cannot mean 'throw the evidence away'.

    _looks_blank returns False when it cannot decode, so troubleshoot_screenshot
    still writes whatever it captured rather than silently producing nothing.
    """
    assert _looks_blank(b"this is not a png at all") is False


def test_tiny_image_is_blank_not_a_crash() -> None:
    assert _looks_blank(_png(Image.new("RGB", (1, 1), (255, 255, 255)))) is True
    assert _looks_blank(_png(Image.new("RGB", (2, 2), (0, 0, 0)))) is True
