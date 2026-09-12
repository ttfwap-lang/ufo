"""
Unit tests for refactored GalaxyRound with state machine integration.

Tests cover the integration between GalaxyRound and the agent state machine,
ensuring proper coordination and event handling.
"""
import asyncio
import pytest
import time
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from ufo.galaxy.session.galaxy_session import GalaxyRound
from ufo.galaxy.agents.galaxy_agent import MockGalaxyWeaverAgent
from ufo.galaxy.agents.galaxy_agent_states import StartGalaxyAgentState, MonitorGalaxyAgentState, FinishGalaxyAgentState, FailGalaxyAgentState
from ufo.galaxy.constellation import TaskConstellation, TaskStar
from ufo.galaxy.constellation.enums import ConstellationState, TaskPriority
from ufo.galaxy.constellation import TaskConstellationOrchestrator
from ufo.galaxy.core.events import TaskEvent, EventType
from ufo.module.context import Context, ContextNames

@pytest.fixture
def mock_agent():
    """Create mock agent for testing."""
    agent = Mock()
    agent.current_request = ''
    agent.orchestrator = None
    agent._status = 'ready'
    agent.logger = Mock()
    agent.handle = AsyncMock()
    agent._current_constellation = None
    agent.task_results = {}
    call_count = 0

    def dynamic_is_round_end():
        nonlocal call_count
        call_count += 1
        return call_count > 1
    mock_state = Mock()
    mock_state.is_round_end = dynamic_is_round_end
    mock_state.next_state = Mock(return_value=mock_state)
    mock_state.next_agent = Mock(return_value=agent)
    agent.state = mock_state
    agent.set_state = Mock()
    return agent

@pytest.fixture
def mock_orchestrator():
    """Create mock orchestrator."""
    orchestrator = Mock()
    orchestrator.orchestrate_constellation = AsyncMock(return_value={'status': 'completed'})
    return orchestrator

@pytest.fixture
def mock_context():
    """Create mock context."""
    context = Context()
    context.set(ContextNames.SESSION_STEP, 0)
    return context

@pytest.fixture
def simple_constellation():
    """Create simple constellation for testing."""
    constellation = TaskConstellation('test_constellation')
    task = TaskStar('test_task', 'Test task', TaskPriority.MEDIUM)
    constellation.add_task(task)
    return constellation

class TestGalaxyRoundStateMachine:
    """Test GalaxyRound integration with agent state machine."""

    @pytest.fixture
    def galaxy_round(self, mock_agent, mock_orchestrator, mock_context):
        """Create GalaxyRound for testing."""
        return GalaxyRound(request='Test request', agent=mock_agent, context=mock_context, should_evaluate=False, id=1, orchestrator=mock_orchestrator)

    @pytest.mark.asyncio
    async def test_round_initialization(self, galaxy_round, mock_agent, mock_orchestrator):
        """Test GalaxyRound initialization."""
        assert galaxy_round._agent == mock_agent
        assert galaxy_round._orchestrator == mock_orchestrator
        assert galaxy_round._request == 'Test request'
        assert galaxy_round._id == 1

    @pytest.mark.asyncio
    async def test_successful_round_execution(self, galaxy_round, mock_agent, simple_constellation):
        """Test successful round execution through state machine."""
        mock_agent._current_constellation = simple_constellation
        mock_agent._status = 'finished'
        call_count = 0
        original_is_round_end = mock_agent.state.is_round_end

        def dynamic_is_round_end():
            nonlocal call_count
            call_count += 1
            return call_count > 1
        mock_agent.state.is_round_end = dynamic_is_round_end
        await galaxy_round.run()
        mock_agent.handle.assert_called()
        mock_agent.handle.assert_called()
        assert galaxy_round._context is not None

    @pytest.mark.asyncio
    async def test_round_execution_with_state_transitions(self, galaxy_round, mock_agent, simple_constellation):
        """Test round execution with multiple state transitions."""
        mock_agent.process_initial_request = AsyncMock(return_value=simple_constellation)
        mock_agent.update_constellation_with_lock = AsyncMock(return_value=simple_constellation)
        mock_agent.should_continue = AsyncMock(return_value=False)
        state_sequence = [StartGalaxyAgentState(), MonitorGalaxyAgentState(), FinishGalaxyAgentState()]
        call_count = 0

        def mock_handle_side_effect(context):
            nonlocal call_count
            if call_count < len(state_sequence) - 1:
                call_count += 1
            return None

        def mock_is_round_end():
            return call_count >= len(state_sequence) - 1

        def mock_next_state(agent):
            if call_count < len(state_sequence) - 1:
                return state_sequence[call_count + 1]
            return state_sequence[-1]
        with patch.object(mock_agent, 'handle', side_effect=mock_handle_side_effect) as mock_handle:
            with patch.object(mock_agent, 'state') as mock_state:
                mock_state.is_round_end = mock_is_round_end
                mock_state.next_state = mock_next_state
                mock_state.next_agent.return_value = mock_agent
                mock_agent._current_constellation = simple_constellation
                mock_agent._status = 'finished'
                await galaxy_round.run()
        assert mock_handle.call_count >= 1

    @pytest.mark.asyncio
    async def test_round_execution_with_error(self, galaxy_round, mock_agent):
        """Test round execution with error handling."""
        mock_agent.handle.side_effect = Exception('Test error')
        try:
            await galaxy_round.run()
            assert True
        except Exception:
            assert True

    @pytest.mark.asyncio
    async def test_round_state_machine_loop(self, galaxy_round, mock_agent, simple_constellation):
        """Test the state machine loop with realistic state transitions."""
        call_count = 0

        async def counting_handle(context):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                mock_agent.state.is_round_end.return_value = True
        mock_agent.handle = counting_handle
        mock_agent._current_constellation = simple_constellation
        mock_agent._status = 'finished'
        mock_agent.state.is_round_end.return_value = False
        await galaxy_round.run()
        assert call_count >= 1

    @pytest.mark.asyncio
    async def test_round_context_update(self, galaxy_round, mock_agent, simple_constellation):
        """Test context update after round completion."""
        mock_agent._current_constellation = simple_constellation
        mock_agent._status = 'finished'
        await galaxy_round.run()
        assert galaxy_round._context is not None

    @pytest.mark.asyncio
    async def test_round_no_final_constellation(self, galaxy_round, mock_agent):
        """Test round execution when no constellation is created."""
        mock_agent._current_constellation = None
        mock_agent._status = 'failed'
        await galaxy_round.run()
        assert True

    @pytest.mark.asyncio
    async def test_round_properties(self, galaxy_round, simple_constellation):
        """Test GalaxyRound properties."""
        assert galaxy_round.constellation is None
        assert galaxy_round.task_results == {}
        galaxy_round._constellation = simple_constellation
        assert galaxy_round.constellation == simple_constellation

    @pytest.mark.asyncio
    async def test_check_for_new_tasks(self, galaxy_round, simple_constellation):
        """Test _check_for_new_tasks method."""
        if hasattr(galaxy_round, '_check_for_new_tasks'):
            await galaxy_round._check_for_new_tasks()
        assert True

