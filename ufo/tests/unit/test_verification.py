"""Deterministic goal checks: request -> checks planning, check semantics, and
HostAgent using them before (instead of) the LLM verifier."""
import asyncio
import os
import time
from types import SimpleNamespace

import pytest

from ufo.verification import checks, registry
from ufo.verification.checks import CheckResult


def _plan(request):
    planned, uncovered = registry.plan_checks(request)
    return [p.description for p in planned], uncovered


@pytest.mark.parametrize(
    "request_text, descriptions, uncovered",
    [
        ("Open Notepad", ["notepad running"], []),
        ("Open notepad and type 'hello world' and save it as notes.txt on the desktop",
         ["notepad running", "notepad text", "file notes.txt"], []),
        ('Type "Quarterly report" in Word', ["word text"], []),
        ("open notepad, type 'a, b and c', then save as C:/temp/x.txt",
         ["notepad running", "notepad text", "file C:/temp/x.txt"], []),
        ('Save the document as "My Report.docx"', ["file My Report.docx"], []),
        ("Open Word and make the title bold", ["word running"], ["make the title bold"]),
        ("Launch chrome to search for cats", ["chrome running"], ["Launch chrome to search for cats"]),
        ("What's the weather today?", [], ["What's the weather today?"]),
    ],
)
def test_plan_checks(request_text, descriptions, uncovered):
    assert _plan(request_text) == (descriptions, uncovered)


def test_retry_context_is_ignored_when_planning():
    req = "Open Notepad" + registry.RETRY_MARKER + "\nprevious attempt typed 'junk' and saved as junk.txt"
    assert _plan(req) == (["notepad running"], [])


def test_quoted_apostrophes_are_not_quotes():
    descriptions, _ = _plan("don't close notepad's window")
    assert descriptions == []


def _fake(monkeypatch, **results):
    for name, value in results.items():
        monkeypatch.setattr(checks, name, lambda *a, _v=value, **k: _v)


def test_evaluate_all_pass_is_achieved(monkeypatch):
    _fake(monkeypatch, check_process=CheckResult("notepad running", True, ""),
          check_editor_text=CheckResult("text", True, ""), check_file=CheckResult("file", True, ""))
    ev = registry.evaluate("open notepad and type 'hi' and save it as a.txt")
    assert ev.achieved is True


def test_evaluate_any_fail_is_rejected(monkeypatch):
    _fake(monkeypatch, check_process=CheckResult("notepad running", True, ""),
          check_editor_text=CheckResult("text", True, ""), check_file=CheckResult("file", False, "not found"))
    ev = registry.evaluate("open notepad and type 'hi' and save it as a.txt")
    assert ev.achieved is False and ev.failed[0].detail == "not found"


def test_closed_app_in_multistep_request_is_not_a_failure(monkeypatch):
    _fake(monkeypatch, check_process=CheckResult("notepad running", False, "not running"),
          check_editor_text=CheckResult("text", None, "no control"), check_file=CheckResult("file", True, ""))
    ev = registry.evaluate("open notepad and type 'hi' and save it as a.txt")
    assert ev.achieved is None and not ev.failed


def test_standalone_open_that_did_not_happen_is_rejected(monkeypatch):
    _fake(monkeypatch, check_process=CheckResult("notepad running", False, "not running"))
    assert registry.evaluate("Open Notepad").achieved is False


def test_uncovered_clause_is_inconclusive(monkeypatch):
    _fake(monkeypatch, check_process=CheckResult("word running", True, ""))
    ev = registry.evaluate("Open Word and make the title bold")
    assert ev.achieved is None and "make the title bold" in ev.summary()


