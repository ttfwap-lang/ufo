import sys
from pathlib import Path

# Fix sys.path for test discovery so the UFO root is at sys.path[0]
# Prevents tests/config and tests/aip from shadowing root packages config and aip
root_dir = str(Path(__file__).resolve().parent.parent.parent)
if sys.path[0] != root_dir:
    if root_dir in sys.path:
        sys.path.remove(root_dir)
    sys.path.insert(0, root_dir)


import pytest


@pytest.fixture(autouse=True)
def _isolate_global_event_bus():
    """Drop observers a test registered on the global Galaxy event bus.

    Sessions, synchronizers and web UI observers subscribe to the process-wide
    bus; leaked ones from earlier tests would otherwise receive (and can block
    on) events published by later tests.
    """
    yield
    try:
        from ufo.galaxy.core.events import get_event_bus
    except Exception:
        return
    bus = get_event_bus()
    bus._observers.clear()
    bus._all_observers.clear()
