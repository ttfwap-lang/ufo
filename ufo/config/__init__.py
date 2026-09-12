# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
UFO² Configuration System

Modern, modular configuration system with type safety and backward compatibility.
"""

from ufo.config.config_loader import (
    ConfigLoader,
    get_ufo_config,
    get_galaxy_config,
    clear_config_cache,
    LazyUFOConfig,
    LazyGalaxyConfig,
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
        with open(file_path, "r", encoding="utf-8") as file:
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


class Config:
    """Legacy backward-compatible Config singleton class for UFO."""
    _instance = None

    def __init__(self):
        self._cfg = get_ufo_config()
        raw = self._cfg.to_dict()
        if hasattr(self._cfg, "system") and hasattr(self._cfg.system, "to_dict"):
            for k, v in self._cfg.system.to_dict().items():
                if k not in raw:
                    raw[k] = v
        if hasattr(self._cfg, "rag") and hasattr(self._cfg.rag, "to_dict"):
            for k, v in self._cfg.rag.to_dict().items():
                if k not in raw:
                    raw[k] = v
        self.config_data = raw

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def initialize(cls):
        cls._instance = cls()
        return cls._instance

    def __getitem__(self, key):
        return self._cfg[key]

    def get(self, key, default=None):
        return self._cfg.get(key, default)


from ufo.config.config_schemas import (
    UFOConfig,
    GalaxyConfig,
    AgentConfig,
    SystemConfig,
    RAGConfig,
)

__all__ = [
    "Config",
    "ConfigLoader",
    "get_ufo_config",
    "get_galaxy_config",
    "clear_config_cache",
    "LazyUFOConfig",
    "LazyGalaxyConfig",
    "UFOConfig",
    "GalaxyConfig",
    "AgentConfig",
    "SystemConfig",
    "RAGConfig",
]
