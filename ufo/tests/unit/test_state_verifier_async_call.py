import asyncio
from types import SimpleNamespace

from PIL import Image

from ufo.agents.evaluation_agent import state_verifier as sv


def _fake(monkeypatch):
    async def fake_completion(messages, agent=None, use_backup_engine=True):
        return SimpleNamespace(responses=['{"success": true, "observed_state": "ok", "confidence": 0.9, "error_reason": ""}'])
    import ufo.llm.llm_call as lc
    monkeypatch.setattr(lc, "get_completion", fake_completion)


def _shots(tmp_path):
    for n in ("a.png", "b.png"):
        Image.new("RGB", (32, 32), "white").save(tmp_path / n)
    return str(tmp_path / "a.png"), str(tmp_path / "b.png")


def _verifier():
    v = sv.StateVerifier.__new__(sv.StateVerifier)
    return v


def test_vlm_verify_outside_event_loop(tmp_path, monkeypatch):
    _fake(monkeypatch)
    a, b = _shots(tmp_path)
    r = _verifier().verify_action_success(SimpleNamespace(description="d"), a, b, "intent")
    assert r.success is True, r


def test_vlm_verify_inside_running_loop(tmp_path, monkeypatch):
    _fake(monkeypatch)
    a, b = _shots(tmp_path)

    async def inside():
        return _verifier().verify_action_success(SimpleNamespace(description="d"), a, b, "intent")
    assert asyncio.run(inside()).success is True
