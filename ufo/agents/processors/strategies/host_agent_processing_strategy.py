"""
Host Agent Processor V2 - Refactored processor for Host Agent using the new framework.

This processor handles the Host Agent's workflow including:
- Desktop screenshot capture
- Application window detection and registration
- Third-party agent integration
- LLM interaction with proper context building
- Action execution and application selection
- Memory management and logging

The processor maintains backward compatibility with BaseProcessor interface
while providing enhanced modularity, error handling, and extensibility.
"""
import json
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from ufo import utils
from ufo.agents.memory.memory import MemoryItem
from ufo.agents.processors.context.host_agent_processing_context import HostAgentProcessorContext
from ufo.agents.processors.core.processor_framework import ProcessingContext, ProcessingPhase, ProcessingResult
from ufo.agents.processors.core.strategy_dependency import depends_on, provides
from ufo.agents.processors.schemas.actions import ActionCommandInfo
from ufo.agents.processors.schemas.log_schema import HostAgentRequestLog
from ufo.agents.processors.schemas.response_schema import HostAgentResponse
from ufo.agents.processors.schemas.target import TargetInfo, TargetKind, TargetRegistry
from ufo.agents.processors.strategies.processing_strategy import BaseProcessingStrategy
from ufo.config.config_loader import LazyUFOConfig
from ufo.aip.messages import Command, Result, ResultStatus
from ufo.llm import AgentType
from ufo.module.context import ContextNames
from ufo.module.dispatcher import BasicCommandDispatcher
ufo_config = LazyUFOConfig()
if TYPE_CHECKING:
    from ufo.agents.agent.host_agent import HostAgent
    from ufo.module.basic import FileWriter

