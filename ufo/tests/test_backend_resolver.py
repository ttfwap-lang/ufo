import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import pytest
import yaml
from ufo.llm.config_helper import BackendProfileError, get_agent_config, get_backend_selection, reset_backend_caches, resolve_backend_profile, set_active_agent_route, set_backend_selection, set_process_override
from ufo.llm import AgentType
from ufo.config.config_loader import ConfigLoader, clear_config_cache

def create_minimal_profile(model_name: str) -> dict:
    return {'HOST_AGENT': {'API_TYPE': 'openai', 'API_MODEL': model_name}, 'APP_AGENT': {'API_TYPE': 'openai', 'API_MODEL': model_name}}

def write_yaml(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        yaml.safe_dump(data, f)

def hash_directory(dir_path: Path) -> dict:
    hashes = {}
    if not dir_path.exists():
        return hashes
    for root, _, files in os.walk(str(dir_path)):
        for f in files:
            path = Path(root) / f
            try:
                with open(path, 'rb') as file_obj:
                    hashes[str(path.relative_to(dir_path))] = hashlib.sha256(file_obj.read()).hexdigest()
            except Exception:
                pass
    return hashes

@pytest.fixture
def temp_config_root(tmp_path):
    config_dir = tmp_path / 'config'
    ufo_dir = config_dir / 'ufo'
    ufo_dir.mkdir(parents=True)
    write_yaml(ufo_dir / 'agents.yaml', create_minimal_profile('disk_model'))
    write_yaml(ufo_dir / 'agents_cloud.yaml', create_minimal_profile('cloud_model'))
    write_yaml(ufo_dir / 'agents_local_vision.yaml', create_minimal_profile('local_model'))
    write_yaml(ufo_dir / 'system.yaml', {'UFO_ROOT': str(tmp_path), 'LOG_LEVEL': 'INFO'})
    ConfigLoader.reset()
    clear_config_cache()
    ConfigLoader.get_instance(str(config_dir))
    reset_backend_caches(clear_override=True)
    yield config_dir
    ConfigLoader.reset()
    clear_config_cache()
    reset_backend_caches(clear_override=True)

def test_state_round_trip(temp_config_root):
    profile_path = str(temp_config_root.parent / 'custom.yaml')
    write_yaml(Path(profile_path), create_minimal_profile('custom_model'))
    state = set_backend_selection('profile', profile_path=profile_path, updated_by='test')
    assert state['selected'] == 'profile'
    assert state['profile_path'] == profile_path
    assert state['updated_by'] == 'test'
    read_state = get_backend_selection()
    assert read_state['selected'] == 'profile'
    assert read_state['profile_path'] == profile_path
    assert read_state['source'] == 'state-file'
    assert 'updated_at' in read_state
    state_file = temp_config_root / 'ufo' / 'backend_state.json'
    content = state_file.read_text(encoding='utf-8')
    assert 'API_KEY' not in content
    assert 'HOST_AGENT' not in content

@pytest.mark.parametrize('state_content, is_raw', [(None, False), ('', True), ('hello', True), (['a'], False), ({'selected': 'invalid'}, False), ({'selected': 'profile'}, False)])
def test_degradation_matrix(temp_config_root, state_content, is_raw):
    state_file = temp_config_root / 'ufo' / 'backend_state.json'
    if state_content is not None:
        if is_raw:
            state_file.write_text(state_content, encoding='utf-8')
        else:
            state_file.write_text(json.dumps(state_content), encoding='utf-8')
    state = get_backend_selection()
    assert state['selected'] == 'disk'
    cfg = get_agent_config(AgentType.HOST)
    assert cfg['API_MODEL'] == 'disk_model'

def test_disk_fallback_ignores_other_profiles(temp_config_root):
    """Prove that profile YAMLs (cloud/local) cannot override the disk fallback."""
    write_yaml(temp_config_root / 'ufo' / 'agents_local_vision.yaml', create_minimal_profile('sneaky_local_override'))
    write_yaml(temp_config_root / 'ufo' / 'agents_cloud.yaml', create_minimal_profile('sneaky_cloud_override'))
    state_file = temp_config_root / 'ufo' / 'backend_state.json'
    if state_file.exists():
        state_file.unlink()
    reset_backend_caches(clear_override=True)
    cfg = get_agent_config(AgentType.HOST)
    assert cfg['API_MODEL'] == 'disk_model', 'Disk fallback must load only agents.yaml, not merge other profile YAMLs'

def test_resolution_kinds(temp_config_root):
    set_backend_selection('cloud')
    assert get_agent_config(AgentType.HOST)['API_MODEL'] == 'cloud_model'
    set_backend_selection('local')
    assert get_agent_config(AgentType.HOST)['API_MODEL'] == 'local_model'
    custom_path = temp_config_root.parent / 'custom.yaml'
    write_yaml(custom_path, create_minimal_profile('custom_model'))
    set_backend_selection('profile', profile_path=str(custom_path))
    assert get_agent_config(AgentType.HOST)['API_MODEL'] == 'custom_model'

def test_loud_failure(temp_config_root):
    set_backend_selection('cloud')
    cloud_file = temp_config_root / 'ufo' / 'agents_cloud.yaml'
    cloud_file.unlink()
    with pytest.raises(BackendProfileError):
        get_agent_config(AgentType.HOST)

def test_auto_resolution(temp_config_root, monkeypatch):
    probe_count = 0

    def stub_probe():
        nonlocal probe_count
        probe_count += 1
        return True
    import ufo.llm.config_helper as ch
    monkeypatch.setattr(ch, '_probe_local_auto', stub_probe)
    set_backend_selection('auto')
    initial_probe_count = probe_count
    reset_backend_caches(clear_override=True)
    assert get_agent_config(AgentType.HOST)['API_MODEL'] == 'local_model'
    probe_after_first_read = probe_count
    assert probe_after_first_read == initial_probe_count + 1
    for _ in range(5):
        get_agent_config(AgentType.HOST)
        get_backend_selection()
    assert probe_count == probe_after_first_read

def test_auto_reevaluates_per_fresh_process_cache(temp_config_root, monkeypatch):
    """A fresh resolver cache re-evaluates auto based on probe, not stale state."""
    import ufo.llm.config_helper as ch
    monkeypatch.setattr(ch, '_probe_local_auto', lambda: True)
    set_backend_selection('auto')
    reset_backend_caches(clear_override=True)
    assert get_agent_config(AgentType.HOST)['API_MODEL'] == 'local_model'
    reset_backend_caches(clear_override=True)
    monkeypatch.setattr(ch, '_probe_local_auto', lambda: False)
    assert get_agent_config(AgentType.HOST)['API_MODEL'] == 'cloud_model'

def test_env_var_expansion_in_profile(temp_config_root, monkeypatch):
    """Prove that ${VAR} placeholders in profile YAML are expanded via env vars."""
    monkeypatch.setenv('TEST_UFO_API_KEY', 'sk-expanded-secret-key')
    profile_path = temp_config_root.parent / 'envtest_profile.yaml'
    write_yaml(profile_path, {'HOST_AGENT': {'API_TYPE': 'openai', 'API_MODEL': 'test_model', 'API_KEY': '${TEST_UFO_API_KEY}'}, 'APP_AGENT': {'API_TYPE': 'openai', 'API_MODEL': 'test_model'}})
    reset_backend_caches(clear_override=True)
    prof = resolve_backend_profile('profile', profile_path=str(profile_path))
    assert prof['HOST_AGENT']['API_KEY'] == 'sk-expanded-secret-key', 'Environment variable placeholder must be expanded in resolved profile'

def test_cross_process_persistence(temp_config_root):
    set_backend_selection('local')
    script_path = temp_config_root.parent / 'check_model.py'
    script_content = f'\nimport sys\nfrom pathlib import Path\nsys.path.insert(0, r"C:\\ufo")\n\nfrom ufo.config.config_loader import ConfigLoader, clear_config_cache\nfrom ufo.llm.config_helper import get_agent_config\nfrom ufo.llm import AgentType\n\nConfigLoader.reset()\nclear_config_cache()\nConfigLoader.get_instance(r"{str(temp_config_root)}")\n\ncfg = get_agent_config(AgentType.HOST)\nprint(cfg.get("API_MODEL"))\n'
    script_path.write_text(script_content)
    env = os.environ.copy()
    env['PYTHONPATH'] = 'C:\\ufo'
    res = subprocess.run([sys.executable, str(script_path)], capture_output=True, text=True, env=env)
    assert 'local_model' in res.stdout
    set_backend_selection('cloud')
    res2 = subprocess.run([sys.executable, str(script_path)], capture_output=True, text=True, env=env)
    assert 'cloud_model' in res2.stdout

def test_no_write_invariant(temp_config_root):
    hash_before = hash_directory(temp_config_root)
    files_before = set(hash_before.keys())
    set_backend_selection('local')
    resolve_backend_profile()
    get_agent_config(AgentType.HOST)
    hash_after = hash_directory(temp_config_root)
    files_after = set(hash_after.keys())
    diff_files = files_after - files_before
    assert diff_files == {'ufo\\backend_state.json'} or diff_files == {'ufo/backend_state.json'}
    for f in files_before:
        assert hash_before[f] == hash_after[f]

def test_process_override_writes_nothing(temp_config_root):
    set_backend_selection('local')
    hash_before = hash_directory(temp_config_root)
    assert set_process_override('cloud')
    assert get_agent_config(AgentType.HOST)['API_MODEL'] == 'cloud_model'
    set_active_agent_route(None)
    assert get_agent_config(AgentType.HOST)['API_MODEL'] == 'local_model'
    hash_after = hash_directory(temp_config_root)
    assert hash_before == hash_after

def test_launcher_commands(temp_config_root, monkeypatch):
    import sys
    import urllib.request

    def stub_probe_stack():
        return (True, 'Mock')

    def stub_urlopen(req, timeout=1):

        class MockResp:
            status = 200

            def read(self):
                return b'{"models": [{"name": "models/gemini"}]}'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass
        return MockResp()
    monkeypatch.setattr(urllib.request, 'urlopen', stub_urlopen)
    sb_path = Path('C:\\ufo\\ufo\\scripts\\switch_backend.py')
    spec = importlib.util.spec_from_file_location('switch_backend', str(sb_path))
    sb = importlib.util.module_from_spec(spec)
    sys.modules['switch_backend'] = sb
    spec.loader.exec_module(sb)
    monkeypatch.setattr(sb, 'probe_local_stack', stub_probe_stack)
    pcs_path = Path('C:\\ufo\\ufo\\scripts\\prepare_cloud_smoke.py')
    spec_pcs = importlib.util.spec_from_file_location('prepare_cloud_smoke', str(pcs_path))
    pcs = importlib.util.module_from_spec(spec_pcs)
    sys.modules['prepare_cloud_smoke'] = pcs
    spec_pcs.loader.exec_module(pcs)
    hash_before = hash_directory(temp_config_root)
    original_argv = sys.argv.copy()
    for mode in ['local', 'cloud', 'auto', 'status']:
        sys.argv = ['switch_backend.py', mode]
        try:
            sb.main()
        except SystemExit as e:
            assert e.code == 0
    sys.argv = ['prepare_cloud_smoke.py']
    try:
        pcs.main()
    except SystemExit as e:
        assert e.code == 0
    sys.argv = original_argv
    hash_after = hash_directory(temp_config_root)
    files_before = set(hash_before.keys())
    files_after = set(hash_after.keys())
    new_files = files_after - files_before
    allowed_new = {f for f in new_files if f.endswith('backend_state.json')}
    forbidden_new = new_files - allowed_new
    assert not forbidden_new, f'Launcher created forbidden new files: {forbidden_new}'
    for f in files_after:
        assert not f.endswith('.bak'), f'Launcher left .bak file: {f}'
        assert not f.endswith('.watchdog_bak'), f'Launcher left .watchdog_bak file: {f}'
        assert not f.endswith('.tmp'), f'Launcher left .tmp file: {f}'
    for k in files_before:
        if 'backend_state.json' not in k:
            assert hash_before[k] == hash_after[k], f'Launcher modified pre-existing file: {k}'

def test_real_directory_guard(temp_config_root, monkeypatch):
    real_config_dir = Path('C:\\ufo\\ufo\\config\\ufo')
    hash_before = hash_directory(real_config_dir)
    files_before = set(hash_before.keys())
    test_launcher_commands(temp_config_root, monkeypatch)
    hash_after = hash_directory(real_config_dir)
    files_after = set(hash_after.keys())
    new_files = files_after - files_before
    assert not new_files, f'Launcher created new files in real config dir: {new_files}'
    assert hash_before == hash_after, f'Launcher modified real config files: {set(hash_before.items()) ^ set(hash_after.items())}'