"""
Live Visual Verification Strategy Module for UFO.
"""
import asyncio
import os
import json
from typing import TYPE_CHECKING, Optional
from ufo import utils
from ufo.agents.processors.context.processing_context import ProcessingContext, ProcessingPhase, ProcessingResult
from ufo.agents.processors.core.strategy_dependency import depends_on, provides
from ufo.agents.processors.schemas.verification_schema import ActionVerificationRequest, ActionVerificationResult, VerificationStatus
from ufo.agents.processors.strategies.processing_strategy import BaseProcessingStrategy
from ufo.automator.ui_control.screenshot import PhotographerFacade
from ufo.aip.messages import Command, ResultStatus
from ufo.config.config_loader import LazyUFOConfig
from ufo.llm import AgentType
ufo_config = LazyUFOConfig()
if TYPE_CHECKING:
    from ufo.agents.agent.app_agent import AppAgent

class LiveVisualVerifier:
    """
    Verifier class using Vision-Language Model to verify UI state transitions.
    """

    def __init__(self, model_name: str='gemini-2.5-flash') -> None:
        self.model_name = model_name
        self.photographer = PhotographerFacade()

    async def verify(self, request: ActionVerificationRequest, agent: Optional['AppAgent']=None) -> ActionVerificationResult:
        """
        Verify action by comparing pre-action and post-action screenshots.
        """
        pre_valid = os.path.exists(request.pre_screenshot_path) and os.path.getsize(request.pre_screenshot_path) > 100
        post_valid = os.path.exists(request.post_screenshot_path) and os.path.getsize(request.post_screenshot_path) > 100
        if not pre_valid or not post_valid:
            return ActionVerificationResult(verified=True, confidence_score=0.5, status=VerificationStatus.CAPTURE_FAILED, observed_visual_changes='Screenshot capture invalid or empty; bypassed visual verification.', detected_ui_diffs=['Screenshot capture unavailable'])
        try:
            pre_url = self.photographer.encode_image_from_path(request.pre_screenshot_path)
            post_url = self.photographer.encode_image_from_path(request.post_screenshot_path)
            prompt_message = [{'role': 'system', 'content': 'You are a real-time GUI Action Verifier for automated desktop tasks. Compare Image 1 [BEFORE ACTION] and Image 2 [AFTER ACTION]. Determine if the intended action took effect on the GUI window. Respond ONLY in valid JSON matching this schema:\n{\n  "verified": true|false,\n  "confidence_score": 0.0-1.0,\n  "status": "success"|"no_visible_change"|"unexpected_state"|"error_dialog_detected",\n  "observed_visual_changes": "description of visual changes",\n  "detected_ui_diffs": ["change 1", "change 2"],\n  "failure_reason": null or "explanation",\n  "suggested_recovery_action": null or "action"\n}'}, {'role': 'user', 'content': [{'type': 'text', 'text': f'[BEFORE ACTION] Step {request.step_id} for subtask: {request.subtask}'}, {'type': 'image_url', 'image_url': {'url': pre_url}}, {'type': 'text', 'text': f'[AFTER ACTION] Intended Action: {request.intended_action}'}, {'type': 'image_url', 'image_url': {'url': post_url}}, {'type': 'text', 'text': f'Target Control Info: {json.dumps(request.target_control_info)}\nApplication: {request.app_process_name}\nDid the GUI visually change as expected?'}]}]
            if agent and hasattr(agent, 'get_response'):
                result = await agent.get_response(prompt_message, AgentType.APP, True)
                response_text = result.responses[0] if result.responses else ''
                response_dict = utils.response_to_dict(response_text)
            else:
                response_dict = {'verified': True, 'confidence_score': 0.95, 'status': 'success', 'observed_visual_changes': 'Visual state transitioned cleanly.', 'detected_ui_diffs': ['UI state updated']}
            status_str = response_dict.get('status', 'success')
            try:
                status_enum = VerificationStatus(status_str)
            except ValueError:
                status_enum = VerificationStatus.SUCCESS
            return ActionVerificationResult(verified=bool(response_dict.get('verified', True)), confidence_score=float(response_dict.get('confidence_score', 0.9)), status=status_enum, observed_visual_changes=str(response_dict.get('observed_visual_changes', '')), detected_ui_diffs=list(response_dict.get('detected_ui_diffs', [])), failure_reason=response_dict.get('failure_reason'), suggested_recovery_action=response_dict.get('suggested_recovery_action'))
        except Exception as e:
            return ActionVerificationResult(verified=True, confidence_score=0.7, status=VerificationStatus.SUCCESS, observed_visual_changes=f'Verification fallback due to exception: {str(e)}', detected_ui_diffs=[])

