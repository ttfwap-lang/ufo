"""
Unit tests for updated ConstellationProgressObserver

Tests the refactored observer that queues events for agent state machine
instead of directly calling update methods.
"""
import asyncio
import pytest
import time
from unittest.mock import Mock, AsyncMock, patch
from ufo.galaxy.session.observers import ConstellationProgressObserver
from ufo.galaxy.agents.galaxy_agent import MockGalaxyWeaverAgent
from ufo.galaxy.core.events import TaskEvent, ConstellationEvent, EventType
from ufo.module.context import Context

class TestConstellationProgressObserver:
    """Test the refactored ConstellationProgressObserver."""

    @pytest.fixture
    def mock_agent(self):
        """Create mock agent for testing."""
        agent = MockGalaxyWeaverAgent()
        agent._task_completion_queue = asyncio.Queue()
        agent.logger = Mock()
        return agent

    @pytest.fixture
    def mock_context(self):
        """Create mock context."""
        return Mock(spec=Context)

    @pytest.fixture
    def observer(self, mock_agent, mock_context):
        """Create observer for testing."""
        return ConstellationProgressObserver(mock_agent, mock_context)

    @pytest.mark.asyncio
    async def test_task_event_handling(self, observer, mock_agent):
        """Test task event handling and queueing."""
        task_event = TaskEvent(event_type=EventType.TASK_COMPLETED, source_id='test_orchestrator', timestamp=time.time(), data={'test': 'data'}, task_id='test_task_1', status='completed', result={'success': True}, error=None)
        await observer._handle_task_event(task_event)
        assert 'test_task_1' in observer.task_results
        stored_result = observer.task_results['test_task_1']
        assert stored_result['task_id'] == 'test_task_1'
        assert stored_result['status'] == 'completed'
        assert stored_result['result'] == {'success': True}
        assert not mock_agent.task_completion_queue.empty()
        queued_event = await mock_agent.task_completion_queue.get()
        assert queued_event == task_event

    @pytest.mark.asyncio
    async def test_task_event_with_error(self, observer, mock_agent):
        """Test task event handling with error."""
        error = Exception('Task failed')
        task_event = TaskEvent(event_type=EventType.TASK_FAILED, source_id='test_orchestrator', timestamp=time.time(), data={'error': 'test error'}, task_id='failed_task', status='failed', result=None, error=error)
        await observer._handle_task_event(task_event)
        stored_result = observer.task_results['failed_task']
        assert stored_result['status'] == 'failed'
        assert stored_result['error'] == error
        queued_event = await mock_agent.task_completion_queue.get()
        assert queued_event.status == 'failed'
        assert queued_event.error == error

    @pytest.mark.asyncio
    async def test_agent_without_queue(self, mock_context):
        """Test handling when agent doesn't have task_completion_queue."""
        agent_no_queue = MockGalaxyWeaverAgent()
        agent_no_queue._task_completion_queue = None
        agent_no_queue.logger = Mock()
        observer = ConstellationProgressObserver(agent_no_queue, mock_context)
        task_event = TaskEvent(event_type=EventType.TASK_COMPLETED, source_id='test', timestamp=time.time(), data={'test': 'data'}, task_id='test_task', status='completed', result={}, error=None)
        await observer._handle_task_event(task_event)
        assert hasattr(agent_no_queue, 'task_completion_queue')
        assert isinstance(agent_no_queue.task_completion_queue, asyncio.Queue)
        queued_event = await agent_no_queue.task_completion_queue.get()
        assert queued_event == task_event

    @pytest.mark.asyncio
    async def test_task_event_exception_handling(self, observer, mock_agent):
        """Test exception handling in task event processing."""
        mock_agent.task_completion_queue.put = AsyncMock(side_effect=Exception('Queue error'))
        task_event = TaskEvent(event_type=EventType.TASK_COMPLETED, source_id='test', timestamp=time.time(), data={'test': 'data'}, task_id='test_task', status='completed', result={}, error=None)
        try:
            await observer._handle_task_event(task_event)
        except Exception:
            pytest.fail('Task event handling should not raise exceptions')

    @pytest.mark.asyncio
    async def test_constellation_event_handling(self, observer):
        """Test constellation event handling."""
        constellation_event = ConstellationEvent(event_type=EventType.DAG_MODIFIED, source_id='test_orchestrator', timestamp=time.time(), data={'new_ready_tasks': ['task1', 'task2']}, constellation_id='test_constellation', constellation_state='running', new_ready_tasks=['task1', 'task2'])
        await observer._handle_constellation_event(constellation_event)
        assert True

    @pytest.mark.asyncio
    async def test_constellation_event_exception_handling(self, observer):
        """Test exception handling in constellation event processing."""
        observer.agent.logger.info = Mock(side_effect=Exception('Logger error'))
        constellation_event = ConstellationEvent(event_type=EventType.DAG_MODIFIED, source_id='test', timestamp=time.time(), data={'new_ready_tasks': ['task1']}, constellation_id='test_constellation', constellation_state='running', new_ready_tasks=['task1'])
        try:
            await observer._handle_constellation_event(constellation_event)
        except Exception:
            pytest.fail('Constellation event handling should not raise exceptions')

    @pytest.mark.asyncio
    async def test_on_event_routing(self, observer, mock_agent):
        """Test event routing in on_event method."""
        task_event = TaskEvent(event_type=EventType.TASK_COMPLETED, source_id='test', timestamp=time.time(), data={'test': 'data'}, task_id='route_test_task', status='completed', result={}, error=None)
        await observer.on_event(task_event)
        assert 'route_test_task' in observer.task_results
        queued_event = await mock_agent.task_completion_queue.get()
        assert queued_event == task_event
        constellation_event = ConstellationEvent(event_type=EventType.DAG_MODIFIED, source_id='test', timestamp=time.time(), data={'new_ready_tasks': []}, constellation_id='test_constellation', constellation_state='running', new_ready_tasks=[])
        await observer.on_event(constellation_event)

    @pytest.mark.asyncio
    async def test_multiple_task_events_ordering(self, observer, mock_agent):
        """Test that multiple task events maintain order."""
        events = []
        for i in range(5):
            event = TaskEvent(event_type=EventType.TASK_COMPLETED, source_id='test', timestamp=time.time() + i * 0.001, data={'order': i}, task_id=f'ordered_task_{i}', status='completed', result={'order': i}, error=None)
            events.append(event)
        for event in events:
            await observer._handle_task_event(event)
        queued_events = []
        while not mock_agent.task_completion_queue.empty():
            queued_event = await mock_agent.task_completion_queue.get()
            queued_events.append(queued_event)
        assert len(queued_events) == 5
        for i, event in enumerate(queued_events):
            assert event.task_id == f'ordered_task_{i}'
            assert event.result['order'] == i

    @pytest.mark.asyncio
    async def test_task_result_storage_format(self, observer, mock_agent):
        """Test the format of stored task results."""
        task_event = TaskEvent(event_type=EventType.TASK_COMPLETED, source_id='comprehensive_test', timestamp=1234567890.123, data={'test': 'comprehensive_data'}, task_id='comprehensive_task', status='completed', result={'data': 'test_data', 'metrics': {'duration': 1.5}}, error=None)
        await observer._handle_task_event(task_event)
        stored_result = observer.task_results['comprehensive_task']
        expected_format = {'task_id': 'comprehensive_task', 'status': 'completed', 'result': {'data': 'test_data', 'metrics': {'duration': 1.5}}, 'error': None, 'timestamp': 1234567890.123}
        assert stored_result == expected_format

    @pytest.mark.asyncio
    async def test_concurrent_event_handling(self, observer, mock_agent):
        """Test concurrent event handling."""
        events = []
        for i in range(10):
            event = TaskEvent(event_type=EventType.TASK_COMPLETED, source_id=f'concurrent_test_{i}', timestamp=time.time(), data={'thread': i}, task_id=f'concurrent_task_{i}', status='completed', result={'thread': i}, error=None)
            events.append(event)
        await asyncio.gather(*[observer._handle_task_event(event) for event in events])
        assert len(observer.task_results) == 10
        queued_count = 0
        while not mock_agent.task_completion_queue.empty():
            await mock_agent.task_completion_queue.get()
            queued_count += 1
        assert queued_count == 10

