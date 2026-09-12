# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Helper for determining whether an LLM endpoint or agent configuration routes to a local model or cloud provider.
"""

from typing import Any, Dict, Optional


def is_local_endpoint(
    api_base: Optional[str] = None,
    api_key: Optional[str] = None,
    api_type: Optional[str] = None,
) -> bool:
    """
    Check if given API parameters indicate a local model proxy (LiteLLM, llama-server, Ollama, etc.).
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

    # 3. Dedicated purely local offline adapters (Ollama, local Llava/CogAgent) without external URL
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
