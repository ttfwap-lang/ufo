"""Tests for the constrained BrowserAct MCP/session layer."""

from __future__ import annotations

import asyncio
import json
import sys

import pytest

from ufo.client.mcp.local_servers.browseract_mcp_server import (
    BrowserActSessionManager,
    _Settings,
    create_browseract_mcp_server,
)


class _FakeCLI:
    def __init__(self):
        self.calls = []
        self.states = 0

    def run(self, args, *, session=None, timeout=None):
        self.calls.append((list(args), session))
        args = list(args)
        if args == ["browser", "list"]:
            return {"ok": True, "browsers": [{"id": "browser-1", "type": "chrome"}]}
        if args[:2] == ["browser", "open"]:
            return {"ok": True, "opened": args[2]}
        if args == ["state"]:
            self.states += 1
            return {"ok": True, "state": {"url": "https://example.com/", "index": self.states}}
        if args[:1] == ["click"]:
            return {"ok": True, "clicked": args[1]}
        if args[:1] == ["input"]:
            return {"ok": True, "input": args[2]}
        if args == ["session", "close"] or args[:2] == ["session", "close"]:
            return {"ok": True, "closed": args[-1]}
        return {"ok": True, "result": args}

    def browser_list(self):
        return self.run(["browser", "list"])

    def session_list(self):
        return self.run(["session", "list"])

    def version(self):
        return {"ok": True, "version": "browser-act test"}


def _manager():
    settings = _Settings(
        {
            "ENABLED": True,
            "CLI_PATH": sys.executable,
            "BROWSER_ID": "browser-1",
            "AUTO_SELECT_SINGLE_BROWSER": True,
            "ALLOW_PRIVATE_NETWORKS": False,
        }
    )
    fake = _FakeCLI()
    return BrowserActSessionManager(settings=settings, cli=fake), fake


def test_open_returns_session_and_fresh_state_token():
    manager, fake = _manager()
    result = manager.open(url="https://example.com")

    assert result["ok"] is True
    assert result["session"].startswith("ufo-ba-")
    assert result["state_token"]
    assert result["state"]["url"] == "https://example.com/"
    assert fake.calls[0][0][:3] == ["browser", "open", "browser-1"]


def test_mutation_requires_current_token_and_refreshes_state():
    manager, fake = _manager()
    opened = manager.open(url="https://example.com")
    stale = opened["state_token"]

    clicked = manager.click(opened["session"], state_token=stale, index=1)
    assert clicked["ok"] is True
    assert clicked["state_token"] != stale
    assert clicked["state"]["index"] == 2

    with pytest.raises(Exception, match="Stale or invalid"):
        manager.click(opened["session"], state_token=stale, index=1)


def test_text_is_capped_before_cli_call():
    manager, fake = _manager()
    opened = manager.open(url="https://example.com")
    manager.settings.values["MAX_INPUT_CHARS"] = 4
    with pytest.raises(Exception, match="exceeds"):
        manager.input(opened["session"], state_token=opened["state_token"], text="12345", index=1)


def test_url_policy_is_applied_to_open():
    manager, _ = _manager()
    with pytest.raises(Exception, match="only http"):
        manager.open(url="javascript:alert(1)")


def test_mcp_exposes_core_tools_without_lifecycle_or_shell_tools():
    mcp = create_browseract_mcp_server()

    async def collect():
        from fastmcp import Client

        async with Client(mcp) as client:
            return {tool.name for tool in await client.list_tools()}

    names = asyncio.run(collect())
    assert "browser_action" in names
    assert "browseract_open" in names
    assert "browseract_state" in names
    assert "browseract_click" in names
    assert not {"browser_create", "browser_delete", "eval", "run_shell", "set_cookie"} & names


def test_multi_action_strategy_allows_only_one_browseract_mutation():
    from ufo.agents.processors.schemas.actions import ActionCommandInfo
    from ufo.agents.processors.strategies import app_agent_processing_strategy as module
    from ufo.aip.messages import Result, ResultStatus

    class Dispatcher:
        def __init__(self):
            self.names = []

        async def execute_commands(self, commands):
            command = commands[0]
            self.names.append(command.tool_name)
            return [Result(status=ResultStatus.SUCCESS, result="ok")]

    strategy = module.AppActionExecutionStrategy.__new__(module.AppActionExecutionStrategy)
    import logging

    strategy.logger = logging.getLogger("test")
    dispatcher = Dispatcher()
    actions = [
        ActionCommandInfo(function="browser_action", arguments={"action": "click"}),
        ActionCommandInfo(function="browser_action", arguments={"action": "input"}),
        ActionCommandInfo(function="click_input", arguments={"id": "1"}),
    ]
    results = asyncio.run(strategy._execute_app_action(dispatcher, actions))

    assert dispatcher.names == ["browser_action"]
    assert results[0].status == ResultStatus.SUCCESS
    assert all(result.status == ResultStatus.SKIPPED for result in results[1:])
