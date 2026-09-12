# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import unittest
from unittest.mock import MagicMock, patch
import pytest
from google.genai import types, errors

from ufo.llm.gemini import GeminiService


@pytest.fixture
def mock_config():
    return {
        "HOST_AGENT": {
            "API_TYPE": "gemini",
            "API_MODEL": "gemini-2.5-computer-use-preview-10-2025",
            "API_KEY": "test_api_key",
            "JSON_SCHEMA": True,
        },
        "PRICES": {
            "gemini/gemini-2.5-computer-use-preview-10-2025": {
                "input": 0.0001,
                "output": 0.0002,
            },
        },
        "TEMPERATURE": 0.7,
        "TOP_P": 0.95,
        "MAX_TOKENS": 1024,
        "MAX_RETRY": 3,
    }


def create_mock_response(text="Test response", prompt_tokens=10, completion_tokens=20):
    mock_response = MagicMock(spec=types.GenerateContentResponse)
    mock_candidate = MagicMock()
    mock_part = MagicMock()
    mock_part.text = text
    mock_part.thought = False
    mock_part.function_call = None
    mock_part.model_dump.return_value = {}
    mock_candidate.content.parts = [mock_part]
    mock_candidate.finish_reason = "STOP"
    mock_response.candidates = [mock_candidate]
    
    mock_usage = MagicMock()
    mock_usage.prompt_token_count = prompt_tokens
    mock_usage.candidates_token_count = completion_tokens
    mock_response.usage_metadata = mock_usage
    return mock_response


@pytest.mark.asyncio
async def test_consecutive_retry_parameter_integrity(mock_config):
    """
    Verify that on attempt 0 (400 client error) tool fallback is attempted,
    and if fallback succeeds, result is returned cleanly.
    """
    with patch.object(GeminiService, "get_gemini_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        err_400 = errors.ClientError(
            code=400,
            response_json={"error": {"code": 400, "message": "INVALID_ARGUMENT: Computer use unsupported"}}
        )
        mock_response = create_mock_response("Success after retry")

        # Initial call fails with 400 -> fallback succeeds with mock_response
        mock_client.models.generate_content.side_effect = [err_400, mock_response]

        service = GeminiService(mock_config, "HOST_AGENT")
        messages = [{"role": "user", "content": [{"type": "text", "text": "Do task"}]}]

        result = await service.chat_completion(messages)

        assert mock_client.models.generate_content.call_count == 2

        # Call 1: initial -> tools set, response_mime_type None, response_schema None
        c1_kwargs = mock_client.models.generate_content.call_args_list[0][1]
        c1_cfg = c1_kwargs["config"]
        assert c1_cfg.tools is not None
        assert c1_cfg.response_mime_type is None

        # Call 2: fallback -> tools None, response_mime_type "application/json", response_schema HostAgentResponse
        c2_kwargs = mock_client.models.generate_content.call_args_list[1][1]
        c2_cfg = c2_kwargs["config"]
        assert c2_cfg.tools is None
        assert c2_cfg.response_mime_type == "application/json"
        assert getattr(c2_cfg, "response_schema", None) is not None

        assert result.responses == ["Success after retry"]


@pytest.mark.asyncio
async def test_no_infinite_loop_on_max_retry_exhaustion(mock_config):
    """
    Verify that when all attempts and fallbacks fail, service raises exception.
    """
    mock_config["MAX_RETRY"] = 5
    with patch.object(GeminiService, "get_gemini_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        err_400 = errors.ClientError(
            code=400,
            response_json={"error": {"code": 400, "message": "INVALID_ARGUMENT"}}
        )
        mock_client.models.generate_content.side_effect = err_400

        service = GeminiService(mock_config, "HOST_AGENT")
        messages = [{"role": "user", "content": [{"type": "text", "text": "Do task"}]}]

        with pytest.raises(Exception):
            await service.chat_completion(messages)


@pytest.mark.asyncio
async def test_rate_limit_429_raises_for_retry(mock_config):
    """
    Verify that rate limit (429) errors raise directly so retry middleware can backoff.
    """
    with patch.object(GeminiService, "get_gemini_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        err_429 = errors.APIError(
            code=429,
            response_json={"error": {"code": 429, "message": "RESOURCE_EXHAUSTED: Rate limit exceeded"}}
        )

        mock_client.models.generate_content.side_effect = err_429

        service = GeminiService(mock_config, "HOST_AGENT")
        messages = [{"role": "user", "content": [{"type": "text", "text": "Do task"}]}]

        with pytest.raises(errors.APIError):
            await service.chat_completion(messages)


def test_candidate_parsing_complex_parts(mock_config):
    """
    Stress-test candidate parsing with mixed thought parts, text parts, and function call parts.
    """
    with patch.object(GeminiService, "get_gemini_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        service = GeminiService(mock_config, "HOST_AGENT")

        mock_response = MagicMock(spec=types.GenerateContentResponse)
        mock_candidate = MagicMock()

        # Part 1: Thinking part (should be ignored)
        p1 = MagicMock()
        p1.text = "Thinking deeply..."
        p1.thought = True
        p1.function_call = None
        p1.model_dump.return_value = {}

        # Part 2: Text part
        p2 = MagicMock()
        p2.text = "Executing tool call:"
        p2.thought = False
        p2.function_call = None
        p2.model_dump.return_value = {}

        # Part 3: Function call part (dict format)
        p3 = MagicMock()
        p3.text = None
        p3.thought = False
        p3.function_call = {"name": "click", "args": {"x": 100, "y": 200}}
        p3.model_dump.return_value = {}

        mock_candidate.content.parts = [p1, p2, p3]
        mock_candidate.finish_reason = "STOP"
        mock_response.candidates = [mock_candidate]

        texts = service.get_text_from_all_candidates(mock_response)
        assert len(texts) == 1
        assert "Thinking deeply..." not in texts[0]
        assert "Executing tool call:" in texts[0]
        assert '{"function_call": {"name": "click", "args": {"x": 100, "y": 200}}}' in texts[0]
