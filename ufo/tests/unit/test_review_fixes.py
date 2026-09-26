"""Regression tests for the ten /code-review findings of 2026-09-26.

Each test fails on the pre-fix code (checked by reverting the fix) and passes
now. Nothing here injects real input: HumanMouse movement/button calls are
stubbed, and no GUI, network or Redis is touched.
"""
import asyncio
import logging
import sys

import pytest


# 1 ---- RULE 1: clicks run the countdown gate; a cancelled gate sends nothing
@pytest.mark.skipif(sys.platform != "win32", reason="HumanMouse uses ctypes.windll")
class TestHumanMouseGate:
    def _mouse(self, hook):
        from ufo.automator.app_apis.telegram.telegram_human_mouse import HumanMouse

        m = HumanMouse(seed=1, first_move_hook=hook)
        m.sent = []
        m._move_with_submovements = lambda x, y: m.sent.append(("move", x, y))
        m._button = lambda down: m.sent.append(("button", down))
        return m

    @pytest.mark.parametrize("action", ["click", "double_click"])
    def test_click_is_gated(self, action):
        calls = []
        m = self._mouse(lambda: calls.append(1))
        getattr(m, action)(10, 20)
        assert calls == [1]
        assert m.sent  # and it did act after the gate passed

    @pytest.mark.parametrize("action", ["click", "double_click", "move_to", "drag", "scroll"])
    def test_cancelled_gate_sends_no_input_and_rearms(self, action):
        calls = []

        def cancel():
            calls.append(1)
            raise RuntimeError("AUTOMATION CANCELLED BY USER")

        m = self._mouse(cancel)
        args = {"drag": ((0, 0), (5, 5)), "scroll": (1, 3, 3)}.get(action, (10, 20))
        with pytest.raises(RuntimeError):
            getattr(m, action)(*args)
        assert m.sent == []  # nothing reached the cursor
        with pytest.raises(RuntimeError):
            getattr(m, action)(*args)
        assert calls == [1, 1]  # the gate is shown again, not skipped


# 2 ---- RULE 5: tokens are masked, including when logged as a format argument
TG_TOKEN = "123456789:" + "A" * 17 + "b" * 18   # built at runtime: not a literal secret


def test_redact_masks_a_bare_telegram_token():
    from ufo.utils.redact import redact

    out = redact(f"Use this token to access the HTTP API: {TG_TOKEN}")
    assert TG_TOKEN not in out and "123456789:***" in out


def test_redacting_filter_masks_secret_passed_as_an_argument(caplog):
    from ufo.utils.redact import RedactingFilter

    log = logging.getLogger("test.redact.args")
    log.addFilter(RedactingFilter())
    with caplog.at_level(logging.INFO, logger="test.redact.args"):
        log.info("token=%s", "s3cr3t-value")
        log.info("bot: %s", TG_TOKEN)
    text = caplog.text
    assert "s3cr3t-value" not in text and TG_TOKEN not in text
    assert "token=***" in text


# 3 ---- the bridge's Telegram relaunch names a variable that exists
def test_bridge_has_no_telelegram_typo():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "ufo_bridge.py").read_text(encoding="utf-8")
    assert "TELELEGRAM" not in src


# 4 ---- a non-raising failure does not satisfy SUCCESS_ONLY dependents
def test_failed_task_without_error_does_not_unblock_success_only_dependents():
    from ufo.galaxy.constellation.task_constellation import TaskConstellation
    from ufo.galaxy.constellation.task_star import TaskStar
    from ufo.galaxy.constellation.task_star_line import TaskStarLine
    from ufo.galaxy.constellation.enums import DependencyType

    c = TaskConstellation()
    a, b = TaskStar(task_id="a", description="a"), TaskStar(task_id="b", description="b")
    c.add_task(a)
    c.add_task(b)
    c.add_dependency(TaskStarLine(from_task_id="a", to_task_id="b",
                                  dependency_type=DependencyType.SUCCESS_ONLY))
    newly_ready = c.mark_task_completed("a", success=False, result=None)  # no error=
    assert [t.task_id for t in newly_ready] == []


