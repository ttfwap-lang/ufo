import pytest

from ufo.ops import api_server


def test_refuses_public_bind_without_key(monkeypatch):
    monkeypatch.setattr(api_server, "_config", {"HOST": "0.0.0.0", "API_KEY": ""})
    with pytest.raises(SystemExit):
        api_server.run_server()


def test_allows_public_bind_with_key(monkeypatch):
    import uvicorn
    called = {}
    monkeypatch.setattr(api_server, "_config", {"HOST": "0.0.0.0", "API_KEY": "k"})
    monkeypatch.setattr(uvicorn, "run", lambda app, host, port, log_level: called.update(host=host))
    api_server.run_server()
    assert called["host"] == "0.0.0.0"


def test_default_is_localhost(monkeypatch):
    import uvicorn
    called = {}
    monkeypatch.setattr(api_server, "_config", {})
    monkeypatch.setattr(uvicorn, "run", lambda app, host, port, log_level: called.update(host=host))
    api_server.run_server()
    assert called["host"] == "127.0.0.1"
