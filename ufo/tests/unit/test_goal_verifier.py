import asyncio
from types import SimpleNamespace

import pytest

from ufo.agents.processors.strategies import goal_verifier as gv


def test_parse_confident_rejection():
    v = gv.parse_verdict('{"achieved": false, "confidence": 0.9, "reason": "file not saved", "missing": "save"}')
    assert v.achieved is False and v.rejects and v.missing == "save"


def test_low_confidence_no_does_not_reject():
    assert not gv.parse_verdict('{"achieved": false, "confidence": 0.3}').rejects


def test_garbage_is_unverified_not_rejected():
    for text in ("", "sure thing", "{not json}", '{"achieved": "maybe", "confidence": 1}'):
        v = gv.parse_verdict(text)
        assert v.achieved is None and not v.rejects


def test_string_booleans_accepted():
    assert gv.parse_verdict('```json\n{"achieved": "yes", "confidence": "0.8"}\n```').achieved is True


def test_model_failure_never_blocks_finish():
    async def boom(_):
        raise RuntimeError("model down")
    v = asyncio.run(gv.verify_goal("do x", "", None, boom))
    assert v.achieved is None and not v.rejects


def test_messages_include_request_and_screenshot():
    msgs = gv.build_messages("rename file", "renamed", "data:image/png;base64,AAA")
    user = msgs[1]["content"]
    assert "rename file" in user[0]["text"] and user[1]["image_url"]["url"].startswith("data:image/")


# --- HostAgent integration --------------------------------------------------

class _Ctx:
    def __init__(self, request):
        self._req = request
        self.command_dispatcher = SimpleNamespace(execute_commands=self._exec)

    async def _exec(self, cmds):
        return [SimpleNamespace(result="data:image/png;base64,AAA")]

    def get(self, key):
        return self._req


def _agent(reply, monkeypatch):
    from ufo.agents.agent.host_agent import HostAgent

    agent = HostAgent.__new__(HostAgent)
    import logging
    agent.logger = logging.getLogger("t")
    agent.status = "FINISH"
    locals_ = {"result": "done", "host_message": []}
    agent.processor = SimpleNamespace(processing_context=SimpleNamespace(get_local=lambda k: locals_.get(k)))
    questions = []
    agent._blackboard = None
    monkeypatch.setattr(HostAgent, "blackboard", property(lambda self: SimpleNamespace(add_questions=questions.append)))

    async def get_response(messages, namescope=None, use_backup_engine=True):
        return SimpleNamespace(responses=[reply])
    agent.get_response = get_response
    return agent, questions


def test_host_agent_reopens_task_on_confident_no(monkeypatch):
    agent, questions = _agent('{"achieved": false, "confidence": 0.95, "reason": "nothing typed", "missing": "type text"}', monkeypatch)
    asyncio.run(agent._verify_goal_before_finish(_Ctx("type hi")))
    assert agent.status == "CONTINUE"
    assert questions and "type text" in questions[0]["answer"]


def test_host_agent_keeps_finish_when_achieved(monkeypatch):
    agent, questions = _agent('{"achieved": true, "confidence": 0.9, "reason": "ok"}', monkeypatch)
    asyncio.run(agent._verify_goal_before_finish(_Ctx("type hi")))
    assert agent.status == "FINISH" and not questions


def test_rejection_limit_prevents_infinite_loop(monkeypatch):
    agent, _ = _agent('{"achieved": false, "confidence": 0.99, "reason": "no"}', monkeypatch)
    for _ in range(gv.GOAL_VERIFY_MAX_REJECTIONS):
        agent.status = "FINISH"
        asyncio.run(agent._verify_goal_before_finish(_Ctx("x")))
        assert agent.status == "CONTINUE"
    agent.status = "FINISH"
    asyncio.run(agent._verify_goal_before_finish(_Ctx("x")))
    assert agent.status == "FINISH"
