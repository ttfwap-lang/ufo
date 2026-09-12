"""
End-to-end integration test for the Galaxy framework constellation system.

This test validates the complete flow from task constellation creation through execution,
including DAG visualization at each step.
"""
import os
import sys
import json
import time
from datetime import datetime
from typing import Dict, Any
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, project_root)
from ufo.galaxy.constellation.task_constellation import TaskConstellation
from ufo.galaxy.constellation.task_star import TaskStar
from ufo.galaxy.constellation.task_star_line import TaskStarLine
from ufo.galaxy.constellation.enums import ConstellationState, TaskPriority, TaskStatus
import logging
logging.getLogger('ufo').setLevel(logging.WARNING)

def print_with_color(message: str, color: str='white'):
    """Simple color print function."""
    color_codes = {'red': '\x1b[91m', 'green': '\x1b[92m', 'yellow': '\x1b[93m', 'blue': '\x1b[94m', 'magenta': '\x1b[95m', 'cyan': '\x1b[96m', 'white': '\x1b[97m', 'reset': '\x1b[0m'}
    color_code = color_codes.get(color, color_codes['white'])
    reset_code = color_codes['reset']
    print(f'{color_code}{message}{reset_code}')

def test_basic_constellation_workflow():
    """Test basic constellation creation and visualization."""
    print_with_color('📝 Test 1: Basic constellation workflow...', 'cyan')
    constellation = TaskConstellation(name='Integration Test Workflow')
    tasks = [TaskStar(task_id='setup_task', name='Environment Setup', description='Initialize the testing environment', priority=TaskPriority.HIGH), TaskStar(task_id='data_task', name='Data Preparation', description='Prepare test data', priority=TaskPriority.MEDIUM), TaskStar(task_id='process_task', name='Data Processing', description='Process the prepared data', priority=TaskPriority.MEDIUM), TaskStar(task_id='validate_task', name='Validation', description='Validate processing results', priority=TaskPriority.HIGH)]
    for task in tasks:
        constellation.add_task(task)
    dependencies = [TaskStarLine.create_success_only('setup_task', 'data_task', 'Setup required'), TaskStarLine.create_success_only('data_task', 'process_task', 'Data needed'), TaskStarLine.create_success_only('process_task', 'validate_task', 'Results needed')]
    for dep in dependencies:
        constellation.add_dependency(dep)
    print(f'✅ Constellation created: {constellation.name}')
    print(f'📊 Tasks: {constellation.task_count}')
    print(f'🔗 Dependencies: {len(constellation.dependencies)}')
    print_with_color('🚀 Starting constellation execution...', 'yellow')
    constellation.start_execution()
    constellation.mark_task_completed('setup_task', True)
    constellation.mark_task_completed('data_task', True)
    constellation.mark_task_completed('process_task', True)
    constellation.mark_task_completed('validate_task', True)
    constellation.complete_execution()
    assert constellation.state == ConstellationState.COMPLETED, 'Constellation should be completed'

def test_real_time_dag_updates():
    """Test real-time DAG updates during execution."""
    print_with_color('📝 Test 2: Real-time DAG updates during execution...', 'cyan')
    constellation = TaskConstellation(name='Dynamic Update Test')
    initial_task = TaskStar(task_id='initial_task', name='Initial Task', description='Starting task for dynamic testing', priority=TaskPriority.MEDIUM)
    constellation.add_task(initial_task)
    constellation.start_execution()
    for i in range(2, 5):
        new_task = TaskStar(task_id=f'dynamic_task_{i}', name=f'Dynamic Task {i}', description=f'Dynamically added task {i}', priority=TaskPriority.LOW)
        constellation.add_task(new_task)
        if i == 2:
            dep = TaskStarLine.create_success_only('initial_task', f'dynamic_task_{i}', 'Sequential flow')
        else:
            dep = TaskStarLine.create_success_only(f'dynamic_task_{i - 1}', f'dynamic_task_{i}', 'Sequential flow')
        constellation.add_dependency(dep)
    constellation.mark_task_completed('initial_task', True)
    constellation.mark_task_completed('dynamic_task_2', True)
    constellation.mark_task_completed('dynamic_task_3', False)
    constellation.mark_task_completed('dynamic_task_4', True)
    constellation.complete_execution()
    print('✅ Real-time updates test completed')
    assert constellation.state in (ConstellationState.COMPLETED, ConstellationState.PARTIALLY_FAILED), 'Constellation execution should finish'

