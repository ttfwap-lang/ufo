# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Unit tests for LLMResult contract across all LLM providers and agents.
"""

import pytest
from dataclasses import FrozenInstanceError
from ufo.llm.llm_result import LLMResult


def test_llm_result_creation_and_defaults():
    """Verify LLMResult creation and default fields."""
    result = LLMResult(responses=["Test response"], cost=0.015)
    assert result.responses == ["Test response"]
    assert result.cost == 0.015
    assert result.prompt_tokens == 0
    assert result.completion_tokens == 0
    assert result.model == ""
    assert result.api_type == ""
    assert result.agent_type == ""


def test_llm_result_immutability():
    """Verify LLMResult is frozen/immutable."""
    result = LLMResult(responses=["Test response"], cost=0.01)
    with pytest.raises(FrozenInstanceError):
        result.cost = 0.02


def test_llm_result_all_fields():
    """Verify LLMResult fully populated with metadata."""
    result = LLMResult(
        responses=["Output 1", "Output 2"],
        cost=0.0045,
        prompt_tokens=150,
        completion_tokens=45,
        model="gpt-5.6-terra",
        api_type="openai",
        agent_type="HOST_AGENT",
    )
    assert len(result.responses) == 2
    assert result.cost == 0.0045
    assert result.prompt_tokens == 150
    assert result.completion_tokens == 45
    assert result.model == "gpt-5.6-terra"
    assert result.api_type == "openai"
    assert result.agent_type == "HOST_AGENT"