class TestObserverIntegrationWithAgent:
    """Test observer integration with agent state machine."""

    @pytest.fixture
    def integrated_setup(self):
        """Setup for integration testing."""
        agent = MockGalaxyWeaverAgent()
        context = Mock(spec=Context)
        observer = ConstellationProgressObserver(agent, context)
        agent.update_constellation_with_lock = AsyncMock()
        agent.should_continue = AsyncMock(return_value=False)
        return (agent, context, observer)

    @pytest.mark.asyncio
    async def test_end_to_end_event_flow(self, integrated_setup):
        """Test end-to-end event flow from observer to agent state machine."""
        agent, context, observer = integrated_setup
        task_event = TaskEvent(event_type=EventType.TASK_COMPLETED, source_id='integration_test', timestamp=time.time(), data={'integration': True}, task_id='integration_task', status='completed', result={'integration': True}, error=None)
        await observer._handle_task_event(task_event)
        from ufo.galaxy.agents.constellation_agent_states import MonitorConstellationAgentState as MonitorGalaxyAgentState
        state = MonitorGalaxyAgentState()
        await state.handle(agent, context)
        agent.update_constellation_with_lock.assert_called_once()
        call_args = agent.update_constellation_with_lock.call_args[1]
        task_result = call_args['task_result']
        assert task_result['task_id'] == 'integration_task'
        assert task_result['status'] == 'completed'
        assert task_result['result'] == {'integration': True}

    @pytest.mark.asyncio
    async def test_multiple_events_processed_sequentially(self, integrated_setup):
        """Test that multiple events are processed sequentially by agent."""
        agent, context, observer = integrated_setup
        events = []
        for i in range(3):
            event = TaskEvent(event_type=EventType.TASK_COMPLETED, source_id='sequential_test', timestamp=time.time() + i * 0.001, data={'sequence': i}, task_id=f'sequential_task_{i}', status='completed', result={'sequence': i}, error=None)
            events.append(event)
        for event in events:
            await observer._handle_task_event(event)
        from ufo.galaxy.agents.constellation_agent_states import MonitorConstellationAgentState as MonitorGalaxyAgentState
        state = MonitorGalaxyAgentState()
        processed_tasks = []
        for _ in range(3):
            await state.handle(agent, context)
            call_args = agent.update_constellation_with_lock.call_args[1]
            task_result = call_args['task_result']
            processed_tasks.append(task_result['task_id'])
        expected_tasks = [f'sequential_task_{i}' for i in range(3)]
        assert processed_tasks == expected_tasks
if __name__ == '__main__':
    pytest.main([__file__, '-v'])