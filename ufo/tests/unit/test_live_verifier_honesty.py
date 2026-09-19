"""The per-step verifier must not invent success, and must not send blind undo keys."""
import asyncio
from types import SimpleNamespace

from PIL import Image

from ufo.agents.processors.schemas.verification_schema import ActionVerificationRequest, VerificationStatus
from ufo.agents.processors.strategies import live_verification_strategy as lv


def _req(tmp_path):
    for n in ("pre.png", "post.png"):
        Image.new("RGB", (64, 64), "white").save(tmp_path / n)
    return ActionVerificationRequest(step_id=1, subtask="s", intended_action="a", target_control_info={},
                                     pre_screenshot_path=str(tmp_path / "pre.png"), post_screenshot_path=str(tmp_path / "post.png"))


def _agent(reply):
    async def get_response(*a, **k):
        return SimpleNamespace(responses=[reply])
    return SimpleNamespace(get_response=get_response)


def test_no_model_is_reported_as_unverified(tmp_path):
    r = asyncio.run(lv.LiveVisualVerifier().verify(_req(tmp_path), None))
    assert r.confidence_score == 0.0 and r.status == VerificationStatus.CAPTURE_FAILED


def test_action_shaped_reply_is_not_treated_as_verified(tmp_path):
    r = asyncio.run(lv.LiveVisualVerifier().verify(_req(tmp_path), _agent('{"function": "click_input", "arguments": {}}')))
    assert r.confidence_score == 0.0 and r.status == VerificationStatus.CAPTURE_FAILED


def test_real_failure_is_reported(tmp_path):
    r = asyncio.run(lv.LiveVisualVerifier().verify(_req(tmp_path), _agent('{"verified": false, "confidence_score": 0.9, "status": "no_visible_change"}')))
    assert r.verified is False and r.status == VerificationStatus.NO_VISIBLE_CHANGE


def test_verifier_requests_plain_json_not_agent_schema(tmp_path):
    from ufo.llm import response_format_override
    seen = {}

    async def get_response(*a, **k):
        seen["fmt"] = response_format_override.current()
        return SimpleNamespace(responses=['{"verified": true, "confidence_score": 0.8}'])
    asyncio.run(lv.LiveVisualVerifier().verify(_req(tmp_path), SimpleNamespace(get_response=get_response)))
    assert seen["fmt"] == {"type": "json_object"}
    assert response_format_override.current() is None


def test_strategy_source_has_no_blind_undo():
    import inspect
    src = inspect.getsource(lv.AppLiveVisualVerificationStrategy)
    assert "pyautogui" not in src and "ctrl', 'z" not in src
