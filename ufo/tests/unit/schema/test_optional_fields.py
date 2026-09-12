"""
Test script for optional fields in BaseModel schemas.

This script verifies that created_at and updated_at fields are now optional
and that task_description has been removed from TaskStarSchema.
"""
from ufo.galaxy.agents.schema import TaskStarSchema, TaskStarLineSchema, TaskConstellationSchema

def test_optional_fields():
    """Test that created_at and updated_at fields are optional."""
    print('[TEST] Testing optional fields...')
    minimal_task_data = {'task_id': 'minimal_task', 'name': 'Minimal Task', 'description': 'A task with minimal fields'}
    task_schema = TaskStarSchema(**minimal_task_data)
    print('[PASS] TaskStarSchema with minimal fields created successfully')
    print(f'   - created_at: {task_schema.created_at}')
    print(f'   - updated_at: {task_schema.updated_at}')
    assert task_schema.created_at is None
    assert task_schema.updated_at is None
    minimal_line_data = {'line_id': 'minimal_line', 'from_task_id': 'task1', 'to_task_id': 'task2'}
    line_schema = TaskStarLineSchema(**minimal_line_data)
    print('[PASS] TaskStarLineSchema with minimal fields created successfully')
    print(f'   - created_at: {line_schema.created_at}')
    print(f'   - updated_at: {line_schema.updated_at}')
    assert line_schema.created_at is None
    assert line_schema.updated_at is None
    minimal_constellation_data = {'constellation_id': 'minimal_constellation', 'name': 'Minimal Constellation'}
    constellation_schema = TaskConstellationSchema(**minimal_constellation_data)
    print('[PASS] TaskConstellationSchema with minimal fields created successfully')
    print(f'   - created_at: {constellation_schema.created_at}')
    print(f'   - updated_at: {constellation_schema.updated_at}')
    assert constellation_schema.created_at is None
    assert constellation_schema.updated_at is None

def test_task_description_removed():
    """Test that task_description field has been removed from TaskStarSchema."""
    print('\n[TEST] Testing task_description field removal...')
    task_schema_fields = set(TaskStarSchema.model_fields.keys())
    assert 'task_description' not in task_schema_fields, 'task_description field still exists in TaskStarSchema'
    print('[PASS] task_description field has been successfully removed')
    task_data = {'task_id': 'test_task', 'name': 'Test Task', 'description': 'Test description', 'task_description': 'This should be ignored'}
    task_schema = TaskStarSchema(**task_data)
    assert not hasattr(task_schema, 'task_description'), 'task_description attribute still accessible'
    print('[PASS] task_description attribute not accessible (as expected)')

def test_backwards_compatibility():
    """Test that the changes don't break backwards compatibility."""
    print('\n[TEST] Testing backwards compatibility...')
    full_task_data = {'task_id': 'full_task', 'name': 'Full Task', 'description': 'A task with all fields', 'created_at': '2025-09-29T06:44:00.951923+00:00', 'updated_at': '2025-09-29T06:44:00.951923+00:00', 'priority': 'HIGH', 'status': 'PENDING'}
    task_schema = TaskStarSchema(**full_task_data)
    print('[PASS] TaskStarSchema with timestamps works correctly')
    assert task_schema.created_at == '2025-09-29T06:44:00.951923+00:00'
    assert task_schema.updated_at == '2025-09-29T06:44:00.951923+00:00'
    json_data = task_schema.model_dump_json()
    restored_schema = TaskStarSchema.model_validate_json(json_data)
    assert restored_schema.task_id == 'full_task'
    print('[PASS] JSON serialization/deserialization works correctly')

def main():
    """Run all tests."""
    print('Testing BaseModel Schema Modifications\n')
    try:
        test_optional_fields()
        test_task_description_removed()
        test_backwards_compatibility()
        print('\n[PASS] All tests passed successfully!')
    except Exception as e:
        print(f'\n[FAIL] Some tests failed: {e}')
        return False
    return True
if __name__ == '__main__':
    success = main()
    exit(0 if success else 1)