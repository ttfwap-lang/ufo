"""
Unified agent configuration getter for LLM calls.

This module provides a unified way to get agent configurations from different
config files based on AgentType. It also supports mapping the OPERATOR AgentType
to HOST_AGENT, and the CONSTELLATION AgentType to Galaxy paths.
"""
import copy
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional
import urllib.request
import yaml
from ufo.llm import AgentType
from ufo.config.config_loader import get_galaxy_config, ConfigLoader
logger = logging.getLogger(__name__)

class BackendProfileError(RuntimeError):
    """Raised when a backend profile is missing, malformed, or unresolvable."""
    pass
_route_lock = threading.RLock()
_process_override: Optional[str] = None
_process_override_cache: Optional[Dict[str, Any]] = None
_profile_cache: Dict[str, Any] = {}
_auto_probe_memo: Optional[bool] = None

def reset_backend_caches(clear_override: bool=False) -> None:
    """Clear resolver caches and optionally the process override."""
    global _auto_probe_memo, _process_override, _process_override_cache
    with _route_lock:
        _profile_cache.clear()
        _auto_probe_memo = None
        if clear_override:
            _process_override = None
            _process_override_cache = None

def _probe_endpoint(url: str, timeout: float=2.0) -> bool:
    try:
        req = urllib.request.Request(url, method='GET')
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False

def _probe_local_auto() -> bool:
    if _probe_endpoint('http://127.0.0.1:4000/health'):
        return True
    if _probe_endpoint('http://127.0.0.1:8080/health') or _probe_endpoint('http://127.0.0.1:8081/health'):
        return True
    return False

def get_backend_selection() -> dict:
    """
    Get the current backend selection from backend_state.json.
    A missing or unknown selection, or a corrupt state (e.g. 'profile' without a path),
    degrades to 'disk'. A valid state pointing at a broken profile fails loudly elsewhere.
    """
    loader = ConfigLoader.get_instance()
    state_path = loader.base_path / 'ufo' / 'backend_state.json'
    if not state_path.exists():
        return {'selected': 'disk', 'source': 'default'}
    try:
        with open(state_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict) and 'selected' in data:
                if data['selected'] not in ['local', 'cloud', 'auto', 'profile', 'disk']:
                    return {'selected': 'disk', 'source': 'default'}
                if data['selected'] == 'profile' and (not isinstance(data.get('profile_path'), str)):
                    logger.warning("Corrupt state: 'profile' selected but 'profile_path' missing or invalid. Degrading to 'disk'.")
                    return {'selected': 'disk', 'source': 'default'}
                data['source'] = 'state-file'
                return copy.deepcopy(data)
    except Exception as e:
        logger.warning('Failed to read backend_state.json, falling back to disk configuration: %s', e)
    return {'selected': 'disk', 'source': 'default'}

def set_backend_selection(selection: str, profile_path: Optional[str]=None, updated_by: str='api') -> dict:
    loader = ConfigLoader.get_instance()
    state_path = loader.base_path / 'ufo' / 'backend_state.json'
    if selection not in ['local', 'cloud', 'auto', 'profile', 'disk']:
        raise ValueError(f'Unknown selection: {selection}')
    if selection == 'profile' and (not profile_path):
        raise ValueError('Profile selection requires profile_path')
    resolved_auto = None
    if selection == 'auto':
        is_local = _probe_local_auto()
        resolved_auto = 'local' if is_local else 'cloud'
    if selection != 'disk':
        validation_target = resolved_auto if selection == 'auto' else selection
        prof = resolve_backend_profile(validation_target, profile_path)
        if not prof:
            raise BackendProfileError(f'Invalid or missing profile for selection: {selection}')
    state = {'selected': selection, 'updated_at': datetime.now(timezone.utc).isoformat(), 'updated_by': updated_by}
    if profile_path:
        state['profile_path'] = profile_path
    if resolved_auto:
        state['resolved'] = resolved_auto
    with _route_lock:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = str(state_path) + '.tmp'
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, state_path)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        reset_backend_caches(clear_override=False)
    return state

def _get_file_stat_key(path: Path) -> str:
    try:
        stat = path.stat()
        return f'{stat.st_mtime_ns}:{stat.st_size}'
    except Exception:
        return '0:0'

def resolve_backend_profile(selection: Optional[str]=None, profile_path: Optional[str]=None) -> Optional[Dict[str, Any]]:
    global _auto_probe_memo
    loader = ConfigLoader.get_instance()
    state_path = loader.base_path / 'ufo' / 'backend_state.json'
    state = get_backend_selection()
    if selection is None:
        selection = state.get('selected', 'disk')
        profile_path = state.get('profile_path')
    actual_selection = selection
    if selection == 'auto':
        with _route_lock:
            if _auto_probe_memo is None:
                _auto_probe_memo = _probe_local_auto()
            actual_selection = 'local' if _auto_probe_memo else 'cloud'
    ufo_dir = loader.base_path / 'ufo'
    if actual_selection == 'cloud':
        target_path = ufo_dir / 'agents_cloud.yaml'
    elif actual_selection == 'local':
        target_path = ufo_dir / 'agents_local_vision.yaml'
    elif actual_selection == 'profile' and profile_path:
        target_path = Path(profile_path)
    elif actual_selection == 'disk':
        target_path = ufo_dir / 'agents.yaml'
    else:
        return None
    state_stat = _get_file_stat_key(state_path)
    target_stat = _get_file_stat_key(target_path)
    cache_key = f'{selection}:{profile_path}:{state_stat}:{target_stat}'
    with _route_lock:
        if cache_key in _profile_cache:
            return copy.deepcopy(_profile_cache[cache_key]['data'])
    if not target_path.exists():
        raise BackendProfileError(f'Target profile path does not exist: {target_path}')
    try:
        with open(target_path, 'r', encoding='utf-8') as f:
            raw_data = yaml.safe_load(f.read())
        if not isinstance(raw_data, dict):
            raise BackendProfileError(f'Profile is not a dict: {target_path}')
        data = copy.deepcopy(raw_data)
        data = loader._expand_env_vars(data)
        loader._apply_env_overrides(data, prefix='UFO_', reserved_suffixes=('ENV', 'ROOT', 'DIR'))
        loader._apply_legacy_transforms(data)
        host = data.get('HOST_AGENT')
        app = data.get('APP_AGENT')
        if not isinstance(host, dict) or not isinstance(app, dict):
            raise BackendProfileError(f'Profile missing HOST_AGENT or APP_AGENT dicts: {target_path}')
        with _route_lock:
            _profile_cache[cache_key] = {'data': copy.deepcopy(data)}
        return copy.deepcopy(data)
    except BackendProfileError:
        raise
    except Exception as e:
        raise BackendProfileError(f'Failed to load profile {target_path}: {e}')