@depends_on('command_dispatcher', 'log_path', 'session_step')
@provides('desktop_screenshot_url', 'desktop_screenshot_path', 'application_windows_info', 'target_registry', 'target_info_list')
class DesktopDataCollectionStrategy(BaseProcessingStrategy):
    """
    Enhanced strategy for collecting desktop environment data with comprehensive error handling.

    This strategy handles:
    - Desktop screenshot capture with proper path management
    - Application window detection and filtering
    - Third-party agent registration and configuration
    - Target registry management for application selection
    """

    def __init__(self, fail_fast: bool=True) -> None:
        """
        Initialize desktop data collection strategy.
        :param fail_fast: Whether to raise exceptions immediately on errors
        """
        super().__init__(name='desktop_data_collection', fail_fast=fail_fast)

    async def execute(self, agent: 'HostAgent', context: ProcessingContext) -> ProcessingResult:
        """
        Execute comprehensive desktop data collection with enhanced error handling.
        :param agent: The HostAgent instance.
        :param context: Processing context with global and local data
        :return: ProcessingResult with collected desktop data or error information
        """
        try:
            command_dispatcher = context.global_context.command_dispatcher
            log_path = context.get('log_path', '')
            session_step = context.get('session_step', 0)
            self.logger.info('Starting desktop screenshot capture')
            desktop_save_path = f'{log_path}action_step{session_step}.png'
            desktop_screenshot_url = await self._capture_desktop_screenshot(command_dispatcher, desktop_save_path)
            self.logger.info('Collecting desktop application information')
            app_windows_info = await self._get_desktop_application_info(command_dispatcher)
            self.logger.info(f'Registering {len(app_windows_info)} applications')
            existing_target_registry = context.get_local('target_registry')
            target_registry = self._register_applications_and_agents(app_windows_info, existing_target_registry)
            target_info_list = target_registry.to_list(keep_keys=['id', 'name', 'kind'])
            return ProcessingResult(success=True, data={'desktop_screenshot_url': desktop_screenshot_url, 'desktop_screenshot_path': desktop_save_path, 'application_windows_info': app_windows_info, 'target_registry': target_registry, 'target_info_list': target_info_list}, phase=ProcessingPhase.DATA_COLLECTION)
        except Exception as e:
            error_msg = f'Desktop data collection failed: {str(e)}'
            self.logger.error(error_msg)
            return self.handle_error(e, ProcessingPhase.DATA_COLLECTION, context)

    async def _capture_desktop_screenshot(self, command_dispatcher: BasicCommandDispatcher, save_path: str) -> str:
        """
        Capture desktop screenshot with proper error handling and path management.
        :param command_dispatcher: Command dispatcher for executing commands
        :param save_path: Log path for saving screenshots
        :return: Screenshot URL
        :raises: Exception if screenshot capture fails
        """
        try:
            if not command_dispatcher:
                raise ValueError('Command dispatcher not available in context')
            result = await command_dispatcher.execute_commands([Command(tool_name='capture_desktop_screenshot', parameters={'all_screens': True}, tool_type='data_collection')])
            if not result or not result[0].result or result[0].status != ResultStatus.SUCCESS:
                raise RuntimeError('Screenshot capture returned empty result')
            desktop_screenshot_url = result[0].result
            if not isinstance(desktop_screenshot_url, str) or not desktop_screenshot_url.startswith('data:image/'):
                raise RuntimeError('Screenshot capture returned invalid image data')
            saved_image = utils.save_image_string(desktop_screenshot_url, save_path)
            if not saved_image or saved_image.size[0] <= 1 or saved_image.size[1] <= 1:
                self.logger.warning('Desktop screenshot capture produced a tiny image; retrying with primary screen only.')
                result = await command_dispatcher.execute_commands([Command(tool_name='capture_desktop_screenshot', parameters={'all_screens': False}, tool_type='data_collection')])
                if not result or not result[0].result or result[0].status != ResultStatus.SUCCESS:
                    raise RuntimeError('Desktop screenshot retry returned empty result')
                desktop_screenshot_url = result[0].result
                if not isinstance(desktop_screenshot_url, str) or not desktop_screenshot_url.startswith('data:image/'):
                    raise RuntimeError('Desktop screenshot retry returned invalid image data')
                saved_image = utils.save_image_string(desktop_screenshot_url, save_path)
                if not saved_image or saved_image.size[0] <= 1 or saved_image.size[1] <= 1:
                    raise RuntimeError('Desktop screenshot retry produced a tiny image')
            self.logger.info(f'Desktop screenshot saved to: {save_path}')
            return desktop_screenshot_url
        except Exception as e:
            self.logger.warning(f'Failed to capture desktop screenshot, using empty image: {str(e)}')
            desktop_screenshot_url = utils._empty_image_string
            utils.save_image_string(desktop_screenshot_url, save_path)
            return desktop_screenshot_url

    async def _get_desktop_application_info(self, command_dispatcher: BasicCommandDispatcher) -> List[TargetInfo]:
        """
        Get comprehensive desktop application information with filtering.
        :param command_dispatcher: Command dispatcher for executing commands
        :return: List of application window information dictionaries
        :raises: Exception if application info collection fails
        """
        try:
            if not command_dispatcher:
                raise ValueError('Command dispatcher not available in context')
            result = await command_dispatcher.execute_commands([Command(tool_name='get_desktop_app_target_info', parameters={'remove_empty': True, 'refresh_app_windows': True}, tool_type='data_collection')])
            if not result:
                raise RuntimeError('Desktop app info collection returned empty result')
            app_windows_info = result[0].result or []
            self.logger.info(f'Found {len(app_windows_info)} desktop windows')
            target_info = []
            for control_info in app_windows_info:
                if isinstance(control_info, TargetInfo):
                    target_info.append(control_info)
                elif isinstance(control_info, dict):
                    c_dict = dict(control_info)
                    if 'kind' not in c_dict or not c_dict['kind']:
                        c_dict['kind'] = TargetKind.WINDOW
                    if 'name' not in c_dict and 'control_text' in c_dict:
                        c_dict['name'] = c_dict['control_text']
                    if 'name' not in c_dict or not c_dict['name']:
                        c_dict['name'] = 'UnknownWindow'
                    target_info.append(TargetInfo(**c_dict))
                else:
                    target_info.append(TargetInfo(kind=TargetKind.WINDOW, name=str(control_info)))
            return target_info
        except Exception as e:
            raise Exception(f'Failed to get desktop application info: {str(e)}')

    def _register_applications_and_agents(self, app_windows_info: List[TargetInfo], target_registry: TargetRegistry=None) -> TargetRegistry:
        """
        Register desktop applications and third-party agents in target registry.
        :param app_windows_info: List of application window information
        :param target_registry: Target registry to use, creates new one if None
        :return: Target registry with registered applications and agents
        """
        try:
            if not target_registry:
                target_registry = TargetRegistry()
            target_registry.register(app_windows_info)
            self.logger.info(f'Registered {len(app_windows_info)} application windows')
            third_party_count = self._register_third_party_agents(target_registry, len(app_windows_info))
            self.logger.info(f'Registered {third_party_count} third-party agents')
            return target_registry
        except Exception as e:
            raise Exception(f'Failed to register applications and agents: {str(e)}')

    def _register_third_party_agents(self, target_registry: TargetRegistry, start_index: int) -> int:
        """
        Register enabled third-party agents with proper indexing.
        :param target_registry: Target registry to add agents to
        :param start_index: Starting index for agent IDs
        :return: Number of third-party agents registered
        """
        try:
            third_party_agent_names = ufo_config.system.enabled_third_party_agents
            if not third_party_agent_names:
                self.logger.info('No third-party agents configured')
                return 0
            third_party_agent_list = []
            for i, agent_name in enumerate(third_party_agent_names):
                agent_id = str(i + start_index + 1)
                third_party_agent_list.append(TargetInfo(kind=TargetKind.THIRD_PARTY_AGENT.value, id=agent_id, type='ThirdPartyAgent', name=agent_name))
            target_registry.register(third_party_agent_list)
            return len(third_party_agent_list)
        except Exception as e:
            self.logger.warning(f'Failed to register third-party agents: {str(e)}')
            return 0

