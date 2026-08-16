"""
Unified agent configuration getter for LLM calls.

This module provides a unified way to get agent configurations from different
config files based on AgentType.
"""

import copy
import threading
from typing import Dict, Any, Optional
from ufo.llm import AgentType
from ufo.config.config_loader import get_ufo_config, get_galaxy_config, ConfigLoader

_route_lock = threading.Lock()
_active_agent_route: Optional[str] = None
_cloud_config_cache: Optional[Dict[str, Any]] = None


def _load_and_validate_cloud_config() -> Optional[Dict[str, Any]]:
    """
    Load, normalize, and validate agents_cloud.yaml.
    Reuses ConfigLoader mechanisms for env expansion and legacy transforms.
    Ensures required agent blocks (HOST_AGENT, APP_AGENT) exist and are valid dictionaries.

    :return: Normalized cloud configuration dictionary, or None if loading/validation fails.
    """
    try:
        loader = ConfigLoader.get_instance()
        cloud_path = loader.base_path / "ufo" / "agents_cloud.yaml"
        if not cloud_path.exists():
            return None

        # Load with environment variable expansion via loader._load_yaml
        raw_data = loader._load_yaml(cloud_path)
        if not isinstance(raw_data, dict):
            return None

        cloud_data = copy.deepcopy(raw_data)

        # Apply standard transformations (API_BASE construction, list conversion, etc.)
        loader._apply_legacy_transforms(cloud_data)

        # Validate required agent blocks exist
        host = cloud_data.get("HOST_AGENT")
        app = cloud_data.get("APP_AGENT")
        if not isinstance(host, dict) or not isinstance(app, dict):
            return None

        return cloud_data
    except Exception:
        return None


def set_active_agent_route(route: Optional[str]) -> bool:
    """
    Set the active in-memory routing target for agent configuration.

    When route is "cloud", validates and loads the required cloud agent blocks
    (with env expansion and config transformations) before marking the route active.

    :param route: "cloud", None (default, read disk config), or custom route name.
    :return: True if route was successfully activated, False if validation/loading failed.
    """
    global _active_agent_route, _cloud_config_cache
    with _route_lock:
        if route == "cloud":
            cloud_data = _load_and_validate_cloud_config()
            if not cloud_data:
                return False
            _cloud_config_cache = cloud_data
            _active_agent_route = "cloud"
            return True
        else:
            _active_agent_route = route
            return True


def get_active_agent_route() -> Optional[str]:
    """Get the currently active in-memory agent route."""
    with _route_lock:
        return _active_agent_route


def get_agent_config(agent_type: str) -> Dict[str, Any]:
    """
    Get agent configuration based on agent type.

    Maps AgentType to the appropriate configuration file:
    - HOST_AGENT, APP_AGENT, BACKUP_AGENT, EVALUATION_AGENT, OPERATOR → config/ufo/agents.yaml (or in-memory cloud route)
    - CONSTELLATION_AGENT → config/galaxy/agent.yaml
    - Third-party agents → config/ufo/third_party.yaml (future)

    :param agent_type: AgentType enum value (e.g., AgentType.HOST, AgentType.CONSTELLATION)
    :return: Agent configuration dictionary
    :raises ValueError: If agent type is not supported
    """
    with _route_lock:
        current_route = _active_agent_route
        cached_cloud = _cloud_config_cache

    # If cloud route is active, return the validated cloud configuration override in memory
    if current_route == "cloud" and cached_cloud:
        cloud_map = {
            AgentType.HOST: "HOST_AGENT",
            AgentType.APP: "APP_AGENT",
            AgentType.BACKUP: "BACKUP_AGENT",
            AgentType.EVALUATION: "EVALUATION_AGENT",
            AgentType.OPERATOR: "OPERATOR",
            AgentType.PREFILL: "HOST_AGENT",
            AgentType.FILTER: "HOST_AGENT",
        }
        if agent_type in cloud_map:
            key = cloud_map[agent_type]
            agent_dict = cached_cloud.get(key)
            if agent_dict is None and agent_type == AgentType.OPERATOR:
                agent_dict = cached_cloud.get("HOST_AGENT", {})
            if isinstance(agent_dict, dict):
                return dict(agent_dict)
            raise ValueError(f"Agent block '{key}' not found in active cloud configuration")

    # UFO agents (from config/ufo/agents.yaml)
    if agent_type in [
        AgentType.HOST,
        AgentType.APP,
        AgentType.BACKUP,
        AgentType.EVALUATION,
        AgentType.OPERATOR,
        AgentType.PREFILL,
        AgentType.FILTER,
    ]:
        ufo_config = get_ufo_config()

        # Map AgentType to typed config attributes
        agent_config_map = {
            AgentType.HOST: ufo_config.host_agent,
            AgentType.APP: ufo_config.app_agent,
            AgentType.BACKUP: ufo_config.backup_agent,
            AgentType.EVALUATION: ufo_config.evaluation_agent,
            AgentType.OPERATOR: ufo_config.operator,
            AgentType.PREFILL: ufo_config.host_agent,  # Prefill uses HOST_AGENT config
            AgentType.FILTER: ufo_config.host_agent,  # Filter uses HOST_AGENT config
        }

        agent_config = agent_config_map.get(agent_type)
        if agent_config is None:
            raise ValueError(f"Agent type {agent_type} not found in UFO config")

        # Convert to dict for backward compatibility
        return _config_to_dict(agent_config)

    # Galaxy constellation agent (from config/galaxy/agent.yaml)
    elif agent_type == AgentType.CONSTELLATION:
        galaxy_config = get_galaxy_config()
        constellation_agent_config = galaxy_config.agent.constellation_agent

        if constellation_agent_config is None:
            raise ValueError("CONSTELLATION_AGENT not found in Galaxy config")

        return _config_to_dict(constellation_agent_config)

    else:
        raise ValueError(f"Unsupported agent type: {agent_type}")


