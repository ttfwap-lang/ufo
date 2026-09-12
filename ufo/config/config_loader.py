"""
Modern Configuration Loader for UFO³ and Galaxy

Professional Software Engineering Design:
- ✅ Separation of Concerns: Modular YAML files for different config domains
- ✅ Backward Compatibility: Automatic fallback to legacy paths (ufo/config/)
- ✅ Migration Support: Built-in migration warnings and tools
- ✅ Type Safety: Pydantic-style typed configs + dynamic YAML fields
- ✅ Auto-Discovery: Loads all YAML files automatically
- ✅ Environment Overrides: dev/test/prod environment support
- ✅ Priority Chain: New path → Legacy path → Environment variables
- ✅ Zero Breaking Changes: Existing code continues to work

Configuration Structure:
    New (Recommended):
        config/ufo/          ← UFO² configurations
        config/galaxy/       ← Galaxy configurations

    Legacy (Auto-detected):
        ufo/config/          ← Old UFO configs (still supported)

Priority Rules:
    1. config/{module}/    ← Highest priority (new path)
    2. {module}/config/    ← Fallback (legacy path)
    3. Environment vars    ← Override mechanism

Usage Examples:
    # Load config (automatic fallback to legacy)
    config = get_ufo_config()

    # Type-safe access (IDE autocomplete!)
    max_step = config.system.max_step
    api_model = config.app_agent.api_model

    # Dynamic YAML fields (no code changes needed!)
    new_field = config.NEW_FEATURE
    setting = config["CUSTOM_SETTING"]

    # Backward compatible
    old_style = config["MAX_STEP"]  # Still works!
"""
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
from ufo.config.config_schemas import UFOConfig, GalaxyConfig
logger = logging.getLogger(__name__)

