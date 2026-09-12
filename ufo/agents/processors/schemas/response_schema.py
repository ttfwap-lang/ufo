# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from ufo.agents.processors.schemas.actions import ActionCommandInfo


class SaveScreenshotConfig(BaseModel):
    save: bool = Field(
        default=False,
        description="Whether to save the screenshot of the current application window",
    )
    reason: Optional[str] = Field(
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
    message: Optional[List[str]] = Field(
        default=None, description="List of messages and information for the AppAgent."
    )
    questions: Optional[List[str]] = Field(
        default=None, description="List of questions for user clarification."
    )
    current_subtask: Optional[str] = Field(
        default=None, description="Description of current sub-task to be completed."
    )
    plan: Optional[List[str]] = Field(
        default=None, description="List of future sub-tasks."
    )
    comment: Optional[str] = Field(
        default=None, description="Additional comments or information."
    )
    function: Optional[str] = Field(
        default=None, description="Precise API function name to call."
    )
    arguments: Optional[Union[Dict[str, Any], str]] = Field(
        default=None, description="Precise arguments dict or JSON string."
    )
    result: Optional[Any] = Field(default=None, description="Execution result.")


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
    function: Optional[str] = Field(
        default=None, description="Precise API function name without arguments."
    )
    arguments: Optional[Union[Dict[str, Any], str]] = Field(
        default=None, description="Precise arguments dict or JSON string."
    )
    status: Optional[str] = Field(
        default="CONTINUE", description="Status of the task given the action."
    )
    plan: Optional[List[str]] = Field(
        default=None, description="List of future actions."
    )
    comment: Optional[str] = Field(
        default=None, description="Additional comments or information."
    )
    action: Union[List[ActionCommandInfo], ActionCommandInfo, None] = Field(
        default=None, description="Structured ActionCommandInfo object or list."
    )
    save_screenshot: Optional[Union[SaveScreenshotConfig, Dict[str, Any]]] = Field(
        default=None, description="Configuration for saving screenshots."
    )
    result: Optional[Any] = Field(default=None, description="Execution result.")


class EvaluationSubscore(BaseModel):
    name: str = Field(default="", description="The sub-score name")
    evaluation: Optional[Literal["yes", "no", "unsure"]] = Field(
        default="unsure", description="Sub-score result"
    )


class EvaluationAgentResponse(BaseModel):
    """
    The response data for the EvaluationAgent.
    """

    complete: Optional[str] = Field(
        default="no", description="Overall completion status of the evaluation"
    )
    sub_scores: Optional[List[Union[EvaluationSubscore, Dict[str, Any]]]] = Field(
        default=None, description="Sub-scores list"
    )
    reason: Optional[str] = Field(
        default=None, description="Detailed reason for judgment"
    )


EvaluationResponse = EvaluationAgentResponse
