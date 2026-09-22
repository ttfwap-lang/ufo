"""Comprehensive audit tests for DGX Spark network model configuration.

Two things are tested here, deliberately kept separate:

1. Config-loading MECHANISM (most tests in this file): env var expansion,
   profile resolution, is_local_endpoint() classification, agent-block
   lookup. These use SYNTHETIC_DGX_CONFIG below -- a placeholder profile
   shaped like agents_dgx.yaml but with made-up model names/ports, chosen
   specifically so these tests keep working regardless of what the DGX
   actually happens to be serving on a given day.

2. What the DGX is ACTUALLY, currently serving (test_dgx_model_names_match_expected
   below): reads the real config/ufo/agents_dgx.yaml and asserts on its real
   values. Update that test (not the synthetic fixture above) when the DGX's
   real model layout changes.
"""
from pathlib import Path

import pytest
import yaml

from ufo.config.config_loader import ConfigLoader, clear_config_cache
from ufo.llm.config_helper import (
    BackendProfileError,
    reset_backend_caches,
    resolve_agent_config,
    resolve_backend_profile,
    set_backend_selection,
    set_process_override,
    clear_process_override,
)
from ufo.llm.endpoint import is_local_endpoint
from ufo.llm import AgentType

DGX_HOST = "192.168.1.10"

# Synthetic/placeholder profile for mechanism tests -- see module docstring.
# These model names and ports are NOT a claim about what the DGX actually
# serves; that's covered separately by test_dgx_model_names_match_expected.
SYNTHETIC_DGX_CONFIG = {
    "HOST_AGENT": {
        "API_TYPE": "openai",
        "API_MODEL": "Qwen3-VL-8B",
        "API_BASE": "http://${UFO_DGX_HOST}:8080/v1",
        "API_KEY": "sk-local",
    },
    "APP_AGENT": {
        "API_TYPE": "openai",
        "API_MODEL": "Gemma-4-12B",
        "API_BASE": "http://${UFO_DGX_HOST}:8081/v1",
        "API_KEY": "sk-local",
    },
    "BACKUP_AGENT": {
        "API_TYPE": "openai",
        "API_MODEL": "Qwen3-VL-8B",
        "API_BASE": "http://${UFO_DGX_HOST}:8080/v1",
        "API_KEY": "sk-local",
    },
    "EVALUATION_AGENT": {
        "API_TYPE": "openai",
        "API_MODEL": "Gemma-4-12B",
        "API_BASE": "http://${UFO_DGX_HOST}:8081/v1",
        "API_KEY": "sk-local",
    },
    "TIMEOUT": 300,
}