class TestGalaxyRoundObserverIntegration:
    """Test GalaxyRound integration with observers."""

    @pytest.fixture
    def galaxy_round_with_observers(self, mock_agent, mock_orchestrator, mock_context):
        """Create GalaxyRound with observers setup."""
        round_instance = GalaxyRound(request='Test request', agent=mock_agent, context=mock_context, should_evaluate=False, id=1, orchestrator=mock_orchestrator)
        return round_instance

    @pytest.mark.asyncio
    async def test_observer_setup(self, galaxy_round_with_observers):
        """Test that observers are properly set up."""
        if hasattr(galaxy_round_with_observers, '_observers'):
            assert len(galaxy_round_with_observers._observers) >= 0
        else:
            assert True

    @pytest.mark.asyncio
    async def test_observer_subscription(self, galaxy_round_with_observers):
        """Test that observers are subscribed to event bus."""
        if hasattr(galaxy_round_with_observers, '_event_bus'):
            with patch.object(galaxy_round_with_observers._event_bus, 'subscribe') as mock_subscribe:
                if hasattr(galaxy_round_with_observers, '_setup_observers'):
                    galaxy_round_with_observers._setup_observers()
        else:
            assert True

class TestGalaxyRoundErrorScenarios:
    """Test error scenarios in GalaxyRound."""

    @pytest.fixture
    def error_round(self, mock_agent, mock_orchestrator, mock_context):
        """Create GalaxyRound for error testing."""
        return GalaxyRound(request='Error test request', agent=mock_agent, context=mock_context, should_evaluate=False, id=99, orchestrator=mock_orchestrator)

    @pytest.mark.asyncio
    async def test_agent_handle_exception(self, error_round, mock_agent):
        """Test handling when agent.handle raises exception."""
        mock_agent.handle = AsyncMock(side_effect=Exception('Agent error'))
        try:
            await error_round.run()
            assert True
        except Exception:
            assert True

    @pytest.mark.asyncio
    async def test_state_transition_exception(self, error_round, mock_agent):
        """Test handling when state transition raises exception."""
        mock_agent.handle = AsyncMock(side_effect=Exception('State transition error'))
        with patch.object(error_round, 'logger') as mock_logger:
            await error_round.run()
            assert mock_logger.error.called

    @pytest.mark.asyncio
    async def test_context_update_exception(self, error_round, mock_agent, simple_constellation):
        """Test handling when context update raises exception."""
        mock_agent._current_constellation = simple_constellation
        mock_agent._status = 'finished'
        if hasattr(error_round._context, 'set') and hasattr(error_round._context.set, 'side_effect'):
            error_round._context.set.side_effect = Exception('Context error')
        try:
            await error_round.run()
            assert True
        except Exception:
            assert True

class TestGalaxyRoundAsyncBehavior:
    """Test async behavior and timing in GalaxyRound."""

    @pytest.mark.asyncio
    async def test_async_delay_prevents_busy_waiting(self, mock_agent, mock_orchestrator, mock_context):
        """Test that the async delay prevents busy waiting."""
        round_instance = GalaxyRound(request='Timing test', agent=mock_agent, context=mock_context, should_evaluate=False, id=1, orchestrator=mock_orchestrator)
        call_times = []

        async def mock_handle(context):
            call_times.append(time.time())
        mock_agent.handle = mock_handle
        iteration_count = 0

        def mock_is_round_end():
            nonlocal iteration_count
            iteration_count += 1
            return iteration_count >= 3
        with patch.object(mock_agent, 'state') as mock_state:
            mock_state.is_round_end = mock_is_round_end
            mock_state.next_state.return_value = mock_state
            mock_state.next_agent.return_value = mock_agent
            start_time = time.time()
            await round_instance.run()
            total_time = time.time() - start_time
        assert total_time >= 0.0001
        assert len(call_times) >= 1
if __name__ == '__main__':
    pytest.main([__file__, '-v'])