@depends_on('target_info_list', 'desktop_screenshot_url')
@provides('parsed_response', 'response_text', 'llm_cost', 'prompt_message', 'subtask', 'plan', 'result', 'host_message', 'status', 'question_list', 'function_name', 'function_arguments')
class HostLLMInteractionStrategy(BaseProcessingStrategy):
    """
    Enhanced LLM interaction strategy for Host Agent with comprehensive context building.

    This strategy handles:
    - Context-aware prompt construction with blackboard integration
    - Robust LLM interaction with retry logic
    - Response parsing and validation
    - Request logging for debugging and analysis
    """

    def __init__(self, fail_fast: bool=True) -> None:
        """
        Initialize Host Agent LLM interaction strategy.
        :param fail_fast: Whether to raise exceptions immediately on errors
        """
        super().__init__(name='host_llm_interaction', fail_fast=fail_fast)

    async def execute(self, agent: 'HostAgent', context: ProcessingContext) -> ProcessingResult:
        """
        Execute LLM interaction with comprehensive error handling and retry logic.
        :param agent: The HostAgent instance.
        :param context: Processing context with desktop data and agent information
        :return: ProcessingResult containing parsed response or error information
        """
        try:
            target_info_list = context.get_local('target_info_list', [])
            desktop_screenshot_url = context.get_local('desktop_screenshot_url', '')
            prev_plan = self._get_prev_plan(agent)
            previous_subtasks = context.get('previous_subtasks', [])
            request = context.get('request', '')
            session_step = context.get('session_step', 0)
            request_logger = context.get_global('request_logger')
            host_agent = agent
            if not host_agent:
                raise ValueError('Host agent not available')
            self.logger.info('Building prompt message with context')
            prompt_message = await self._build_comprehensive_prompt(host_agent, target_info_list, desktop_screenshot_url, prev_plan, previous_subtasks, request, session_step, request_logger)
            self.logger.info('Sending request to LLM')
            response_text, llm_cost = await self._get_llm_response_with_retry(host_agent, prompt_message)

            self.logger.info('Parsing LLM response')
            parsed_response = self._parse_and_validate_response(host_agent, response_text)
            self.logger.info(f"Host LLM interaction status set to: {context.get_local('status')}")
            structured_data = self._extract_structured_response_data(parsed_response)
            return ProcessingResult(success=True, data={'parsed_response': parsed_response, 'response_text': response_text, 'llm_cost': llm_cost, 'prompt_message': prompt_message, **structured_data}, phase=ProcessingPhase.LLM_INTERACTION)
        except Exception as e:
            error_msg = f'Host LLM interaction failed: {str(e)}'
            self.logger.error(error_msg)
            return self.handle_error(e, ProcessingPhase.LLM_INTERACTION, context)

    def _get_prev_plan(self, agent: 'HostAgent') -> List[str]:
        """
        Get the previous plan from the agent's memory.
        :param agent: The AppAgent instance
        :return: List of previous plan steps
        """
        try:
            agent_memory = agent.memory
            if agent_memory.length > 0:
                prev_plan = agent_memory.get_latest_item().to_dict().get('plan', [])
            else:
                prev_plan = []
            return prev_plan
        except Exception as e:
            self.logger.error(f'Failed to get previous plan: {str(e)}')
            return []

    async def _build_comprehensive_prompt(self, agent: 'HostAgent', target_info_list: List[Any], desktop_screenshot_url: str, prev_plan: List[Any], previous_subtasks: List[Any], request: str, session_step: int, request_logger) -> Dict[str, Any]:
        """
        Build comprehensive prompt message with all available context information.
        :param agent: The HostAgent instance.
        :param target_info_list: List of target information
        :param desktop_screenshot_url: URL of desktop screenshot
        :param prev_plan: Previous plan
        :param previous_subtasks: Previous subtasks
        :param request: User request
        :param session_step: Current session step
        :param request_logger: Request logger
        :return: Complete prompt message dictionary for LLM interaction
        """
        try:
            host_agent: 'HostAgent' = agent
            blackboard_prompt = []
            if not host_agent.blackboard.is_empty():
                blackboard_prompt = host_agent.blackboard.blackboard_to_prompt()
                self.logger.debug(f'Including {len(blackboard_prompt)} blackboard items')
            prompt_message = host_agent.message_constructor(image_list=[desktop_screenshot_url] if desktop_screenshot_url else [], os_info=target_info_list, plan=prev_plan, prev_subtask=previous_subtasks, request=request, blackboard_prompt=blackboard_prompt)
            self._log_request_data(session_step, desktop_screenshot_url, target_info_list, prev_plan, previous_subtasks, request, blackboard_prompt, prompt_message, request_logger)
            self.logger.debug(f'Built prompt with {len(target_info_list)} targets')
            return prompt_message
        except Exception as e:
            raise Exception(f'Failed to build prompt message: {str(e)}')

    def _log_request_data(self, session_step: int, desktop_screenshot_url: str, target_info_list: List[Any], prev_plan: List[Any], previous_subtasks: List[Any], request: str, blackboard_prompt: List[str], prompt_message: Dict[str, Any], request_logger: 'FileWriter') -> None:
        """
        Log request data for debugging and analysis (only in debug mode).
        :param session_step: Current session step
        :param desktop_screenshot_url: Desktop screenshot URL
        :param target_info_list: List of target information
        :param prev_plan: Previous plan
        :param previous_subtasks: Previous subtasks
        :param request: User request
        :param blackboard_prompt: Extracted blackboard prompt items
        :param prompt_message: Constructed prompt message
        :param request_logger: Request logger
        """
        try:
            request_data = HostAgentRequestLog(step=session_step, image_list=[desktop_screenshot_url] if desktop_screenshot_url else [], os_info=target_info_list, plan=prev_plan, prev_subtask=previous_subtasks, request=request, blackboard_prompt=blackboard_prompt, prompt=prompt_message)
            request_log_str = json.dumps(asdict(request_data), ensure_ascii=False)
            if request_logger:
                request_logger.write(request_log_str)
        except Exception as e:
            self.logger.warning(f'Failed to log request data: {str(e)}')

    async def _get_llm_response_with_retry(self, host_agent: 'HostAgent', prompt_message: Dict[str, Any]) -> tuple[str, float]:
        """
        Get LLM response with retry logic for JSON parsing failures.
        :param host_agent: Host agent instance
        :param prompt_message: Prompt message for LLM
        :return: Tuple of (response_text, cost)
        :raises: Exception if all retry attempts fail
        """
        max_retries = ufo_config.system.json_parsing_retry
        last_exception = None
        for retry_count in range(max_retries):
            try:
                result = await host_agent.get_response(prompt_message, AgentType.HOST, True)
                response_text = result.responses[0] if result.responses else ''
                cost = result.cost
                host_agent.response_to_dict(response_text)
                if retry_count > 0:
                    self.logger.info(f'LLM response successful after {retry_count} retries')
                return (response_text, cost)
            except Exception as e:
                last_exception = e
                if retry_count < max_retries - 1:
                    self.logger.warning(f'LLM response parsing failed (attempt {retry_count + 1}/{max_retries}): {str(e)}')
                else:
                    self.logger.error(f'LLM response parsing failed after all retries: {str(e)}')
        raise Exception(f'LLM interaction failed after {max_retries} attempts: {str(last_exception)}')

    def _parse_and_validate_response(self, host_agent: 'HostAgent', response_text: str) -> HostAgentResponse:
        """
        Parse and validate LLM response into structured format.
        :param host_agent: Host agent instance
        :param response_text: Raw response text from LLM
        :return: Parsed and validated HostAgentResponse object
        :raises: Exception if response parsing or validation fails
        """
        try:
            response_dict = host_agent.response_to_dict(response_text)
            if isinstance(response_dict, dict):
                response_dict = utils._normalize_keys(response_dict)
                if not response_dict.get('function'):
                    for k, v in list(response_dict.items()):
                        if isinstance(k, str) and k.lower() in ('function', 'func', 'fn', 'action'):
                            if isinstance(v, str) and v.strip():
                                response_dict['function'] = v.strip()
                                break
                            elif isinstance(v, list) and v and isinstance(v[0], dict) and ('function' in v[0]):
                                response_dict['function'] = v[0]['function']
                                if 'arguments' in v[0] and (not response_dict.get('arguments')):
                                    response_dict['arguments'] = v[0]['arguments']
                                break
                            elif isinstance(v, dict):
                                response_dict['function'] = v.get('function', '')
                                response_dict['arguments'] = v.get('arguments', {})
                                break
                if not response_dict.get('arguments'):
                    for k, v in list(response_dict.items()):
                        if isinstance(k, str) and k.lower() in ('arguments', 'args', 'parameters', 'params'):
                            if isinstance(v, dict):
                                response_dict['arguments'] = v
                                break
                if isinstance(response_dict.get('arguments'), dict):
                    args = response_dict['arguments']
                    if 'command' in args:
                        val = args.pop('command')
                        if 'bash_command' not in args:
                            args['bash_command'] = val
                    if 'cmd' in args:
                        val = args.pop('cmd')
                        if 'bash_command' not in args:
                            args['bash_command'] = val
                plan_val = response_dict.get('plan')
                if isinstance(plan_val, str):
                    response_dict['plan'] = [plan_val] if plan_val.strip() else []
                elif plan_val is None:
                    response_dict['plan'] = []
            parsed_response = HostAgentResponse.model_validate(response_dict)
            self._validate_response_fields(parsed_response)
            host_agent.print_response(parsed_response)
            return parsed_response
        except Exception as e:
            raise Exception(f'Failed to parse LLM response: {str(e)}')

    def _validate_response_fields(self, response: HostAgentResponse) -> None:
        """
        Validate that response contains required fields and valid values.
        :param response: Parsed response object
        :raises: ValueError if If response validation fails
        """
        if not response.observation:
            raise ValueError("Response missing required 'observation' field")
        if not response.thought:
            raise ValueError("Response missing required 'thought' field")
        if not response.status:
            raise ValueError("Response missing required 'status' field")
        valid_statuses = ['CONTINUE', 'FINISH', 'ERROR', 'ASSIGN']
        import os
        allow_pending = os.environ.get('UFO_ALLOW_PENDING', '0') == '1'
        if allow_pending:
            valid_statuses.append('PENDING')
        if response.status.upper() not in valid_statuses:
            self.logger.warning(f'Unexpected status value: {response.status}')
            if response.status.upper() == 'PENDING' and (not allow_pending):
                self.logger.error('PENDING status received but cannot be handled automatically. Forcing ERROR.')
                response.status = 'ERROR'
            elif not allow_pending or response.status.upper() != 'PENDING':
                response.status = 'ERROR'

    def _extract_structured_response_data(self, response: HostAgentResponse) -> Dict[str, Any]:
        """
        Extract structured data from parsed response for use by subsequent strategies.
        :param response: Parsed response object
        :return: Dictionary containing extracted structured data
        """
        plan = response.plan
        if isinstance(plan, str) and plan.strip():
            plan = [item.strip() for item in plan.split('\n') if item.strip()]
        elif not isinstance(plan, list):
            plan = []
        return {'subtask': response.current_subtask, 'plan': plan, 'host_message': response.message, 'status': response.status, 'result': response.result, 'question_list': response.questions, 'function_name': response.function, 'function_arguments': response.arguments or {}}

