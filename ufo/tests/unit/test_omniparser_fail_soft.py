"""An unreachable OmniParser must degrade to UIA-only, not break the AppAgent."""
from ufo.agents.processors.strategies import app_agent_processing_strategy as m


def test_unreachable_endpoint_returns_none(monkeypatch):
    def boom(endpoint):
        raise ConnectionError("refused")
    monkeypatch.setattr(m, "get_omniparser", boom)
    monkeypatch.setattr(m.ufo_config.system, "omniparser", {"ENDPOINT": "http://127.0.0.1:1"}, raising=False)
    strat = m.AppControlInfoStrategy.__new__(m.AppControlInfoStrategy)
    import logging
    strat.logger = logging.getLogger("t")
    assert strat._init_omniparser_service() is None


def test_reachable_endpoint_builds_grounding(monkeypatch):
    monkeypatch.setattr(m, "get_omniparser", lambda endpoint: object())
    monkeypatch.setattr(m.ufo_config.system, "omniparser", {"ENDPOINT": "http://127.0.0.1:7861"}, raising=False)
    strat = m.AppControlInfoStrategy.__new__(m.AppControlInfoStrategy)
    import logging
    strat.logger = logging.getLogger("t")
    assert isinstance(strat._init_omniparser_service(), m.OmniparserGrounding)
