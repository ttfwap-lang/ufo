"""
Test for List/Dict compatibility in TaskConstellationSchema.

This test verifies that tasks and dependencies can be provided as either
List or Dict formats and are properly converted and validated.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
from ufo.galaxy.agents.schema import TaskStarSchema, TaskStarLineSchema, TaskConstellationSchema
import json

def test_tasks_and_dependencies_as_lists():
    """Test using List format for tasks and dependencies"""
    print('[TEST] Testing List format for tasks and dependencies')
    task_list = [{'task_id': 'task_001', 'name': 'First Task', 'description': 'First task description'}, {'task_id': 'task_002', 'name': 'Second Task', 'description': 'Second task description'}, {'name': 'Third Task', 'description': 'Task without preset ID'}]
    dependency_list = [{'line_id': 'dep_001', 'from_task_id': 'task_001', 'to_task_id': 'task_002', 'condition_description': 'First dependency'}, {'from_task_id': 'task_002', 'to_task_id': 'task_003', 'condition_description': 'Second dependency'}]
    constellation_data = {'name': 'List format test constellation', 'tasks': task_list, 'dependencies': dependency_list}
    constellation = TaskConstellationSchema(**constellation_data)
    print(f'[PASS] Constellation created: {constellation.name}')
    print(f'   - Constellation ID: {constellation.constellation_id}')
    print(f'   - Task count: {len(constellation.tasks)}')
    print(f'   - Dependency count: {len(constellation.dependencies)}')
    assert isinstance(constellation.tasks, dict), 'Tasks should be converted to Dict format'
    assert isinstance(constellation.dependencies, dict), 'Dependencies should be converted to Dict format'
    task_ids = list(constellation.tasks.keys())
    print(f'   - Task IDs: {task_ids}')
    dep_ids = list(constellation.dependencies.keys())
    print(f'   - Dependency IDs: {dep_ids}')
    auto_generated_tasks = [task for task in constellation.tasks.values() if task.name == 'Third Task']
    assert len(auto_generated_tasks) == 1, 'Should have one task with auto-generated ID'
    print(f'   - Auto generated task ID: {auto_generated_tasks[0].task_id}')

def test_tasks_and_dependencies_as_dicts():
    """Test using Dict format for tasks and dependencies"""
    print('\n[TEST] Testing Dict format for tasks and dependencies')
    task_dict = {'task_001': TaskStarSchema(task_id='task_001', name='Dict task 1', description='First dict task'), 'task_002': TaskStarSchema(task_id='task_002', name='Dict task 2', description='Second dict task')}
    dependency_dict = {'dep_001': TaskStarLineSchema(line_id='dep_001', from_task_id='task_001', to_task_id='task_002', condition_description='Dict dependency')}
    constellation = TaskConstellationSchema(name='Dict format test constellation', tasks=task_dict, dependencies=dependency_dict)
    print(f'[PASS] Constellation created: {constellation.name}')
    assert isinstance(constellation.tasks, dict), 'Tasks should remain Dict format'
    assert isinstance(constellation.dependencies, dict), 'Dependencies should remain Dict format'

def test_mixed_format_compatibility():
    """Test mixed format compatibility"""
    print('\n[TEST] Testing mixed format compatibility')
    constellation1 = TaskConstellationSchema(name='Mixed constellation 1', tasks=[{'name': 'List task 1', 'description': 'From list'}, {'name': 'List task 2', 'description': 'From list'}], dependencies={'manual_dep': TaskStarLineSchema(line_id='manual_dep', from_task_id='task_001', to_task_id='task_002')})
    print(f'[PASS] Mixed format 1 created: tasks={type(constellation1.tasks).__name__}, dependencies={type(constellation1.dependencies).__name__}')
    constellation2 = TaskConstellationSchema(name='Mixed constellation 2', tasks={'manual_task': TaskStarSchema(task_id='manual_task', name='Dict task', description='From dict')}, dependencies=[{'from_task_id': 'manual_task', 'to_task_id': 'some_other_task', 'condition_description': 'From list dependency'}])
    print(f'[PASS] Mixed format 2 created: tasks={type(constellation2.tasks).__name__}, dependencies={type(constellation2.dependencies).__name__}')
    assert isinstance(constellation1.tasks, dict)
    assert isinstance(constellation2.tasks, dict)

def test_conversion_methods():
    """Test conversion methods"""
    print('\n[TEST] Testing conversion methods')
    constellation = TaskConstellationSchema(name='Conversion test constellation', tasks=[{'name': 'Task A', 'description': 'Desc A'}, {'name': 'Task B', 'description': 'Desc B'}, {'name': 'Task C', 'description': 'Desc C'}], dependencies=[{'from_task_id': 'task_001', 'to_task_id': 'task_002'}, {'from_task_id': 'task_002', 'to_task_id': 'task_003'}])
    tasks_list = constellation.get_tasks_as_list()
    print(f'[PASS] Got tasks list: {len(tasks_list)} tasks')
    assert len(tasks_list) == 3
    assert all((isinstance(task, TaskStarSchema) for task in tasks_list))
    deps_list = constellation.get_dependencies_as_list()
    print(f'[PASS] Got dependencies list: {len(deps_list)} dependencies')
    assert len(deps_list) == 2
    assert all((isinstance(dep, TaskStarLineSchema) for dep in deps_list))
    data_with_lists = constellation.to_dict_with_lists()
    print(f"[PASS] Exported as list format: tasks={type(data_with_lists['tasks']).__name__}, dependencies={type(data_with_lists['dependencies']).__name__}")
    assert isinstance(data_with_lists['tasks'], list)
    assert isinstance(data_with_lists['dependencies'], list)

def test_json_serialization():
    """Test JSON serialization compatibility"""
    print('\n[TEST] Testing JSON serialization compatibility')
    constellation = TaskConstellationSchema(name='JSON test constellation', tasks=[{'name': 'JSON task 1', 'description': 'JSON desc 1'}, {'name': 'JSON task 2', 'description': 'JSON desc 2'}], dependencies=[{'from_task_id': 'task_001', 'to_task_id': 'task_002', 'condition_description': 'JSON dependency'}])
    json_dict_format = constellation.model_dump_json(indent=2)
    print(f'[PASS] Dict format JSON length: {len(json_dict_format)} chars')
    json_list_format = json.dumps(constellation.to_dict_with_lists(), indent=2)
    print(f'[PASS] List format JSON length: {len(json_list_format)} chars')
    restored_from_dict = TaskConstellationSchema.model_validate_json(json_dict_format)
    print(f'[PASS] Restored from dict format JSON: {restored_from_dict.name}')
    list_data = json.loads(json_list_format)
    restored_from_list = TaskConstellationSchema(**list_data)
    print(f'[PASS] Restored from list format JSON: {restored_from_list.name}')
    assert restored_from_dict.name == restored_from_list.name
    assert len(restored_from_dict.tasks) == len(restored_from_list.tasks)
    assert len(restored_from_dict.dependencies) == len(restored_from_list.dependencies)

def main():
    """Run all tests"""
    print('TaskConstellationSchema List/Dict Compatibility Test')
    print('=' * 60)
    try:
        test_tasks_and_dependencies_as_lists()
        test_tasks_and_dependencies_as_dicts()
        test_mixed_format_compatibility()
        test_conversion_methods()
        test_json_serialization()
        print('\n' + '=' * 60)
        print('[PASS] All tests passed!')
    except Exception as e:
        print(f'\n[FAIL] Test failed: {e}')
        import traceback
        traceback.print_exc()
        return False
    return True
if __name__ == '__main__':
    success = main()
    exit(0 if success else 1)