@depends_on('target_registry', 'command_dispatcher')
@provides('execution_result', 'action_info', 'selected_target_id', 'selected_application_root', 'assigned_third_party_agent', 'target')
class HostActionExecutionStrategy(BaseProcessingStrategy):
    """
    Enhanced action execution strategy for Host Agent with comprehensive error handling.

    This strategy handles:
    - Application selection and window management
    - Third-party agent assignment and coordination
    - Generic command execution with proper error handling
    - Context state management and updates
    """
    SELECT_APPLICATION_COMMAND: str = 'select_application_window'

    def __init__(self, fail_fast: bool=False) -> None:
        """
        Initialize Host Agent action execution strategy.
        :param fail_fast: Whether to raise exceptions immediately on errors
        """
        super().__init__(name='host_action_execution', fail_fast=fail_fast)

    async def execute(self, agent: 'HostAgent', context: ProcessingContext) -> ProcessingResult:
        """
        Execute Host Agent actions with comprehensive error handling and state management.
        :param agent: The HostAgent instance.
        :param context: Processing context containing response and execution data
        :return: ProcessingResult with execution results or error information
        """
        try:
            parsed_response: HostAgentResponse = context.get_local('parsed_response')
            if not parsed_response:
                return ProcessingResult(success=True, data={'message': 'No response available for action execution'}, phase=ProcessingPhase.ACTION_EXECUTION)
            function_name: str = context.get_local('function_name')
            target_registry: TargetRegistry = context.get_local('target_registry')
            command_dispatcher = context.global_context.command_dispatcher
            selected_target_id = context.get_local('selected_target_id')
            selected_application_root = context.get_local('selected_application_root', '')
            assigned_third_party_agent = context.get_local('assigned_third_party_agent', '')
            self.logger.info(f'Executing action: {function_name}')
            if function_name == self.SELECT_APPLICATION_COMMAND:
                execution_result = await self._execute_application_selection(parsed_response, target_registry, command_dispatcher)
                target_id = parsed_response.arguments.get('id') if parsed_response.arguments else None
                target = target_registry.get(target_id) if target_registry and target_id else None
                selected_target_id = target_id
                selected_application_root = ''
                assigned_third_party_agent = ''
                if target:
                    if target.kind == TargetKind.THIRD_PARTY_AGENT:
                        assigned_third_party_agent = target.name
                    elif execution_result and execution_result[0].result:
                        selected_application_root = execution_result[0].result.get('root_name', '')
            elif function_name == 'execute_constellation':
                execution_result = await self._execute_constellation_dag(parsed_response, context)
            else:
                execution_result = await self._execute_generic_command(parsed_response, command_dispatcher)
            action_info = self._create_action_info(parsed_response, execution_result, target_registry, selected_target_id)
            return ProcessingResult(success=True, data={'execution_result': execution_result, 'action_info': action_info, 'target': action_info.target, 'selected_target_id': selected_target_id, 'selected_application_root': selected_application_root, 'assigned_third_party_agent': assigned_third_party_agent}, phase=ProcessingPhase.ACTION_EXECUTION)
        except Exception as e:
            error_msg = f'Host action execution failed: {str(e)}'
            self.logger.error(error_msg)
            return self.handle_error(e, ProcessingPhase.ACTION_EXECUTION, context)

    async def _execute_constellation_dag(self, parsed_response, context: ProcessingContext) -> List[Any]:
        """Execute a predefined Constellation DAG for a specific task."""
        from ufo.galaxy.constellation.editor.constellation_editor import ConstellationEditor
        from ufo.galaxy.constellation.orchestrator.orchestrator import TaskConstellationOrchestrator
        from ufo.galaxy.client.device_manager import ConstellationDeviceManager
        from ufo.aip.messages import Result, ResultStatus
        try:
            config = parsed_response.arguments.get('config', {})
            self.logger.info(f"Executing Constellation DAG with {len(config.get('tasks', []))} tasks")
            editor = ConstellationEditor()
            constellation = editor.build_constellation(config, clear_existing=True)
            device_manager = ConstellationDeviceManager()
            orchestrator = TaskConstellationOrchestrator(device_manager=device_manager)
            result_data = await orchestrator.orchestrate_constellation(constellation)
            return [Result(status=ResultStatus.SUCCESS, result=f'Constellation DAG executed successfully.', data=result_data)]
        except Exception as e:
            self.logger.error(f'Constellation execution failed: {e}')
            return [Result(status=ResultStatus.ERROR, result=f'Error executing DAG: {e}', error=str(e))]

    async def _execute_application_selection(self, parsed_response: HostAgentResponse, target_registry: TargetRegistry, command_dispatcher: BasicCommandDispatcher) -> List[Result]:
        """
        Execute application selection with proper handling of different target types.
        :param parsed_response: Parsed response containing function arguments
        :param target_registry: Target registry containing available targets
        :param command_dispatcher: Command dispatcher for executing commands
        :return: List of execution results
        """
        try:
            target_id = parsed_response.arguments.get('id') if parsed_response.arguments else None
            if not target_id:
                raise ValueError('No target ID specified for application selection')
            if not target_registry:
                raise ValueError('Target registry not available')
            target = target_registry.get(target_id)
            if not target:
                raise ValueError(f"Target with ID '{target_id}' not found")
            self.logger.info(f'Selecting target: {target.name} (ID: {target_id}, Kind: {target.kind})')
            if target.kind == TargetKind.THIRD_PARTY_AGENT:
                return await self._select_third_party_agent(target)
            else:
                return await self._select_regular_application(target, command_dispatcher)
        except Exception as e:
            raise Exception(f'Application selection failed: {str(e)}')

    async def _select_third_party_agent(self, target: TargetInfo) -> List[Result]:
        """
        Handle third-party agent selection and assignment.
        This method processes the selection of a third-party agent and records
        the assignment in the processing context for subsequent use.
        :param target: Third-party agent target object containing agent details
        :return: List of Result objects indicating successful third-party agent selection
        :raises: Exception if third-party agent selection encounters critical errors
        """
        try:
            self.logger.info(f'Assigned third-party agent: {target.name}')
            return [Result(status='success', result={'id': target.id, 'name': target.name, 'type': 'third_party_agent'})]
        except Exception as e:
            raise Exception(f'Third-party agent selection failed: {str(e)}')

    async def _select_regular_application(self, target: TargetInfo, command_dispatcher: BasicCommandDispatcher) -> List[Result]:
        """
        Handle regular application selection and window management.
        This method executes the application selection command and manages
        the window state, including setting the application root and updating
        the global context for use by other components.
        :param target: Application target object containing application details
        :param command_dispatcher: Command dispatcher for executing commands
        :return: List of Result objects from application selection command execution
        :raises: Exception if application selection or window management fails
        """
        try:
            if not command_dispatcher:
                raise ValueError('Command dispatcher not available')
            execution_result = await command_dispatcher.execute_commands([Command(tool_name=self.SELECT_APPLICATION_COMMAND, parameters={'id': str(target.id), 'name': target.name}, tool_type='action')])
            if execution_result and execution_result[0].result:
                app_root = execution_result[0].result.get('root_name', '')
                self.logger.info(f'Selected application: {target.name}, root: {app_root}')
            return execution_result
        except Exception as e:
            raise Exception(f'Regular application selection failed: {str(e)}')

    async def _execute_generic_command(self, parsed_response: HostAgentResponse, command_dispatcher: BasicCommandDispatcher) -> List[Result]:
        """
        Execute generic command using command dispatcher.
        This method handles the execution of arbitrary commands that are not
        specifically handled by other execution methods. It provides a generic
        interface for command execution with proper error handling.
        :param parsed_response: Parsed response containing function name and arguments
        :param command_dispatcher: Command dispatcher for executing commands
        :return: List of Result objects from command execution
        :raises: Exception if command dispatcher is unavailable or command execution fails
        """
        try:
            if not command_dispatcher:
                raise ValueError('Command dispatcher not available')
            function_name = parsed_response.function
            arguments = parsed_response.arguments or {}
            if not function_name:
                return []
            if function_name == 'run_shell':
                if 'command' in arguments:
                    val = arguments.pop('command')
                    if 'bash_command' not in arguments:
                        arguments['bash_command'] = val
                if 'cmd' in arguments:
                    val = arguments.pop('cmd')
                    if 'bash_command' not in arguments:
                        arguments['bash_command'] = val
            self.logger.info(f'Executing generic command: {function_name} with args: {arguments}')
            execution_result = await command_dispatcher.execute_commands([Command(tool_name=function_name, parameters=arguments, tool_type='action')])
            return execution_result
        except Exception as e:
            raise Exception(f'Generic command execution failed: {str(e)}')

    def _create_action_info(self, parsed_response: HostAgentResponse, execution_result: List[Result], target_registry: TargetRegistry, selected_target_id: str) -> ActionCommandInfo:
        """
        Create action information object for memory and tracking.
        This method constructs a comprehensive action information object that
        captures the complete context of the executed action, including the
        target object, execution results, and status information.
        :param parsed_response: Parsed response with action details
        :param execution_result: Results from action execution
        :param target_registry: Target registry containing available targets
        :param selected_target_id: ID of the selected target
        :return: ActionCommandInfo object with complete execution details
        """
        try:
            if not parsed_response.function:
                for attr in ('function', 'func', 'action'):
                    val = getattr(parsed_response, attr, None)
                    if val and isinstance(val, str) and val.strip():
                        parsed_response.function = val.strip()
                        break
                if not parsed_response.function:
                    return ActionCommandInfo(function='no_action', arguments={})
            target_object = None
            if target_registry and selected_target_id:
                target_object = target_registry.get(selected_target_id)
            action_info = ActionCommandInfo(function=parsed_response.function, arguments=parsed_response.arguments or {}, target=target_object, status=parsed_response.status, result=execution_result[0] if execution_result else Result(status='none'))
            return action_info
        except Exception as e:
            self.logger.warning(f'Failed to create action info: {str(e)}')
            return ActionCommandInfo(function=parsed_response.function or 'unknown', arguments=parsed_response.arguments or {}, target=None, status=parsed_response.status or 'unknown', result=Result(status='error', result={'error': str(e)}))

