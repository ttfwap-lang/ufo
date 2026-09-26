"""Configuration/contract tests for the Featherless + BrowserAct route."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_featherless_profile_is_safe_and_openai_compatible():
    path = ROOT / "config" / "ufo" / "profiles" / "agents_featherless.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for block_name in ("HOST_AGENT", "APP_AGENT", "BACKUP_AGENT", "EVALUATION_AGENT"):
        block = data[block_name]
        assert block["API_TYPE"] == "openai"
        assert block["API_BASE"] == "https://api.featherless.ai/v1"
        assert block["API_KEY"] == "${FEATHERLESS_API_KEY}"
        assert block["USE_RESPONSES"] is False
        assert block["JSON_SCHEMA"] is False
        assert block["PRICE_PROVIDER"] == "featherless"
    assert data["HOST_AGENT"]["VISUAL_MODE"] is False
    assert data["APP_AGENT"]["VISUAL_MODE"] is False
    assert data["HOST_AGENT"]["API_MODEL"] == "DavidAU/Qwen3.5-27B-Claude-4.6-OS-INSTRUCT"
    assert data["APP_AGENT"]["API_MODEL"] == "Qwen/Qwen3.8-Flash-Next"
    assert data["BACKUP_AGENT"]["API_MODEL"].startswith("DavidAU/Qwen3.5-9B-")
    assert data["EVALUATION_AGENT"]["API_MODEL"] == data["BACKUP_AGENT"]["API_MODEL"]


def test_featherless_profile_resolves_without_being_merged_into_default_config(monkeypatch):
    from ufo.llm.config_helper import reset_backend_caches, resolve_backend_profile

    monkeypatch.setenv("FEATHERLESS_API_KEY", "unit-test-key")
    reset_backend_caches(clear_override=True)
    profile = resolve_backend_profile("featherless")
    assert profile is not None
    assert profile["APP_AGENT"]["API_BASE"] == "https://api.featherless.ai/v1"
    # The profile lives below config/ufo/profiles, so the normal top-level
    # config discovery cannot silently overwrite agents.yaml with it.
    assert (ROOT / "config" / "ufo" / "profiles").is_dir()


def test_mcp_config_registers_browseract_for_default_browser_agents():
    data = yaml.safe_load((ROOT / "config" / "ufo" / "mcp.yaml").read_text(encoding="utf-8"))
    servers = data["mcp_servers"]
    assert "BrowserActExecutor" in servers
    host_actions = data["HOST_AGENT"]["default"]["action"]
    app_actions = data["APP_AGENT"]["default"]["action"]
    assert any(item["name"] == "BrowserActExecutor" for item in host_actions)
    assert any(item["name"] == "BrowserActExecutor" for item in app_actions)
    # BrowserAct is not injected into unrelated Office-only action blocks.
    for root in ("WINWORD.EXE", "EXCEL.EXE", "POWERPNT.EXE"):
        assert not any(item["name"] == "BrowserActExecutor" for item in data["APP_AGENT"][root]["action"])


def test_featherless_price_namespace_is_present():
    prices = yaml.safe_load((ROOT / "config" / "ufo" / "prices.yaml").read_text(encoding="utf-8"))["PRICES"]
    assert "featherless/Qwen/Qwen3.6-35B-A3B" in prices
    assert "featherless/Qwen/Qwen3.8-Flash-Next" in prices
    assert "featherless/DavidAU/Qwen3.5-9B-Claude-4.6-OS-HERETIC-UNCENSORED-INSTRUCT" in prices
    assert "featherless/DavidAU/Qwen3.5-27B-Claude-4.6-OS-INSTRUCT" in prices
