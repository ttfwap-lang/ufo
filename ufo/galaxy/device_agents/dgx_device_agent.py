# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
DGX Device Agent

Client-side process for the "DGX Spark" (Blackwell GB10) box. It:

1. Registers itself with a Galaxy constellation server over the AIP
   WebSocket protocol (`register()`), which causes the server to create
   exactly one `AgentProfile` record via the existing
   `galaxy.client.components.device_registry.DeviceRegistry` path — this
   class does NOT maintain a second, parallel "what is a device" model.
2. Executes inference tasks (`execute_task()`) by proxying them over HTTP
   to whichever local DGX backend is appropriate:
   - Ollama (`http://<UFO_DGX_HOST>:11434`) serving the vision model
     `gemma4-ufo`, for tasks tagged as vision/image tasks.
   - vLLM's OpenAI-compatible endpoint (`http://<UFO_DGX_HOST>:8000`)
     serving `qwen-abliterated`, for everything else.
3. Reports basic liveness of both backends (`health_check()`).

IMPORTANT — not live-tested: `register()`, `execute_task()`, and
`health_check()` are implemented against the verified method signatures of
`RegistrationProtocol`, `WebSocketTransport`, and `TaskExecutionProtocol`
(see module docstrings there), and this module imports cleanly, but none of
these methods have been exercised against a running Galaxy server or the
real DGX host from this environment. Only mocked unit tests back this code
today (see `tests/galaxy/device_agents/test_dgx_device_agent.py`).
"""

import logging
from typing import Any, Dict, List, Optional

import aiohttp

from ufo.aip.protocol.registration import RegistrationProtocol
from ufo.aip.protocol.task_execution import TaskExecutionProtocol
from ufo.aip.transport.websocket import WebSocketTransport
from ufo.llm.config_helper import get_dgx_host

logger = logging.getLogger(__name__)

# Default ports for the two DGX-hosted backends (Correction per Phase 0/1
# audit: Ollama on :11434 and vLLM on :8000 — NOT the old :8080/:8081
# llama-server layout).
DEFAULT_OLLAMA_PORT = 11434
DEFAULT_VLLM_PORT = 8000

DEFAULT_VISION_MODEL = "gemma4-ufo"
DEFAULT_TEXT_MODEL = "qwen-abliterated"

# Task metadata keys/tags that indicate a task should be routed to the
# vision backend (Ollama) instead of the text backend (vLLM).
_VISION_TAGS = {"vision", "image", "screenshot", "gemma4", "multimodal"}


class DGXDeviceAgentError(RuntimeError):
    """Raised when the DGX device agent cannot complete an operation."""


class DGXDeviceAgent:
    """
    Client-side device agent for the DGX Spark box.

    This is the process that runs ON (or alongside) the DGX host and speaks
    for it: it registers the device with a Galaxy constellation server and
    executes inference tasks assigned to it by proxying them to the local
    Ollama/vLLM backends.

    Usage:
        agent = DGXDeviceAgent()
        await agent.register("ws://galaxy-server:5005/ws")
        result = await agent.execute_task({"request": "...", "tags": ["vision"]})
        health = await agent.health_check()
    """

    def __init__(
        self,
        device_id: str = "dgx-spark-01",
        capabilities: Optional[List[str]] = None,
        dgx_host: Optional[str] = None,
        ollama_port: int = DEFAULT_OLLAMA_PORT,
        vllm_port: int = DEFAULT_VLLM_PORT,
        vision_model: str = DEFAULT_VISION_MODEL,
        text_model: str = DEFAULT_TEXT_MODEL,
    ):
        """
        Initialize the DGX device agent.

        :param device_id: Unique device identifier used during registration
        :param capabilities: Capability tags advertised at registration time
        :param dgx_host: DGX host override. If not provided, resolved lazily
            via `ufo.llm.config_helper.get_dgx_host()` (reads
            `UFO_DGX_HOST`), so a missing host at __init__ time does not
            prevent constructing the agent for testing purposes.
        :param ollama_port: Port Ollama is serving on (default 11434)
        :param vllm_port: Port vLLM's OpenAI-compatible server is on (default 8000)
        :param vision_model: Ollama model name for vision tasks
        :param text_model: vLLM model name for text tasks
        """
        self.device_id = device_id
        self.capabilities: List[str] = capabilities or [
            "llm_inference",
            "vision",
            "qwen3",
            "gemma4",
            "blackwell_gb10",
        ]
        self._dgx_host_override = dgx_host
        self.ollama_port = ollama_port
        self.vllm_port = vllm_port
        self.vision_model = vision_model
        self.text_model = text_model

        self.logger = logging.getLogger(f"{__name__}.DGXDeviceAgent")

        # Populated by register(); None until a successful registration.
        self._transport: Optional[WebSocketTransport] = None
        self._registration_protocol: Optional[RegistrationProtocol] = None
        self._task_protocol: Optional[TaskExecutionProtocol] = None
        self.registered: bool = False

    @property
    def dgx_host(self) -> Optional[str]:
        """
        Resolve the DGX host, preferring an explicit override (mainly for
        tests) and otherwise deferring to the shared
        `ufo.llm.config_helper.get_dgx_host()` helper so this class never
        duplicates that normalization logic.
        """
        if self._dgx_host_override:
            return self._dgx_host_override
        return get_dgx_host()

    @property
    def ollama_base_url(self) -> Optional[str]:
        host = self.dgx_host
        if not host:
            return None
        return f"http://{host}:{self.ollama_port}"

    @property
    def vllm_base_url(self) -> Optional[str]:
        host = self.dgx_host
        if not host:
            return None
        return f"http://{host}:{self.vllm_port}"

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    async def register(self, galaxy_server_url: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        Register this device agent with a Galaxy constellation server.

        Connects a `WebSocketTransport` to `galaxy_server_url`, wraps it in
        a `RegistrationProtocol`, and calls the real
        `RegistrationProtocol.register_as_device(device_id, metadata,
        platform)` coroutine — verified signature:

            async def register_as_device(
                self, device_id: str,
                metadata: Optional[Dict[str, Any]] = None,
                platform: str = "windows",
            ) -> bool

        A successful call here is what causes the server to create exactly
        one `AgentProfile` (via `DeviceRegistry.register_device()`) for this
        device — this method does not create any client-side duplicate of
        that record; `self.registered`/`self._registration_protocol` are
        just local handles to keep the connection alive.

        :param galaxy_server_url: Galaxy AIP WebSocket URL,
            e.g. "ws://localhost:5005/ws"
        :param metadata: Optional extra metadata merged into the
            registration payload (host, models, ports, etc. are added
            automatically)
        :return: True if registration succeeded, False otherwise
        """
        merged_metadata: Dict[str, Any] = {
            "capabilities": self.capabilities,
            "dgx_host": self.dgx_host,
            "ollama_base_url": self.ollama_base_url,
            "vllm_base_url": self.vllm_base_url,
            "vision_model": self.vision_model,
            "text_model": self.text_model,
        }
        if metadata:
            merged_metadata.update(metadata)

        transport = WebSocketTransport()
        try:
            await transport.connect(galaxy_server_url)
        except ConnectionError as e:
            self.logger.error(f"Failed to connect to Galaxy server {galaxy_server_url}: {e}")
            return False

        registration_protocol = RegistrationProtocol(transport)
        try:
            success = await registration_protocol.register_as_device(
                device_id=self.device_id,
                metadata=merged_metadata,
                platform="linux",
            )
        except Exception as e:
            self.logger.error(f"Error registering device {self.device_id}: {e}", exc_info=True)
            await transport.close()
            return False

        if success:
            self._transport = transport
            self._registration_protocol = registration_protocol
            self._task_protocol = TaskExecutionProtocol(transport)
            self.registered = True
            self.logger.info(f"DGX device agent '{self.device_id}' registered with {galaxy_server_url}")
        else:
            await transport.close()
            self.registered = False

        return success

    async def close(self) -> None:
        """Close the underlying transport connection, if any."""
        if self._transport is not None:
            await self._transport.close()
        self.registered = False
        self._transport = None
        self._registration_protocol = None
        self._task_protocol = None

    # ------------------------------------------------------------------
    # Task execution
    # ------------------------------------------------------------------

    def _is_vision_task(self, task: Dict[str, Any]) -> bool:
        """Decide whether a task should be routed to the vision (Ollama) backend."""
        tags = set()
        for key in ("tags", "capabilities"):
            value = task.get(key)
            if value:
                tags.update(str(t).lower() for t in value)
        task_name = str(task.get("task_name", "")).lower()
        if any(tag in _VISION_TAGS for tag in tags):
            return True
        if "images" in task or "image" in task or "screenshot" in task:
            return True
        return any(vt in task_name for vt in _VISION_TAGS)

    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a task by proxying it to the appropriate DGX backend.

        Vision-tagged tasks (task["tags"]/task["capabilities"] containing
        any of `_VISION_TAGS`, or an "images"/"image"/"screenshot" key) are
        sent to Ollama's `/api/generate` endpoint using `self.vision_model`.
        Everything else is sent to vLLM's OpenAI-compatible
        `/v1/chat/completions` endpoint using `self.text_model`.

        :param task: Task payload. Expected keys: "request" (prompt text),
            optionally "images" (list of base64-encoded images for vision
            tasks), "tags"/"capabilities" (used for routing), and
            "task_name" (for logging).
        :return: Dict with at least {"success": bool, "output": str} or
            {"success": False, "error": str} on failure.
        """
        if not self.dgx_host:
            return {
                "success": False,
                "error": "UFO_DGX_HOST is not set; cannot resolve DGX backend URLs",
            }

        prompt = task.get("request") or task.get("prompt") or ""
        is_vision = self._is_vision_task(task)

        try:
            if is_vision:
                return await self._execute_vision_task(prompt, task)
            return await self._execute_text_task(prompt, task)
        except aiohttp.ClientError as e:
            self.logger.error(f"HTTP error executing task on DGX backend: {e}")
            return {"success": False, "error": f"HTTP error: {e}"}
        except Exception as e:
            self.logger.error(f"Unexpected error executing task on DGX backend: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def _execute_vision_task(self, prompt: str, task: Dict[str, Any]) -> Dict[str, Any]:
        """Proxy a vision task to Ollama's /api/generate endpoint."""
        url = f"{self.ollama_base_url}/api/generate"
        payload: Dict[str, Any] = {
            "model": self.vision_model,
            "prompt": prompt,
            "stream": False,
        }
        images = task.get("images")
        if images:
            payload["images"] = images

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()

        return {
            "success": True,
            "backend": "ollama",
            "model": self.vision_model,
            "output": data.get("response", ""),
            "raw": data,
        }

    async def _execute_text_task(self, prompt: str, task: Dict[str, Any]) -> Dict[str, Any]:
        """Proxy a text task to vLLM's OpenAI-compatible /v1/chat/completions endpoint."""
        url = f"{self.vllm_base_url}/v1/chat/completions"
        payload: Dict[str, Any] = {
            "model": self.text_model,
            "messages": [{"role": "user", "content": prompt}],
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()

        output = ""
        choices = data.get("choices") or []
        if choices:
            output = choices[0].get("message", {}).get("content", "")

        return {
            "success": True,
            "backend": "vllm",
            "model": self.text_model,
            "output": output,
            "raw": data,
        }

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def health_check(self) -> Dict[str, Any]:
        """
        Probe both DGX backends for liveness.

        Checks `GET {ollama_base_url}/api/tags` and
        `GET {vllm_base_url}/v1/models`. Neither check raises on failure —
        failures are reported in the returned dict instead.

        :return: {
            "dgx_host": Optional[str],
            "ollama": {"healthy": bool, "url": str, "error": Optional[str]},
            "vllm": {"healthy": bool, "url": str, "error": Optional[str]},
            "healthy": bool,  # True only if both backends are healthy
        }
        """
        host = self.dgx_host
        if not host:
            return {
                "dgx_host": None,
                "ollama": {"healthy": False, "url": None, "error": "UFO_DGX_HOST not set"},
                "vllm": {"healthy": False, "url": None, "error": "UFO_DGX_HOST not set"},
                "healthy": False,
            }

        ollama_url = f"{self.ollama_base_url}/api/tags"
        vllm_url = f"{self.vllm_base_url}/v1/models"

        ollama_result = await self._probe(ollama_url)
        vllm_result = await self._probe(vllm_url)

        return {
            "dgx_host": host,
            "ollama": ollama_result,
            "vllm": vllm_result,
            "healthy": ollama_result["healthy"] and vllm_result["healthy"],
        }

    @staticmethod
    async def _probe(url: str, timeout: float = 5.0) -> Dict[str, Any]:
        """GET a URL and report whether it returned HTTP 200, without raising."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                    return {"healthy": resp.status == 200, "url": url, "error": None}
        except Exception as e:
            return {"healthy": False, "url": url, "error": str(e)}
