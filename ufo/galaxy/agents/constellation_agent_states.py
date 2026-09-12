"""
Galaxy Agent State Machine

This module implements the state machine for Constellation to handle
constellation orchestration with proper synchronization between task completion
events and agent updates.
"""
import asyncio
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, Type
from ufo.galaxy.agents.schema import WeavingMode
from ufo.galaxy.core.events import EventType
from ufo.agents.states.basic import AgentState, AgentStateManager
from ufo.module.context import Context, ContextNames
if TYPE_CHECKING:
    from ufo.galaxy.agents.constellation_agent import ConstellationAgent

class ConstellationAgentStatus(Enum):
    """Galaxy Agent states"""
    START = 'START'
    CONTINUE = 'CONTINUE'
    FINISH = 'FINISH'
    FAIL = 'FAIL'
    CREATING = 'START'
    EXECUTING = 'executing'
    MONITOR = 'CONTINUE'
    MONITORING = 'CONTINUE'
    FINISHED = 'FINISH'
    FAILED = 'FAIL'

class ConstellationAgentStateManager(AgentStateManager):
    """State manager for Galaxy Agent"""
    _state_mapping: Dict[str, Type[AgentState]] = {}
    START = ConstellationAgentStatus.START
    CONTINUE = ConstellationAgentStatus.CONTINUE
    FINISH = ConstellationAgentStatus.FINISH
    FAIL = ConstellationAgentStatus.FAIL
    CREATING = ConstellationAgentStatus.CREATING
    EXECUTING = ConstellationAgentStatus.EXECUTING
    MONITOR = ConstellationAgentStatus.MONITOR
    MONITORING = ConstellationAgentStatus.MONITORING
    FINISHED = ConstellationAgentStatus.FINISHED
    FAILED = ConstellationAgentStatus.FAILED

    @property
    def none_state(self) -> AgentState:
        return StartConstellationAgentState()

    def get_state(self, status: str) -> AgentState:
        """
        Get the state for the status.
        :param status: The status string or Enum.
        :return: The state object.
        """
        if isinstance(status, Enum):
            status = status.value
        status_str = str(status).upper() if status is not None else ''
        status_mapping = {'START': 'START', 'CREATING': 'START', 'CONTINUE': 'CONTINUE', 'EXECUTING': 'CONTINUE', 'MONITOR': 'CONTINUE', 'MONITORING': 'CONTINUE', 'FINISH': 'FINISH', 'FINISHED': 'FINISH', 'FAIL': 'FAIL', 'FAILED': 'FAIL'}
        lookup_key = status_mapping.get(status_str, status_str)
        if lookup_key not in self._state_instance_mapping:
            state_class = self._state_mapping.get(lookup_key)
            if state_class:
                self._state_instance_mapping[lookup_key] = state_class()
            else:
                return self.none_state
        return self._state_instance_mapping.get(lookup_key, self.none_state)

class ConstellationAgentState(AgentState):
    """Base state for Galaxy Agent"""

    @classmethod
    def agent_class(cls):
        from .constellation_agent import ConstellationAgent
        return ConstellationAgent

    def next_state(self, agent: 'ConstellationAgent') -> AgentState:
        """
        Get the next state of the agent.
        :param agent: The current agent.
        """
        status = getattr(agent, 'status', getattr(agent, '_status', None))
        state = ConstellationAgentStateManager().get_state(status)
        return state

    async def queue_task_update(self, task_update: Dict[str, Any]) -> None:
        """Queue task update method for base state."""
        pass

