"""Tests for the standalone gx10 BrowserAct navigation boundary."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

GX10_DIR = Path(__file__).resolve().parents[2] / "gx10_runner"
if str(GX10_DIR) not in sys.path:
    sys.path.insert(0, str(GX10_DIR))

import agent_runner  # noqa: E402
from browseract_navigation import BrowserActError, BrowserActNavigator, is_mutation  # noqa: E402


class _Completed:
    def __init__(self, payload, returncode=0, stderr=""):
        self.returncode = returncode
        self.stdout = json.dumps(payload)
        self.stderr = stderr


class _FakeCLI:
    def __init__(self):
        self.calls = []
        self.states = 0

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        args = list(argv[3:])
        if args[:1] == ["--session"]:
            args = args[2:]
        if args[:2] == ["browser", "open"]:
            return _Completed({"ok": True, "opened": args[3]})
        if args == ["state"]:
            self.states += 1
            return _Completed({"ok": True, "state": {"index": self.states}})
        if args[:2] == ["session", "close"]:
            return _Completed({"ok": True, "closed": args[-1]})
        if args[:1] == ["get"]:
            return _Completed({"ok": True, "result": {"kind": args[1]}})
        return _Completed({"ok": True, "result": args})

    def find(self, prefix):
        for argv, _kwargs in self.calls:
            args = list(argv[3:])
            if args[:1] == ["--session"]:
                args = args[2:]
            if args[: len(prefix)] == prefix:
                return args
        raise AssertionError(f"command {prefix!r} not found in {self.calls!r}")


def _navigator(fake):
    return BrowserActNavigator(
        cli_path=sys.executable,
        browser_id="browser-1",
        runner=fake,
        allow_private_networks=False,
    )


def test_open_state_mutation_refresh_and_close_are_fixed_argv():
    fake = _FakeCLI()
    navigator = _navigator(fake)

    opened = json.loads(navigator.execute({"action": "open", "url": "https://8.8.8.8"}))
    assert opened["ok"] is True
    assert opened["session"].startswith("ufo-gx10-")
    assert opened["state_token"]

    clicked = json.loads(
        navigator.execute(
            {
                "action": "click",
                "session": opened["session"],
                "state_token": opened["state_token"],
                "selector": "button.go",
            }
        )
    )
    assert clicked["state_token"] != opened["state_token"]
    assert fake.find(["click", "--selector", "button.go"])
    assert fake.calls[0][1]["shell"] is False

    closed = json.loads(navigator.close())
    assert closed["ok"] is True
    assert navigator.session is None


def test_selector_input_uses_selector_flags_and_bounds_text():
    fake = _FakeCLI()
    navigator = _navigator(fake)
    opened = json.loads(navigator.execute({"action": "open", "url": "https://8.8.8.8"}))

    navigator.execute(
        {
            "action": "input",
            "session": opened["session"],
            "state_token": opened["state_token"],
            "selector": "input[name=email]",
            "text": "person@example.com",
        }
    )
    assert fake.find(["input", "--selector", "input[name=email]", "--text", "person@example.com", "--mode", "fill"])

    opened = json.loads(navigator.execute({"action": "state", "session": opened["session"]}))
    navigator.max_input_chars = 5
    with pytest.raises(BrowserActError, match="exceeds"):
        navigator.execute(
            {
                "action": "input",
                "session": opened["session"],
                "state_token": opened["state_token"],
                "index": 1,
                "text": "x" * 20,
            }
        )


def test_stale_token_and_timeout_prevent_blind_mutation_retry():
    fake = _FakeCLI()
    navigator = _navigator(fake)
    opened = json.loads(navigator.execute({"action": "open", "url": "https://8.8.8.8"}))
    stale = opened["state_token"]
    fresh = json.loads(
        navigator.execute(
            {
                "action": "click",
                "session": opened["session"],
                "state_token": stale,
                "index": 1,
            }
        )
    )
    assert fresh["state_token"] != stale

    with pytest.raises(BrowserActError, match="Stale"):
        navigator.execute(
            {
                "action": "click",
                "session": opened["session"],
                "state_token": stale,
                "index": 1,
            }
        )

    def timeout_runner(argv, **kwargs):
        if "--session" in argv and "click" in argv:
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        return fake(argv, **kwargs)

    navigator._runner = timeout_runner
    with pytest.raises(BrowserActError, match="do not blindly retry"):
        navigator.execute(
            {
                "action": "click",
                "session": opened["session"],
                "state_token": fresh["state_token"],
                "index": 1,
            }
        )
    assert navigator.state_token is None


def test_browseract_url_policy_and_action_classification():
    navigator = BrowserActNavigator(cli_path=sys.executable, runner=_FakeCLI())
    with pytest.raises(BrowserActError, match="http/https"):
        navigator.execute({"action": "open", "url": "javascript:alert(1)"})
    with pytest.raises(BrowserActError, match="Private/local"):
        navigator.execute({"action": "open", "url": "http://127.0.0.1:8000"})

    assert is_mutation("open") is True
    assert is_mutation("scroll-into-view") is True
    assert is_mutation("state") is False
    assert is_mutation("get") is False


def test_native_agent_executes_only_one_browseract_mutation_per_response(monkeypatch):
    calls = []
    responses = [
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "one",
                                "function": {
                                    "name": "browser_action",
                                    "arguments": '{"action":"click","index":1}',
                                },
                            },
                            {
                                "id": "two",
                                "function": {
                                    "name": "browser_action",
                                    "arguments": '{"action":"input","index":1,"text":"x"}',
                                },
                            },
                        ]
                    }
                }
            ]
        },
        {"choices": [{"message": {"content": "finished"}}]},
    ]

    monkeypatch.setattr(agent_runner, "llm_chat", lambda _messages: responses.pop(0))
    monkeypatch.setitem(agent_runner.TOOL_IMPLS, "browser_action", lambda args: calls.append(args) or "ok")
    agent_runner.HISTORY.clear()

    assert agent_runner.agent(7, "navigate") == "finished"
    assert calls == [{"action": "click", "index": 1}]


def test_native_agent_cleanup_closes_owned_navigator(monkeypatch):
    class Navigator:
        session = "owned"

        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    navigator = Navigator()
    monkeypatch.setattr(agent_runner, "_BROWSERACT_NAVIGATOR", navigator)
    agent_runner.close_browseract_session()
    assert navigator.closed is True
    assert agent_runner._BROWSERACT_NAVIGATOR is None


def test_failed_state_invalidates_token_and_close_retains_ambiguous_ownership():
    fake = _FakeCLI()
    navigator = _navigator(fake)
    opened = json.loads(navigator.execute({"action": "open", "url": "https://8.8.8.8"}))
    original_token = opened["state_token"]
    assert original_token

    def fail_state(argv, **kwargs):
        args = list(argv[3:])
        if args[:1] == ["--session"]:
            args = args[2:]
        if args == ["state"] and fake.states >= 1:
            return _Completed({"ok": False, "error": "state unavailable"}, returncode=1)
        return fake(argv, **kwargs)

    navigator._runner = fail_state
    with pytest.raises(BrowserActError, match="state unavailable"):
        navigator.execute({"action": "state", "session": opened["session"]})
    assert navigator.state_token is None

    def fail_close(argv, **kwargs):
        args = list(argv[3:])
        if args[:1] == ["--session"]:
            args = args[2:]
        if args[:2] == ["session", "close"]:
            return _Completed({"ok": False, "error": "network unavailable"}, returncode=1)
        return fake(argv, **kwargs)

    navigator._runner = fail_close
    close_result = json.loads(navigator.close())
    assert close_result["ok"] is False
    assert navigator.session == opened["session"]


def test_get_dispatches_only_valid_browseract_arguments():
    fake = _FakeCLI()
    navigator = _navigator(fake)
    opened = json.loads(navigator.execute({"action": "open", "url": "https://8.8.8.8"}))
    session = opened["session"]
    navigator.execute({"action": "get", "session": session, "kind": "html", "selector": "main"})
    assert fake.find(["get", "html", "--selector", "main"])
    navigator.execute({"action": "get", "session": session, "kind": "markdown", "index": 2})
    assert fake.find(["get", "markdown", "2"])
    with pytest.raises(BrowserActError, match="does not accept"):
        navigator.execute({"action": "get", "session": session, "kind": "title", "index": 1})


def test_option_like_model_values_cannot_be_reparsed_as_browseract_globals():
    fake = _FakeCLI()
    navigator = _navigator(fake)
    opened = json.loads(navigator.execute({"action": "open", "url": "https://8.8.8.8"}))
    with pytest.raises(BrowserActError, match="option marker"):
        navigator.execute(
            {
                "action": "input",
                "session": opened["session"],
                "state_token": opened["state_token"],
                "index": 1,
                "text": "--session",
            }
        )
    with pytest.raises(BrowserActError, match="option marker"):
        navigator.execute(
            {
                "action": "click",
                "session": opened["session"],
                "state_token": opened["state_token"],
                "selector": "--format",
            }
        )


def test_second_open_is_refused_and_wait_gets_outer_timeout():
    fake = _FakeCLI()
    navigator = _navigator(fake)
    navigator.execute({"action": "open", "url": "https://8.8.8.8"})
    with pytest.raises(BrowserActError, match="already open"):
        navigator.execute({"action": "open", "url": "https://8.8.8.8"})

    fake = _FakeCLI()
    navigator = _navigator(fake)
    opened = json.loads(navigator.execute({"action": "open", "url": "https://8.8.8.8"}))
    navigator.execute(
        {
            "action": "wait",
            "session": opened["session"],
            "timeout_ms": 120000,
        }
    )
    wait_call = next(
        (argv, kwargs)
        for argv, kwargs in fake.calls
        if len(argv) > 3 and argv[-3] == "stable"
    )
    assert wait_call[1]["timeout"] == 150


def test_model_tool_surface_has_no_shell_and_host_status_is_fixed(monkeypatch):
    assert "shell" not in agent_runner.TOOL_IMPLS
    assert all(tool["function"]["name"] != "shell" for tool in agent_runner.TOOLS_SCHEMA)
    calls = []
    monkeypatch.setattr(agent_runner.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)) or type("R", (), {"stdout": "ok", "stderr": ""})())
    assert "Blocked" in agent_runner.run_shell(["cat", "/app/ufo_bridge_token.txt"])
    assert "Blocked" in agent_runner.run_shell(["curl", "https://example.com"])
    assert calls == []
    assert "host_status" in agent_runner.TOOL_IMPLS
