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
    import logging
    import os
    import json
    logger = logging.getLogger(__name__)
    file_path = "learner/records.json"
    if not os.path.exists(file_path):
        logger.debug(
            "Offline learner index not found at '%s'; returning empty config.", file_path
        )
        return {}
    try:
        with open(file_path, "r") as file:
            data = json.load(file)
            if not isinstance(data, dict):
                logger.warning(
                    "Offline learner index at '%s' is not a dict (got %s); returning empty config.",
                    file_path, type(data).__name__,
                )
                return {}
            return data
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(
            "Failed to parse offline learner index at '%s': %s", file_path, e
        )
        return {}
    except OSError as e:
        logger.error(
            "Failed to read offline learner index at '%s': %s", file_path, e
        )
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