@ConstellationAgentStateManager.register
class StartConstellationAgentState(ConstellationAgentState):
    """Start state - create and execute constellation"""

    def _configure_task_timeouts(self, constellation) -> None:
        """Configure task timeouts based on config and task priority."""
        if not constellation or not hasattr(constellation, 'tasks'):
            return
        from ufo.galaxy.constellation.enums import TaskPriority
        from ufo.config import Config
        config = Config.get_instance().config_data
        default_timeout = config.get('GALAXY_TASK_TIMEOUT', 1800.0)
        critical_timeout = config.get('GALAXY_CRITICAL_TASK_TIMEOUT', 3600.0)
        tasks = constellation.tasks.values() if isinstance(constellation.tasks, dict) else constellation.tasks
        for task in tasks:
            if getattr(task, '_timeout', None) is None:
                priority = getattr(task, 'priority', None)
                if priority in [TaskPriority.HIGH, 'high', 'HIGH']:
                    task._timeout = critical_timeout
                else:
                    task._timeout = default_timeout

    async def handle(self, agent: 'ConstellationAgent', context: Context=None) -> None:
        if context is None:
            context = Context()
        try:
            if hasattr(agent, 'logger') and agent.logger:
                agent.logger.info('Starting constellation orchestration')
            current_status = getattr(agent, 'status', getattr(agent, '_status', None))
            if current_status in [ConstellationAgentStatus.FINISH.value, ConstellationAgentStatus.FAIL.value, 'finished', 'failed']:
                return
            timing_info = {}
            if not agent.current_constellation:
                if context is not None and hasattr(context, 'set'):
                    context.set(ContextNames.WEAVING_MODE, WeavingMode.CREATION)
                res = None
                if hasattr(agent, 'process_initial_request') and callable(agent.process_initial_request):
                    try:
                        res = await agent.process_initial_request(context)
                    except TypeError:
                        res = await agent.process_initial_request(getattr(agent, 'current_request', 'test request'), context)
                elif hasattr(agent, 'process_creation') and callable(agent.process_creation):
                    res = await agent.process_creation(context)
                if isinstance(res, tuple):
                    agent._current_constellation = res[0]
                    timing_info = res[1] if len(res) > 1 else {}
                else:
                    agent._current_constellation = res
                    timing_info = {}
            if agent.current_constellation and getattr(agent, 'orchestrator', None):
                if timing_info:
                    task = asyncio.create_task(agent.orchestrator.orchestrate_constellation(agent.current_constellation, metadata=timing_info))
                else:
                    task = asyncio.create_task(agent.orchestrator.orchestrate_constellation(agent.current_constellation))
                agent._orchestration_task = task
                if hasattr(agent, 'logger') and agent.logger:
                    agent.logger.info(f"Started orchestration for constellation {getattr(agent.current_constellation, 'constellation_id', 'unknown')}")
                agent._status = 'executing'
                agent.status = 'executing'
            elif agent.current_constellation:
                if hasattr(agent, 'logger') and agent.logger:
                    agent.logger.info(f"Created constellation {getattr(agent.current_constellation, 'constellation_id', 'unknown')} (no orchestrator)")
                agent._status = 'executing'
                agent.status = 'executing'
            else:
                agent._status = 'failed'
                agent.status = 'failed'
                if hasattr(agent, 'logger') and agent.logger:
                    agent.logger.error('Failed to create constellation')
        except Exception as e:
            if hasattr(agent, 'logger') and agent.logger:
                agent.logger.error(f'Error in start state: {e}')
            agent._status = 'failed'
            agent.status = 'failed'

    def next_agent(self, agent):
        return agent

    def is_round_end(self) -> bool:
        return False

    def is_subtask_end(self) -> bool:
        return False

    @classmethod
    def name(cls) -> str:
        return ConstellationAgentStatus.START.value

