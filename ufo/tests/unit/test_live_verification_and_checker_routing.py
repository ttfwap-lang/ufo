# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Unit tests for Live Verification and Doer-Checker Swarm agent routing.
Proves both strategies pass supported AgentType to agent.get_response() and handle LLM calls cleanly.
"""

import os
import shutil
import tempfile
import pytest
from unittest.mock import AsyncMock, MagicMock
from PIL import Image

from ufo.agents.processors.strategies.live_verification_strategy import LiveVisualVerifier
from ufo.agents.processors.strategies.doer_checker_swarm import DoerCheckerSwarmStrategy
from ufo.agents.processors.schemas.verification_schema import ActionVerificationRequest
from ufo.llm import AgentType
from ufo.llm.llm_result import LLMResult


@pytest.mark.asyncio
async def test_live_visual_verifier_routes_with_app_agent_type():
    """Verify LiveVisualVerifier.verify passes AgentType.APP to agent.get_response."""
    temp_dir = tempfile.mkdtemp()
    try:
        pre_img_path = os.path.join(temp_dir, "pre.png")
        post_img_path = os.path.join(temp_dir, "post.png")
        Image.new("RGB", (100, 100), color="white").save(pre_img_path)
        Image.new("RGB", (100, 100), color="blue").save(post_img_path)

        verifier = LiveVisualVerifier()
        mock_agent = MagicMock()
        mock_agent.get_response = AsyncMock(
            return_value=LLMResult(
                responses=['{"verified": true, "confidence_score": 0.95, "status": "success"}'],
                cost=0.01,
                prompt_tokens=100,
                completion_tokens=50,
                model="gpt-4o",
                api_type="openai",
                agent_type="APP_AGENT",
            )
        )

        request = ActionVerificationRequest(
            step_id=1,
            subtask="Click button",
            intended_action="click",
            target_control_info={"name": "Button"},
            pre_screenshot_path=pre_img_path,
            post_screenshot_path=post_img_path,
            expected_outcome="Button clicked",
            app_process_name="notepad.exe",
        )

        result = await verifier.verify(request, agent=mock_agent)
        assert result.verified is True
        assert mock_agent.get_response.called
        call_args = mock_agent.get_response.call_args
        # Second arg must be AgentType.APP
        assert call_args[0][1] == AgentType.APP
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_doer_checker_swarm_routes_with_app_agent_type():
    """Verify DoerCheckerSwarmStrategy._run_checker passes AgentType.APP to agent.get_response."""
    strategy = DoerCheckerSwarmStrategy()
    mock_agent = MagicMock()
    mock_agent.get_response = AsyncMock(
        return_value=LLMResult(
            responses=['{"approved": true, "confidence": 0.95, "reason": "Target confirmed"}'],
            cost=0.01,
            prompt_tokens=100,
            completion_tokens=50,
            model="gpt-4o",
            api_type="openai",
            agent_type="APP_AGENT",
        )
    )

    parsed_response = MagicMock()
    parsed_response.action = {"name": "click", "args": {"x": 50, "y": 50}}
    parsed_response.control_text = "Submit button"

    context = MagicMock()
    context.get = MagicMock(side_effect=lambda k, d="": "Click submit" if k == "subtask" else d)

    checker_res = await strategy._run_checker(
        agent=mock_agent,
        parsed_response=parsed_response,
        screenshot_path="",
        context=context,
    )

    assert checker_res["approved"] is True
    assert mock_agent.get_response.called
    call_args = mock_agent.get_response.call_args
    assert call_args[0][1] == AgentType.APP
