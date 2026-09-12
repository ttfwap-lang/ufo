"""
Simple test for DAG visualization.
"""
import sys
import os
project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, project_root)
try:
    from ufo.galaxy.constellation.task_constellation import TaskConstellation
    from ufo.galaxy.constellation.task_star import TaskStar
    from ufo.galaxy.constellation.enums import TaskPriority
    from ufo.galaxy.visualization.dag_visualizer import DAGVisualizer
    print('✅ All imports successful!')
    constellation = TaskConstellation(name='Test Constellation')
    task = TaskStar(task_id='test_task', name='Test Task', description='This is a test task', priority=TaskPriority.MEDIUM)
    print('📊 Adding task...')
    constellation.add_task(task)
    print('🎨 Testing manual visualization...')
    constellation.display_dag('overview')
    print('🎉 DAG visualization test completed successfully!')
except ImportError as e:
    print(f'❌ Import error: {e}')
except Exception as e:
    print(f'❌ Error: {e}')
    import traceback
    traceback.print_exc()
