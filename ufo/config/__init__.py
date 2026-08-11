# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
UFO² Configuration System

Modern, modular configuration system with type safety and backward compatibility.
"""

from config.config_loader import (
    ConfigLoader,
    get_ufo_config,
    get_galaxy_config,
    clear_config_cache,
)

get_config = get_ufo_config

def get_offline_learner_indexer_config():
    import os
    import json
    file_path = "learner/records.json"
    if os.path.exists(file_path):
        with open(file_path, "r") as file:
            return json.load(file)
    return {}


from config.config_schemas import (
    UFOConfig,
    GalaxyConfig,
    AgentConfig,
    SystemConfig,
    RAGConfig,
)

__all__ = [
    "ConfigLoader",
    "get_ufo_config",
    "get_galaxy_config",
    "clear_config_cache",
    "UFOConfig",
    "GalaxyConfig",
    "AgentConfig",
    "SystemConfig",
    "RAGConfig",
]