def _config_to_dict(config_obj: Any) -> Dict[str, Any]:
    """
    Convert config object to dictionary with both uppercase and lowercase keys.

    This ensures backward compatibility with code expecting dict access while
    also supporting the new typed config objects.

    :param config_obj: Config object (AgentConfig or similar)
    :return: Dictionary representation with uppercase keys
    """
    if hasattr(config_obj, "to_dict"):
        return config_obj.to_dict()

    # Fallback: create dict from object attributes
    config_dict = {}
    for attr in dir(config_obj):
        if not attr.startswith("_") and not callable(getattr(config_obj, attr)):
            value = getattr(config_obj, attr)
            # Store with uppercase key for compatibility
            config_dict[attr.upper()] = value

    return config_dict


class AgentConfigAccessor:
    """
    Wrapper class that provides both dict-style and attribute access to agent configs.

    This class wraps the typed config objects to provide backward compatibility
    with code expecting dictionary access (config['API_TYPE']) while also
    supporting modern attribute access (config.api_type).
    """

    def __init__(self, config_obj: Any):
        """
        Initialize accessor with config object.

        :param config_obj: Config object (AgentConfig or similar)
        """
        self._config_obj = config_obj
        self._dict_cache = None

    def __getitem__(self, key: str) -> Any:
        """Support dict-style access: config['API_TYPE']"""
        # Try direct attribute access on config object (handles uppercase automatically)
        try:
            return getattr(self._config_obj, key)
        except AttributeError:
            pass

        # Try lowercase
        try:
            return getattr(self._config_obj, key.lower())
        except AttributeError:
            pass

        # Fallback to dict
        if self._dict_cache is None:
            self._dict_cache = _config_to_dict(self._config_obj)

        if key in self._dict_cache:
            return self._dict_cache[key]

        raise KeyError(f"Config key '{key}' not found")

    def __getattr__(self, name: str) -> Any:
        """Support attribute access: config.api_type"""
        if name.startswith("_"):
            return object.__getattribute__(self, name)
        return getattr(self._config_obj, name)

    def __contains__(self, key: str) -> bool:
        """Support 'in' operator: 'API_TYPE' in config"""
        try:
            self[key]
            return True
        except (KeyError, AttributeError):
            return False

    def get(self, key: str, default: Any = None) -> Any:
        """Support dict.get(): config.get('API_TYPE', 'default')"""
        try:
            return self[key]
        except (KeyError, AttributeError):
            return default

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        if self._dict_cache is None:
            self._dict_cache = _config_to_dict(self._config_obj)
        return self._dict_cache.copy()
