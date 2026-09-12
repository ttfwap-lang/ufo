"""
Creation mode strategies for Constellation Agent processing.

This module provides specific strategies for constellation creation mode,
implementing the abstract methods defined in the base strategies.
"""
import asyncio
import time
from typing import TYPE_CHECKING, List
from ufo.galaxy.agents.processors.strategies.base_constellation_strategy import BaseConstellationActionExecutionStrategy, ConstellationLLMInteractionStrategy

class ConstellationCreationLLMInteractionStrategy(ConstellationLLMInteractionStrategy):
    """LLM interaction strategy for constellation creation mode."""

    def __init__(self, fail_fast: bool=True) -> None:
        super().__init__(fail_fast=fail_fast)
        self.name = 'constellation_llm_interaction_creation'
        self.weaving_mode = WeavingMode.CREATION
from ufo.galaxy.agents.schema import ConstellationAgentResponse, WeavingMode
from ufo.galaxy.constellation.task_constellation import TaskConstellation
from ufo.galaxy.core.events import AgentEvent, EventType, get_event_bus
from ufo.agents.processors.context.processing_context import ProcessingContext
from ufo.agents.processors.schemas.actions import ActionCommandInfo, ListActionCommandInfo
from ufo.aip.messages import Result
from ufo.module.context import ContextNames
if TYPE_CHECKING:
    from ufo.galaxy.agents.constellation_agent import ConstellationAgent

class ConstellationCreationActionExecutionStrategy(BaseConstellationActionExecutionStrategy):
    """
    Action execution strategy specifically for constellation creation mode.

    This strategy handles:
    - Creation-specific action generation
    - New constellation building commands
    """

    def __init__(self, fail_fast: bool=False) -> None:
        """
        Initialize Constellation creation action execution strategy.
        :param fail_fast: Whether to raise exceptions immediately on errors
        """
        super().__init__(weaving_mode=WeavingMode.CREATION, fail_fast=fail_fast)

    async def _create_mode_specific_action_info(self, agent: 'ConstellationAgent', parsed_response: ConstellationAgentResponse) -> List[ActionCommandInfo]:
        """
        Create creation-specific action information for constellation building.
        """
        if not parsed_response.constellation:
            self.logger.warning('No valid constellation found in response.')
            return []
        try:
            action_info = [ActionCommandInfo(function=agent._constellation_creation_tool_name, arguments={'config': parsed_response.constellation})]
            return action_info
        except Exception as e:
            self.logger.warning(f'Failed to create creation action info: {str(e)}')
            return [ActionCommandInfo(function=agent._constellation_creation_tool_name, arguments={'config': parsed_response.constellation if parsed_response.constellation else '{}'}, status=parsed_response.status if parsed_response.status else 'FAILED')]

    async def publish_actions(self, agent: 'ConstellationAgent', actions: ListActionCommandInfo) -> None:
        """
        Publish constellation creation actions as events.
        For creation mode, publish a simplified action event for WebUI display.

        :param agent: The constellation agent
        :param actions: List of action command information
        """
        if not actions or not actions.actions:
            return
        task_count = 0
        dep_count = 0
        for action in actions.actions:
            if action.function == agent._constellation_creation_tool_name:
                config = action.arguments.get('config')
                if config and hasattr(config, 'tasks'):
                    task_count = len(config.tasks)
                    dep_count = len(config.dependencies) if hasattr(config, 'dependencies') else 0
                elif isinstance(config, dict):
                    task_count = len(config.get('tasks', []))
                    dep_count = len(config.get('dependencies', []))
        status = actions.status
        if not status or status == 'CONTINUE':
            status = 'FINISH'
        event = AgentEvent(event_type=EventType.AGENT_ACTION, source_id=agent.name, timestamp=time.time(), data={}, agent_name=agent.name, agent_type='constellation', output_type='action', output_data={'actions': [{'function': 'build_constellation', 'arguments': {'task_count': task_count, 'dependency_count': dep_count}, 'status': 'success', 'result': {'status': 'success'}}], 'status': status})
        asyncio.create_task(get_event_bus().publish_event(event))

    def sync_constellation(self, results: List[Result], context: ProcessingContext) -> None:
        """
        Synchronize the constellation state. Do nothing for editing mode.
        :param results: List of execution results
        :param context: Processing context to access and update constellation state
        """
        constellation_json = results[0].result if results else None
        if constellation_json:
            constellation = TaskConstellation.from_json(constellation_json)
            context.global_context.set(ContextNames.CONSTELLATION, constellation)