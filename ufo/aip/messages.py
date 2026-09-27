# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Agent Interaction Protocol (AIP) - Message Definitions

This module defines the core message types and structures used in the Agent Interaction Protocol.
Messages are strongly typed using Pydantic for validation and serialization.

Message Flow:
    Client → Server: ClientMessage (REGISTER, TASK, HEARTBEAT, COMMAND_RESULTS, etc.)
    Server → Client: ServerMessage (TASK, COMMAND, TASK_END, HEARTBEAT, etc.)

Key Concepts:
    - ClientType: Distinguishes between device agents and constellation clients
    - MessageType: Defines the purpose of each message
    - TaskStatus: Tracks the state of task execution
    - Result: Encapsulates command execution outcomes
"""

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ufo.client.mcp.mcp_server_manager import BaseMCPServer

# ============================================================================
# Core Data Structures
# ============================================================================


class Rect(BaseModel):
    """
    Rectangle coordinates for UI elements.
    Represents a rectangle with x, y coordinates and width and height.
    """

    x: int
    y: int
    width: int
    height: int


class ControlInfo(BaseModel):
    """
    Information about a UI control.
    """

    annotation_id: str | None = None
    name: str | None = None
    title: str | None = None
    handle: int | None = None
    class_name: str | None = None
    rectangle: Rect | None = None
    control_type: str | None = None
    automation_id: str | None = None
    is_enabled: bool | None = None
    is_visible: bool | None = None
    source: str | None = None
    text_content: str | None = None


class WindowInfo(ControlInfo):
    """
    Information about a window in the UI.
    """

    process_id: int | None = None
    process_name: str | None = None
    is_visible: bool | None = None
    is_minimized: bool | None = None
    is_maximized: bool | None = None
    is_active: bool | None = None


class AppWindowControlInfo(BaseModel):
    """
    Information about a window and its controls.
    """

    window_info: WindowInfo
    controls: list[ControlInfo] | None = None


# ============================================================================
# Tool and Command Structures
# ============================================================================


class MCPToolInfo(BaseModel):
    """
    Information about a tool registered with the computer.
    """

    tool_key: str
    tool_name: str
    title: str | None = None
    namespace: str
    tool_type: str
    description: str | None = None
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    meta: dict[str, Any] | None = None
    annotations: dict[str, Any] | None = None


class MCPToolCall(BaseModel):
    """
    Information about a tool registered with the computer and its associated MCP server.
    """

    tool_key: str  # Unique key for the tool, e.g., "namespace.tool_name"
    tool_name: str  # Name of the tool
    title: str | None = None  # Title of the tool, if any
    namespace: str  # Namespace of the tool, same as the MCP server namespace
    tool_type: str  # Type of the tool (e.g., "action", "data_collection")
    description: str  # Description of the tool
    input_schema: dict[str, Any] | None = None  # Input schema for the tool, if any
    output_schema: dict[str, Any] | None = None  # Output schema for the tool, if any
    parameters: dict[str, Any] | None = None  # Parameters for the tool, if any
    mcp_server: BaseMCPServer  # The BaseMCPServer instance where the tool is registered
    meta: dict[str, Any] | None = None  # Metadata about the tool, if any
    annotations: dict[str, Any] | None = None  # Annotations for the tool, if any

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def tool_info(self) -> MCPToolInfo:
        """
        Get a dictionary representation of the tool call.
        :return: Dictionary with tool information.
        """
        return MCPToolInfo(
            tool_key=self.tool_key,
            tool_name=self.tool_name,
            title=self.title,
            namespace=self.namespace,
            tool_type=self.tool_type,
            description=self.description,
            input_schema=self.input_schema,
            output_schema=self.output_schema,
            meta=self.meta,
            annotations=self.annotations,
        )


class Command(BaseModel):
    """
    Represents a command to be executed by an agent.
    Commands are atomic units of work dispatched by the orchestrator.
    """

    tool_name: str = Field(..., description="Name of the tool to execute")
    parameters: dict[str, Any] | None = Field(
        default=None, description="Parameters for the tool"
    )
    tool_type: Literal["data_collection", "action"] = Field(
        ..., description="Type of tool: data_collection or action"
    )
    call_id: str | None = Field(
        default=None, description="Unique identifier for this command call"
    )


# ============================================================================
# Result and Status Enums
# ============================================================================


class ResultStatus(str, Enum):
    """
    Represents the status of a command execution result.
    """

    SUCCESS = "success"
    FAILURE = "failure"
    SKIPPED = "skipped"
    NONE = "none"


class Result(BaseModel):
    """
    Represents the result of a command execution.
    Contains status, error information, and the actual result payload.
    """

    status: ResultStatus = Field(..., description="Execution status")
    error: str | None = Field(default=None, description="Error message if failed")
    result: Any = Field(default=None, description="Result payload")
    namespace: str | None = Field(
        default=None, description="Namespace of the executed tool"
    )
    call_id: str | None = Field(
        default=None, description="ID matching the Command.call_id"
    )


class TaskStatus(str, Enum):
    """
    Represents the status of a task in the AIP protocol.

    States:
        CONTINUE: Task is ongoing, more steps needed
        COMPLETED: Task finished successfully
        FAILED: Task encountered an error
        OK: Acknowledgment or health check passed
        ERROR: Protocol-level error occurred
    """

    CONTINUE = "continue"
    COMPLETED = "completed"
    FAILED = "failed"
    OK = "ok"
    ERROR = "error"


# ============================================================================
# Message Type Enums
# ============================================================================


class ClientMessageType(str, Enum):
    """
    Message types sent from client to server.

    Registration & Health:
        REGISTER: Initial registration with server
        HEARTBEAT: Periodic keepalive signal

    Task Execution:
        TASK: Request to execute a task
        TASK_END: Notify task completion
        COMMAND_RESULTS: Return results of executed commands

    Device Info:
        DEVICE_INFO_REQUEST: Request device information
        DEVICE_INFO_RESPONSE: Response with device information

    Error Handling:
        ERROR: Report an error condition
    """

    TASK = "task"
    HEARTBEAT = "heartbeat"
    COMMAND_RESULTS = "command_results"
    ERROR = "error"
    REGISTER = "register"
    TASK_END = "task_end"
    DEVICE_INFO_REQUEST = "device_info_request"
    DEVICE_INFO_RESPONSE = "device_info_response"


class ServerMessageType(str, Enum):
    """
    Message types sent from server to client.

    Task Execution:
        TASK: Task assignment to device
        COMMAND: Command(s) to execute
        TASK_END: Task completion notification

    Health & Info:
        HEARTBEAT: Keepalive acknowledgment
        DEVICE_INFO_REQUEST: Request for device information
        DEVICE_INFO_RESPONSE: Device information response

    Error Handling:
        ERROR: Error notification
    """

    TASK = "task"
    HEARTBEAT = "heartbeat"
    TASK_END = "task_end"
    COMMAND = "command"
    ERROR = "error"
    DEVICE_INFO_REQUEST = "device_info_request"
    DEVICE_INFO_RESPONSE = "device_info_response"


class ClientType(str, Enum):
    """
    Type of client in the AIP system.

    DEVICE: A device agent that executes tasks
    CONSTELLATION: An orchestrator that manages multiple devices
    """

    DEVICE = "device"
    CONSTELLATION = "constellation"


# ============================================================================
# Core Message Classes
# ============================================================================


class ServerMessage(BaseModel):
    """
    Message sent from server to client.

    Represents all server-to-client communications including task assignments,
    command dispatches, heartbeats, and error notifications.

    Fields:
        type: Message type (TASK, COMMAND, HEARTBEAT, etc.)
        status: Task status (CONTINUE, COMPLETED, FAILED, OK, ERROR)
        user_request: Original user request text
        agent_name: Name of the agent handling the task
        process_name: Process name for execution context
        root_name: Root application name
        actions: List of commands to execute
        messages: List of message strings (e.g., logs)
        error: Error description if status is ERROR
        session_id: Unique session identifier
        task_name: Human-readable task name
        timestamp: ISO 8601 timestamp
        response_id: Unique response identifier for correlation
        result: Result payload for TASK_END or DEVICE_INFO_RESPONSE
    """

    type: ServerMessageType = Field(..., description="Type of server message")
    status: TaskStatus = Field(..., description="Current task status")
    user_request: str | None = Field(
        default=None, description="Original user request"
    )
    agent_name: str | None = Field(default=None, description="Agent name")
    process_name: str | None = Field(default=None, description="Process name")
    root_name: str | None = Field(default=None, description="Root application name")
    actions: list[Command] | None = Field(
        default=None, description="Commands to execute"
    )
    messages: list[str] | None = Field(default=None, description="Log messages")
    error: str | None = Field(default=None, description="Error message")
    session_id: str | None = Field(default=None, description="Session ID")
    task_name: str | None = Field(default=None, description="Task name")
    timestamp: str | None = Field(default=None, description="ISO 8601 timestamp")
    response_id: str | None = Field(default=None, description="Unique response ID")
    result: Any | None = Field(default=None, description="Result payload")


class ClientMessage(BaseModel):
    """
    Message sent from client to server.

    Represents all client-to-server communications including registration,
    task requests, command results, heartbeats, and error reports.

    Fields:
        type: Message type (REGISTER, TASK, HEARTBEAT, etc.)
        status: Task status
        client_type: Type of client (DEVICE or CONSTELLATION)
        session_id: Unique session identifier
        task_name: Human-readable task name
        client_id: Unique client identifier
        target_id: Target device ID (for constellation clients)
        request: Request text (for TASK messages)
        action_results: Results of executed commands
        timestamp: ISO 8601 timestamp
        request_id: Unique request identifier
        prev_response_id: Previous response ID for correlation
        error: Error message
        metadata: Additional metadata (e.g., system info, capabilities)
    """

    type: ClientMessageType = Field(..., description="Type of client message")
    status: TaskStatus = Field(..., description="Current task status")
    client_type: ClientType = Field(
        default=ClientType.DEVICE, description="Type of client"
    )
    session_id: str | None = Field(default=None, description="Session ID")
    task_name: str | None = Field(default=None, description="Task name")
    client_id: str | None = Field(default=None, description="Client ID")
    target_id: str | None = Field(
        default=None, description="Target device ID (for constellation)"
    )
    request: str | None = Field(default=None, description="Request text")
    action_results: list[Result] | None = Field(
        default=None, description="Command execution results"
    )
    timestamp: str | None = Field(default=None, description="ISO 8601 timestamp")
    request_id: str | None = Field(default=None, description="Unique request ID")
    prev_response_id: str | None = Field(
        default=None, description="Previous response ID"
    )
    error: str | None = Field(default=None, description="Error message")
    metadata: dict[str, Any] | None = Field(
        default=None, description="Additional metadata"
    )


# ============================================================================
# Message Validation and Utilities
# ============================================================================


class MessageValidator:
    """
    Validates AIP messages for protocol compliance.

    Provides static methods to validate message structures, required fields,
    and protocol-level constraints.
    """

    @staticmethod
    def validate_registration(msg: ClientMessage) -> bool:
        """
        Validate a registration message.

        :param msg: Client message to validate
        :return: True if valid, False otherwise
        """
        if msg.type != ClientMessageType.REGISTER:
            return False
        if not msg.client_id:
            return False
        if msg.client_type == ClientType.CONSTELLATION and not msg.target_id:
            # Constellation clients should specify target device
            pass  # Optional, can be set later
        return True

    @staticmethod
    def validate_task_request(msg: ClientMessage) -> bool:
        """
        Validate a task request message.

        :param msg: Client message to validate
        :return: True if valid, False otherwise
        """
        if msg.type != ClientMessageType.TASK:
            return False
        if not msg.request:
            return False
        if not msg.client_id:
            return False
        return True

    @staticmethod
    def validate_command_results(msg: ClientMessage) -> bool:
        """
        Validate a command results message.

        :param msg: Client message to validate
        :return: True if valid, False otherwise
        """
        if msg.type != ClientMessageType.COMMAND_RESULTS:
            return False
        if not msg.prev_response_id:
            return False
        if msg.action_results is None:
            return False
        return True

    @staticmethod
    def validate_server_message(msg: ServerMessage) -> bool:
        """
        Validate a server message.

        :param msg: Server message to validate
        :return: True if valid, False otherwise
        """
        # Basic validation
        if not msg.type:
            return False
        if not msg.status:
            return False

        # Type-specific validation
        if msg.type == ServerMessageType.COMMAND:
            if not msg.actions:
                return False
            if not msg.response_id:
                return False

        return True


# ============================================================================
# Binary Transfer Message Types (New Feature)
# ============================================================================


class BinaryMetadata(BaseModel):
    """
    Metadata for binary data transfer.

    This metadata is sent as a text frame before the actual binary data,
    allowing receivers to prepare for and validate incoming binary transfers.
    """

    type: Literal["binary_data"] = "binary_data"
    filename: str | None = None
    mime_type: str | None = None
    size: int = Field(..., description="Size of binary data in bytes")
    checksum: str | None = Field(
        None, description="MD5 or SHA256 checksum for validation"
    )
    session_id: str | None = None
    description: str | None = None
    timestamp: str | None = None
    # Allow additional custom fields
    model_config = ConfigDict(extra="allow")


class FileTransferStart(BaseModel):
    """
    Message to initiate a chunked file transfer.

    Sent before sending file chunks to inform the receiver about
    the file details and transfer parameters.
    """

    type: Literal["file_transfer_start"] = "file_transfer_start"
    filename: str = Field(..., description="Name of file being transferred")
    size: int = Field(..., description="Total file size in bytes")
    chunk_size: int = Field(..., description="Size of each chunk in bytes")
    total_chunks: int = Field(..., description="Total number of chunks")
    mime_type: str | None = Field(None, description="MIME type of file")
    session_id: str | None = None
    description: str | None = None
    # Allow additional custom fields
    model_config = ConfigDict(extra="allow")


class FileTransferComplete(BaseModel):
    """
    Message to signal completion of a chunked file transfer.

    Sent after all file chunks have been transmitted, includes
    checksum for validation.
    """

    type: Literal["file_transfer_complete"] = "file_transfer_complete"
    filename: str = Field(..., description="Name of transferred file")
    total_chunks: int = Field(..., description="Total chunks sent")
    checksum: str | None = Field(None, description="MD5 checksum of complete file")
    session_id: str | None = None
    # Allow additional custom fields
    model_config = ConfigDict(extra="allow")


class ChunkMetadata(BaseModel):
    """
    Metadata for a single file chunk.

    Sent with each chunk during chunked file transfer to track
    chunk sequence and validate chunk integrity.
    """

    chunk_num: int = Field(..., description="Chunk sequence number (0-indexed)")
    chunk_size: int = Field(..., description="Size of this chunk in bytes")
    checksum: str | None = Field(None, description="Checksum of this chunk")
    # Allow additional custom fields
    model_config = ConfigDict(extra="allow")
