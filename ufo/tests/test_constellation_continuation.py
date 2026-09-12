"""
测试constellation完成后继续添加新任务的场景
"""
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock
from ufo.galaxy.agents.galaxy_agent_state import MonitoringGalaxyAgentState, GalaxyAgentStatus
from ufo.galaxy.core.events import EventType
from ufo.module.context import Context

class MockGalaxyWeaverAgent:
    """Mock GalaxyWeaverAgent for testing constellation continuation"""

    def __init__(self):
        self._status = GalaxyAgentStatus.MONITORING.value
        self._current_constellation = None
        self.continue_call_count = 0
        self.new_tasks_added = False

    @property
    def current_constellation(self):
        return self._current_constellation

    @current_constellation.setter
    def current_constellation(self, value):
        self._current_constellation = value

    async def update_constellation_with_lock(self, task_result, context=None):
        return self._current_constellation

    async def should_continue(self, constellation, context=None):
        """模拟agent决定是否继续"""
        self.continue_call_count += 1
        if self.continue_call_count == 1:
            await self._add_new_tasks()
            return True
        else:
            return False

    async def _add_new_tasks(self):
        """模拟添加新任务到constellation"""
        self.new_tasks_added = True

class TestConstellationContinuation:
    """测试constellation完成后的继续执行"""

    @pytest.mark.asyncio
    async def test_continuation_after_completion(self):
        """测试constellation完成后继续添加任务"""
        monitoring_state = MonitoringGalaxyAgentState()
        agent = MockGalaxyWeaverAgent()
        context = Context()
        mock_constellation = MagicMock()
        mock_constellation.is_complete.return_value = True
        agent.current_constellation = mock_constellation
        agent.queue_task_update_to_current_state = monitoring_state.queue_task_update
        try:
            await asyncio.wait_for(monitoring_state.handle(agent, context), timeout=2.0)
        except asyncio.TimeoutError:
            print('Handle method timed out - this indicates the busy waiting issue')
        assert agent.continue_call_count > 0
        assert agent.new_tasks_added
        print(f'should_continue called {agent.continue_call_count} times')
        print(f'New tasks added: {agent.new_tasks_added}')

    @pytest.mark.asyncio
    async def test_constellation_continuation_with_new_tasks(self):
        """测试constellation完成后添加新任务并正确执行"""
        monitoring_state = MonitoringGalaxyAgentState()
        agent = MockGalaxyWeaverAgent()
        context = Context()
        mock_constellation = MagicMock()
        agent.current_constellation = mock_constellation
        agent.queue_task_update_to_current_state = monitoring_state.queue_task_update
        mock_constellation.is_complete.return_value = True

        async def mock_should_continue(constellation, context=None):
            agent.continue_call_count += 1
            if agent.continue_call_count == 1:
                await monitoring_state.queue_task_update({'task_id': 'new_task_1', 'event_type': EventType.TASK_STARTED.value, 'status': 'running'})
                return True
            else:
                return False
        agent.should_continue = mock_should_continue
        monitoring_task = asyncio.create_task(monitoring_state.handle(agent, context))
        await asyncio.sleep(0.1)
        await monitoring_state.queue_task_update({'task_id': 'new_task_1', 'event_type': EventType.TASK_COMPLETED.value, 'status': 'completed'})
        try:
            await asyncio.wait_for(monitoring_task, timeout=1.0)
        except asyncio.TimeoutError:
            monitoring_task.cancel()
            pytest.fail('Monitoring did not complete in expected time')
        assert agent.continue_call_count >= 1
        assert agent._status == GalaxyAgentStatus.FINISHED.value
if __name__ == '__main__':

    async def run_tests():
        test_case = TestConstellationContinuation()
        print('🧪 Testing constellation completion continuation...')
        try:
            await test_case.test_continuation_after_completion()
            print('✅ Basic continuation test completed')
        except Exception as e:
            print(f'❌ Basic continuation test failed: {e}')
        try:
            await test_case.test_constellation_continuation_with_new_tasks()
            print('✅ Continuation with new tasks test completed')
        except Exception as e:
            print(f'❌ Continuation with new tasks test failed: {e}')
    asyncio.run(run_tests())