def set_process_override(selection: str) -> bool:
    global _process_override, _process_override_cache
    try:
        prof = resolve_backend_profile(selection)
    except BackendProfileError as e:
        logger.error(f'Process override failed: {e}')
        return False
    if not prof:
        logger.error(f'Process override failed: profile unresolved for {selection}')
        return False
    with _route_lock:
        _process_override = selection
        _process_override_cache = copy.deepcopy(prof)
    return True

def clear_process_override() -> None:
    global _process_override, _process_override_cache
    with _route_lock:
        _process_override = None
        _process_override_cache = None

def set_active_agent_route(route: Optional[str]) -> bool:
    """
    Set process-local memory override.
    Passing None clears the process override and restores persisted intent.
    """
    if route:
        return set_process_override(route)
    clear_process_override()
    return True

def get_active_agent_route() -> Optional[str]:
    with _route_lock:
        return _process_override

def resolve_agent_config(agent_type: str) -> Dict[str, Any]:
    with _route_lock:
        current_route = _process_override
        cached_override = _process_override_cache
    if current_route and cached_override:
        prof = copy.deepcopy(cached_override)
    else:
        try:
            prof = resolve_backend_profile()
        except BackendProfileError as e:
            state = get_backend_selection()
            raise BackendProfileError(f"Resolution failed for active selection '{state.get('selected', 'unknown')}': {e}") from e
    if prof:
        cloud_map = {AgentType.HOST: 'HOST_AGENT', AgentType.APP: 'APP_AGENT', AgentType.BACKUP: 'BACKUP_AGENT', AgentType.EVALUATION: 'EVALUATION_AGENT', AgentType.OPERATOR: 'OPERATOR', AgentType.PREFILL: 'HOST_AGENT', AgentType.FILTER: 'HOST_AGENT'}
        if agent_type in cloud_map:
            key = cloud_map[agent_type]
            agent_dict = prof.get(key)
            if agent_dict is None and agent_type == AgentType.OPERATOR:
                agent_dict = prof.get('HOST_AGENT', {})
            if isinstance(agent_dict, dict):
                return copy.deepcopy(agent_dict)
            state = get_backend_selection()
            raise BackendProfileError(f"Agent block '{key}' not found in resolved configuration for selection '{state.get('selected')}'")
    if agent_type == AgentType.CONSTELLATION:
        galaxy_config = get_galaxy_config()
        constellation_agent_config = galaxy_config.agent.constellation_agent
        if constellation_agent_config is None:
            raise ValueError('CONSTELLATION_AGENT not found in Galaxy config')
        return copy.deepcopy(_config_to_dict(constellation_agent_config))
    state = get_backend_selection()
    raise BackendProfileError(f"Could not resolve agent config for '{agent_type}' under active selection '{state.get('selected', 'unknown')}'")

def get_agent_config(agent_type: str) -> Dict[str, Any]:
    return resolve_agent_config(agent_type)

def _config_to_dict(config_obj: Any) -> Dict[str, Any]:
    if hasattr(config_obj, 'to_dict'):
        return config_obj.to_dict()
    config_dict = {}
    for attr in dir(config_obj):
        if not attr.startswith('_') and (not callable(getattr(config_obj, attr))):
            value = getattr(config_obj, attr)
            config_dict[attr.upper()] = value
    return config_dict

class AgentConfigAccessor:

    def __init__(self, config_obj: Any):
        self._config_obj = config_obj
        self._dict_cache = None

    def __getitem__(self, key: str) -> Any:
        try:
            return getattr(self._config_obj, key)
        except AttributeError:
            pass
        try:
            return getattr(self._config_obj, key.lower())
        except AttributeError:
            pass
        if self._dict_cache is None:
            self._dict_cache = _config_to_dict(self._config_obj)
        if key in self._dict_cache:
            return self._dict_cache[key]
        raise KeyError(f"Config key '{key}' not found")

    def __getattr__(self, name: str) -> Any:
        if name.startswith('_'):
            return object.__getattribute__(self, name)
        return getattr(self._config_obj, name)

    def __contains__(self, key: str) -> bool:
        try:
            self[key]
            return True
        except (KeyError, AttributeError):
            return False

    def get(self, key: str, default: Any=None) -> Any:
        try:
            return self[key]
        except (KeyError, AttributeError):
            return default

    def to_dict(self) -> Dict[str, Any]:
        if self._dict_cache is None:
            self._dict_cache = _config_to_dict(self._config_obj)
        return self._dict_cache.copy()