# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
LLMResult contract for UFO LLM calls.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LLMResult:
    """
    Structured result returned by all LLM chat completion services and llm_call helpers.
    """
    responses: list = field(default_factory=list)
    cost: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""
    api_type: str = ""
    agent_type: str = ""
