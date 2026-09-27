from dataclasses import dataclass, field
from typing import Any

from ufo.agents.processors.context.processing_context import BasicProcessorContext
from ufo.agents.processors.schemas.target import TargetInfo


@dataclass
class AppAgentProcessorContext(BasicProcessorContext):
    """
    Extended processing context for App Agent with app-specific data fields.

    This context extends the basic ProcessingContext to include app-specific data:
    - Application window information and screenshot paths
    - UI control information and filtering results
    - LLM interaction data and parsed responses
    - Action execution results and memory updates
    - Performance metrics and debugging information

    All fields support selective serialization for robust error handling.
    """

    # App Agent type identifier
    agent_type: str = "AppAgent"
    prev_plan: list[str] = field(default_factory=list)
    subtask: str = ""  # Current subtask description
    subtask_index: int = 0
    agent_name: str = ""  # Agent name for logging
    agent_step: int = 0

    # Application and UI data
    app_root: Any | None = None  # Application window root element
    application_process_name: str = ""  # Application window name/identifier

    # Screenshot and visual data
    clean_screenshot_path: str = ""  # Path to clean screenshot
    annotated_screenshot_path: str = ""  # Path to annotated screenshot
    desktop_screenshot_path: str = ""  # Path to desktop screenshot
    selected_control_screenshot_path: str = ""  # Path to selected control screenshot
    concat_screenshot_path: str = ""  # Path to concatenated screenshot
    screenshot_saved_time: float = 0.0  # Time taken for screenshot operations

    # Control and UI information
    filtered_controls: list[dict[str, Any]] = field(
        default_factory=list
    )  # Filtered UI controls
    control_info: list[dict[str, TargetInfo]] = field(
        default_factory=list
    )  # Alias for filtered_controls
    annotation_dict: dict[str, Any] = field(
        default_factory=dict
    )  # Control annotation dictionary
    application_window: Any | None = (
        None  # Application window object (from original)
    )

    # LLM interaction data - extends base parsed_response
    response_text: str = ""  # Raw LLM response text
    prompt_message: dict[str, Any] = field(
        default_factory=dict
    )  # Constructed prompt message
    function_name: str = ""  # Function name from response
    function_arguments: dict[str, Any] = field(
        default_factory=dict
    )  # Function arguments from response
    save_screenshot: dict[str, Any] = field(
        default_factory=dict
    )  # Screenshot saving configuration

    # Action execution data
    execution_result: list[Any] = field(
        default_factory=list
    )  # Action execution results
    action_info: Any | None = None  # Action command information
    action_success: bool = False  # Whether action was successful
    control_log: dict[str, Any] = field(default_factory=dict)  # Control interaction log

    # Memory and blackboard data
    additional_memory: Any | None = (
        None  # Additional memory data (AppAgentAdditionalMemory)
    )
    memory_item: Any | None = None  # Created memory item
    updated_blackboard: bool = False  # Whether blackboard was updated
    log_path: str = ""

    # Performance and debugging data
    app_performance_metrics: dict[str, Any] = field(
        default_factory=dict
    )  # Performance monitoring data
    app_error_handler_active: bool = False  # Error handler status
    app_logging_active: bool = False  # Logging middleware status
    app_memory_sync_active: bool = False  # Memory sync middleware status

    @property
    def selected_keys(self) -> list[str]:
        """
        Get keys that should be included in selective serialization.
        Excludes potentially unpicklable objects.
        """
        return [
            # Basic fields from parent
            "agent_type",
            "agent_name",
            "app_root",
            "application_process_name",
            "session_step",
            "round_step",
            "round_num",
            "status",
            "request",
            "llm_cost",
            "observation",
            "thought",
            "plan",
            "comment",
            "action",
            "action_type",
            "subtask",
            "app_root",
            "action_representation",
            "result",
            # App-specific serializable fields
            "clean_screenshot_path",
            "annotated_screenshot_path",
            "concat_screenshot_path",
            "selected_control_screenshot_path",
            "desktop_screenshot_path",
            "action_success",
            "function_call",
            "save_screenshot",
            "control_log",
        ]
