# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Tests for DGXDeviceAgent.

These tests mock the AIP transport/protocol layer and the aiohttp HTTP
calls to Ollama/vLLM. They verify the class instantiates correctly and
that its methods call the underlying APIs with the expected shapes — they
do NOT prove the agent works against a real Galaxy server or the real DGX
host; no live infrastructure is exercised here.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ufo.galaxy.device_agents.dgx_device_agent import DGXDeviceAgent


class TestDGXDeviceAgentInit:
    def test_default_construction(self):
        agent = DGXDeviceAgent()
        assert agent.device_id == "dgx-spark-01"
        assert "llm_inference" in agent.capabilities
        assert "vision" in agent.capabilities
        assert "qwen3" in agent.capabilities
        assert "gemma4" in agent.capabilities
        assert "blackwell_gb10" in agent.capabilities
        assert agent.registered is False

    def test_dgx_host_resolution_uses_config_helper(self, monkeypatch):
        monkeypatch.setenv("UFO_DGX_HOST", "100.64.1.2")
        agent = DGXDeviceAgent()
        assert agent.dgx_host == "100.64.1.2"
        assert agent.ollama_base_url == "http://100.64.1.2:11434"
        assert agent.vllm_base_url == "http://100.64.1.2:8000"

    def test_dgx_host_override_takes_precedence(self, monkeypatch):
        monkeypatch.setenv("UFO_DGX_HOST", "100.64.1.2")
        agent = DGXDeviceAgent(dgx_host="10.0.0.5")
        assert agent.dgx_host == "10.0.0.5"

    def test_no_dgx_host_returns_none(self, monkeypatch):
        monkeypatch.delenv("UFO_DGX_HOST", raising=False)
        agent = DGXDeviceAgent()
        assert agent.dgx_host is None
        assert agent.ollama_base_url is None
        assert agent.vllm_base_url is None


class TestDGXDeviceAgentRegister:
    @pytest.mark.asyncio
    async def test_register_success_calls_registration_protocol(self, monkeypatch):
        """
        Verifies register() calls the real
        RegistrationProtocol.register_as_device(device_id, metadata, platform)
        signature, and that a successful call leaves the agent 'registered'
        with a live task protocol handle — no server or network involved,
        both the transport and protocol are mocked.
        """
        monkeypatch.setenv("UFO_DGX_HOST", "100.64.1.2")
        agent = DGXDeviceAgent()

        with patch(
            "ufo.galaxy.device_agents.dgx_device_agent.WebSocketTransport"
        ) as mock_transport_cls, patch(
            "ufo.galaxy.device_agents.dgx_device_agent.RegistrationProtocol"
        ) as mock_reg_proto_cls, patch(
            "ufo.galaxy.device_agents.dgx_device_agent.TaskExecutionProtocol"
        ) as mock_task_proto_cls:
            mock_transport = AsyncMock()
            mock_transport.connect = AsyncMock()
            mock_transport_cls.return_value = mock_transport

            mock_reg_proto = MagicMock()
            mock_reg_proto.register_as_device = AsyncMock(return_value=True)
            mock_reg_proto_cls.return_value = mock_reg_proto

            mock_task_proto = MagicMock()
            mock_task_proto_cls.return_value = mock_task_proto

            success = await agent.register("ws://localhost:5005/ws")

            assert success is True
            assert agent.registered is True
            mock_transport.connect.assert_awaited_once_with("ws://localhost:5005/ws")
            mock_reg_proto_cls.assert_called_once_with(mock_transport)
            mock_reg_proto.register_as_device.assert_awaited_once()
            call_kwargs = mock_reg_proto.register_as_device.call_args.kwargs
            assert call_kwargs["device_id"] == "dgx-spark-01"
            assert call_kwargs["platform"] == "linux"
            assert "capabilities" in call_kwargs["metadata"]

    @pytest.mark.asyncio
    async def test_register_failure_closes_transport(self, monkeypatch):
        monkeypatch.setenv("UFO_DGX_HOST", "100.64.1.2")
        agent = DGXDeviceAgent()

        with patch(
            "ufo.galaxy.device_agents.dgx_device_agent.WebSocketTransport"
        ) as mock_transport_cls, patch(
            "ufo.galaxy.device_agents.dgx_device_agent.RegistrationProtocol"
        ) as mock_reg_proto_cls:
            mock_transport = AsyncMock()
            mock_transport.connect = AsyncMock()
            mock_transport.close = AsyncMock()
            mock_transport_cls.return_value = mock_transport

            mock_reg_proto = MagicMock()
            mock_reg_proto.register_as_device = AsyncMock(return_value=False)
            mock_reg_proto_cls.return_value = mock_reg_proto

            success = await agent.register("ws://localhost:5005/ws")

            assert success is False
            assert agent.registered is False
            mock_transport.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_register_connect_failure_returns_false(self, monkeypatch):
        monkeypatch.setenv("UFO_DGX_HOST", "100.64.1.2")
        agent = DGXDeviceAgent()

        with patch(
            "ufo.galaxy.device_agents.dgx_device_agent.WebSocketTransport"
        ) as mock_transport_cls:
            mock_transport = AsyncMock()
            mock_transport.connect = AsyncMock(side_effect=ConnectionError("no route"))
            mock_transport_cls.return_value = mock_transport

            success = await agent.register("ws://localhost:5005/ws")

            assert success is False
            assert agent.registered is False


