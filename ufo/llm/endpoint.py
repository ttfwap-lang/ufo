# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Helper for determining whether an LLM endpoint or agent configuration routes to a local model or cloud provider.

Supports:
- Localhost (127.0.0.1, localhost, 0.0.0.0)
- Local inference ports (:4000 LiteLLM, :8080 llama-server, :8081, etc.)
- DGX Spark on the network (configured via UFO_DGX_HOST env var)
- Synthetic API keys (sk-local)
- Dedicated local adapter types (ollama, llava, cogagent)
"""

from typing import Any, Dict, Optional

from ufo.llm.config_helper import get_dgx_host


def is_local_endpoint(
    api_base: Optional[str] = None,
    api_key: Optional[str] = None,
    api_type: Optional[str] = None,
) -> bool:
    """
    Check if given API parameters indicate a local model proxy (LiteLLM, llama-server, Ollama, etc.).

    Recognizes localhost, local ports, DGX Spark on the network (via UFO_DGX_HOST env var),
    synthetic API keys, and dedicated local adapter types.
    """
    # 1. Local synthetic API keys
    if api_key == "sk-local":
        return True

    # 2. Localhost / internal ports on api_base
    if api_base:
        api_base_str = str(api_base).lower()
        if any(
            local_id in api_base_str
            for local_id in ("127.0.0.1", "localhost", "0.0.0.0", ":4000", ":8080", ":8081", ":11434", ":8000", ":1234")
        ):
            return True
        # 3. DGX Spark on the local network (via UFO_DGX_HOST env var).
        # Reuses config_helper.get_dgx_host() rather than a second inline
        # os.getenv() so the two can't drift on how the value is normalized.
        dgx_host = (get_dgx_host() or "").lower()
        if dgx_host and api_base_str:
            if dgx_host in api_base_str or f":{dgx_host}" in api_base_str:
                return True

    # 4. Dedicated purely local offline adapters (Ollama, local Llava/CogAgent) without external URL
    if api_type and api_type.lower() in ("ollama", "llava", "cogagent"):
        if not api_base:
            return True

    return False


def is_local_agent_config(agent_config: Dict[str, Any]) -> bool:
    """
    Check if an agent configuration dictionary routes to a local model.
    """
    if not isinstance(agent_config, dict):
        return False
    return is_local_endpoint(
        api_base=agent_config.get("API_BASE"),
        api_key=agent_config.get("API_KEY"),
        api_type=agent_config.get("API_TYPE"),
    )


def is_cloud_agent_config(agent_config: Dict[str, Any]) -> bool:
    """
    Check if an agent configuration dictionary routes to a cloud model provider.
    """
    return not is_local_agent_config(agent_config)
