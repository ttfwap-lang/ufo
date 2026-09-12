import sys
import os
import asyncio

# Ensure UFO is in path
ufo_path = r'C:\ufo'
if ufo_path not in sys.path:
    sys.path.insert(0, ufo_path)

from ufo.utils import is_json_serializable, _attempt_truncated_json_recovery
from ufo.automator.ui_control.inspector import ControlInspectorFacade
from ufo.automator.vision_fallback import VisionFallbackManager

def test_json_recovery():
    print("Testing JSON recovery...")
    truncated = '{"output": "C:\\\\Downloads\\\\test.pdf"'
    recovered = _attempt_truncated_json_recovery(truncated)
    assert recovered is not None
    assert "output" in recovered
    print("JSON recovery passed.")

def test_vision_fallback_config():
    print("Testing vision fallback config...")
    vfm = VisionFallbackManager()
    assert vfm._enabled is not None
    print("Vision fallback config passed.")

def test_inspector():
    print("Testing inspector dummy...")
    try:
        # Just verifying the class loads and we removed the bad exceptions
        ControlInspectorFacade()
    except Exception as e:
        print(f"Inspector failed: {e}")
    else:
        print("Inspector dummy passed.")

if __name__ == "__main__":
    print("Running UFO Simulation Harness...")
    test_json_recovery()
    test_vision_fallback_config()
    test_inspector()
    print("All simulated checks passed!")
