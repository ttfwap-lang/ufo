"""Retry-until-verified: sequential attempts, outcome assessment, narratives."""
import asyncio
import json
from types import SimpleNamespace

from ufo.agents.processors.strategies.goal_verifier import GoalVerdict
from ufo.module import attempts
from ufo.verification.registry import RETRY_MARKER, original_request


def _session(log_path="", error=False, status="FINISH", verdict=None):
    host = SimpleNamespace(status=status, last_goal_verdict=verdict)
    return SimpleNamespace(is_error=lambda: error, host_agent=host, log_path=log_path)


def test_assess():
    assert attempts.assess(_session(error=True), "t").success is False
    assert attempts.assess(_session(verdict=GoalVerdict(False, 1.0, "file missing", "save a.txt")), "t").reason == \
        "file missing Still missing: save a.txt"
    assert attempts.assess(_session(status="CONTINUE"), "t").success is False
    assert attempts.assess(_session(verdict=GoalVerdict(True, 1.0, "ok")), "t").success is True
    # Unverifiable (no verdict) but finished: accept, never risk a duplicate run.
    assert attempts.assess(_session(status="FINISH"), "t").success is True
    # A low-confidence "no" still counts as failed for the session outcome.
    assert attempts.assess(_session(verdict=GoalVerdict(False, 0.3, "unsure")), "t").success is False


def _write_log(tmp_path):
    records = [
        {"agent_name": "HostAgent", "action": [{"function": "run_shell", "action_string": "run_shell(bash_command='start notepad')",
                                                  "result": {"status": "success", "error": None}}]},
        {"agent_name": "AppAgent/notepad", "action": [
            {"function": "type_text", "action_string": "type_text(text='hello')", "result": {"status": "success"}},
            {"function": "click_input", "action_string": "click_input(id='12')", "result": {"status": "failure", "error": "control gone"}},
            {"function": "", "result": {}},
        ]},
    ]
    (tmp_path / "response.log").write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return str(tmp_path)


def test_behaviour_narrative(tmp_path):
    text = attempts.behaviour_narrative(_write_log(tmp_path))
    assert text.splitlines() == [
        "- HostAgent: run_shell(bash_command='start notepad') -> success",
        "- AppAgent/notepad: type_text(text='hello') -> success",
        "- AppAgent/notepad: click_input(id='12') -> failure (control gone)",
    ]
    assert attempts.behaviour_narrative(str(tmp_path / "missing")) == ""


def test_retry_request_keeps_original_and_is_not_nested(tmp_path):
    prev = attempts.AttemptOutcome("t", False, "file missing", _write_log(tmp_path))
    first = attempts.build_retry_request("save as a.txt", prev)
    second = attempts.build_retry_request(first, prev)
    assert first.startswith("save as a.txt" + RETRY_MARKER)
    assert "type_text(text='hello') -> success" in first and "Do not repeat" in first
    assert second.count(RETRY_MARKER) == 1 and original_request(second) == "save as a.txt"


def test_run_until_verified_stops_at_first_success(tmp_path):
    calls = []
    script = [_session(str(tmp_path), verdict=GoalVerdict(False, 1.0, "nope")), _session(verdict=GoalVerdict(True, 1.0, "ok"))]

    async def run_attempt(name, request):
        calls.append((name, request))
        return script[len(calls) - 1]

    outcomes = asyncio.run(attempts.run_until_verified("task", "do it", run_attempt, max_attempts=3))
    assert [c[0] for c in calls] == ["task", "task_try2"]
    assert calls[0][1] == "do it" and RETRY_MARKER in calls[1][1] and "nope" in calls[1][1]
    assert [o.success for o in outcomes] == [False, True]


def test_run_until_verified_respects_budget():
    calls = []

    async def run_attempt(name, request):
        calls.append(name)
        return _session(error=True)

    outcomes = asyncio.run(attempts.run_until_verified("t", "x", run_attempt, max_attempts=2))
    assert calls == ["t", "t_try2"] and not any(o.success for o in outcomes)
    assert attempts.outcomes_as_dicts(outcomes)[0]["task"] == "t"


def test_single_attempt_budget():
    calls = []

    async def run_attempt(name, request):
        calls.append(name)
        return _session(error=True)

    asyncio.run(attempts.run_until_verified("t", "x", run_attempt, max_attempts=1))
    assert calls == ["t"]
