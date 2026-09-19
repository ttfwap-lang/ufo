"""ComputerManager must find HOST_AGENT / APP_AGENT blocks for HostAgent / AppAgent.

Regression: the lookup tried AppAgent/APPAGENT/appagent/Appagent but never the
underscored config key, so every agent silently fell back to a hardcoded
two-server set and never saw FileSystem/WebResearch/PDF/COM/toolkit tools.
"""
import asyncio

from ufo.client.computer import ComputerManager


class _FakeServerManager:
    pass


def _cfg():
    return {
        "mcp": {
            "HOST_AGENT": {"default": {"data_collection": [], "action": [{"name": "HostOnly", "namespace": "HostOnly", "type": "local"}]}},
            "APP_AGENT": {"default": {"data_collection": [], "action": [{"name": "AppOnly", "namespace": "AppOnly", "type": "local"}]}},
        }
    }


def _resolved_agent_config(agent_name, monkeypatch):
    captured = {}
    import ufo.client.computer as _m
    mod_computer = _m.Computer

    class _StubComputer:
        _data_collection_namespaces = mod_computer._data_collection_namespaces
        _action_namespaces = mod_computer._action_namespaces

        def __init__(self, *args, **kwargs):
            captured.update(kwargs)
            captured["args"] = args

        async def async_init(self):
            return None

    import ufo.client.computer as mod
    monkeypatch.setattr(mod, "Computer", _StubComputer)
    mgr = ComputerManager(_cfg(), _FakeServerManager())
    asyncio.run(mgr.get_or_create(agent_name=agent_name, process_name="p", root_name="Notepad.exe"))
    return repr(captured)


def test_app_agent_gets_app_agent_block(monkeypatch):
    got = _resolved_agent_config("AppAgent", monkeypatch)
    assert "AppOnly" in got and "HostOnly" not in got


def test_host_agent_gets_host_agent_block(monkeypatch):
    got = _resolved_agent_config("HostAgent", monkeypatch)
    assert "HostOnly" in got and "AppOnly" not in got


def _resolved_for_root(root_name, monkeypatch):
    import yaml
    from pathlib import Path
    cfg = yaml.safe_load((Path(__file__).resolve().parents[2] / "config" / "ufo" / "mcp.yaml").read_text(encoding="utf-8"))
    captured = {}
    import ufo.client.computer as mod
    real = mod.Computer

    class _Stub:
        _data_collection_namespaces = real._data_collection_namespaces
        _action_namespaces = real._action_namespaces

        def __init__(self, *a, **k):
            captured.update(k)

        async def async_init(self):
            return None

    monkeypatch.setattr(mod, "Computer", _Stub)
    mgr = ComputerManager({"mcp": {"APP_AGENT": cfg["APP_AGENT"]}}, _FakeServerManager())
    asyncio.run(mgr.get_or_create(agent_name="AppAgent", process_name="Doc1 - Word", root_name=root_name))
    return [e["name"] for e in captured["action_servers_config"]]


def test_office_servers_only_attach_to_their_app(monkeypatch):
    word = _resolved_for_root("WINWORD.EXE", monkeypatch)
    assert "server_5_WordCOMExecutor" in word and "excel_wincom_mcp_server" not in word
    assert "excel_wincom_mcp_server" in _resolved_for_root("excel.exe", monkeypatch)
    notepad = _resolved_for_root("Notepad.exe", monkeypatch)
    assert not {"server_5_WordCOMExecutor", "excel_wincom_mcp_server", "PowerPointCOMExecutor"} & set(notepad)
