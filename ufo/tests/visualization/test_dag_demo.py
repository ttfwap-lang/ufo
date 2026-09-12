"""
Test script for DAG visualization functionality.

This script demonstrates the DAG visualization features by creating
a sample constellation with tasks and dependencies, then displaying
various visualization modes.
"""
import asyncio
import sys
import os
project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, project_root)
from ufo.galaxy.constellation.task_constellation import TaskConstellation
from ufo.galaxy.constellation.task_star import TaskStar
from ufo.galaxy.constellation.task_star_line import TaskStarLine
from ufo.galaxy.constellation.enums import TaskStatus, DependencyType, TaskPriority, ConstellationState
from ufo.galaxy.visualization.dag_visualizer import DAGVisualizer, visualize_dag

def create_sample_constellation() -> TaskConstellation:
    """Create a sample constellation for demonstration."""
    constellation = TaskConstellation(name='Sample DAG Demo', enable_visualization=True)
    tasks = [TaskStar(task_id='task_1', name='Initialize Project', description='Set up the project environment and dependencies', priority=TaskPriority.HIGH), TaskStar(task_id='task_2', name='Load Data', description='Load and validate input data sources', priority=TaskPriority.MEDIUM), TaskStar(task_id='task_3', name='Process Data', description='Clean and transform the loaded data', priority=TaskPriority.MEDIUM), TaskStar(task_id='task_4', name='Train Model', description='Train the machine learning model', priority=TaskPriority.HIGH), TaskStar(task_id='task_5', name='Evaluate Results', description='Evaluate model performance and generate reports', priority=TaskPriority.LOW), TaskStar(task_id='task_6', name='Deploy Model', description='Deploy the trained model to production', priority=TaskPriority.HIGH)]
    print('📊 Adding tasks to constellation...')
    for task in tasks:
        constellation.add_task(task)
    print('\n🔗 Adding dependencies...')
    dependencies = [TaskStarLine.create_unconditional('task_1', 'task_2', 'Initialize before loading'), TaskStarLine.create_success_only('task_2', 'task_3', 'Data must load successfully'), TaskStarLine.create_success_only('task_1', 'task_4', 'Project setup required'), TaskStarLine.create_success_only('task_3', 'task_4', 'Processed data needed'), TaskStarLine.create_success_only('task_4', 'task_5', 'Model needed for evaluation'), TaskStarLine.create_success_only('task_4', 'task_6', 'Model needed for deployment')]
    for dep in dependencies:
        constellation.add_dependency(dep)
    return constellation

def simulate_execution(constellation: TaskConstellation):
    """Simulate task execution with progress updates."""
    print('\n🚀 Starting constellation execution simulation...')
    constellation.start_execution()
    tasks_to_complete = [('task_1', True, 'Project initialized successfully'), ('task_2', True, 'Data loaded: 10,000 records'), ('task_3', True, 'Data processed and cleaned'), ('task_4', False, 'Model training failed due to insufficient memory'), ('task_5', True, 'Evaluation completed with baseline model'), ('task_6', False, 'Deployment skipped due to model failure')]
    for task_id, success, result in tasks_to_complete:
        print(f"\n📋 Completing task: {task_id} ({('✅ Success' if success else '❌ Failed')})")
        constellation.mark_task_completed(task_id, success, result if success else None, Exception(result) if not success else None)
        import time
        time.sleep(1)
    constellation.complete_execution()

def demonstrate_visualization_modes(constellation: TaskConstellation):
    """Demonstrate different visualization modes."""
    visualizer = DAGVisualizer()
    print('\n' + '=' * 60)
    print('🎨 VISUALIZATION MODES DEMONSTRATION')
    print('=' * 60)
    print('\n1️⃣ OVERVIEW MODE:')
    visualizer.display_constellation_overview(constellation)
    input('\nPress Enter to continue to topology view...')
    print('\n2️⃣ TOPOLOGY MODE:')
    visualizer.display_dag_topology(constellation)
    input('\nPress Enter to continue to task details...')
    print('\n3️⃣ TASK DETAILS MODE:')
    visualizer.display_task_details(constellation)
    input('\nPress Enter to continue to execution flow...')
    print('\n4️⃣ EXECUTION FLOW MODE:')
    visualizer.display_execution_flow(constellation)
    input('\nPress Enter to continue to dependency summary...')
    print('\n5️⃣ DEPENDENCY SUMMARY MODE:')
    visualizer.display_dependency_summary(constellation)

def main():
    """Main demonstration function."""
    print('🌌 DAG Visualization Demo')
    print('=' * 50)
    try:
        constellation = create_sample_constellation()
        print(f'\n✅ Created constellation: {constellation.name}')
        print(f'📊 Tasks: {constellation.task_count}')
        print(f'🔗 Dependencies: {len(constellation.dependencies)}')
        print('\nShowing different visualization modes...')
        demonstrate_visualization_modes(constellation)
        print('\nSimulating task execution...')
        simulate_execution(constellation)
        print('\n🎉 Demo completed!')
        print(f'Final constellation state: {constellation.state.value}')
    except Exception as e:
        print(f'❌ Error during demo: {e}')
        import traceback
        traceback.print_exc()
if __name__ == '__main__':
    main()