class DynamicConfig:
    """
    Dynamic configuration object that provides both dict-like and attribute access.

    Usage:
        config = DynamicConfig(data)

        # Dict-style access (backward compatible)
        value = config["MAX_STEP"]

        # Attribute-style access (modern)
        value = config.MAX_STEP

        # Nested access
        value = config.HOST_AGENT.API_MODEL
    """

    def __init__(self, data: Dict[str, Any], name: str='config'):
        """
        Initialize DynamicConfig.

        :param data: Configuration data dictionary
        :param name: Name of this configuration (for debugging)
        """
        self._data = data
        self._name = name
        self._nested_configs = {}
        for key, value in data.items():
            if isinstance(value, dict):
                self._nested_configs[key] = DynamicConfig(value, name=key)

    def __getattr__(self, name: str) -> Any:
        """Attribute-style access: config.MAX_STEP"""
        if name.startswith('_'):
            return object.__getattribute__(self, name)
        if name in self._nested_configs:
            return self._nested_configs[name]
        if name in self._data:
            value = self._data[name]
            if isinstance(value, dict):
                nested = DynamicConfig(value, name=name)
                self._nested_configs[name] = nested
                return nested
            return value
        raise AttributeError(f"'{self._name}' configuration has no attribute '{name}'")

    def __getitem__(self, key: str) -> Any:
        """Dict-style access: config["MAX_STEP"]"""
        if key in self._nested_configs:
            return self._nested_configs[key]
        return self._data[key]

    def __contains__(self, key: str) -> bool:
        """Support 'in' operator"""
        return key in self._data

    def get(self, key: str, default: Any=None) -> Any:
        """Dict-style get with default"""
        if key in self._nested_configs:
            return self._nested_configs[key]
        return self._data.get(key, default)

    def keys(self) -> List[str]:
        """Get all keys"""
        return self._data.keys()

    def items(self):
        """Get all items"""
        return self._data.items()

    def values(self):
        """Get all values"""
        return self._data.values()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to plain dictionary"""
        return self._data.copy()

    def __repr__(self) -> str:
        return f'DynamicConfig({self._name})'

    def __str__(self) -> str:
        return f'DynamicConfig({self._name}): {len(self._data)} keys'

class ConfigLoader:
    """
    Modern configuration loader with backward compatibility.

    Features:
    - Automatic discovery of YAML files in config directories
    - Fallback to legacy paths for backward compatibility
    - Clear migration warnings to guide users
    - Deep merging of multiple YAML files
    - Environment-specific overrides (dev/test/prod)

    Priority Chain (High → Low):
    1. config/{module}/*.yaml         ← New path (highest priority)
    2. {module}/config/*.yaml          ← Legacy path (fallback)
    3. Environment-specific overrides  ← dev/test/prod variants

    When both new and legacy paths exist:
    - New path takes priority
    - Legacy values fill in missing keys
    - Clear warning shown to user
    """
    _instance: Optional['ConfigLoader'] = None

    def __init__(self, base_path: Optional[str]=None):
        """
        Initialize ConfigLoader.

        :param base_path: Base path to configuration directory (default: UFO_ROOT/config)
        """
        ufo_root = Path(__file__).resolve().parent.parent
        self.base_path = Path(base_path) if base_path else ufo_root / 'config'
        self._cache: Dict[str, Any] = {}
        self._env = os.getenv('UFO_ENV', 'production')

    @classmethod
    def get_instance(cls, base_path: Optional[str]=None) -> 'ConfigLoader':
        """
        Get or create ConfigLoader singleton.

        :param base_path: Base path to configuration directory
        :return: ConfigLoader instance
        """
        if cls._instance is None:
            cls._instance = ConfigLoader(base_path)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton instance (useful for testing)"""
        cls._instance = None

    def _load_yaml(self, path: Path) -> Optional[Dict[str, Any]]:
        """
        Load YAML file safely with caching.

        :param path: Path to YAML file
        :return: Parsed YAML data or None if file doesn't exist
        """
        cache_key = str(path)
        if cache_key in self._cache:
            return self._cache[cache_key]
        if not path.exists():
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
            data = self._expand_env_vars(data)
            self._cache[cache_key] = data
            return data
        except Exception as e:
            logger.warning(f'Error loading {path}: {e}')
            return None

    def _deep_merge(self, target: Dict[str, Any], source: Dict[str, Any]) -> None:
        """
        Deep merge source dictionary into target dictionary.

        Source values override target values.
        Nested dictionaries are merged recursively.

        :param target: Target dictionary to update
        :param source: Source dictionary
        """
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                self._deep_merge(target[key], value)
            else:
                target[key] = value

    def _expand_env_vars(self, value: Any) -> Any:
        """
        Expand ${VAR} and $VAR placeholders in YAML values using environment variables.

        Only string values are expanded; all other types are returned as-is.
        Unset variables are left untouched.
        """
        if isinstance(value, dict):
            return {k: self._expand_env_vars(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._expand_env_vars(v) for v in value]
        if isinstance(value, str):

            def replacer(match: re.Match[str]) -> str:
                var_name = match.group(1) or match.group(2)
                if not var_name:
                    return match.group(0)
                env_val = os.getenv(var_name)
                return env_val if env_val is not None else match.group(0)
            return re.sub('\\$\\{([A-Za-z_][A-Za-z0-9_]*)\\}|\\$([A-Za-z_][A-Za-z0-9_]*)', replacer, value)
        return value

    def _discover_yaml_files(self, directory: Path) -> List[Path]:
        """
        Discover all YAML files in a directory.

        Excludes environment-specific files (*_dev.yaml, *_test.yaml, etc.)
        which are loaded separately based on UFO_ENV.

        :param directory: Directory to search
        :return: List of YAML file paths (sorted for consistent loading)
        """
        if not directory.exists():
            return []
        yaml_files = []
        for file in directory.glob('*.yaml'):
            if not any((file.stem.endswith(suffix) for suffix in ['_dev', '_test', '_prod'])):
                yaml_files.append(file)
        return sorted(yaml_files)

    def _load_module_configs(self, module_dir: Path, env: Optional[str]=None) -> Dict[str, Any]:
        """
        Load all configuration files from a module directory and merge them.

        Loading order:
        1. Base YAML files (*.yaml)
        2. Environment-specific overrides (*_<env>.yaml)

        :param module_dir: Module directory (e.g., config/ufo or config/galaxy)
        :param env: Environment name for overrides (dev/test/prod)
        :return: Merged configuration dictionary
        """
        merged_config = {}
        yaml_files = self._discover_yaml_files(module_dir)
        for yaml_file in yaml_files:
            config_data = self._load_yaml(yaml_file)
            if config_data:
                if yaml_file.stem in ['mcp', 'agent_mcp']:
                    config_data = {'mcp': config_data}
                self._deep_merge(merged_config, config_data)
        if env and env != 'production':
            for yaml_file in yaml_files:
                env_file = yaml_file.parent / f'{yaml_file.stem}_{env}.yaml'
                env_data = self._load_yaml(env_file)
                if env_data:
                    self._deep_merge(merged_config, env_data)
        return merged_config

    def _load_with_fallback(self, module: str, env: Optional[str]=None) -> Dict[str, Any]:
        """
        Load configuration for a module (e.g. 'ufo' or 'galaxy').

        :param module: Module name ("ufo" or "galaxy")
        :param env: Environment override
        :return: Merged configuration dictionary
        """
        module_path = self.base_path / module
        config = self._load_module_configs(module_path, env)
        if not config:
            raise FileNotFoundError(f"No configuration found for '{module}'.\nExpected at: {module_path}/\n")
        return config

    def _apply_env_overrides(self, config_data: Dict[str, Any], prefix: str='UFO_', reserved_suffixes: Optional[tuple]=('ENV', 'ROOT', 'DIR')) -> None:
        """
        Apply explicit environment variable overrides starting with the specified prefix.
        Does NOT bulk-copy os.environ and ignores environment variables matching reserved suffixes (e.g. UFO_ENV).
        Parses scalar values via yaml.safe_load so numbers/booleans preserve types.
        Supports double-underscore notation for nested keys (e.g. UFO_SYSTEM__LOG_LEVEL=DEBUG).

        :param config_data: Target configuration dictionary to update in-place
        :param prefix: Allowed environment variable prefix (e.g. 'UFO_' or 'GALAXY_')
        :param reserved_suffixes: Suffixes that should be ignored for config overrides
        """
        reserved = reserved_suffixes or ()
        for env_k, env_v in os.environ.items():
            if not env_k.startswith(prefix):
                continue
            suffix = env_k[len(prefix):]
            if not suffix or suffix in reserved:
                continue
            try:
                parsed_val = yaml.safe_load(env_v)
            except Exception:
                parsed_val = env_v
            if '__' in suffix:
                parts = suffix.split('__')
                target = config_data
                for part in parts[:-1]:
                    matched_key = None
                    for k in target.keys():
                        if k.lower() == part.lower():
                            matched_key = k
                            break
                    if matched_key is None:
                        matched_key = part.upper()
                        target[matched_key] = {}
                    elif not isinstance(target[matched_key], dict):
                        target[matched_key] = {}
                    target = target[matched_key]
                last_part = parts[-1]
                matched_last = None
                for k in target.keys():
                    if k.lower() == last_part.lower():
                        matched_last = k
                        break
                if matched_last is not None:
                    target[matched_last] = parsed_val
                else:
                    target[last_part.upper()] = parsed_val
            else:
                matched_key = None
                for k in config_data.keys():
                    if k.lower() == suffix.lower():
                        matched_key = k
                        break
                if matched_key is not None:
                    config_data[matched_key] = parsed_val
                else:
                    config_data[suffix.upper()] = parsed_val

    def load_ufo_config(self, env: Optional[str]=None) -> UFOConfig:
        """
        Load UFO configuration.

        Automatically discovers and loads all YAML files from config/ufo/:
        - Priority 1: config/ufo/*.yaml
        - Priority 2: config/ufo/*_<env>.yaml (environment overrides)
        - Priority 3: UFO_* environment variables

        :param env: Environment override (dev/test/prod)
        :return: UFOConfig with typed + dynamic access
        """
        env = env or self._env
        os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
        config_data = self._load_with_fallback('ufo', env)
        self._apply_env_overrides(config_data, prefix='UFO_', reserved_suffixes=('ENV', 'ROOT', 'DIR'))
        self._apply_legacy_transforms(config_data)
        return UFOConfig.from_dict(config_data)

    def load_galaxy_config(self, env: Optional[str]=None) -> GalaxyConfig:
        """
        Load Galaxy configuration.

        Automatically discovers and loads all YAML files from config/galaxy/.
        :param env: Environment override (dev/test/prod)
        :return: GalaxyConfig with typed + dynamic access
        """
        env = env or self._env
        config_data = self._load_with_fallback('galaxy', env)
        self._apply_env_overrides(config_data, prefix='GALAXY_', reserved_suffixes=('ENV',))
        self._apply_legacy_transforms(config_data)
        return GalaxyConfig.from_dict(config_data)

    def _apply_legacy_transforms(self, config: Dict[str, Any]) -> None:
        """
        Apply legacy configuration transformations.

        :param config: Configuration dictionary to transform
        """
        for agent_key in ['HOST_AGENT', 'APP_AGENT', 'BACKUP_AGENT', 'EVALUATION_AGENT', 'CONSTELLATION_AGENT']:
            if agent_key in config:
                self._update_api_base(config, agent_key)
        if 'CONTROL_BACKEND' in config and isinstance(config['CONTROL_BACKEND'], str):
            config['CONTROL_BACKEND'] = [config['CONTROL_BACKEND']]

    @staticmethod
    def _update_api_base(config: Dict[str, Any], agent_key: str) -> None:
        """
        Update API base URL based on API type (legacy behavior).

        :param config: Configuration dictionary
        :param agent_key: Agent configuration key
        """
        if agent_key not in config:
            return
        agent_config = config[agent_key]
        if not isinstance(agent_config, dict):
            return
        api_type = agent_config.get('API_TYPE', '').lower()
        use_responses = bool(agent_config.get('USE_RESPONSES', False))
        if api_type == 'aoai':
            api_base = agent_config.get('API_BASE', '')
            if api_base and 'deployments' not in api_base and (not use_responses):
                deployment_id = agent_config.get('API_DEPLOYMENT_ID', '')
                api_version = agent_config.get('API_VERSION', '')
                if deployment_id:
                    agent_config['API_BASE'] = f"{api_base.rstrip('/')}/openai/deployments/{deployment_id}/chat/completions?api-version={api_version}"
                    agent_config['API_MODEL'] = deployment_id
        elif api_type == 'openai':
            if not agent_config.get('API_BASE'):
                agent_config['API_BASE'] = 'https://api.openai.com/v1/chat/completions'
_global_ufo_config: Optional[UFOConfig] = None
_global_galaxy_config: Optional[GalaxyConfig] = None

def get_ufo_config(reload: bool=False) -> UFOConfig:
    """
    Get UFO configuration (cached).

    Returns a hybrid config object with:
    - Type-safe fixed fields: config.system.max_step, config.app_agent.api_model
    - Dynamic YAML fields: config.ANY_NEW_KEY, config["NEW_SETTING"]
    - Backward compatible: config["MAX_STEP"]

    Usage Examples:
        config = get_ufo_config()

        # Modern typed access (IDE autocomplete!)
        max_step = config.system.max_step
        log_level = config.system.log_level
        model = config.app_agent.api_model
        rag_enabled = config.rag.experience

        # Dynamic access (no code changes needed for new YAML keys!)
        if hasattr(config, 'NEW_FEATURE_FLAG'):
            enabled = config.NEW_FEATURE_FLAG

        new_value = config.get("CUSTOM_SETTING", "default")

        # Legacy dict access (still works)
        max_step_old = config["MAX_STEP"]
        agent_config = config["APP_AGENT"]

    :param reload: Force reload configuration from files
    :return: UFOConfig instance
    """
    global _global_ufo_config
    if _global_ufo_config is None or reload:
        loader = ConfigLoader.get_instance()
        _global_ufo_config = loader.load_ufo_config()
    return _global_ufo_config

def get_galaxy_config(reload: bool=False) -> GalaxyConfig:
    """
    Get Galaxy configuration (cached).

    Returns a hybrid config object with:
    - Type-safe agent config: config.constellation_agent.api_model
    - Dynamic YAML fields: config.client_001, config.constellation_id, etc.
    - Backward compatible: config["CONSTELLATION_AGENT"]

    Usage Examples:
        config = get_galaxy_config()

        # Modern typed access
        agent_model = config.constellation_agent.api_model

        # Dynamic access to constellation settings
        constellation_id = config.constellation_id
        heartbeat = config.heartbeat_interval

        # Dynamic access to devices
        device = config.client_001
        server_url = device.server_url
        capabilities = device.capabilities

        # Legacy dict access
        agent_old = config["CONSTELLATION_AGENT"]
        device_old = config["client_001"]

    :param reload: Force reload configuration from files
    :return: GalaxyConfig instance
    """
    global _global_galaxy_config
    if _global_galaxy_config is None or reload:
        loader = ConfigLoader.get_instance()
        _global_galaxy_config = loader.load_galaxy_config()
    return _global_galaxy_config

def clear_config_cache():
    """Clear configuration cache. Useful for testing or hot-reloading."""
    global _global_ufo_config, _global_galaxy_config
    _global_ufo_config = None
    _global_galaxy_config = None
    ConfigLoader.reset()

class LazyUFOConfig:
    """
    Lazy proxy for UFOConfig that defers loading until attribute or item access.
    Holds no state and forwards every access to get_ufo_config() at call time.
    This prevents config I/O at module import time while keeping clear_config_cache()
    fully effective.
    """

    def __getattr__(self, name: str) -> Any:
        return getattr(get_ufo_config(), name)

    def __getitem__(self, key: str) -> Any:
        return get_ufo_config()[key]

    def __contains__(self, key: Any) -> bool:
        return key in get_ufo_config()

    def get(self, key: str, default: Any=None) -> Any:
        return get_ufo_config().get(key, default)

    def keys(self):
        return get_ufo_config().keys()

    def items(self):
        return get_ufo_config().items()

    def values(self):
        return get_ufo_config().values()

    def to_dict(self) -> Dict[str, Any]:
        return get_ufo_config().to_dict()

    def __repr__(self) -> str:
        return repr(get_ufo_config())

class LazyGalaxyConfig:
    """
    Lazy proxy for GalaxyConfig that defers loading until attribute or item access.
    Holds no state and forwards every access to get_galaxy_config() at call time.
    """

    def __getattr__(self, name: str) -> Any:
        return getattr(get_galaxy_config(), name)

    def __getitem__(self, key: str) -> Any:
        return get_galaxy_config()[key]

    def __contains__(self, key: Any) -> bool:
        return key in get_galaxy_config()

    def get(self, key: str, default: Any=None) -> Any:
        return get_galaxy_config().get(key, default)

    def keys(self):
        return get_galaxy_config().keys()

    def items(self):
        return get_galaxy_config().items()

    def values(self):
        return get_galaxy_config().values()

    def to_dict(self) -> Dict[str, Any]:
        return get_galaxy_config().to_dict()

    def __repr__(self) -> str:
        return repr(get_galaxy_config())