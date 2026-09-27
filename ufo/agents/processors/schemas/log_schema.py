from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass
class ControlInfoRecorder:
    """
    The control meta information recorder for the current application window.
    """

    recording_fields: ClassVar[list[str]] = [
        "control_text",
        "control_type",
        "control_rect",
        "source",
    ]

    application_windows_info: dict[str, Any] = field(default_factory=dict)
    uia_controls_info: list[dict[str, Any]] = field(default_factory=dict)
    grounding_controls_info: list[dict[str, Any]] = field(default_factory=dict)
    merged_controls_info: list[dict[str, Any]] = field(default_factory=dict)


@dataclass
class HostAgentRequestLog:
    """
    The request log data for the AppAgent.
    """

    step: int
    image_list: list[str]
    os_info: dict[str, str]
    plan: list[str]
    prev_subtask: list[str]
    request: str
    blackboard_prompt: list[str]
    prompt: dict[str, Any]


@dataclass
class AppAgentRequestLog:
    """
    The request log data for the AppAgent.
    """

    step: int
    dynamic_examples: list[str]
    experience_examples: list[str]
    demonstration_examples: list[str]
    offline_docs: str
    online_docs: str
    dynamic_knowledge: str
    image_list: list[str]
    prev_subtask: list[str]
    plan: list[str]
    request: str
    control_info: list[dict[str, str]]
    subtask: str
    current_application: str
    host_message: str
    blackboard_prompt: list[str]
    last_success_actions: list[dict[str, Any]]
    include_last_screenshot: bool
    prompt: dict[str, Any]
    control_info_recording: dict[str, Any] | None = None
