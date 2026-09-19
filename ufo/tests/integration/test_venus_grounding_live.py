"""Live UI-Venus grounding on a saved Notepad screenshot (no desktop interaction).

Skipped unless the grounding endpoint answers on 127.0.0.1:8002 (scripts/gx10_up.ps1).
"""
import socket
from pathlib import Path

import pytest

from ufo.automator.ui_control.grounding.venus import VenusGrounder

SHOT = str(Path(__file__).resolve().parents[1] / "fixtures" / "notepad_window.png")


def _reachable():
    try:
        socket.create_connection(("127.0.0.1", 8002), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _reachable(), reason="UI-Venus not reachable on 127.0.0.1:8002")

# Element boxes (fractions of the window) measured by OmniParser on the same screenshot.
EXPECTED = {
    "the Bullets button": (0.405, 0.064, 0.453, 0.110),
    "the Italic button": (0.483, 0.064, 0.511, 0.110),
    "the View menu": (0.094, 0.065, 0.137, 0.111),
}


@pytest.mark.parametrize("description", list(EXPECTED))
def test_locates_real_elements(description):
    r = VenusGrounder("http://127.0.0.1:8002/v1").locate(SHOT, description)
    x0, y0, x1, y1 = EXPECTED[description]
    assert r is not None and x0 <= r.fx <= x1 and y0 <= r.fy <= y1


def test_rejects_elements_that_are_not_there():
    assert VenusGrounder("http://127.0.0.1:8002/v1").locate(SHOT, "the Send email button") is None
