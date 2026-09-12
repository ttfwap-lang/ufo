import logging
import traceback
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional
import json
from ufo.agents.processors.context.processing_context import ProcessingContext, ProcessingResult
from ufo.agents.processors.core.processor_framework import ProcessingContext, ProcessingResult
from ufo.module.context import ContextNames
from pydantic_core import to_jsonable_python
if TYPE_CHECKING:
    from ufo.agents.processors.core.processor_framework import ProcessorTemplate
    from ufo.module.basic import FileWriter

class ProcessorMiddleware(ABC):
    """
    Processor middleware base class.
    """

    def __init__(self, name: Optional[str]=None):
        """
        Initialize the middleware.
        :param name: Optional custom name for the middleware. If not provided, uses class name.
        """
        self.name = name or self.__class__.__name__

    @abstractmethod
    async def before_process(self, processor: 'ProcessorTemplate', context: ProcessingContext) -> None:
        """
        Before processing hook.
        :param processor: The processor instance.
        :param context: The processing context.
        """
        pass

    @abstractmethod
    async def after_process(self, processor: 'ProcessorTemplate', result: ProcessingResult) -> None:
        """
        After processing hook.
        :param processor: The processor instance.
        :param result: The processing result.
        """
        pass

    @abstractmethod
    async def on_error(self, processor: 'ProcessorTemplate', error: Exception) -> None:
        """
        Error handling hook.
        :param processor: The processor instance.
        :param error: The error that occurred.
        """
        pass

class EnhancedLoggingMiddleware(ProcessorMiddleware):
    """
    Enhanced logging middleware that handles different types of errors appropriately.
    """

    def __init__(self, log_level: int=logging.INFO, name: Optional[str]=None):
        super().__init__(name)
        self.logger = logging.getLogger(f'{self.__class__.__name__}.{self.name}')
        self.log_level = log_level

    async def before_process(self, processor: 'ProcessorTemplate', context: ProcessingContext) -> None:
        """Log processing start with context information."""
        round_num = context.get('round_num', 0)
        round_step = context.get('round_step', 0)
        self.logger.log(self.log_level, f'Starting processing: Round {round_num + 1}, Step {round_step + 1}, Processor: {processor.__class__.__name__}')

    async def after_process(self, processor: 'ProcessorTemplate', result: ProcessingResult) -> None:
        """Log processing completion with result summary."""
        if result.success:
            self.logger.log(self.log_level, f'Processing completed successfully in {result.execution_time:.2f}s')
            data_keys = list(result.data.keys())
            if data_keys:
                self.logger.debug(f'Result data keys: {data_keys}')
        else:
            self.logger.warning(f'Processing completed with failure: {result.error}')
        local_logger: 'FileWriter' = processor.processing_context.global_context.get(ContextNames.LOGGER)
        local_context = processor.processing_context.local_context
        local_context.total_time = result.execution_time
        phrase_time_cost = {}
        for phrase, phrase_result in processor.processing_context.phase_results.items():
            phrase_time_cost[phrase.name] = phrase_result.execution_time
        local_context.execution_times = phrase_time_cost
        safe_obj = to_jsonable_python(local_context.to_dict(selective=True))
        local_context_string = json.dumps(safe_obj, ensure_ascii=False)
        if local_logger is not None:
            local_logger.write(local_context_string)
            self.logger.info('Log saved successfully.')
        else:
            self.logger.debug('ContextNames.LOGGER is None; skipping file log write.')
        try:
            log_dir = processor.processing_context.get_local('log_path') or processor.processing_context.get_global(ContextNames.LOG_PATH) or ''
            if log_dir:
                from datetime import datetime, timezone
                from ufo.ufo_logging.enhanced_logger import EnhancedActionLogRecord, JSONLEventStreamWriter
                ctx = processor.processing_context
                verification_res = ctx.get_local('verification_result')
                verification_passed = True
                verification_confidence = 1.0
                verification_status = 'success'
                verification_observed_changes = 'No verification executed.'
                if verification_res:
                    verification_passed = bool(getattr(verification_res, 'verified', True))
                    verification_confidence = float(getattr(verification_res, 'confidence_score', 1.0))
                    status_val = getattr(verification_res, 'status', 'success')
                    verification_status = status_val.value if hasattr(status_val, 'value') else str(status_val)
                    verification_observed_changes = str(getattr(verification_res, 'observed_visual_changes', ''))
                record = EnhancedActionLogRecord(session_id=str(ctx.get('session_id', '') or getattr(processor.agent, 'name', 'AppAgent')), timestamp_utc=datetime.now(timezone.utc).isoformat(), round_index=int(ctx.get('round_num', 0) or 0), step_index=int(ctx.get('session_step', 0) or 0), agent_name=str(getattr(processor.agent, 'name', 'AppAgent')), agent_type=str(getattr(processor.agent, 'agent_type', 'app_agent')), user_request=str(ctx.get('request', '') or ''), subtask=str(ctx.get('subtask', '') or ''), application_name=str(ctx.get('application_process_name', '') or ''), process_id=int(ctx.get('process_id', 0) or 0), window_title=str(ctx.get('window_title', '') or ''), observation=str(ctx.get('observation', '') or ''), thought=str(ctx.get('thought', '') or ''), plan=list(ctx.get('plan', []) or []), selected_action_name=str(ctx.get('action_type', '') or ''), action_parameters=dict(ctx.get('arguments', {}) or {}), target_control=dict(ctx.get_local('control_log', {}) or {}), pre_action_screenshot_path=str(ctx.get_local('clean_screenshot_path', '') or ''), post_action_screenshot_path=str(ctx.get_local('post_screenshot_path', '') or ''), annotated_screenshot_path=str(ctx.get_local('annotated_screenshot_path', '') or ''), clean_screenshot_path=str(ctx.get_local('clean_screenshot_path', '') or ''), ui_state_diff=dict(ctx.get_local('ui_state_diff', {}) or {}), verification_passed=verification_passed, verification_confidence=verification_confidence, verification_status=verification_status, verification_observed_changes=verification_observed_changes, execution_duration_ms=float(result.execution_time * 1000.0), llm_cost_usd=float(ctx.get('llm_cost', 0.0) or 0.0), error_stacktrace=str(result.error) if not result.success else None)
                writer = JSONLEventStreamWriter(log_dir)
                writer.write_event(record)
                self.logger.info('Enhanced action log record written to events.jsonl')
        except Exception as e:
            self.logger.warning(f'Failed writing enhanced action log record: {str(e)}')

    async def on_error(self, processor: 'ProcessorTemplate', error: Exception) -> None:
        """Enhanced error logging with context information."""
        from ufo.agents.processors.core.processor_framework import ProcessingException
        if isinstance(error, ProcessingException):
            self.logger.error(f'ProcessingException in {processor.__class__.__name__}:\n  Phase: {error.phase}\n  Message: {str(error)}\n  Context: {error.context_data}\n  Original Exception: {error.original_exception}')
            if error.original_exception:
                self.logger.info(f"Original traceback:\n{''.join(traceback.format_exception(type(error.original_exception), error.original_exception, error.original_exception.__traceback__))}")
        else:
            self.logger.error(f"Unexpected error in {processor.__class__.__name__}: {str(error)}\nError type: {type(error).__name__}\nTraceback:\n{''.join(traceback.format_exception(type(error), error, error.__traceback__))}")