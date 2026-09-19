import asyncio
from types import SimpleNamespace

import pytest
import yaml

from ufo.agents.processors.schemas.actions import ActionCommandInfo
from ufo.agents.processors.strategies import app_agent_processing_strategy as m
from ufo.aip.messages import Result, ResultStatus


class _Dispatcher:
    def __init__(self, unstable_after=None, fail_on=None):
        self.ran = []
        self.unstable_after = unstable_after
        self.fail_on = fail_on

    async def execute_commands(self, cmds):
        cmd = cmds[0]
        if cmd.tool_name == "check_ui_stable":
            ok = self.unstable_after is None or len(self.ran) < self.unstable_after
            return [Result(status=ResultStatus.SUCCESS, result={"stable": ok, "reason": "" if ok else "dialog opened"})]
        self.ran.append(cmd.tool_name + ":" + str(cmd.parameters.get("id")))
        if self.fail_on and cmd.parameters.get("id") == self.fail_on:
            return [Result(status=ResultStatus.FAILURE, error="boom")]
        return [Result(status=ResultStatus.SUCCESS, result="ok")]


def _strategy():
    s = m.AppActionExecutionStrategy.__new__(m.AppActionExecutionStrategy)
    import logging
    s.logger = logging.getLogger("t")
    return s


def _acts(*ids):
    return [ActionCommandInfo(function="click_input", arguments={"id": i, "name": "n"}) for i in ids]


def test_all_actions_run_when_ui_is_stable():
    d = _Dispatcher()
    r = asyncio.run(_strategy()._execute_app_action(d, _acts("1", "2", "3")))
    assert d.ran == ["click_input:1", "click_input:2", "click_input:3"]
    assert [x.status for x in r] == [ResultStatus.SUCCESS] * 3


def test_remaining_actions_skipped_when_ui_changes():
    d = _Dispatcher(unstable_after=1)
    r = asyncio.run(_strategy()._execute_app_action(d, _acts("1", "2", "3")))
    assert d.ran == ["click_input:1"]
    assert [x.status for x in r] == [ResultStatus.SUCCESS, ResultStatus.SKIPPED, ResultStatus.SKIPPED]
    assert "dialog opened" in r[1].error


def test_failure_skips_the_rest():
    d = _Dispatcher(fail_on="2")
    r = asyncio.run(_strategy()._execute_app_action(d, _acts("1", "2", "3")))
    assert d.ran == ["click_input:1", "click_input:2"]
    assert r[2].status == ResultStatus.SKIPPED


def test_cap_and_alignment_with_empty_actions():
    d = _Dispatcher()
    acts = _acts("1", "2") + [ActionCommandInfo(function="", arguments={})] + _acts("3", "4", "5")
    r = asyncio.run(_strategy()._execute_app_action(d, acts))
    assert len(r) == len(acts)
    assert len(d.ran) == m.MAX_ACTIONS_PER_STEP
    assert r[2].status == ResultStatus.SKIPPED and r[-1].status == ResultStatus.SKIPPED


def test_prompt_has_multi_action_variant_with_examples():
    from pathlib import Path
    d = yaml.safe_load((Path(__file__).resolve().parents[2] / "prompts" / "share" / "base" / "app_agent.yaml").read_text(encoding="utf-8"))
    for key in ("system", "system_nonvisual", "system_as"):
        text = d[key].format(apis="APIS", examples="EXAMPLES")
        assert "APIS" in text and "EXAMPLES" in text and "COMPLETION RULE" in text


def test_ollama_app_schema_uses_action_list():
    from ufo.llm.ollama import OllamaService
    svc = OllamaService.__new__(OllamaService)
    svc.agent_type = "APP_AGENT"
    schema = svc._response_format()["json_schema"]["schema"]
    assert schema["properties"]["action"]["type"] == "array"
    assert schema["properties"]["action"]["maxItems"] == 4
    assert "action" in schema["required"]


def test_check_ui_stable(monkeypatch):
    from ufo.client.mcp.local_servers import ui_mcp_server as ui
    import win32gui

    class _Ctl:
        def __init__(self, rect, visible=True):
            self._rect, self._visible = rect, visible
            self.element_info = object()

        def is_visible(self):
            return self._visible

        def rectangle(self):
            l, t, r, b = self._rect
            return SimpleNamespace(left=l, top=t, right=r, bottom=b)

    state = ui.UIServerState()
    monkeypatch.setattr(state, "selected_app_window", SimpleNamespace(handle=42), raising=False)
    ctl = _Ctl((0, 0, 10, 10))
    monkeypatch.setattr(state, "control_dict", {"5": ctl}, raising=False)
    monkeypatch.setattr(state, "control_rects", {"5": (0, 0, 10, 10)}, raising=False)
    monkeypatch.setattr(win32gui, "GetForegroundWindow", lambda: 42)
    from fastmcp import Client

    async def check(cid):
        async with Client(ui.create_data_mcp_server()) as c:
            r = await c.call_tool("check_ui_stable", {"control_id": cid})
            import json
            return json.loads(r.content[0].text)
    assert asyncio.run(check("5"))["stable"] is True
    assert asyncio.run(check("9"))["stable"] is False
    ctl._rect = (5, 5, 15, 15)
    assert "moved" in asyncio.run(check("5"))["reason"]
    monkeypatch.setattr(win32gui, "GetForegroundWindow", lambda: 7)
    assert "front" in asyncio.run(check("5"))["reason"]