@ConstellationAgentStateManager.register
class ContinueConstellationAgentState(ConstellationAgentState):
    """Continue state - wait for task completion events"""

    def __init__(self):
        super().__init__()
        self._pending_task_updates = asyncio.Queue()
        self._running_tasks = set()

    async def queue_task_update(self, task_update: Dict[str, Any]) -> None:
        """Queue a task update to be processed by the state machine."""
        await self._pending_task_updates.put(task_update)

    async def _process_pending_updates(self, agent: 'ConstellationAgent', context=None) -> None:
        """Process all pending task updates in the queue."""
        has_completion = False
        while not self._pending_task_updates.empty():
            try:
                update = self._pending_task_updates.get_nowait()
                task_id = update.get('task_id')
                event_type = update.get('event_type')
                if event_type in ('task_started', EventType.TASK_STARTED.value):
                    if task_id:
                        self._running_tasks.add(task_id)
                elif event_type in ('task_completed', EventType.TASK_COMPLETED.value, 'task_failed', EventType.TASK_FAILED.value):
                    if task_id:
                        self._running_tasks.discard(task_id)
                    has_completion = True
            except asyncio.QueueEmpty:
                break
        if has_completion and hasattr(agent, 'update_constellation_with_lock'):
            if callable(agent.update_constellation_with_lock):
                res = agent.update_constellation_with_lock()
                if asyncio.iscoroutine(res):
                    await res

    async def _check_true_completion(self, agent: 'ConstellationAgent', context=None) -> bool:
        """Check if constellation is truly complete."""
        if not self._pending_task_updates.empty():
            return False
        if len(self._running_tasks) > 0:
            return False
        if agent and hasattr(agent, 'should_continue') and callable(agent.should_continue):
            should_cont = agent.should_continue()
            if asyncio.iscoroutine(should_cont):
                should_cont = await should_cont
            if should_cont:
                return False
        if agent and agent.current_constellation:
            if hasattr(agent.current_constellation, 'is_complete'):
                if callable(agent.current_constellation.is_complete):
                    return agent.current_constellation.is_complete()
        return self._pending_task_updates.empty() and len(self._running_tasks) == 0

    async def _get_merged_constellation(self, agent: 'ConstellationAgent', orchestrator_constellation):
        """
        Get real-time merged constellation from synchronizer.

        This ensures that the agent always processes with the most up-to-date
        constellation state, including any structural modifications from previous
        editing sessions that may have completed while this task was running.

        :param agent: The ConstellationAgent instance
        :param orchestrator_constellation: The constellation from orchestrator's event
        :return: Merged constellation with latest agent modifications + orchestrator state
        """
        if not agent or not getattr(agent, 'orchestrator', None):
            if hasattr(agent, 'logger') and agent.logger:
                agent.logger.debug('No orchestrator available, using orchestrator constellation')
            return orchestrator_constellation
        synchronizer = getattr(agent.orchestrator, '_modification_synchronizer', None)
        if not synchronizer:
            if hasattr(agent, 'logger') and agent.logger:
                agent.logger.debug('No modification synchronizer available, using orchestrator constellation')
            return orchestrator_constellation
        merged_constellation = synchronizer.merge_and_sync_constellation_states(orchestrator_constellation=orchestrator_constellation)
        if hasattr(agent, 'logger') and agent.logger:
            agent.logger.info(f"🔄 Real-time merged constellation for editing. Tasks before: {(len(orchestrator_constellation.tasks) if orchestrator_constellation and hasattr(orchestrator_constellation, 'tasks') else 0)}, Tasks after merge: {(len(merged_constellation.tasks) if merged_constellation and hasattr(merged_constellation, 'tasks') else 0)}")
        return merged_constellation

    async def handle(self, agent: 'ConstellationAgent', context=None) -> None:
        if context is None:
            context = Context()
        try:
            if hasattr(agent, 'logger') and agent.logger:
                agent.logger.info('Continue monitoring for task completion events...')
            if context is not None and hasattr(context, 'set'):
                try:
                    context.set(ContextNames.WEAVING_MODE, WeavingMode.EDITING)
                except Exception:
                    pass
            await self._process_pending_updates(agent, context)
            if hasattr(agent, 'update_constellation_with_lock') and callable(agent.update_constellation_with_lock):
                completed_task_events = []
                if hasattr(agent, 'task_completion_queue') and agent.task_completion_queue is not None:
                    try:
                        first_event = await asyncio.wait_for(agent.task_completion_queue.get(), timeout=0.2)
                        completed_task_events.append(first_event)
                    except (asyncio.TimeoutError, AttributeError):
                        pass
                if completed_task_events:
                    event = completed_task_events[0]
                    task_result = {'task_id': event.task_id, 'status': event.status, 'result': getattr(event, 'result', {}), 'error': getattr(event, 'error', None)}
                    try:
                        res = agent.update_constellation_with_lock(completed_task_events[0], context, task_result=task_result)
                    except TypeError:
                        try:
                            res = agent.update_constellation_with_lock(completed_task_events[0], context)
                        except TypeError:
                            res = agent.update_constellation_with_lock()
                    if asyncio.iscoroutine(res) or hasattr(res, '__await__'):
                        await res
                if hasattr(agent, 'should_continue') and callable(agent.should_continue):
                    should_cont = agent.should_continue()
                    if asyncio.iscoroutine(should_cont) or isinstance(should_cont, asyncio.Future):
                        should_cont = await should_cont
                    if not should_cont:
                        agent._status = 'finished'
                        agent.status = 'finished'
                    else:
                        agent._status = 'continue'
                        agent.status = 'continue'
                return
            completed_task_events = []
            if hasattr(agent, 'task_completion_queue') and agent.task_completion_queue is not None:
                try:
                    first_event = await asyncio.wait_for(agent.task_completion_queue.get(), timeout=0.2)
                    completed_task_events.append(first_event)
                except asyncio.TimeoutError:
                    if agent.current_constellation and hasattr(agent.current_constellation, 'is_complete') and callable(agent.current_constellation.is_complete) and agent.current_constellation.is_complete():
                        agent._status = 'finished'
                        agent.status = 'finished'
                    return
                while not agent.task_completion_queue.empty():
                    try:
                        event = agent.task_completion_queue.get_nowait()
                        completed_task_events.append(event)
                    except asyncio.QueueEmpty:
                        break
            if completed_task_events:
                task_ids = [event.task_id for event in completed_task_events]
                latest_constellation = completed_task_events[-1].data.get('constellation') if hasattr(completed_task_events[-1], 'data') and completed_task_events[-1].data else agent.current_constellation
                merged_constellation = await self._get_merged_constellation(agent, latest_constellation)
                await agent.process_editing(context=context, task_ids=task_ids, before_constellation=merged_constellation)
        except Exception as e:
            if hasattr(agent, 'logger') and agent.logger:
                agent.logger.error(f'Error in continue state: {e}')
            agent._status = 'failed'
            agent.status = 'failed'

    def next_agent(self, agent):
        return agent

    def is_round_end(self) -> bool:
        return False

    def is_subtask_end(self) -> bool:
        return False

    @classmethod
    def name(cls) -> str:
        return ConstellationAgentStatus.CONTINUE.value

