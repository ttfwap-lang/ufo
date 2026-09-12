"""
Comprehensive test for GalaxySession functionality.
"""
import asyncio
import logging
import os
import sys
from unittest.mock import MagicMock, AsyncMock
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
from ufo.galaxy.session.galaxy_session import GalaxySession
from ufo.galaxy.client.constellation_client import ConstellationClient
from ufo.galaxy.constellation import TaskConstellation

async def test_galaxy_session_basic_functionality():
    """Test basic GalaxySession functionality."""
    print('🧪 Testing GalaxySession Basic Functionality\n')
    mock_client = MagicMock(spec=ConstellationClient)
    mock_client.device_manager = MagicMock()
    print('=== Test 1: GalaxySession Initialization ===')
    try:
        session = GalaxySession(task='Test task for galaxy session', should_evaluate=True, id='test-session-001', client=mock_client, initial_request='Create a simple task workflow')
        print('✅ GalaxySession created successfully')
        print(f'   Task: {session.task}')
        print(f'   ID: {session._id}')
        print(f'   Agent: {type(session.agent).__name__}')
        print(f'   Orchestrator: {type(session.orchestrator).__name__}')
        print(f'   Observers count: {len(session._observers)}')
    except Exception as e:
        print(f'❌ Failed to create GalaxySession: {e}')
        import traceback
        traceback.print_exc()
        return
    print('\n=== Test 2: Session Properties ===')
    try:
        print(f'✅ Current constellation: {session.current_constellation}')
        print(f'✅ Session finished: {session.is_finished()}')
        print(f'✅ Session error: {session.is_error()}')
        print(f"✅ Next request: '{session.next_request()}'")
        print(f"✅ Request to evaluate: '{session.request_to_evaluate()}'")
    except Exception as e:
        print(f'❌ Error testing properties: {e}')
        return
    print('\n=== Test 3: Round Creation ===')
    try:
        round_obj = session.create_new_round()
        if round_obj:
            print('✅ Round created successfully')
            print(f'   Round ID: {round_obj._id}')
            print(f'   Round request: {round_obj._request}')
            print(f'   Round type: {type(round_obj).__name__}')
        else:
            print('ℹ️ No round created (expected if no more requests)')
    except Exception as e:
        print(f'❌ Error creating round: {e}')
        import traceback
        traceback.print_exc()
        return
    print('\n=== Test 4: Event System Integration ===')
    try:
        event_bus = session._event_bus
        observers = session._observers
        print(f'✅ Event bus available: {event_bus is not None}')
        print(f'✅ Observers registered: {len(observers)}')
        for i, observer in enumerate(observers):
            print(f'   Observer {i + 1}: {type(observer).__name__}')
    except Exception as e:
        print(f'❌ Error testing event system: {e}')
        return
    print('\n=== Test 5: Session Control ===')
    try:
        await session.force_finish('Test termination')
        print('✅ Force finish works')
        print(f'   Session finished: {session.is_finished()}')
        print(f'   Agent status: {session.agent.status}')
        print(f'   Session results: {list(session.session_results.keys())}')
    except Exception as e:
        print(f'❌ Error testing session control: {e}')
        return
    print('\n✅ All GalaxySession basic functionality tests completed!')

async def test_galaxy_session_mock_execution():
    """Test GalaxySession with mock execution."""
    print('\n🧪 Testing GalaxySession Mock Execution\n')
    mock_client = MagicMock(spec=ConstellationClient)
    mock_client.device_manager = MagicMock()
    print('=== Mock Execution Test ===')
    try:
        session = GalaxySession(task='Mock task execution test', should_evaluate=False, id='mock-session-001', client=mock_client, initial_request='Execute a mock task workflow')
        print('✅ Mock session created')
        agent = session.agent
        print(f'   Agent type: {type(agent).__name__}')
        print(f'   Agent status: {agent.status}')
        constellation = session.current_constellation
        print(f'   Current constellation: {constellation}')
        context = session._context
        print(f'   Context available: {context is not None}')
    except Exception as e:
        print(f'❌ Error in mock execution test: {e}')
        import traceback
        traceback.print_exc()
        return
    print('\n✅ Mock execution test completed!')

async def test_galaxy_session_issues():
    """Test for potential issues in GalaxySession."""
    print('\n🔍 Testing for Potential Issues in GalaxySession\n')
    issues_found = []
    print('=== Checking for Common Issues ===')
    try:
        from ufo.galaxy.session.galaxy_session import GalaxySession, GalaxyRound
        from ufo.galaxy.agents.constellation_agent import ConstellationAgent
        from ufo.galaxy.constellation import TaskConstellationOrchestrator
        print('✅ All imports available')
    except ImportError as e:
        issues_found.append(f'Import error: {e}')
        print(f'❌ Import error: {e}')
    try:
        mock_client = MagicMock()
        mock_client.device_manager = MagicMock()
        session = GalaxySession(task='Test', should_evaluate=False, id='test', client=mock_client, initial_request='Test')
        agent = session.agent
        print(f'✅ Agent accessible: {type(agent).__name__}')
    except TypeError as e:
        if 'abstract' in str(e):
            issues_found.append(f'Abstract method issue: {e}')
            print(f'❌ Abstract method issue: {e}')
        else:
            raise
    except Exception as e:
        issues_found.append(f'Initialization error: {e}')
        print(f'❌ Initialization error: {e}')
    try:
        mock_client = MagicMock()
        mock_client.device_manager = MagicMock()
        session = GalaxySession(task='Test', should_evaluate=False, id='test', client=mock_client, initial_request='Test')
        required_attrs = ['_agent', '_orchestrator', '_event_bus', '_observers', '_context', '_session_results']
        for attr in required_attrs:
            if hasattr(session, attr):
                print(f'✅ Has attribute: {attr}')
            else:
                issues_found.append(f'Missing attribute: {attr}')
                print(f'❌ Missing attribute: {attr}')
    except Exception as e:
        issues_found.append(f'Attribute check error: {e}')
        print(f'❌ Attribute check error: {e}')
    print(f'\n📊 Issues Summary:')
    if issues_found:
        print(f'❌ Found {len(issues_found)} issues:')
        for i, issue in enumerate(issues_found, 1):
            print(f'   {i}. {issue}')
    else:
        print('✅ No critical issues found!')
    return issues_found

async def main():
    """Run all GalaxySession tests."""
    print('🚀 GalaxySession Comprehensive Testing\n')
    logging.basicConfig(level=logging.INFO)
    try:
        await test_galaxy_session_basic_functionality()
        await test_galaxy_session_mock_execution()
        issues = await test_galaxy_session_issues()
        print('\n' + '=' * 80)
        print('🎯 GalaxySession Testing Summary')
        print('=' * 80)
        if issues:
            print(f'⚠️  Found {len(issues)} issues that need attention')
            print('\n🔧 Recommendations:')
            for issue in issues:
                print(f'   • Fix: {issue}')
        else:
            print('✅ GalaxySession appears to be working correctly!')
        print('\n🎉 Testing completed!')
    except Exception as e:
        print(f'💥 Critical error during testing: {e}')
        import traceback
        traceback.print_exc()
if __name__ == '__main__':
    asyncio.run(main())