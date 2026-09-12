"""
Test script for configuration loading with backward compatibility.

This script demonstrates the configuration loading behavior in different scenarios.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

def test_ufo_config():
    """Test UFO configuration loading."""
    print('\n' + '=' * 70)
    print('Testing UFO Configuration Loading')
    print('=' * 70)
    try:
        from ufo.config.config_loader import get_ufo_config
        config = get_ufo_config()
        print('\n✓ Typed access (recommended):')
        print(f'  config.system.max_step = {config.system.max_step}')
        print(f'  config.system.timeout = {config.system.timeout}')
        print(f'  config.app_agent.api_type = {config.app_agent.api_type}')
        print(f'  config.app_agent.api_model = {config.app_agent.api_model}')
        print('\n✓ Dict-style access (backward compatible):')
        print(f"  config['MAX_STEP'] = {config.get('MAX_STEP', 'N/A')}")
        print(f"  config['TIMEOUT'] = {config.get('TIMEOUT', 'N/A')}")
        if 'HOST_AGENT' in config:
            host_agent = config['HOST_AGENT']
            print(f"  config['HOST_AGENT']['API_TYPE'] = {host_agent.get('API_TYPE', 'N/A')}")
        print('\n✓ Dynamic access:')
        print(f'  config keys count = {len(list(config.keys()))}')
        print(f'  Sample keys = {list(config.keys())[:5]}...')
        print('\n✅ UFO configuration loaded successfully!')
        return True
    except Exception as e:
        print(f'\n❌ Error loading UFO configuration: {e}')
        import traceback
        traceback.print_exc()
        return False

def test_galaxy_config():
    """Test Galaxy configuration loading."""
    print('\n' + '=' * 70)
    print('Testing Galaxy Configuration Loading')
    print('=' * 70)
    try:
        from ufo.config.config_loader import get_galaxy_config
        config = get_galaxy_config()
        print('\n✓ Typed access (recommended):')
        print(f'  config.constellation_agent.api_type = {config.constellation_agent.api_type}')
        print(f'  config.constellation_agent.api_model = {config.constellation_agent.api_model}')
        print('\n✓ Dict-style access (backward compatible):')
        if 'CONSTELLATION_AGENT' in config:
            agent = config['CONSTELLATION_AGENT']
            print(f"  config['CONSTELLATION_AGENT']['API_TYPE'] = {agent.get('API_TYPE', 'N/A')}")
        print('\n✓ Dynamic access:')
        print(f'  config keys count = {len(list(config.keys()))}')
        print(f'  Sample keys = {list(config.keys())[:5]}...')
        print('\n✅ Galaxy configuration loaded successfully!')
        return True
    except Exception as e:
        print(f'\n❌ Error loading Galaxy configuration: {e}')
        import traceback
        traceback.print_exc()
        return False

def test_path_detection():
    """Test configuration path detection."""
    print('\n' + '=' * 70)
    print('Testing Path Detection')
    print('=' * 70)
    ufo_new = Path('config/ufo')
    ufo_legacy = Path('ufo/config')
    print('\nUFO Configuration Paths:')
    print(f"  New path (config/ufo/):     {('✓ EXISTS' if ufo_new.exists() else '✗ NOT FOUND')}")
    if ufo_new.exists():
        yaml_files = list(ufo_new.glob('*.yaml'))
        print(f'    Files: {len(yaml_files)}')
        for f in yaml_files[:3]:
            print(f'      - {f.name}')
    print(f"  Legacy path (ufo/config/):  {('✓ EXISTS' if ufo_legacy.exists() else '✗ NOT FOUND')}")
    if ufo_legacy.exists():
        yaml_files = list(ufo_legacy.glob('*.yaml'))
        print(f'    Files: {len(yaml_files)}')
        for f in yaml_files[:3]:
            print(f'      - {f.name}')
    galaxy_new = Path('config/galaxy')
    print('\nGalaxy Configuration Paths:')
    print(f"  New path (config/galaxy/):  {('✓ EXISTS' if galaxy_new.exists() else '✗ NOT FOUND')}")
    if galaxy_new.exists():
        yaml_files = list(galaxy_new.glob('*.yaml'))
        print(f'    Files: {len(yaml_files)}')
        for f in yaml_files[:3]:
            print(f'      - {f.name}')

def main():
    """Main test function."""
    print('\n' + '=' * 70)
    print('UFO³ Configuration System Test')
    print('=' * 70)
    test_path_detection()
    ufo_success = test_ufo_config()
    galaxy_success = test_galaxy_config()
    print('\n' + '=' * 70)
    print('Test Summary')
    print('=' * 70)
    print(f"  UFO Configuration:    {('✅ PASS' if ufo_success else '❌ FAIL')}")
    print(f"  Galaxy Configuration: {('✅ PASS' if galaxy_success else '❌ FAIL')}")
    print('=' * 70)
    return ufo_success and galaxy_success
if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)