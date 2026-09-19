"""Live check of hybrid UIA + OmniParser control collection (no desktop interaction).

Runs the AppAgent's real grounding + merge code against the OmniParser service
using a saved screenshot. Skipped unless the service answers at the configured
endpoint (e.g. via scripts/gx10_up.ps1).
"""
import asyncio
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from ufo.agents.processors.schemas.target import TargetInfo, TargetKind
from ufo.agents.processors.strategies import app_agent_processing_strategy as m

SHOT = Path(__file__).resolve().parents[1] / "fixtures" / "notepad_window.png"


def _reachable(host="127.0.0.1", port=7861):
    try:
        socket.create_connection((host, port), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _reachable(), reason="OmniParser not reachable on 127.0.0.1:7861")


def test_hybrid_collection_merges_and_registers_vision_controls(monkeypatch):
    monkeypatch.setattr(m.ufo_config.system, "omniparser", {"ENDPOINT": "http://127.0.0.1:7861", "USE_PADDLEOCR": False}, raising=False)
    strat = m.AppControlInfoStrategy.__new__(m.AppControlInfoStrategy)
    import logging
    strat.logger = logging.getLogger("t")
    from ufo.automator.ui_control.screenshot import PhotographerFacade
    strat.photographer = PhotographerFacade()
    strat.grounding_service = strat._init_omniparser_service()
    assert strat.grounding_service is not None

    w, h = Image.open(SHOT).size
    win = TargetInfo(kind=TargetKind.WINDOW, name="Notepad", id="1", type="Window", rect=[100, 100, 100 + w, 100 + h])
    vision = asyncio.run(strat._collect_grounding_controls(str(SHOT), win))
    assert len(vision) >= 10, "OmniParser should find the menu/status-bar elements"
    assert all(100 <= c.rect[0] <= 100 + w and 100 <= c.rect[1] <= 100 + h for c in vision)

    uia = [TargetInfo(kind=TargetKind.CONTROL, name=vision[0].name, id="1", type="Button", rect=vision[0].rect, source="uia")]
    sent = []

    async def execute_commands(cmds):
        sent.extend(cmds)
        return [SimpleNamespace(result="ok", status="success")]
    merged = asyncio.run(strat._collect_merged_control_list(uia, vision, SimpleNamespace(execute_commands=execute_commands)))
    assert len(merged) == len(vision), "the UIA duplicate should replace its vision twin, not add to it"
    assert any(c.tool_name == "add_control_list" for c in sent), "vision-only controls must be registered for clicking"
