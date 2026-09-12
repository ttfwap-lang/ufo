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
            "JSON_SCHEMA": False,
        },
        "PRICES": {
            "gemini/gemini-2.5-computer-use-preview-10-2025": {
                "input": 0.0001,
                "output": 0.0002,
            },
            "gemini/gemini-1.5-pro": {
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


async def test_computer_use_tool_injection_and_mime_type_omitted(mock_config):
    with patch.object(GeminiService, "get_gemini_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_response = create_mock_response("Computer use ok")
        mock_client.models.generate_content.return_value = mock_response

        service = GeminiService(mock_config, "HOST_AGENT")
        messages = [
            {
                "role": "user",
                "content": [{"type": "text", "text": "Open notepad"}],
            }
        ]

        result = await service.chat_completion(messages)
        texts, cost = result.responses, result.cost

        assert mock_client.models.generate_content.call_count == 1
        called_args, called_kwargs = mock_client.models.generate_content.call_args
        
        config_passed = called_kwargs.get("config")
        assert config_passed is not None
        assert config_passed.tools is not None
        assert len(config_passed.tools) == 1
        
        tool = config_passed.tools[0]
        assert getattr(tool, "computer_use", None) is not None
        assert tool.computer_use.environment == types.Environment.ENVIRONMENT_DESKTOP
        assert config_passed.response_mime_type is None
        assert texts == ["Computer use ok"]


async def test_non_computer_use_model_has_mime_type_and_no_tools(mock_config):
    mock_config["HOST_AGENT"]["API_MODEL"] = "gemini-1.5-pro"
    with patch.object(GeminiService, "get_gemini_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_response = create_mock_response("Standard text response")
        mock_client.models.generate_content.return_value = mock_response

        service = GeminiService(mock_config, "HOST_AGENT")
        messages = [
            {
                "role": "user",
                "content": [{"type": "text", "text": "Hello"}],
            }
        ]

        result = await service.chat_completion(messages)
        texts, cost = result.responses, result.cost

        assert mock_client.models.generate_content.call_count == 1
        called_args, called_kwargs = mock_client.models.generate_content.call_args
        
        config_passed = called_kwargs.get("config")
        assert config_passed is not None
        assert config_passed.tools is None
        assert config_passed.response_mime_type == "application/json"
        assert texts == ["Standard text response"]


async def test_fallback_mechanism_on_400_invalid_argument(mock_config):
    with patch.object(GeminiService, "get_gemini_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        
        err = errors.ClientError(
            code=400,
            response_json={
                "error": {
                    "code": 400,
                    "message": "Function calling with a response mime type: 'application/json' is unsupported",
                }
            },
        )
        mock_response = create_mock_response("Fallback response text")
        
        mock_client.models.generate_content.side_effect = [err, mock_response]

        service = GeminiService(mock_config, "HOST_AGENT")
        messages = [
            {
                "role": "user",
                "content": [{"type": "text", "text": "Open calculator"}],
            }
        ]

        result = await service.chat_completion(messages)
        texts, cost = result.responses, result.cost

        assert mock_client.models.generate_content.call_count == 2
        
        # 1st call check (computer_use tool attached, no mime_type)
        first_call_kwargs = mock_client.models.generate_content.call_args_list[0][1]
        first_config = first_call_kwargs.get("config")
        assert first_config.tools is not None
        assert first_config.response_mime_type is None
        
        # 2nd call check (fallback: tools stripped, application/json restored)
        second_call_kwargs = mock_client.models.generate_content.call_args_list[1][1]
        second_config = second_call_kwargs.get("config")
        assert second_config.tools is None
        assert second_config.response_mime_type == "application/json"

        assert texts == ["Fallback response text"]


async def test_fallback_mechanism_on_403_forbidden(mock_config):
    with patch.object(GeminiService, "get_gemini_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        
        err = errors.ClientError(
            code=403,
            response_json={"error": {"code": 403, "message": "Forbidden access to computer use feature"}},
        )
        mock_response = create_mock_response("Fallback 403 response")
        
        mock_client.models.generate_content.side_effect = [err, mock_response]

        service = GeminiService(mock_config, "HOST_AGENT")
        messages = [
            {
                "role": "user",
                "content": [{"type": "text", "text": "Do task"}],
            }
        ]

        result = await service.chat_completion(messages)
        texts, cost = result.responses, result.cost

        assert mock_client.models.generate_content.call_count == 2
        second_call_kwargs = mock_client.models.generate_content.call_args_list[1][1]
        second_config = second_call_kwargs.get("config")
        assert second_config.tools is None
        assert second_config.response_mime_type == "application/json"
        assert texts == ["Fallback 403 response"]


def test_candidate_parsing_function_call_part(mock_config):
    with patch.object(GeminiService, "get_gemini_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        service = GeminiService(mock_config, "HOST_AGENT")

        mock_response = MagicMock(spec=types.GenerateContentResponse)
        mock_candidate = MagicMock()
        
        mock_part = MagicMock()
        mock_part.text = None
        mock_part.thought = False
        mock_part.function_call = types.FunctionCall(
            name="open_web_browser",
            args={"url": "https://google.com"},
        )
        mock_part.model_dump.return_value = {}

        mock_candidate.content.parts = [mock_part]
        mock_candidate.finish_reason = "STOP"
        mock_response.candidates = [mock_candidate]

        texts = service.get_text_from_all_candidates(mock_response)
        assert len(texts) == 1
        assert texts[0] is not None
        assert '"function_call"' in texts[0]
        assert '"open_web_browser"' in texts[0]
        assert '"https://google.com"' in texts[0]


def test_candidate_parsing_empty_response(mock_config):
    with patch.object(GeminiService, "get_gemini_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        service = GeminiService(mock_config, "HOST_AGENT")

        texts = service.get_text_from_all_candidates(None)
        assert texts == []

        empty_resp = MagicMock(candidates=[])
        texts = service.get_text_from_all_candidates(empty_resp)
        assert texts == []