@pytest.fixture
def dgx_config_root(tmp_path, monkeypatch):
    """Create a temp config tree with agents_dgx.yaml using env-var expansion."""
    config_dir = tmp_path / "config"
    ufo_dir = config_dir / "ufo"
    ufo_dir.mkdir(parents=True)
    with open(ufo_dir / "agents_dgx.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(SYNTHETIC_DGX_CONFIG, f)
    with open(ufo_dir / "system.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump({"UFO_ROOT": str(tmp_path), "LOG_LEVEL": "INFO"}, f)
    monkeypatch.setenv("UFO_DGX_HOST", DGX_HOST)
    ConfigLoader.reset()
    clear_config_cache()
    ConfigLoader.get_instance(str(config_dir))
    reset_backend_caches(clear_override=True)
    yield config_dir
    ConfigLoader.reset()
    clear_config_cache()
    reset_backend_caches(clear_override=True)


def test_dgx_host_agent_is_qwen_on_8080(dgx_config_root):
    """HOST_AGENT should be Qwen3-VL-8B on port :8080."""
    set_backend_selection("dgx")
    prof = resolve_backend_profile("dgx")
    host = prof["HOST_AGENT"]
    assert host["API_MODEL"] == "Qwen3-VL-8B"
    assert ":8080/v1" in host["API_BASE"]
    assert DGX_HOST in host["API_BASE"]


def test_dgx_app_agent_is_gemma_on_8081(dgx_config_root):
    """APP_AGENT should be Gemma-4-12B on port :8081."""
    set_backend_selection("dgx")
    prof = resolve_backend_profile("dgx")
    app = prof["APP_AGENT"]
    assert app["API_MODEL"] == "Gemma-4-12B"
    assert ":8081/v1" in app["API_BASE"]
    assert DGX_HOST in app["API_BASE"]


def test_dgx_backup_is_qwen_on_8080(dgx_config_root):
    """BACKUP_AGENT should mirror HOST_AGENT on Qwen3-VL :8080."""
    set_backend_selection("dgx")
    prof = resolve_backend_profile("dgx")
    backup = prof["BACKUP_AGENT"]
    assert backup["API_MODEL"] == "Qwen3-VL-8B"
    assert ":8080/v1" in backup["API_BASE"]


def test_dgx_evaluation_is_gemma_on_8081(dgx_config_root):
    """EVALUATION_AGENT should mirror APP_AGENT on Gemma-4 :8081."""
    set_backend_selection("dgx")
    prof = resolve_backend_profile("dgx")
    eval_agent = prof["EVALUATION_AGENT"]
    assert eval_agent["API_MODEL"] == "Gemma-4-12B"
    assert ":8081/v1" in eval_agent["API_BASE"]


def test_dgx_all_agents_use_openai_type(dgx_config_root):
    """All DGX agents should use API_TYPE: openai (routes to OpenAIService)."""
    set_backend_selection("dgx")
    prof = resolve_backend_profile("dgx")
    for agent in ["HOST_AGENT", "APP_AGENT", "BACKUP_AGENT", "EVALUATION_AGENT"]:
        assert prof[agent]["API_TYPE"] == "openai"


def test_dgx_all_agents_use_sk_local_key(dgx_config_root):
    """All DGX agents should use the synthetic sk-local API key."""
    set_backend_selection("dgx")
    prof = resolve_backend_profile("dgx")
    for agent in ["HOST_AGENT", "APP_AGENT", "BACKUP_AGENT", "EVALUATION_AGENT"]:
        assert prof[agent]["API_KEY"] == "sk-local"


def test_dgx_env_var_expansion(dgx_config_root, monkeypatch):
    """${UFO_DGX_HOST} should be expanded to the actual host IP."""
    monkeypatch.setenv("UFO_DGX_HOST", DGX_HOST)
    reset_backend_caches(clear_override=True)
    prof = resolve_backend_profile("dgx")
    for agent in ["HOST_AGENT", "APP_AGENT", "BACKUP_AGENT", "EVALUATION_AGENT"]:
        assert "${UFO_DGX_HOST}" not in prof[agent]["API_BASE"]
        assert DGX_HOST in prof[agent]["API_BASE"]


def test_dgx_is_local_endpoint_host(dgx_config_root, monkeypatch):
    """is_local_endpoint() should return True for Qwen3-VL on DGX :8080."""
    monkeypatch.setenv("UFO_DGX_HOST", DGX_HOST)
    reset_backend_caches(clear_override=True)
    prof = resolve_backend_profile("dgx")
    host = prof["HOST_AGENT"]
    assert is_local_endpoint(
        api_base=host["API_BASE"],
        api_key=host["API_KEY"],
        api_type=host["API_TYPE"],
    ) is True


def test_dgx_is_local_endpoint_app(dgx_config_root, monkeypatch):
    """is_local_endpoint() should return True for Gemma-4 on DGX :8081."""
    monkeypatch.setenv("UFO_DGX_HOST", DGX_HOST)
    reset_backend_caches(clear_override=True)
    prof = resolve_backend_profile("dgx")
    app = prof["APP_AGENT"]
    assert is_local_endpoint(
        api_base=app["API_BASE"],
        api_key=app["API_KEY"],
        api_type=app["API_TYPE"],
    ) is True


def test_dgx_uses_different_ports(dgx_config_root):
    """HOST_AGENT and APP_AGENT should be on different DGX ports."""
    set_backend_selection("dgx")
    prof = resolve_backend_profile("dgx")
    host_port = prof["HOST_AGENT"]["API_BASE"]
    app_port = prof["APP_AGENT"]["API_BASE"]
    assert ":8080" in host_port
    assert ":8081" in app_port
    assert host_port != app_port


def test_dgx_env_var_not_set_profile_resolves_fine(dgx_config_root, monkeypatch):
    """resolve_backend_profile() loads the whole file and must NOT fail just
    because some unrelated agent block references an unset var -- different
    agent blocks can reference different providers' env vars, so a user who
    only cares about HOST_AGENT shouldn't be blocked by e.g. an unset key on
    BACKUP_AGENT. The check is scoped per-agent instead (see below)."""
    monkeypatch.delenv("UFO_DGX_HOST", raising=False)
    reset_backend_caches(clear_override=True)
    prof = resolve_backend_profile("dgx")
    assert prof is not None
    assert "${UFO_DGX_HOST}" in prof["HOST_AGENT"]["API_BASE"]


def test_dgx_env_var_not_set_fails_fast_per_agent(dgx_config_root, monkeypatch):
    """Resolving a specific DGX agent's config must still raise rather than
    silently return an unusable URL -- scoped to the agent block actually
    being used, not the whole profile."""
    monkeypatch.delenv("UFO_DGX_HOST", raising=False)
    reset_backend_caches(clear_override=True)
    set_backend_selection("dgx")
    try:
        with pytest.raises(BackendProfileError, match="UFO_DGX_HOST"):
            resolve_agent_config(AgentType.HOST)
    finally:
        reset_backend_caches(clear_override=True)


def test_dgx_model_names_match_expected():
    """DGX config model names should match the models actually running on gx10."""
    dgx_yaml_path = Path(__file__).resolve().parent.parent / "config" / "ufo" / "agents_dgx.yaml"
    if not dgx_yaml_path.exists():
        pytest.skip("agents_dgx.yaml not found in real config")
    with open(dgx_yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    # Stack B (2026-09-22): the multimodal Qwen on :8000 plans for every role; screenshots are
    # capped (MAX_IMAGE_PIXELS) because its processor rejects images above ~2047 tokens.
    for role in ("HOST_AGENT", "APP_AGENT", "BACKUP_AGENT", "EVALUATION_AGENT"):
        assert data[role]["API_MODEL"] == "qwen-abliterated"
        assert data[role]["API_TYPE"] == "openai"
        assert ":8000" in data[role]["API_BASE"]
    for role in ("HOST_AGENT", "APP_AGENT", "BACKUP_AGENT"):
        assert data[role]["MAX_IMAGE_PIXELS"] <= 1_900_000
        assert data[role]["EXTRA_BODY"]["chat_template_kwargs"]["enable_thinking"] is False