def test_broken_probe_is_inconclusive(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("uia exploded")
    monkeypatch.setattr(checks, "check_process", boom)
    ev = registry.evaluate("Open Notepad")
    assert ev.achieved is None and "uia exploded" in ev.summary()


# --- check semantics -----------------------------------------------------------

def test_check_file_found_contains_and_since(tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("Hello   World\n", encoding="utf-8")
    assert checks.check_file(str(f), "hello world").passed is True
    assert checks.check_file(str(f), "goodbye").passed is False
    assert checks.check_file(str(f), since=time.time() + 60).passed is False
    assert checks.check_file(str(tmp_path / "missing.txt")).passed is False


def test_check_file_searches_known_folders(tmp_path, monkeypatch):
    (tmp_path / "report.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(checks, "candidate_dirs", lambda: [tmp_path])
    assert checks.check_file("report.txt").passed is True


def test_check_file_binary_formats_skip_content(tmp_path):
    f = tmp_path / "r.docx"
    f.write_bytes(b"PK\x03\x04zipdata")
    assert checks.check_file(str(f), "some text").passed is True


def test_check_process(monkeypatch):
    monkeypatch.setattr(checks, "running_process_names", lambda: ["Notepad.exe", "explorer.exe"])
    assert checks.check_process(["notepad.exe"]).passed is True
    assert checks.check_process(["WINWORD.EXE"]).passed is False


def test_check_editor_text(monkeypatch):
    monkeypatch.setattr(checks, "_uia_editor_texts", lambda names: ["first tab", "Hello\r\nworld"])
    assert checks.check_editor_text("hello world", ["notepad.exe"]).passed is True
    assert checks.check_editor_text("absent", ["notepad.exe"]).passed is False
    monkeypatch.setattr(checks, "_uia_editor_texts", lambda names: [])
    assert checks.check_editor_text("x", ["notepad.exe"]).passed is None


def test_check_office_text_never_starts_office(monkeypatch):
    monkeypatch.setattr(checks, "_office_text", lambda app: None)  # GetActiveObject failed
    assert checks.check_office_text("word", "x").passed is None
    monkeypatch.setattr(checks, "_office_text", lambda app: "Quarterly  Report")
    assert checks.check_office_text("word", "quarterly report").passed is True


def test_run_with_timeout():
    with pytest.raises(TimeoutError):
        checks._run_with_timeout(lambda: time.sleep(2), timeout=0.2)
    assert checks._run_with_timeout(lambda: "ok", timeout=5) == "ok"


# --- HostAgent integration --------------------------------------------------------

class _Ctx:
    def __init__(self, request):
        self._req = request
        self.command_dispatcher = SimpleNamespace(execute_commands=self._exec)

    async def _exec(self, cmds):
        return [SimpleNamespace(result="data:image/png;base64,AAA")]

    def get(self, key):
        return self._req


def _agent(monkeypatch, llm_reply='{"achieved": true, "confidence": 0.9, "reason": "llm"}'):
    import logging

    from ufo.agents.agent.host_agent import HostAgent

    agent = HostAgent.__new__(HostAgent)
    agent.logger = logging.getLogger("t")
    agent.status = "FINISH"
    agent.processor = SimpleNamespace(processing_context=SimpleNamespace(get_local=lambda k: None))
    questions, llm_calls = [], []
    monkeypatch.setattr(HostAgent, "blackboard", property(lambda self: SimpleNamespace(add_questions=questions.append)))

    async def get_response(messages, namescope=None, use_backup_engine=True):
        llm_calls.append(messages)
        return SimpleNamespace(responses=[llm_reply])
    agent.get_response = get_response
    return agent, questions, llm_calls


def test_host_deterministic_fail_reopens_without_llm(monkeypatch):
    monkeypatch.setattr(checks, "check_file", lambda *a, **k: CheckResult("file 'a.txt'", False, "not found"))
    agent, questions, llm_calls = _agent(monkeypatch)
    asyncio.run(agent._verify_goal_before_finish(_Ctx("save it as a.txt")))
    assert agent.status == "CONTINUE" and not llm_calls
    assert "not found" in questions[0]["answer"]
    assert agent.last_goal_verdict.confidence == 1.0


def test_host_deterministic_pass_skips_llm(monkeypatch):
    monkeypatch.setattr(checks, "check_file", lambda *a, **k: CheckResult("file", True, "ok"))
    agent, questions, llm_calls = _agent(monkeypatch)
    asyncio.run(agent._verify_goal_before_finish(_Ctx("save it as a.txt")))
    assert agent.status == "FINISH" and not llm_calls and agent.last_goal_verdict.achieved is True


def test_host_inconclusive_checks_go_to_llm_as_evidence(monkeypatch):
    monkeypatch.setattr(checks, "check_process", lambda *a, **k: CheckResult("word running", True, "WINWORD.EXE"))
    agent, _, llm_calls = _agent(monkeypatch)
    asyncio.run(agent._verify_goal_before_finish(_Ctx("Open Word and make the title bold")))
    assert len(llm_calls) == 1
    user_text = llm_calls[0][1]["content"][0]["text"]
    assert "AUTOMATED CHECKS" in user_text and "[PASS] word running" in user_text


def test_host_keeps_negative_verdict_after_rejection_limit(monkeypatch):
    from ufo.agents.processors.strategies import goal_verifier as gv

    monkeypatch.setattr(checks, "check_file", lambda *a, **k: CheckResult("file", False, "missing"))
    agent, _, _ = _agent(monkeypatch)
    for _ in range(gv.GOAL_VERIFY_MAX_REJECTIONS):
        agent.status = "FINISH"
        asyncio.run(agent._verify_goal_before_finish(_Ctx("save as a.txt")))
        assert agent.status == "CONTINUE"
    agent.status = "FINISH"
    asyncio.run(agent._verify_goal_before_finish(_Ctx("save as a.txt")))
    assert agent.status == "FINISH" and agent.last_goal_verdict.achieved is False
