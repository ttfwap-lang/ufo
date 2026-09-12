"""
Test script for automatic ID assignment in BaseModel schemas.

This script tests the automatic generation of constellation_id, task_id, and line_id,
as well as the uniqueness validation within constellation contexts.
"""
from ufo.galaxy.agents.schema import TaskStarSchema, TaskStarLineSchema, TaskConstellationSchema, IDManager

def test_automatic_id_generation():
    """Test automatic ID generation for all schema types."""
    print('[TEST] Testing automatic ID generation...')
    task_data = {'name': 'Auto Task', 'description': 'Task with auto-generated ID'}
    task_schema = TaskStarSchema(**task_data)
    print(f'[PASS] TaskStarSchema auto task_id: {task_schema.task_id}')
    assert task_schema.task_id is not None
    assert task_schema.task_id.startswith('task_')
    line_data = {'from_task_id': 'task1', 'to_task_id': 'task2'}
    line_schema = TaskStarLineSchema(**line_data)
    print(f'[PASS] TaskStarLineSchema auto line_id: {line_schema.line_id}')
    assert line_schema.line_id is not None
    assert line_schema.line_id.startswith('line_')
    constellation_data = {'name': 'Auto Constellation'}
    constellation_schema = TaskConstellationSchema(**constellation_data)
    print(f'[PASS] TaskConstellationSchema auto constellation_id: {constellation_schema.constellation_id}')
    assert constellation_schema.constellation_id is not None
    assert constellation_schema.constellation_id.startswith('constellation_')

def test_explicit_id_preservation():
    """Test that explicitly provided IDs are preserved."""
    print('\n[TEST] Testing explicit ID preservation...')
    task_schema = TaskStarSchema(task_id='explicit_task_001', name='Explicit Task', description='Task with explicit ID')
    print(f'[PASS] Explicit task_id preserved: {task_schema.task_id}')
    assert task_schema.task_id == 'explicit_task_001'
    line_schema = TaskStarLineSchema(line_id='explicit_line_001', from_task_id='task1', to_task_id='task2')
    print(f'[PASS] Explicit line_id preserved: {line_schema.line_id}')
    assert line_schema.line_id == 'explicit_line_001'
    constellation_schema = TaskConstellationSchema(constellation_id='explicit_constellation_001', name='Explicit Constellation')
    print(f'[PASS] Explicit constellation_id preserved: {constellation_schema.constellation_id}')
    assert constellation_schema.constellation_id == 'explicit_constellation_001'

def test_uniqueness_validation():
    """Test uniqueness validation within constellation context."""
    print('\n[TEST] Testing ID uniqueness validation...')
    task1 = TaskStarSchema(task_id='unique_task_001', name='Task 1', description='First task')
    task2 = TaskStarSchema(task_id='unique_task_002', name='Task 2', description='Second task')
    dependency = TaskStarLineSchema(line_id='unique_line_001', from_task_id='unique_task_001', to_task_id='unique_task_002')
    constellation = TaskConstellationSchema(constellation_id='test_constellation', name='Test Constellation', tasks={'unique_task_001': task1, 'unique_task_002': task2}, dependencies={'unique_line_001': dependency})
    assert constellation.constellation_id == 'test_constellation'
    print('[PASS] Constellation with unique IDs created successfully')
    duplicate_task = TaskStarSchema(task_id='unique_task_001', name='Duplicate Task', description='Task with duplicate ID')
    try:
        TaskConstellationSchema(constellation_id='test_constellation_bad', name='Bad Constellation', tasks={'unique_task_001': task1, 'duplicate_task': duplicate_task})
        assert False, 'Duplicate task ID validation failed - should have been caught'
    except ValueError as e:
        print(f'[PASS] Duplicate task ID correctly detected: {e}')

def test_id_manager_context():
    """Test that ID Manager maintains context properly."""
    print('\n[TEST] Testing ID Manager context...')
    id_manager = IDManager()
    task_id_1a = id_manager.generate_task_id('constellation_a')
    task_id_2a = id_manager.generate_task_id('constellation_a')
    task_id_1b = id_manager.generate_task_id('constellation_b')
    task_id_2b = id_manager.generate_task_id('constellation_b')
    print(f'[PASS] Constellation A task IDs: {task_id_1a}, {task_id_2a}')
    print(f'[PASS] Constellation B task IDs: {task_id_1b}, {task_id_2b}')
    assert task_id_1a != task_id_2a
    assert task_id_1b != task_id_2b
    assert not id_manager.is_task_id_available('constellation_a', task_id_1a)
    assert id_manager.is_task_id_available('constellation_a', 'unused_task_id')
    print('[PASS] ID availability check working correctly')

def test_sequential_id_generation():
    """Test that IDs are generated sequentially within constellation context."""
    print('\n[TEST] Testing sequential ID generation...')
    id_manager = IDManager()
    constellation_id = 'seq_test_constellation'
    task_ids = []
    for i in range(5):
        task_id = id_manager.generate_task_id(constellation_id)
        task_ids.append(task_id)
    print(f'[PASS] Generated task IDs: {task_ids}')
    for i, task_id in enumerate(task_ids, 1):
        expected = f'task_{i:03d}'
        assert task_id == expected, f'Expected {expected}, got {task_id}'
    line_ids = []
    for i in range(3):
        line_id = id_manager.generate_line_id(constellation_id)
        line_ids.append(line_id)
    print(f'[PASS] Generated line IDs: {line_ids}')
    for i, line_id in enumerate(line_ids, 1):
        expected = f'line_{i:03d}'
        assert line_id == expected, f'Expected {expected}, got {line_id}'
    print('[PASS] Sequential ID generation working correctly')

def test_empty_string_handling():
    """Test that empty strings are treated as None for ID generation."""
    print('\n[TEST] Testing empty string handling...')
    task_schema = TaskStarSchema(task_id='', name='Empty ID Task', description='Task with empty string ID')
    print(f'[PASS] Empty task_id generated as: {task_schema.task_id}')
    assert task_schema.task_id != ''
    assert task_schema.task_id.startswith('task_')
    line_schema = TaskStarLineSchema(line_id='', from_task_id='task1', to_task_id='task2')
    print(f'[PASS] Empty line_id generated as: {line_schema.line_id}')
    assert line_schema.line_id != ''
    assert line_schema.line_id.startswith('line_')

def main():
    """Run all tests."""
    print('Testing Automatic ID Assignment and Validation\n')
    try:
        test_automatic_id_generation()
        test_explicit_id_preservation()
        test_uniqueness_validation()
        test_id_manager_context()
        test_sequential_id_generation()
        test_empty_string_handling()
        print('\n[PASS] All tests passed successfully!')
    except Exception as e:
        print(f'\n[FAIL] Some tests failed: {e}')
        return False
    return True
if __name__ == '__main__':
    success = main()
    exit(0 if success else 1)