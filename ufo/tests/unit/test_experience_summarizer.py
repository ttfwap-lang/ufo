# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Unit test for ExperienceSummarizer async get_summary with supported AgentType.APP.
"""

import pytest
from unittest.mock import AsyncMock, patch
from ufo.experience.summarizer import ExperienceSummarizer
from ufo.llm import AgentType
from ufo.llm.llm_result import LLMResult


@pytest.mark.asyncio
async def test_experience_summarizer_calls_app_agent():
    """Verify ExperienceSummarizer.get_summary calls get_completion with AgentType.APP."""
    summarizer = ExperienceSummarizer(
        is_visual=False,
        prompt_template="",
        example_prompt_template="",
        api_prompt_template="",
    )

    mock_llm_result = LLMResult(
        responses=['{"Observation": "obs", "Thought": "thought", "Plan": "plan"}'],
        cost=0.01,
        prompt_tokens=100,
        completion_tokens=50,
        model="gemini-3.7-flash",
        api_type="gemini",
        agent_type="APP_AGENT",
    )

    with patch("ufo.experience.summarizer.get_completion", new_callable=AsyncMock) as mock_get_comp:
        mock_get_comp.return_value = mock_llm_result
        summary, cost = await summarizer.get_summary([{"role": "user", "content": "test"}])

        assert mock_get_comp.called
        call_args = mock_get_comp.call_args
        # Agent parameter should be AgentType.APP or "APP_AGENT"
        agent_param = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("agent")
        assert agent_param in (AgentType.APP, "APP_AGENT", "app")
        assert summary["example"]["Observation"] == "obs"
        assert cost == 0.01
