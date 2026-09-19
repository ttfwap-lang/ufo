from types import SimpleNamespace

from ufo.aip.messages import Command
from ufo.client.computer import Computer


def _computer(schema):
    c = Computer.__new__(Computer)
    tool = SimpleNamespace(input_schema=schema, parameters=None)
    c._tools_registry = {"action::execute_command": tool}
    c._data_collection_namespaces = "data_collection"
    c._action_namespaces = "action"
    c.make_tool_key = lambda t, n: f"{t}::{n}"
    return c


def test_api_key_injected_from_env(monkeypatch):
    monkeypatch.setenv("UFO_MCP_API_KEY", "secret")
    c = _computer({"properties": {"command": {}, "api_key": {}}})
    tool = c.command2tool(Command(tool_name="execute_command", tool_type="action", parameters={"command": "ls", "api_key": "hallucinated"}))
    assert tool.parameters == {"command": "ls", "api_key": "secret"}


def test_no_injection_for_tools_without_api_key(monkeypatch):
    monkeypatch.setenv("UFO_MCP_API_KEY", "secret")
    c = _computer({"properties": {"command": {}}})
    tool = c.command2tool(Command(tool_name="execute_command", tool_type="action", parameters={"command": "ls"}))
    assert "api_key" not in tool.parameters
