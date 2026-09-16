"""Tests for is_local_endpoint() with DGX Spark network configurations.

Covers the specific edge cases discovered during the DGX model audit:
- Empty string dgx_host should NOT match (the __main__.py bug)
- DGX host in api_base should be recognized as local
- Cloud OpenAI endpoints should NOT be classified as local even when
  UFO_DGX_HOST is set
"""

import pytest

from ufo.llm.endpoint import is_local_endpoint


@pytest.fixture
def clean_env(monkeypatch):
    """Remove UFO_DGX_HOST so tests start clean."""
    monkeypatch.delenv("UFO_DGX_HOST", raising=False)
    yield


class TestIsLocalEndpointDGX:
    """DGX-specific is_local_endpoint() tests."""

    def test_dgx_host_in_api_base_is_local(self, monkeypatch):
        """api_base containing UFO_DGX_HOST should be recognized as local."""
        monkeypatch.setenv("UFO_DGX_HOST", "192.168.1.10")
        assert is_local_endpoint(
            api_base="http://192.168.1.10:8080/v1",
            api_key="sk-local",
            api_type="openai",
        ) is True

    def test_dgx_gemma_port_is_local(self, monkeypatch):
        """Gemma-4 on DGX :8081 should be recognized as local."""
        monkeypatch.setenv("UFO_DGX_HOST", "192.168.1.10")
        assert is_local_endpoint(
            api_base="http://192.168.1.10:8081/v1",
            api_key="sk-local",
            api_type="openai",
        ) is True

    def test_cloud_openai_base_is_not_local(self, monkeypatch):
        """Cloud OpenAI endpoint should NOT be local even with UFO_DGX_HOST set."""
        monkeypatch.setenv("UFO_DGX_HOST", "192.168.1.10")
        assert is_local_endpoint(
            api_base="https://api.openai.com/v1",
            api_key="sk-real-cloud-key",
            api_type="openai",
        ) is False

    def test_empty_dgx_host_does_not_match_cloud(self, monkeypatch):
        """Empty UFO_DGX_HOST must not cause cloud endpoints to pass the local gate."""
        monkeypatch.setenv("UFO_DGX_HOST", "")
        assert is_local_endpoint(
            api_base="https://api.openai.com/v1",
            api_key="sk-real-cloud-key",
            api_type="openai",
        ) is False

    def test_localhost_api_base_is_local(self):
        """Standard localhost endpoints should be local."""
        assert is_local_endpoint(
            api_base="http://127.0.0.1:8080/v1",
            api_key="sk-local",
            api_type="openai",
        ) is True

    def test_litellm_port_is_local(self):
        """LiteLLM on :4000 should be recognized as local."""
        assert is_local_endpoint(
            api_base="http://127.0.0.1:4000",
            api_key="sk-local",
            api_type="openai",
        ) is True

    def test_sk_local_key_always_local(self, monkeypatch):
        """sk-local synthetic key should always be local regardless of base URL."""
        monkeypatch.setenv("UFO_DGX_HOST", "")
        assert is_local_endpoint(
            api_base="https://api.openai.com/v1",
            api_key="sk-local",
            api_type="openai",
        ) is True

    def test_ollama_type_is_local(self):
        """Ollama API type without api_base should be local."""
        assert is_local_endpoint(
            api_base=None,
            api_key=None,
            api_type="ollama",
        ) is True

    def test_llava_type_is_local(self):
        """Llava API type without api_base should be local."""
        assert is_local_endpoint(
            api_base=None,
            api_key=None,
            api_type="llava",
        ) is True

    def test_cogagent_type_is_local(self):
        """Cogagent API type without api_base should be local."""
        assert is_local_endpoint(
            api_base=None,
            api_key=None,
            api_type="cogagent",
        ) is True

    def test_gemini_type_is_not_local(self):
        """Gemini API type should not be classified as local."""
        assert is_local_endpoint(
            api_base=None,
            api_key="sk-real-key",
            api_type="gemini",
        ) is False

    def test_dgx_host_with_ip_in_base(self, monkeypatch):
        """DGX host IP appearing in api_base (even without explicit port match) is local."""
        monkeypatch.setenv("UFO_DGX_HOST", "10.0.0.5")
        assert is_local_endpoint(
            api_base="http://10.0.0.5:8080/v1",
            api_key="sk-local",
            api_type="openai",
        ) is True

    def test_no_args_not_local(self):
        """No arguments should not be local."""
        assert is_local_endpoint() is False

    def test_dgx_port_8080_in_base_is_local_without_env(self):
        """Port :8080 in api_base should be local even without UFO_DGX_HOST."""
        assert is_local_endpoint(
            api_base="http://192.168.1.10:8080/v1",
            api_key="sk-local",
            api_type="openai",
        ) is True

    def test_dgx_port_8081_in_base_is_local_without_env(self):
        """Port :8081 in api_base should be local even without UFO_DGX_HOST."""
        assert is_local_endpoint(
            api_base="http://192.168.1.10:8081/v1",
            api_key="sk-local",
            api_type="openai",
        ) is True
