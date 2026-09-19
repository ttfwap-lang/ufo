import asyncio
from types import SimpleNamespace

import pytest
from PIL import Image

from ufo.automator.ui_control.grounding import venus


@pytest.mark.parametrize("text,expected", [
    ("[429, 85]", (429.0, 85.0)),
    ("[100,200,300,400]", (200.0, 300.0)),
    ("[10, 20], [30, 40]", (20.0, 30.0)),
    ("[-1,-1]", None),
    ("[-1,-1,-1,-1]", None),
    ("I cannot find it", None),
    ("", None),
])
def test_extract_point(text, expected):
    assert venus.extract_point(text) == expected


class _FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls += 1
        assert kw["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
        assert kw["temperature"] == 0
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.replies.pop(0)))])


@pytest.fixture
def shot(tmp_path):
    p = tmp_path / "w.png"
    Image.new("RGB", (400, 300), "white").save(p)
    return str(p)


def test_confirmed_point_is_returned_as_fraction(shot):
    g = venus.VenusGrounder("x", client=_FakeClient(["[500, 250]", "yes"]))
    r = g.locate(shot, "the OK button")
    assert (r.fx, r.fy, r.confirmed) == (0.5, 0.25, True)


def test_unconfirmed_point_is_rejected(shot):
    g = venus.VenusGrounder("x", client=_FakeClient(["[914, 87]", "no"]))
    assert g.locate(shot, "the Send email button") is None


def test_infeasible_skips_confirmation(shot):
    c = _FakeClient(["[-1,-1]"])
    assert venus.VenusGrounder("x", client=c).locate(shot, "missing") is None
    assert c.calls == 1


def test_results_are_cached_per_image_and_description(shot):
    c = _FakeClient(["[500, 250]", "yes"])
    g = venus.VenusGrounder("x", client=c)
    g.locate(shot, "the OK button")
    g.locate(shot, "The OK button ")
    assert c.calls == 2


def test_coordinates_are_clamped(shot):
    r = venus.VenusGrounder("x", client=_FakeClient(["[1200, 999]", "yes"])).locate(shot, "edge")
    assert r.fx == 1.0 and r.fy == 0.999


def test_get_grounder_disabled_configs():
    venus._grounder = None
    assert venus.get_grounder(None) is None
    assert venus.get_grounder({"ENABLED": False, "ENDPOINT": "http://x"}) is None
    assert venus.get_grounder({"ENABLED": True, "ENDPOINT": ""}) is None


def test_confirmation_crop_marks_point(shot):
    img = Image.open(shot).convert("RGB")
    crop = venus.confirmation_crop(img, 0.5, 0.5)
    assert crop.size == (220, 220)
    assert (255, 0, 0) in [crop.getpixel((110 + dx, 110)) for dx in range(-8, 9)]


def test_click_on_description_tool_clicks_confirmed_point(monkeypatch, tmp_path):
    from fastmcp import Client
    from ufo.client.mcp.local_servers import ui_mcp_server as m

    class _Grounder:
        def locate(self, path, desc):
            return venus.GroundingResult(0.25, 0.75, "[250,750]", True) if "Bold" in desc else None

    monkeypatch.setattr(m, "get_grounder", lambda cfg: _Grounder())
    state = m.UIServerState()
    monkeypatch.setattr(state, "selected_app_window", object(), raising=False)
    monkeypatch.setattr(state, "puppeteer", object(), raising=False)
    monkeypatch.setattr(state.photographer, "capture_app_window_screenshot", lambda w, save_path=None: Image.new("RGB", (10, 10)).save(save_path))
    executed = []
    monkeypatch.setattr(m.ActionExecutor, "execute", lambda self, action, *a, **k: executed.append(action) or "ok")

    async def run():
        async with Client(m.create_app_action_mcp_server()) as c:
            ok = await c.call_tool("click_on_description", {"description": "the Bold button"})
            with pytest.raises(Exception):
                await c.call_tool("click_on_description", {"description": "the Send email button"})
            return ok
    ok = asyncio.run(run())
    assert "0.250" in ok.content[0].text
    assert len(executed) == 1
    assert executed[0].function == "click_on_coordinates"
    assert executed[0].arguments["x"] == 0.25 and executed[0].arguments["y"] == 0.75


def test_click_fallback_never_clicks_a_guess(monkeypatch):
    from ufo.automator.ui_control import controller as ctl
    rc = ctl.ControlReceiver.__new__(ctl.ControlReceiver)
    rc.control = SimpleNamespace(element_info=SimpleNamespace(name="Frobnicate", control_type="Button"))
    rc.application = SimpleNamespace(rectangle=lambda: SimpleNamespace(left=0, top=0, width=lambda: 100, height=lambda: 100))
    import pyautogui
    monkeypatch.setattr(pyautogui, "screenshot", lambda path, region=None: Image.new("RGB", (100, 100)).save(path))
    from ufo.automator.ui_control.grounding import omniparser as om
    monkeypatch.setattr(om.OmniparserGrounding, "predict", lambda self, *a, **k: [{"bbox": [0.1, 0.1, 0.2, 0.2], "content": "Unrelated", "interactivity": True}])
    monkeypatch.setattr(ctl.ufo_config.system, "omniparser", {"ENDPOINT": "http://x"}, raising=False)
    import ufo.llm.grounding_model.omniparser_service as svc
    monkeypatch.setattr(svc, "get_omniparser", lambda e: object())
    monkeypatch.setattr(venus, "get_grounder", lambda cfg: None)
    assert rc._vision_fallback_point() is None


def test_missing_control_hint_mentions_click_on_description():
    from ufo.agents.processors.strategies.response_checks import app_response_problems
    act = SimpleNamespace(function="click_input", arguments={"id": "99", "name": "x"})
    p = app_response_problems([act], "CONTINUE", {"1"}, {"click_input", "click_on_description"})
    assert "click_on_description" in p[0]
