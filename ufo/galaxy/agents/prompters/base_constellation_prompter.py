"""
Base Constellation Agent Prompter.

This module provides the base prompter class for Constellation Agents with
shared functionality between different weaving modes.
"""
from abc import ABC
import json
from typing import Dict, List, Optional, Type
from ufo.config.config_loader import LazyGalaxyConfig, get_galaxy_config
from ufo.aip.messages import MCPToolInfo
from ufo.galaxy.agents.schema import WeavingMode
from ufo.galaxy.client.components.types import AgentProfile, DeviceStatus
from ufo.galaxy.constellation.task_constellation import TaskConstellation
from ufo.prompter.basic import BasicPrompter
from ufo.prompter.prompt_sanitizer import sanitize_user_input
galaxy_config = LazyGalaxyConfig()

class BaseConstellationPrompter(BasicPrompter, ABC):
    """
    Base prompter for Constellation Agent with shared functionality.

    This class provides common prompt construction logic that is shared
    between different weaving modes (CREATION and EDITING).
    """

    def __init__(self, prompt_template: str, example_prompt_template: str):
        """
        Initialize base constellation prompter.

        :param prompt_template: Main prompt template or template string
        :param example_prompt_template: Example prompt template or template string
        """
        super().__init__(None, prompt_template, example_prompt_template)

    def load_prompt_template(self, template_path: str, is_visual: Optional[bool]=None) -> Dict:
        """
        Load the prompt template from the specified path.

        :param template_path: The path to the prompt template
        :param is_visual: Whether to load visual prompt template
        :return: The loaded prompt template as a dictionary
        """
        if not template_path:
            return {}
        import os
        if os.path.exists(template_path):
            return super().load_prompt_template(template_path, is_visual)
        return {'system': template_path, 'user': template_path, 'template': template_path}

    def get_prompt_template(self) -> Dict:
        """Get the prompt template."""
        return getattr(self, 'prompt_template', {})

    def _format_agent_profile(self, device_info: Dict[str, AgentProfile]) -> str:
        """
        Format device information for prompt inclusion.

        :param device_info: Dictionary of device information
        :return: Formatted device information string
        """
        if not device_info:
            return 'No devices available.'
        formatted_agent_profiles = []
        for _, info in device_info.items():
            if info.status == DeviceStatus.DISCONNECTED:
                continue
            capabilities = ', '.join(info.capabilities) if info.capabilities else 'None'
            os = info.os if info.os else 'Unknown'
            metadata_str = ''
            if info.metadata:
                metadata_items = [f'{k}: {v}' for k, v in info.metadata.items()]
                metadata_str = f" | Metadata: {', '.join(metadata_items)}"
            device_summary = f'Device ID: {info.device_id}\nOS: {os}\n  - Capabilities: {capabilities}\n{metadata_str}'
            formatted_agent_profiles.append(device_summary)
        return 'Available Device Agent Profiles:\n\n' + '\n\n'.join(formatted_agent_profiles)

    def _format_constellation(self, constellation: TaskConstellation) -> str:
        """
        Format constellation information for prompt inclusion with modification hints.

        :param constellation: Task constellation object
        :return: Formatted constellation string with modification indicators
        """
        if constellation is None:
            return 'No constellation information available.'
        try:
            constellation_dict = constellation.to_dict()
        except Exception:
            return 'Constellation information unavailable due to formatting error.'
        lines = []
        lines.append(f"Task Constellation: {constellation_dict.get('name', 'Unnamed')}")
        lines.append(f"Status: {constellation_dict.get('state', 'unknown')}")
        lines.append(f"Total Tasks: {len(constellation_dict.get('tasks', {}))}")
        lines.append('')
        try:
            modifiable_task_ids = {task.task_id for task in constellation.get_modifiable_tasks()}
            modifiable_dep_ids = {dep.line_id for dep in constellation.get_modifiable_dependencies()}
        except Exception:
            modifiable_task_ids = set()
            modifiable_dep_ids = set()
        tasks = constellation_dict.get('tasks', {})
        if tasks:
            lines.append('Tasks:')
            for task_id, task_data in tasks.items():
                task_name = task_data.get('name', task_id)
                task_status = task_data.get('status', 'unknown')
                target_device = task_data.get('target_device_id', 'unassigned')
                modifiable_indicator = '✏️ [MODIFIABLE]' if task_id in modifiable_task_ids else '🔒 [READ-ONLY]'
                lines.append(f'  [{task_id}] {task_name} {modifiable_indicator}')
                lines.append(f'    Status: {task_status}')
                lines.append(f'    Device: {target_device}')
                description = task_data.get('description', '')
                if description:
                    lines.append(f'    Description: {description}')
                tips = task_data.get('tips', [])
                if tips:
                    lines.append('    Tips:')
                    for tip in tips:
                        lines.append(f'      - {tip}')
                result = task_data.get('result')
                if result is not None:
                    result_str = str(result)
                    lines.append(f'    Result: {result_str}')
                error = task_data.get('error')
                if error:
                    lines.append(f'    Error: {error}')
                if task_id in modifiable_task_ids:
                    lines.append(f'    💡 Hint: This task can be modified (description, tips, device assignment, etc.)')
                lines.append('')
        dependencies = constellation_dict.get('dependencies', {})
        if dependencies:
            lines.append('Task Dependencies:')
            for dep_id, dep_data in dependencies.items():
                from_task = dep_data.get('from_task_id', 'unknown')
                to_task = dep_data.get('to_task_id', 'unknown')
                condition_desc = dep_data.get('condition_description', '')
                modifiable_indicator = '✏️ [MODIFIABLE]' if dep_id in modifiable_dep_ids else '🔒 [READ-ONLY]'
                dependency_line = f'  [{dep_id}] {from_task} → {to_task} {modifiable_indicator}'
                if condition_desc:
                    dependency_line += f' - {condition_desc}'
                lines.append(dependency_line)
                if dep_id in modifiable_dep_ids:
                    lines.append(f'    💡 Hint: This dependency can be modified (condition, type, etc.)')
            lines.append('')
        total_tasks = len(tasks)
        total_deps = len(dependencies)
        modifiable_tasks_count = len(modifiable_task_ids)
        modifiable_deps_count = len(modifiable_dep_ids)
        lines.append('📊 Modification Summary:')
        lines.append(f'   Tasks: {total_tasks} total, {modifiable_tasks_count} modifiable')
        lines.append(f'   Dependencies: {total_deps} total, {modifiable_deps_count} modifiable')
        lines.append('')
        lines.append('💡 Note: Only PENDING or WAITING_DEPENDENCY items can be modified.')
        lines.append('   RUNNING, COMPLETED, or FAILED items are read-only.')
        result = '\n'.join(lines)
        return result

    def user_content_construction(self, request: str, device_info: Dict[str, AgentProfile], constellation: TaskConstellation) -> List[Dict[str, str]]:
        """
        Construct the prompt for LLMs.
        :param request: The user request.
        :param device_info: The device information.
        :param constellation: The task constellation.
        return: The prompt for LLMs.
        """
        prompt_text = self.user_prompt_construction(request, device_info, constellation)
        return [{'type': 'text', 'text': prompt_text}]

    def system_prompt_construction(self) -> str:
        """
        Construct the prompt for app selection.
        return: The prompt for app selection.
        """
        examples = self.examples_prompt_helper()
        apis = self.api_prompt_template
        return self.prompt_template['system'].format(examples=examples, apis=apis)

    def user_prompt_construction(self, request: str, device_info: Dict[str, AgentProfile], constellation: TaskConstellation) -> str:
        """
        Construct the prompt for LLMs.
        :param request: The user request.
        :param device_info: The device information.
        :param constellation: The task constellation.
        return: The prompt for LLMs.
        """
        prompt = self.prompt_template['user'].format(request=sanitize_user_input(request, 'request'), device_info=self._format_agent_profile(device_info), constellation=self._format_constellation(constellation))
        return prompt

    def examples_prompt_helper(self, header: str='## Response Examples', separator: str='Example') -> str:
        """
        Construct the prompt for examples.
        :param examples: The examples.
        :param header: The header of the prompt.
        :param separator: The separator of the prompt.
        :param additional_examples: The additional examples added to the prompt.
        return: The prompt for examples.
        """
        template = '\n        [User Request]:\n            {request}\n        [Device Info]:\n            {device_info}\n        [Response]:\n            {response}'
        example_dict = [self.example_prompt_template[key] for key in self.example_prompt_template.keys() if key.startswith('example')]
        example_list = []
        for example in example_dict:
            example_str = template.format(request=example.get('Request'), device_info=json.dumps(example.get('Device-Info')), response=json.dumps(example.get('Response')))
            example_list.append(example_str)
        return self.retrieved_documents_prompt_helper(header, separator, example_list)

    def create_api_prompt_template(self, tools: List[MCPToolInfo]):
        """
        Create the API prompt template.
        :param tools: The list of tools.
        """
        tool_prompt = BasicPrompter.tools_to_llm_prompt(tools, generate_example=False)
        self.api_prompt_template = tool_prompt
        return tool_prompt

