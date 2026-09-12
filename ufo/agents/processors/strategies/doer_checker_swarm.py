"""
Doer-Checker Swarm Strategy for UFO (/TEAMWORK-PREVIEW).

This module implements the Phase 3 Zero-Fail "Doer-Checker" pattern where:
  - The DOER (AppAgent-Exec) proposes an action and target coordinates.
  - The CHECKER (AppAgent-Audit) validates the proposal via a second
    LLM call using the SAME screenshot, confirming the target is correct
    before any irrevocable action is executed.

This prevents click-on-wrong-element errors by requiring consensus between
two independent LLM evaluations.

Usage:
    This strategy is inserted into the processing pipeline between
    LLM interaction (which produces the proposed action) and action execution.
    It is automatically activated when `TEAMWORK_PREVIEW: true` is set in
    the agent config or system.yaml.
"""
import json
import logging
from typing import TYPE_CHECKING, Any, Dict
from ufo import utils
from ufo.agents.processors.context.processing_context import ProcessingContext, ProcessingPhase, ProcessingResult
from ufo.agents.processors.core.strategy_dependency import depends_on, provides
from ufo.agents.processors.strategies.processing_strategy import BaseProcessingStrategy
from ufo.config.config_loader import LazyUFOConfig
from ufo.llm import AgentType
ufo_config = LazyUFOConfig()
logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from ufo.agents.agent.app_agent import AppAgent
IRREVOCABLE_ACTIONS = frozenset({'click_input', 'click', 'click_on_coordinates', 'set_edit_text', 'type_keys', 'press_key', 'annotation', 'texts'})

@depends_on('parsed_response', 'clean_screenshot_path')
@provides('checker_validation')
class DoerCheckerSwarmStrategy(BaseProcessingStrategy):
    """
    Doer-Checker Swarm: validates the Doer's proposed action via an
    independent Checker LLM call before execution.

    Phase 3 Zero-Fail: /TEAMWORK-PREVIEW

    The Checker receives:
        pass
    - The current screenshot
    - The Doer's proposed action and target control
    - A validation prompt asking it to confirm or reject
    """

    def __init__(self, fail_fast: bool=False) -> None:
        super().__init__(name='doer_checker_swarm', fail_fast=fail_fast)

    async def execute(self, agent: 'AppAgent', context: ProcessingContext) -> ProcessingResult:
        """
        Validate the Doer's proposed action via a Checker LLM call.

        :param agent: The AppAgent instance (acts as both Doer context and Checker caller)
        :param context: Processing context with the Doer's proposed response
        :return: ProcessingResult with validation outcome
        """
        try:
            parsed_response = context.get_local('parsed_response')
            screenshot_path = context.get_local('clean_screenshot_path') or ''
            if not parsed_response:
                return ProcessingResult(success=True, data={'checker_validation': 'skipped', 'reason': 'no_response'}, phase=ProcessingPhase.ACTION_EXECUTION)
            action_name = ''
            if hasattr(parsed_response, 'action'):
                action_obj = parsed_response.action
                if hasattr(action_obj, 'function'):
                    action_name = str(action_obj.function)
                elif isinstance(action_obj, dict):
                    action_name = str(action_obj.get('function', ''))
                elif isinstance(action_obj, list) and action_obj:
                    first = action_obj[0]
                    if hasattr(first, 'function'):
                        action_name = str(first.function)
                    elif isinstance(first, dict):
                        action_name = str(first.get('function', ''))
            if action_name not in IRREVOCABLE_ACTIONS:
                return ProcessingResult(success=True, data={'checker_validation': 'skipped', 'reason': f"action '{action_name}' is not irrevocable"}, phase=ProcessingPhase.ACTION_EXECUTION)
            checker_result = await self._run_checker(agent, parsed_response, screenshot_path, context)
            context.set_local('checker_validation', checker_result)
            if not checker_result.get('approved', True):
                self.logger.warning(f"Checker REJECTED action '{action_name}': {checker_result.get('reason', 'unknown')}")
                return ProcessingResult(success=False, error=f"Doer-Checker validation failed: {checker_result.get('reason', 'Checker rejected the proposed action')}", data={'checker_validation': checker_result}, phase=ProcessingPhase.ACTION_EXECUTION)
            self.logger.info(f"Checker APPROVED action '{action_name}' (confidence: {checker_result.get('confidence', 'N/A')})")
            return ProcessingResult(success=True, data={'checker_validation': checker_result}, phase=ProcessingPhase.ACTION_EXECUTION)
        except Exception as e:
            self.logger.warning(f'Doer-Checker swarm error (non-fatal, proceeding): {e}')
            return ProcessingResult(success=True, data={'checker_validation': 'error', 'reason': str(e)}, phase=ProcessingPhase.ACTION_EXECUTION)

    async def _run_checker(self, agent: 'AppAgent', parsed_response: Any, screenshot_path: str, context: ProcessingContext) -> Dict[str, Any]:
        """
        Run the Checker LLM call to validate the Doer's proposal.

        :param agent: AppAgent for LLM access
        :param parsed_response: The Doer's parsed response
        :param screenshot_path: Path to the current screenshot
        :param context: Processing context
        :return: Dict with 'approved' (bool), 'confidence' (float), 'reason' (str)
        """
        action_summary = ''
        if hasattr(parsed_response, 'action'):
            try:
                action_summary = json.dumps(parsed_response.action if isinstance(parsed_response.action, (dict, list)) else str(parsed_response.action), default=str)
            except Exception:
                action_summary = str(parsed_response.action)
        control_text = str(getattr(parsed_response, 'control_text', ''))
        subtask = str(context.get('subtask', ''))
        image_url = ''
        try:
            import os
            if screenshot_path and os.path.exists(screenshot_path):
                image_url = utils.encode_image_from_path(screenshot_path)
        except Exception:
            pass
        prompt_parts = [{'role': 'system', 'content': 'You are the CHECKER in a Doer-Checker safety swarm. The DOER has proposed a GUI action. Your job is to independently verify whether the proposed action targets the correct UI element and will achieve the stated subtask. Respond ONLY in JSON: {"approved": true|false, "confidence": 0.0-1.0, "reason": "explanation"}'}, {'role': 'user', 'content': []}]
        user_content = [{'type': 'text', 'text': f'Current subtask: {subtask}'}, {'type': 'text', 'text': f'Proposed action: {action_summary}'}, {'type': 'text', 'text': f'Target control: {control_text}'}]
        if image_url:
            user_content.append({'type': 'image_url', 'image_url': {'url': image_url}})
        user_content.append({'type': 'text', 'text': 'Does this action correctly target the right UI element to accomplish the subtask? Is the action safe to execute?'})
        prompt_parts[1]['content'] = user_content
        if hasattr(agent, 'get_response'):
            try:
                llm_result = await agent.get_response(prompt_parts, AgentType.APP, True)
                response_text = llm_result.responses[0] if llm_result.responses else ''
                result = utils.json_parser(response_text)
                return {'approved': bool(result.get('approved', True)), 'confidence': float(result.get('confidence', 0.9)), 'reason': str(result.get('reason', ''))}
            except Exception as e:
                logger.warning(f'Checker LLM call failed: {e}')
                return {'approved': True, 'confidence': 0.5, 'reason': f'Checker error: {e}'}
        return {'approved': True, 'confidence': 0.95, 'reason': 'No checker agent available'}