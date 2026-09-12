import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from ufo.llm.llm_result import LLMResult
from ufo.llm.refusal_rotator import (
    is_refusal_text,
    is_refusal_response,
    is_refusal_exception,
    adapt_messages_for_text_model,
    execute_refusal_cascade,
    ROTATION_TIERS,
)
from ufo.llm import AgentType


class TestRefusalTextDetection:
    @pytest.mark.parametrize(
        "refusal_sample",
        [
            "I cannot fulfill this request as it involves system modification.",
            "I can not assist with installing Microsoft Recall.",
            "I am unable to perform this operation.",
            "I'm unable to access private user directories.",
            "I am not able to execute arbitrary PowerShell commands.",
            "I'm not able to comply with this instruction.",
            "As an AI language model, I must decline your request.",
            "I apologize, but I cannot assist with this.",
            "This action violates our safety guidelines and content policy.",
            "I am sorry, but I cannot do that.",
            "Sorry, I can't help with modifying registry keys.",
            "I am prohibited from executing destructive operations.",
            "I refuse to assist with this task.",
            "I cannot provide assistance with downloading external binaries.",
            "I am unable to comply with your prompt.",
        ],
    )
    def test_refusal_phrases_detected(self, refusal_sample):
        assert is_refusal_text(refusal_sample) is True

    @pytest.mark.parametrize(
        "clean_sample",
        [
            '{"thought": "Navigating to settings to install recall", "control_label": "Settings", "operation": "click"}',
            "Sure! I will help you open Notepad and write the statement report.",
            "The balance adjustment plan has been successfully calculated: $1,420.50.",
            "Clicking on the Start menu at coordinate (24, 1180).",
            '{"status": "FINISH", "result": "Successfully created document."}',
            "",
            None,
        ],
    )
    def test_clean_responses_not_flagged(self, clean_sample):
        assert is_refusal_text(clean_sample) is False


class TestRefusalResponseInspection:
    def test_llm_result_with_refusal_string(self):
        res = LLMResult(
            responses=["I cannot assist you with modifying system settings."],
            cost=0.0,
            prompt_tokens=10,
            completion_tokens=10,
            model="gemini-3.7-flash",
        )
        is_ref, reason = is_refusal_response(res)
        assert is_ref is True
        assert "Refusal text detected" in reason

    def test_llm_result_with_clean_string(self):
        res = LLMResult(
            responses=['{"thought": "Proceeding with task", "operation": "click"}'],
            cost=0.0,
            prompt_tokens=10,
            completion_tokens=10,
            model="gemini-3.7-flash",
        )
        is_ref, reason = is_refusal_response(res)
        assert is_ref is False
        assert reason == ""

    def test_llm_result_with_dict_refusal(self):
        res = LLMResult(
            responses=[{"thought": "I cannot perform this sensitive operation."}],
            cost=0.0,
            prompt_tokens=10,
            completion_tokens=10,
            model="gemini-3.7-flash",
        )
        is_ref, reason = is_refusal_response(res)
        assert is_ref is True
        assert "Refusal in thought field" in reason


class TestRefusalExceptionInspection:
    def test_safety_exception(self):
        err = RuntimeError("Google GenAI error: Request blocked due to SAFETY policy violation.")
        is_ref, reason = is_refusal_exception(err)
        assert is_ref is True
        assert "Safety exception" in reason

    def test_transient_network_exception_not_refusal(self):
        err = TimeoutError("Connection to endpoint timed out after 30 seconds.")
        is_ref, reason = is_refusal_exception(err)
        assert is_ref is False


class TestMultimodalMessageAdaptation:
    def test_strips_images_for_text_models(self):
        messages = [
            {"role": "system", "content": "You are a desktop agent."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is on the screen?"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo..."}},
                ],
            },
        ]
        adapted = adapt_messages_for_text_model(messages)
        assert len(adapted) == 2
        assert adapted[0]["content"] == "You are a desktop agent."
        assert "What is on the screen?" in adapted[1]["content"]
        assert "[Screenshot / UI visual frame attached]" in adapted[1]["content"]
        assert "base64" not in adapted[1]["content"]