class ConstellationPrompterFactory:
    """
    Factory class for creating Constellation prompters based on weaving mode.

    This factory ensures that the correct prompter implementation is used
    based on the current weaving mode (CREATION or EDITING).

    Benefits:
    - Centralized prompter creation logic
    - Type-safe prompter selection
    - Easy extensibility for new modes
    - Consistent parameter handling
    """
    _prompter_classes: Dict[WeavingMode, Type[BasicPrompter]] = {}

    @classmethod
    def create_prompter(cls, weaving_mode: WeavingMode, prompt_template: Optional[str]=None, example_prompt_template: Optional[str]=None, *args, **kwargs) -> BasicPrompter:
        """
        Create prompter based on weaving mode.

        :param weaving_mode: The weaving mode (CREATION or EDITING)
        :param prompt_template: The prompt template for the prompter
        :param example_prompt_template: The example prompt template for the prompter
        :raises ValueError: If weaving mode is not supported
        """
        if not cls._prompter_classes:
            from ufo.galaxy.agents.prompters.constellation_creation_prompter import ConstellationCreationPrompter
            from ufo.galaxy.agents.prompters.constellation_editing_prompter import ConstellationEditingPrompter
            cls._prompter_classes = {WeavingMode.CREATION: ConstellationCreationPrompter, WeavingMode.EDITING: ConstellationEditingPrompter}
        if weaving_mode not in cls._prompter_classes:
            raise ValueError(f'Unsupported weaving mode for prompter: {weaving_mode}')
        if prompt_template is None:
            prompt_template = kwargs.get('creation_prompt_template') or kwargs.get('editing_prompt_template')
        if example_prompt_template is None:
            example_prompt_template = kwargs.get('creation_example_prompt_template') or kwargs.get('editing_example_prompt_template')
        if prompt_template is None and len(args) > 0:
            prompt_template = args[0]
        if example_prompt_template is None and len(args) > 1:
            example_prompt_template = args[1]
        agent_config = galaxy_config.agent.CONSTELLATION_AGENT
        if prompt_template is None or example_prompt_template is None:
            if weaving_mode == WeavingMode.CREATION:
                if prompt_template is None:
                    prompt_template = agent_config.CONSTELLATION_CREATION_PROMPT
                if example_prompt_template is None:
                    example_prompt_template = agent_config.CONSTELLATION_CREATION_EXAMPLE_PROMPT
            elif weaving_mode == WeavingMode.EDITING:
                if prompt_template is None:
                    prompt_template = agent_config.CONSTELLATION_EDITING_PROMPT
                if example_prompt_template is None:
                    example_prompt_template = agent_config.CONSTELLATION_EDITING_EXAMPLE_PROMPT
        prompter_class = cls._prompter_classes[weaving_mode]
        return prompter_class(prompt_template, example_prompt_template)

    @classmethod
    def get_supported_weaving_modes(cls) -> list[WeavingMode]:
        """
        Get list of supported weaving modes.

        :return: List of supported WeavingMode values
        """
        return list(cls._prompter_classes.keys())