# 6 ---- a probe that ends in a non-endpoint error hands the ticket back
def test_endpoint_gate_probe_ticket_is_released():
    from ufo.llm.endpoint_health import EndpointDown, EndpointGate

    now = [0.0]
    g = EndpointGate(threshold=1, base_cooldown=10, clock=lambda: now[0])
    g.record_failure("k", "timeout", hard=True)
    now[0] = 11.0
    g.check("k")                     # this caller becomes the half-open probe
    with pytest.raises(EndpointDown):
        g.check("k")                 # others fail fast while it is in flight
    g.release_probe("k")             # the probe got a 400: neither success nor failure
    g.check("k")                     # the next caller can probe; the gate is not stuck


def test_llm_call_releases_ticket_on_non_endpoint_error(monkeypatch):
    from ufo.llm import llm_call
    from ufo.llm.endpoint_health import EndpointDown

    gate = llm_call.ENDPOINT_GATE
    gate.reset()
    now = [0.0]
    monkeypatch.setattr(gate, "_clock", lambda: now[0])
    monkeypatch.setattr(llm_call, "_gated_endpoint_key", lambda s: "gx10:8000")
    gate.record_failure("gx10:8000", "timeout", hard=True)
    now[0] = 10_000.0

    class BadRequest(Exception):
        pass

    class Svc:
        async def chat_completion(self, messages, n=1):
            raise BadRequest("400 invalid schema")

    with pytest.raises(BadRequest):
        asyncio.run(llm_call._retry_with_backoff.retry_with(stop=lambda *_: True)(Svc(), [], 1))
    try:
        gate.check("gx10:8000")      # would raise 'recovery probe in flight' before the fix
    except EndpointDown as e:
        pytest.fail(f"half-open ticket leaked: {e}")
    finally:
        gate.reset()


# 7 ---- a lock taken via the local fallback is released locally
def test_fallback_lock_is_released():
    from ufo.fleet.distributed_lock import DistributedLockManager

    class DeadRedis:
        def set(self, *a, **k):
            raise ConnectionError("redis down")

        def eval(self, *a, **k):
            return 0  # 'not the owner': no such key in Redis

    m = DistributedLockManager.__new__(DistributedLockManager)
    DistributedLockManager.__init__(m) if False else None
    import threading
    m._redis, m._worker_id, m._lock_prefix, m._lock_expiry = DeadRedis(), "w1", "p", 60
    m._local_locks, m._local_lock_guard, m._fallback_keys = {}, threading.Lock(), set()
    type(m).is_distributed = property(lambda self: True)
    try:
        assert m.acquire_lock("K") is True
        assert m.release_lock("K") is True
        assert m.acquire_lock("K") is True   # not blocked forever
    finally:
        del type(m).is_distributed


# 8 ---- execute() uses the same name-matched target the selection used
def test_resolve_target_matches_by_name():
    from ufo.agents.processors.strategies.host_agent_processing_strategy import (
        HostActionExecutionStrategy,
    )
    from ufo.agents.processors.schemas.target import TargetInfo, TargetKind, TargetRegistry

    reg = TargetRegistry()
    reg.register(TargetInfo(kind=TargetKind.WINDOW, id="7", name="Untitled - Notepad"))
    s = HostActionExecutionStrategy()
    assert s._resolve_target(reg, "7").id == "7"
    assert s._resolve_target(reg, "notepad").id == "7"   # the LLM answered with a name
    assert s._resolve_target(reg, "nothing-like-it") is None


# 9 ---- an SSRF-rejected URL is never written to devices.yaml
def test_rejected_device_url_is_not_persisted(monkeypatch):
    from fastapi import HTTPException

    from ufo.galaxy.webui.routers import devices as r

    written = []

    class FakeConfig:
        def load_devices_config(self):
            pass

        def device_id_exists(self, _):
            return False

        def add_device_to_config(self, **kw):
            written.append(kw)
            return kw

    class FakeDevices:
        def __init__(self, *_):
            pass

        async def register_and_connect_device(self, **kw):
            raise AssertionError("must not get this far")

    monkeypatch.setattr(r, "ConfigService", FakeConfig)
    monkeypatch.setattr(r, "DeviceService", FakeDevices)
    monkeypatch.setattr(r, "get_app_state", lambda: None)

    class Req:
        device_id, server_url, os = "evil", "ws://169.254.169.254/", "linux"
        capabilities, metadata, auto_connect, max_retries = [], {}, True, 1

    with pytest.raises(HTTPException) as ei:
        asyncio.run(r.add_device(Req()))
    assert ei.value.status_code == 409
    assert written == []