class TestDGXDeviceAgentExecuteTask:
    @pytest.mark.asyncio
    async def test_text_task_routes_to_vllm(self, monkeypatch):
        monkeypatch.setenv("UFO_DGX_HOST", "100.64.1.2")
        agent = DGXDeviceAgent()

        fake_response = {
            "choices": [{"message": {"content": "hello from qwen"}}]
        }
        mock_resp = AsyncMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(return_value=fake_response)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "ufo.galaxy.device_agents.dgx_device_agent.aiohttp.ClientSession",
            return_value=mock_session,
        ):
            result = await agent.execute_task({"request": "hi", "task_name": "greet"})

        assert result["success"] is True
        assert result["backend"] == "vllm"
        assert result["model"] == "qwen-abliterated"
        assert result["output"] == "hello from qwen"

    @pytest.mark.asyncio
    async def test_vision_task_routes_to_ollama(self, monkeypatch):
        monkeypatch.setenv("UFO_DGX_HOST", "100.64.1.2")
        agent = DGXDeviceAgent()

        fake_response = {"response": "I see a browser window"}
        mock_resp = AsyncMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(return_value=fake_response)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "ufo.galaxy.device_agents.dgx_device_agent.aiohttp.ClientSession",
            return_value=mock_session,
        ):
            result = await agent.execute_task(
                {"request": "describe this screenshot", "tags": ["vision"], "images": ["base64=="]}
            )

        assert result["success"] is True
        assert result["backend"] == "ollama"
        assert result["model"] == "gemma4-ufo"
        assert result["output"] == "I see a browser window"

    @pytest.mark.asyncio
    async def test_execute_task_without_dgx_host_fails_gracefully(self, monkeypatch):
        monkeypatch.delenv("UFO_DGX_HOST", raising=False)
        agent = DGXDeviceAgent()
        result = await agent.execute_task({"request": "hi"})
        assert result["success"] is False
        assert "UFO_DGX_HOST" in result["error"]


class TestDGXDeviceAgentHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_both_up(self, monkeypatch):
        monkeypatch.setenv("UFO_DGX_HOST", "100.64.1.2")
        agent = DGXDeviceAgent()

        async def fake_probe(url, timeout=5.0):
            return {"healthy": True, "url": url, "error": None}

        with patch.object(DGXDeviceAgent, "_probe", side_effect=fake_probe):
            result = await agent.health_check()

        assert result["healthy"] is True
        assert result["ollama"]["url"] == "http://100.64.1.2:11434/api/tags"
        assert result["vllm"]["url"] == "http://100.64.1.2:8000/v1/models"

    @pytest.mark.asyncio
    async def test_health_check_no_host(self, monkeypatch):
        monkeypatch.delenv("UFO_DGX_HOST", raising=False)
        agent = DGXDeviceAgent()
        result = await agent.health_check()
        assert result["healthy"] is False
        assert result["dgx_host"] is None

    @pytest.mark.asyncio
    async def test_health_check_probe_failure_does_not_raise(self, monkeypatch):
        monkeypatch.setenv("UFO_DGX_HOST", "100.64.1.2")
        agent = DGXDeviceAgent()

        async def fake_probe(url, timeout=5.0):
            return {"healthy": False, "url": url, "error": "connection refused"}

        with patch.object(DGXDeviceAgent, "_probe", side_effect=fake_probe):
            result = await agent.health_check()

        assert result["healthy"] is False
        assert result["ollama"]["error"] == "connection refused"