@depends_on('session_step')
@provides('additional_memory', 'memory_item', 'memory_keys_count')
class HostMemoryUpdateStrategy(BaseProcessingStrategy):
    """
    Enhanced memory update strategy for Host Agent with comprehensive data management.

    This strategy handles:
    - Memory item creation with structured data
    - Agent memory synchronization
    - Blackboard trajectory management
    - Structural logging for debugging and analysis
    """

    def __init__(self, fail_fast: bool=False) -> None:
        """
        Initialize Host Agent memory update strategy.
        :param fail_fast: Whether to raise exceptions immediately on errors
        """
        super().__init__(name='host_memory_update', fail_fast=fail_fast)

    async def execute(self, agent: 'HostAgent', context: ProcessingContext) -> ProcessingResult:
        """
        Execute comprehensive memory update with error handling.
        :param agent: The HostAgent instance.
        :param context: Processing context containing all execution data
        :return: ProcessingResult with memory update results or error information
        """
        try:
            parsed_response = context.get_local('parsed_response')
            host_agent = agent
            self.logger.info('Creating additional memory data')
            additional_memory = self._create_additional_memory_data(host_agent, context)
            memory_item = self._create_and_populate_memory_item(parsed_response, additional_memory)
            host_agent.add_memory(memory_item)
            self._update_structural_logs(memory_item, context.global_context)
            self._update_blackboard_trajectories(host_agent, memory_item)
            self.logger.info('Memory update completed successfully')
            return ProcessingResult(success=True, data={'additional_memory': additional_memory, 'memory_item': memory_item, 'memory_keys_count': len(memory_item.to_dict())}, phase=ProcessingPhase.MEMORY_UPDATE)
        except Exception as e:
            error_msg = f'Host memory update failed: {str(e)}'
            self.logger.error(error_msg)
            return self.handle_error(e, ProcessingPhase.MEMORY_UPDATE, context)

    def _create_additional_memory_data(self, agent: 'HostAgent', context: ProcessingContext) -> 'HostAgentProcessorContext':
        """
        Create comprehensive additional memory data from processing context using HostAgentProcessorContext.
        This method extracts data from the unified typed context and converts to legacy format
        for backward compatibility.
        :param context: Processing context with execution data
        :return: HostAgentProcessorContext object with structured data compatible with original format
        """
        try:
            host_context: HostAgentProcessorContext = context.local_context
            host_context.session_step = context.get_global(ContextNames.SESSION_STEP.name, 0)
            host_context.round_step = context.get_global(ContextNames.CURRENT_ROUND_STEP.name, 0)
            host_context.round_num = context.get_global(ContextNames.CURRENT_ROUND_ID.name, 0)
            host_context.agent_step = agent.step if agent else 0
            action_info: ActionCommandInfo = host_context.action_info
            if action_info:
                host_context.action = [action_info.model_dump()]
                host_context.function_call = action_info.function or ''
                host_context.arguments = action_info.arguments
                host_context.action_representation = action_info.to_representation()
                if action_info.result:
                    host_context.action_type = action_info.result.namespace
                if action_info.result and action_info.result.result:
                    host_context.results = str(action_info.result.result)
            host_context.application = host_context.selected_application_root or ''
            host_context.agent_name = agent.name
            host_context.execution_times = self._calculate_time_costs()
            host_context.control_log = self._create_control_log(host_context.action_info, context.get_local('control_text', ''))
            return host_context
        except Exception as e:
            raise Exception(f'Failed to create additional memory data: {str(e)}')

    def _calculate_time_costs(self) -> Dict[str, float]:
        """
        Calculate time costs for different processing phases.
        :return: Dictionary mapping phase names to execution times
        """
        try:
            time_costs = {}
            return time_costs
        except Exception as e:
            self.logger.warning(f'Failed to calculate time costs: {str(e)}')
            return {}

    def _create_control_log(self, action_info: Optional[ActionCommandInfo], control_text: str='') -> Dict[str, Any]:
        """
        Create control log information for debugging and analysis.
        :param action_info: Action information if available
        :param control_text: Control text from context
        :return: Dictionary containing control log data
        """
        try:
            control_log = {}
            if action_info and action_info.target:
                control_log = {'target_id': getattr(action_info.target, 'id', ''), 'target_name': getattr(action_info.target, 'name', ''), 'target_kind': getattr(action_info.target, 'kind', ''), 'control_text': control_text}
            return control_log
        except Exception as e:
            self.logger.warning(f'Failed to create control log: {str(e)}')
            return {}

    def _create_and_populate_memory_item(self, parsed_response: HostAgentResponse, additional_memory: 'HostAgentProcessorContext') -> MemoryItem:
        """
        Create and populate memory item with response and additional data.
        :param parsed_response: Parsed response containing response data
        :param additional_memory: Additional memory data
        :return: Populated MemoryItem object
        """
        try:
            memory_item = MemoryItem()
            if parsed_response:
                memory_item.add_values_from_dict(parsed_response.model_dump())
            memory_item.add_values_from_dict(additional_memory.to_dict(selective=True))
            return memory_item
        except Exception as e:
            import traceback
            raise Exception(f'Failed to create and populate memory item: {str(traceback.format_exc())}')

    def _update_structural_logs(self, memory_item: MemoryItem, global_context) -> None:
        """
        Update structural logs for debugging and analysis.
        :param memory_item: Memory item to log
        :param global_context: Global context for structural logs
        """
        try:
            global_context.add_to_structural_logs(memory_item.to_dict())
        except Exception as e:
            self.logger.warning(f'Failed to update structural logs: {str(e)}')

    def _update_blackboard_trajectories(self, host_agent: 'HostAgent', memory_item: MemoryItem) -> None:
        """
        Update blackboard trajectories with memorized actions.
        :param host_agent: Host agent instance
        :param memory_item: Memory item with trajectory data
        """
        try:
            history_keys = ufo_config.system.history_keys
            if not history_keys:
                self.logger.debug('No history keys configured for blackboard')
                return
            memory_dict = memory_item.to_dict()
            memorized_action = {key: memory_dict.get(key) for key in history_keys if key in memory_dict}
            if memorized_action:
                host_agent.blackboard.add_trajectories(memorized_action)
                self.logger.debug(f'Added {len(memorized_action)} items to blackboard')
        except Exception as e:
            self.logger.warning(f'Failed to update blackboard trajectories: {str(e)}')