# 5 ---- recovery after an early exception returns instead of raising UnboundLocalError
def test_recovered_early_failure_does_not_raise_unboundlocal():
    from unittest.mock import AsyncMock, MagicMock

    from ufo.galaxy.constellation.orchestrator.orchestrator import TaskConstellationOrchestrator

    orch = TaskConstellationOrchestrator.__new__(TaskConstellationOrchestrator)
    orch._event_bus = MagicMock(publish_event=AsyncMock())
    orch._logger = None
    orch._inject_recovery_node = AsyncMock(return_value=True)

    task = MagicMock(task_id="t1")
    task.start_execution.side_effect = RuntimeError("device vanished")   # before `result =`
    task.should_retry.return_value = False
    constellation = MagicMock(constellation_id="c1")
    constellation.mark_task_completed.return_value = []

    assert asyncio.run(orch._execute_task_with_events(task, constellation)) is None


# ---- late finder report (automator partition)

def test_lockout_default_cancel_keys_include_ctrl_shift_q():
    """AGENTS.md RULE 1: Ctrl+Shift+Q cancels. Registration is not exercised here."""
    from ufo.automator.app_apis.telegram.telegram_lockout import ScreenLockout

    keys = ScreenLockout()._cancel_hotkeys
    assert (0x0002 | 0x0004, 0x51) in keys          # Ctrl+Shift+Q
    assert (0, 0x1B) in keys                         # ESC backup still there


def test_uia_launch_returns_the_real_pid(monkeypatch):
    from ufo.automation.uia_adapter import UIADesktop

    class App:
        process = 4242                               # pywinauto stores the int PID

        def start(self, cmd):
            return self

    d = UIADesktop.__new__(UIADesktop)
    d._application_cls = lambda backend: App()
    d._ensure_imported = lambda: None
    assert asyncio.run(d.launch("notepad.exe")) == 4242


def test_playwright_screenshot_accepts_the_protocol_signature():
    from ufo.automation.desktop import Rect
    from ufo.automation.playwright_adapter import PlaywrightDesktop

    seen = []

    class Page:
        async def screenshot(self, clip=None):
            seen.append(clip)
            return b"png"

    p = PlaywrightDesktop.__new__(PlaywrightDesktop)
    p._page = Page()
    r = Rect(left=1, top=2, right=11, bottom=22)
    assert asyncio.run(p.screenshot(window=None, region=r)) == b"png"   # protocol form
    assert asyncio.run(p.screenshot(r)) == b"png"                       # legacy positional
    assert seen[0] == seen[1] == {"x": 1, "y": 2, "width": 10, "height": 20}


def test_set_text_that_did_not_stick_uses_the_fallback_and_skips_enter(monkeypatch):
    from ufo.automator.ui_control import controller as ctl

    class Ctrl:
        iface_value = None

        def window_text(self):
            return ""                                # the text never arrived

        def set_text(self, text):
            pass

    r = ctl.ControlReceiver.__new__(ctl.ControlReceiver)
    r.control = Ctrl()
    calls = []

    def atomic(name, params):
        calls.append((name, params.get("keys") if isinstance(params, dict) else None))
        return "ok"

    r.atomic_execution = atomic
    monkeypatch.setattr(ctl.ufo_config.system, "input_text_api", "set_text", raising=False)
    monkeypatch.setattr(ctl.ufo_config.system, "input_text_enter", True, raising=False)
    monkeypatch.setattr(ctl.ufo_config.system, "input_text_inter_key_pause", 0.0, raising=False)
    r.set_edit_text({"text": "hello"})
    names = [c[0] for c in calls]
    assert names[0] == "set_text"
    assert names[1] == "type_keys" and "hello" in (calls[1][1] or "")  # keystroke fallback ran
    assert ("type_keys", "{ENTER}") not in calls                       # no Enter on an empty field