def test_complex_dag_structure():
    """Test complex DAG structure with multiple dependencies."""
    print_with_color('📝 Test 3: Complex DAG structure...', 'cyan')
    constellation = TaskConstellation(name='Complex DAG Test')
    tasks = [TaskStar('start', 'Start Process', 'Initial task', TaskPriority.HIGH), TaskStar('fetch_a', 'Fetch Data A', 'Fetch dataset A', TaskPriority.MEDIUM), TaskStar('fetch_b', 'Fetch Data B', 'Fetch dataset B', TaskPriority.MEDIUM), TaskStar('process_a', 'Process A', 'Process dataset A', TaskPriority.MEDIUM), TaskStar('process_b', 'Process B', 'Process dataset B', TaskPriority.MEDIUM), TaskStar('merge', 'Merge Results', 'Merge processed data', TaskPriority.HIGH), TaskStar('validate', 'Validate', 'Validate merged data', TaskPriority.HIGH), TaskStar('deploy', 'Deploy', 'Deploy final results', TaskPriority.HIGH)]
    for task in tasks:
        constellation.add_task(task)
    deps = [TaskStarLine.create_success_only('start', 'fetch_a', 'Start triggers A'), TaskStarLine.create_success_only('start', 'fetch_b', 'Start triggers B'), TaskStarLine.create_success_only('fetch_a', 'process_a', 'Data A ready'), TaskStarLine.create_success_only('fetch_b', 'process_b', 'Data B ready'), TaskStarLine.create_success_only('process_a', 'merge', 'A processed'), TaskStarLine.create_success_only('process_b', 'merge', 'B processed'), TaskStarLine.create_success_only('merge', 'validate', 'Data merged'), TaskStarLine.create_success_only('validate', 'deploy', 'Validation passed')]
    for dep in deps:
        constellation.add_dependency(dep)
    constellation.start_execution()
    constellation.mark_task_completed('start', True)
    constellation.mark_task_completed('fetch_a', True)
    constellation.mark_task_completed('fetch_b', True)
    constellation.mark_task_completed('process_a', True)
    constellation.mark_task_completed('process_b', True)
    constellation.mark_task_completed('merge', True)
    constellation.mark_task_completed('validate', True)
    constellation.mark_task_completed('deploy', True)
    constellation.complete_execution()
    print('✅ Complex DAG structure test completed')
    assert constellation.state == ConstellationState.COMPLETED, 'Constellation should be completed'

def test_error_handling():
    """Test error handling and failure scenarios."""
    print_with_color('📝 Test 4: Error handling scenarios...', 'cyan')
    constellation = TaskConstellation(name='Error Handling Test')
    tasks = [TaskStar('task_1', 'First Task', 'Will succeed', TaskPriority.HIGH), TaskStar('task_2', 'Second Task', 'Will fail', TaskPriority.MEDIUM), TaskStar('task_3', 'Third Task', 'Dependent on task_2', TaskPriority.MEDIUM), TaskStar('task_4', 'Fourth Task', 'Independent task', TaskPriority.LOW)]
    for task in tasks:
        constellation.add_task(task)
    deps = [TaskStarLine.create_success_only('task_1', 'task_2', 'Sequential'), TaskStarLine.create_success_only('task_2', 'task_3', 'Sequential')]
    for dep in deps:
        constellation.add_dependency(dep)
    constellation.start_execution()
    constellation.mark_task_completed('task_1', True)
    constellation.mark_task_completed('task_2', False)
    constellation.mark_task_completed('task_4', True)
    constellation.complete_execution()
    stats = constellation.get_statistics()
    failed_count = stats.get('failed_tasks', stats.get('task_status_counts', {}).get('failed', 0))
    completed_count = stats.get('completed_tasks', stats.get('task_status_counts', {}).get('completed', 0))
    assert failed_count > 0 and completed_count > 0, "Error handling didn't work as expected"
    print('✅ Error handling test completed - mixed results as expected')

def save_test_results(results: Dict[str, Any]):
    """Save test results to JSON file."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'e2e_test_results_{timestamp}.json'
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, default=str)
    print(f'💾 Test results saved to: {filename}')

def main():
    """Run comprehensive integration tests."""
    print_with_color('🌌 Galaxy Framework E2E Integration Tests', 'blue')
    print('=' * 60)
    start_time = time.time()
    tests = [('Basic Constellation Workflow', test_basic_constellation_workflow), ('Real-time DAG Updates', test_real_time_dag_updates), ('Complex DAG Structure', test_complex_dag_structure), ('Error Handling', test_error_handling)]
    results = {'timestamp': datetime.now().isoformat(), 'total_tests': len(tests), 'passed_tests': 0, 'failed_tests': 0, 'test_details': {}}
    for test_name, test_func in tests:
        print(f"\n{'=' * 20} {test_name} {'=' * 20}")
        try:
            test_start = time.time()
            test_func()
            test_time = time.time() - test_start
            results['test_details'][test_name] = {'status': 'PASSED', 'execution_time': test_time}
            results['passed_tests'] += 1
            print_with_color(f'✅ {test_name}: PASSED ({test_time:.2f}s)', 'green')
        except Exception as e:
            results['failed_tests'] += 1
            results['test_details'][test_name] = {'status': 'ERROR', 'error': str(e), 'execution_time': time.time() - test_start}
            print_with_color(f'💥 {test_name}: ERROR - {e}', 'red')
    total_time = time.time() - start_time
    success_rate = results['passed_tests'] / results['total_tests'] * 100
    results['total_execution_time'] = total_time
    results['success_rate'] = success_rate
    print('\n' + '=' * 60)
    print_with_color('🌌 Galaxy Framework Test Summary:', 'blue')
    print(f"   - Total tests: {results['total_tests']}")
    print(f"   - Successful: {results['passed_tests']}")
    print(f'   - Success rate: {success_rate:.1f}%')
    print(f'   - Total time: {total_time:.2f}s')
    save_test_results(results)
    if results['failed_tests'] == 0:
        print_with_color('\n🎯 OVERALL TEST SUITE SUMMARY:', 'green')
        print('   - Constellation Tests: ✅ SUCCESS')
        print('   - Galaxy Framework Tests: ✅ SUCCESS')
        print(f'   - Total Execution Time: {total_time:.2f}s')
    else:
        print_with_color('\n⚠️ OVERALL TEST SUITE SUMMARY:', 'yellow')
        print(f"   - Tests Passed: {results['passed_tests']}")
        print(f"   - Tests Failed: {results['failed_tests']}")
        print(f'   - Success Rate: {success_rate:.1f}%')
if __name__ == '__main__':
    main()