@ConstellationAgentStateManager.register
class FinishConstellationAgentState(ConstellationAgentState):
    """Finish state - task completed successfully"""

    async def handle(self, agent: 'ConstellationAgent', context=None) -> None:
        if context is None:
            context = Context()
        if hasattr(agent, 'logger') and agent.logger:
            agent.logger.info('Galaxy task completed successfully')
        if agent:
            agent._status = 'finished'
            agent.status = 'finished'
        if hasattr(agent, '_orchestration_task') and agent._orchestration_task and hasattr(agent._orchestration_task, 'done') and (not agent._orchestration_task.done()):
            agent._orchestration_task.cancel()

    def next_state(self, agent: 'ConstellationAgent') -> AgentState:
        return self

    def next_agent(self, agent: 'ConstellationAgent'):
        return agent

    def is_round_end(self) -> bool:
        return True

    def is_subtask_end(self) -> bool:
        return True

    @classmethod
    def name(cls) -> str:
        return ConstellationAgentStatus.FINISH.value

@ConstellationAgentStateManager.register
class FailConstellationAgentState(ConstellationAgentState):
    """Fail state - task failed"""

    async def handle(self, agent: 'ConstellationAgent', context=None) -> None:
        if context is None:
            context = Context()
        if hasattr(agent, 'logger') and agent.logger:
            agent.logger.error('Galaxy task failed')
        if agent:
            agent._status = 'failed'
            agent.status = 'failed'
        if hasattr(agent, '_orchestration_task') and agent._orchestration_task and hasattr(agent._orchestration_task, 'done') and (not agent._orchestration_task.done()):
            agent._orchestration_task.cancel()

    def next_state(self, agent: 'ConstellationAgent') -> AgentState:
        return self

    def next_agent(self, agent: 'ConstellationAgent'):
        return agent

    def is_round_end(self) -> bool:
        return True

    def is_subtask_end(self) -> bool:
        return True

    @classmethod
    def name(cls) -> str:
        return ConstellationAgentStatus.FAIL.value
MonitorConstellationAgentState = ContinueConstellationAgentState