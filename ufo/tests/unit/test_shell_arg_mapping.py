import json
from types import SimpleNamespace

from ufo import utils
from ufo.agents.processors.strategies.app_agent_processing_strategy import AppLLMInteractionStrategy


def _parse(action):
    strat = AppLLMInteractionStrategy.__new__(AppLLMInteractionStrategy)
    import logging
    strat.logger = logging.getLogger("t")
    agent = SimpleNamespace(response_to_dict=utils.json_parser, print_response=lambda *a, **k: None)
    resp = strat._parse_app_response(agent, json.dumps({"thought": "t", "status": "CONTINUE", "action": action}))
    act = resp.action[0] if isinstance(resp.action, list) else resp.action
    return act.arguments


def test_execute_command_keeps_command():
    assert _parse({"function": "execute_command", "arguments": {"command": "df -h"}}) == {"command": "df -h"}


def test_execute_command_maps_bash_command_alias():
    assert _parse({"function": "execute_command", "arguments": {"bash_command": "uptime"}}) == {"command": "uptime"}


def test_run_shell_maps_command_alias():
    assert _parse({"function": "run_shell", "arguments": {"command": "notepad"}}) == {"bash_command": "notepad"}
