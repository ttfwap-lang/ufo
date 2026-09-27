# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from typing import Any, Literal

from pydantic import BaseModel, Field

from ufo.agents.processors.schemas.actions import ActionCommandInfo


class SaveScreenshotConfig(BaseModel):
    save: bool = Field(
        default=False,
        description="Whether to save the screenshot of the current application window",
    )
    reason: str | None = Field(
        default="", description="The reason for saving the screenshot"
    )


class HostAgentResponse(BaseModel):
    """
    The response data for the HostAgent.
    """

    observation: str = Field(
        default="",
        description="Detailed description of the screenshot of the current window.",
    )
    thought: str = Field(
        default="",
        description="Logical thinking process that decomposes the user request.",
    )
    status: str = Field(
        default="CONTINUE",
        description="Status of the HostAgent: 'FINISH', 'CONTINUE', 'PENDING', or 'ASSIGN'.",
    )
    message: list[str] | None = Field(
        default=None, description="List of messages and information for the AppAgent."
    )
    questions: list[str] | None = Field(
        default=None, description="List of questions for user clarification."
    )
    current_subtask: str | None = Field(
        default=None, description="Description of current sub-task to be completed."
    )
    plan: list[str] | None = Field(
        default=None, description="List of future sub-tasks."
    )
    comment: str | None = Field(
        default=None, description="Additional comments or information."
    )
    function: str | None = Field(
        default=None, description="Precise API function name to call."
    )
    arguments: dict[str, Any] | str | None = Field(
        default=None, description="Precise arguments dict or JSON string."
    )
    result: Any | None = Field(default=None, description="Execution result.")


class AppAgentResponse(BaseModel):
    """
    The response data for the AppAgent.
    """

    observation: str = Field(
        default="",
        description="Detailed description of the screenshot of the current application window.",
    )
    thought: str = Field(
        default="", description="Thinking and logic for the current action."
    )
    function: str | None = Field(
        default=None, description="Precise API function name without arguments."
    )
    arguments: dict[str, Any] | str | None = Field(
        default=None, description="Precise arguments dict or JSON string."
    )
    status: str | None = Field(
        default="CONTINUE", description="Status of the task given the action."
    )
    plan: list[str] | None = Field(
        default=None, description="List of future actions."
    )
    comment: str | None = Field(
        default=None, description="Additional comments or information."
    )
    action: list[ActionCommandInfo] | ActionCommandInfo | None = Field(
        default=None, description="Structured ActionCommandInfo object or list."
    )
    save_screenshot: SaveScreenshotConfig | dict[str, Any] | None = Field(
        default=None, description="Configuration for saving screenshots."
    )
    result: Any | None = Field(default=None, description="Execution result.")


class EvaluationSubscore(BaseModel):
    name: str = Field(default="", description="The sub-score name")
    evaluation: Literal["yes", "no", "unsure"] | None = Field(
        default="unsure", description="Sub-score result"
    )


class EvaluationAgentResponse(BaseModel):
    """
    The response data for the EvaluationAgent.
    """

    complete: str | None = Field(
        default="no", description="Overall completion status of the evaluation"
    )
    sub_scores: list[EvaluationSubscore | dict[str, Any]] | None = Field(
        default=None, description="Sub-scores list"
    )
    reason: str | None = Field(
        default=None, description="Detailed reason for judgment"
    )


EvaluationResponse = EvaluationAgentResponse