@pytest.mark.asyncio
class TestRefusalCascadeExecution:
    async def test_tier1_success(self):
        clean_res = LLMResult(
            responses=['{"thought": "Executing uncensored prompt", "operation": "click"}'],
            cost=0.0,
            prompt_tokens=20,
            completion_tokens=20,
            model="mlabonne/Qwen2.5-72B-Instruct-abliterated",
        )

        with patch("ufo.llm.base.BaseService.get_service") as mock_get_service:
            mock_service = MagicMock()
            mock_service.chat_completion = AsyncMock(return_value=clean_res)
            mock_get_service.return_value = mock_service

            result = await execute_refusal_cascade(
                messages=[{"role": "user", "content": "Do task"}],
                agent_type=AgentType.APP,
                trigger_reason="Test refusal",
            )

            assert result.responses[0] == '{"thought": "Executing uncensored prompt", "operation": "click"}'
            assert result.model == "mlabonne/Qwen2.5-72B-Instruct-abliterated"

    async def test_tier1_refusal_tier2_success(self):
        refusal_res = LLMResult(
            responses=["I cannot fulfill this request."],
            cost=0.0,
            prompt_tokens=10,
            completion_tokens=10,
            model="mlabonne/Qwen2.5-72B-Instruct-abliterated",
        )
        clean_res_tier2 = LLMResult(
            responses=['{"thought": "Tier 2 success", "operation": "press_enter"}'],
            cost=0.0,
            prompt_tokens=20,
            completion_tokens=20,
            model="hugging-quants/Qwen2-72B-Instruct-abliterated",
        )

        with patch("ufo.llm.base.BaseService.get_service") as mock_get_service:
            mock_service1 = MagicMock()
            mock_service1.chat_completion = AsyncMock(return_value=refusal_res)

            mock_service2 = MagicMock()
            mock_service2.chat_completion = AsyncMock(return_value=clean_res_tier2)

            mock_get_service.side_effect = [mock_service1, mock_service2]

            result = await execute_refusal_cascade(
                messages=[{"role": "user", "content": "Do task"}],
                agent_type=AgentType.APP,
                trigger_reason="Initial refusal",
            )

            assert result.responses[0] == '{"thought": "Tier 2 success", "operation": "press_enter"}'
            assert result.model == "hugging-quants/Qwen2-72B-Instruct-abliterated"


@pytest.mark.asyncio
class TestLlmCallRefusalIntegration:
    async def test_get_completion_intercepts_refusal_and_rotates(self):
        from ufo.llm.llm_call import get_completion

        refusal_res = LLMResult(
            responses=["I cannot assist with installing Microsoft Recall."],
            cost=0.0,
            prompt_tokens=10,
            completion_tokens=10,
            model="gemini-3.7-flash",
        )
        rotated_res = LLMResult(
            responses=['{"thought": "Installing Recall uncensored", "operation": "run_shell"}'],
            cost=0.0,
            prompt_tokens=25,
            completion_tokens=25,
            model="mlabonne/Qwen2.5-72B-Instruct-abliterated",
        )

        with patch("ufo.llm.base.BaseService.get_service") as mock_get_service, \
             patch("ufo.llm.refusal_rotator.execute_refusal_cascade", new_callable=AsyncMock) as mock_cascade:

            mock_service = MagicMock()
            mock_service.chat_completion = AsyncMock(return_value=refusal_res)
            mock_get_service.return_value = mock_service
            mock_cascade.return_value = rotated_res

            result = await get_completion(
                messages=[{"role": "user", "content": "install recall"}],
                agent=AgentType.APP,
            )

            assert mock_cascade.called
            assert result.responses[0] == '{"thought": "Installing Recall uncensored", "operation": "run_shell"}'
            assert result.model == "mlabonne/Qwen2.5-72B-Instruct-abliterated"