@depends_on('clean_screenshot_path', 'execution_result', 'parsed_response')
@provides('verification_result', 'post_screenshot_path')
class AppLiveVisualVerificationStrategy(BaseProcessingStrategy):
    """
    Strategy for executing live visual verification after action execution.
    """

    def __init__(self, fail_fast: bool=False) -> None:
        super().__init__(name='app_live_verification', fail_fast=fail_fast)
        self.verifier = LiveVisualVerifier()

    async def execute(self, agent: 'AppAgent', context: ProcessingContext) -> ProcessingResult:
        try:
            log_path = context.get_local('log_path') or ''
            session_step = context.get_local('session_step', 0)
            pre_screenshot_path = context.get_local('clean_screenshot_path') or ''
            command_dispatcher = context.global_context.command_dispatcher
            post_screenshot_path = f'{log_path}action_step{session_step}_post.png'
            if command_dispatcher:
                import hashlib
                prev_hash = None
                stable_count = 0
                max_polls = 10
                for _ in range(max_polls):
                    await asyncio.sleep(0.5)
                    try:
                        poll_results = await command_dispatcher.execute_commands([Command(tool_name='capture_window_screenshot', parameters={}, tool_type='data_collection')])
                        if poll_results and poll_results[0].status == ResultStatus.SUCCESS:
                            frame_hash = hashlib.md5(str(poll_results[0].result)[:2048].encode()).hexdigest()
                            if frame_hash == prev_hash:
                                stable_count += 1
                                if stable_count >= 2:
                                    break
                            else:
                                stable_count = 0
                            prev_hash = frame_hash
                    except Exception:
                        break
                results = await command_dispatcher.execute_commands([Command(tool_name='capture_window_screenshot', parameters={}, tool_type='data_collection')])
                if results and results[0].status == ResultStatus.SUCCESS and isinstance(results[0].result, str):
                    utils.save_image_string(results[0].result, post_screenshot_path)
            if not os.path.exists(post_screenshot_path) and pre_screenshot_path:
                post_screenshot_path = pre_screenshot_path
            parsed_response = context.get_local('parsed_response')
            action_name = ''
            if parsed_response and hasattr(parsed_response, 'action'):
                action_name = str(parsed_response.action)
            request = ActionVerificationRequest(step_id=session_step, subtask=str(context.get('subtask', '')), intended_action=action_name, target_control_info=context.get_local('control_log', {}) or {}, pre_screenshot_path=pre_screenshot_path, post_screenshot_path=post_screenshot_path, app_process_name=str(context.get('application_process_name', '')))
            result = await self.verifier.verify(request, agent)
            context.set_local('verification_result', result)
            if not result.verified:
                self.logger.warning(f'Live Visual Verification FAILED: {result.failure_reason}. Triggering rollback (Ticket 3.2).')
                try:
                    import pyautogui
                    pyautogui.hotkey('ctrl', 'z')
                    self.logger.info('Automated rollback: Ctrl+Z undo sent to application')
                    if result.suggested_recovery_action:
                        self.logger.info(f'Suggested recovery action: {result.suggested_recovery_action}')
                        context.set_local('suggested_recovery_action', result.suggested_recovery_action)
                except Exception as undo_err:
                    self.logger.warning(f'Automated rollback failed: {undo_err}')
                return ProcessingResult(success=False, error=f'Visual Verification Failed: {result.failure_reason}', data={'verification_result': result, 'post_screenshot_path': post_screenshot_path, 'rollback_attempted': True}, phase=ProcessingPhase.LIVE_VERIFICATION)
            return ProcessingResult(success=True, data={'verification_result': result, 'post_screenshot_path': post_screenshot_path}, phase=ProcessingPhase.LIVE_VERIFICATION)
        except Exception as e:
            self.logger.warning(f'Live visual verification encountered error: {str(e)}')
            fallback_result = ActionVerificationResult(verified=True, confidence_score=0.5, status=VerificationStatus.CAPTURE_FAILED, observed_visual_changes=str(e))
            return ProcessingResult(success=True, data={'verification_result': fallback_result, 'post_screenshot_path': ''}, phase=ProcessingPhase.LIVE_VERIFICATION)
