# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Adversarial and Stress Test Suite for GeminiService (Milestone 1 Verification)
"""

import json
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


# ============================================================================
# 1. MODEL NAME VARIATIONS & DETECTION TESTS
# ============================================================================

@pytest.mark.parametrize("model_name, expected_computer_use", [
    ("gemini-2.5-computer-use-preview-10-2025", True),
    ("gemini-2.5-COMPUTER-USE-preview", True),
    ("gemini-2.5-computer_use-v1", True),
    ("GEMINI-2.5-COMPUTER_USE-PREVIEW", True),
    ("gemini-1.5-pro", False),
    ("gemini-2.0-flash", False),
    ("custom-model-with-computer-use-capability", True),
])
@pytest.mark.asyncio
async def test_model_name_detection_variations(mock_config, model_name, expected_computer_use):
    mock_config["HOST_AGENT"]["API_MODEL"] = model_name
    with patch.object(GeminiService, "get_gemini_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_response = create_mock_response("Model test OK")
        mock_client.models.generate_content.return_value = mock_response

        service = GeminiService(mock_config, "HOST_AGENT")
        messages = [{"role": "user", "content": [{"type": "text", "text": "test"}]}]
        result = await service.chat_completion(messages)

        assert mock_client.models.generate_content.call_count == 1
        _, called_kwargs = mock_client.models.generate_content.call_args
        config = called_kwargs.get("config")

        if expected_computer_use:
            assert config.tools is not None
            assert len(config.tools) == 1
            assert config.response_mime_type is None
        else:
            assert config.tools is None
            assert config.response_mime_type == "application/json"


# ============================================================================
# 2. EMPTY, NULL, AND TRUNCATED CANDIDATES
# ============================================================================

def test_candidate_parsing_null_response(mock_config):
    with patch.object(GeminiService, "get_gemini_client"):
        service = GeminiService(mock_config, "HOST_AGENT")
        assert service.get_text_from_all_candidates(None) == []


def test_candidate_parsing_empty_candidates_list(mock_config):
    with patch.object(GeminiService, "get_gemini_client"):
        service = GeminiService(mock_config, "HOST_AGENT")
        empty_resp = MagicMock(spec=types.GenerateContentResponse, candidates=[])
        assert service.get_text_from_all_candidates(empty_resp) == []


def test_candidate_parsing_candidate_with_none_content(mock_config):
    with patch.object(GeminiService, "get_gemini_client"):
        service = GeminiService(mock_config, "HOST_AGENT")
        cand = MagicMock(content=None, finish_reason="SAFETY")
        resp = MagicMock(spec=types.GenerateContentResponse, candidates=[cand])
        assert service.get_text_from_all_candidates(resp) == [None]


def test_candidate_parsing_candidate_with_none_parts(mock_config):
    with patch.object(GeminiService, "get_gemini_client"):
        service = GeminiService(mock_config, "HOST_AGENT")
        cand = MagicMock(content=MagicMock(parts=None), finish_reason="SAFETY")
        resp = MagicMock(spec=types.GenerateContentResponse, candidates=[cand])
        assert service.get_text_from_all_candidates(resp) == [None]


def test_candidate_parsing_candidate_with_empty_parts(mock_config):
    with patch.object(GeminiService, "get_gemini_client"):
        service = GeminiService(mock_config, "HOST_AGENT")
        cand = MagicMock(content=MagicMock(parts=[]), finish_reason="SAFETY")
        resp = MagicMock(spec=types.GenerateContentResponse, candidates=[cand])
        assert service.get_text_from_all_candidates(resp) == [None]


def test_candidate_parsing_thinking_parts(mock_config):
    """
    Gemini 2.0 / 2.5 thinking models output parts with thought=True which should be ignored.
    """
    with patch.object(GeminiService, "get_gemini_client"):
        service = GeminiService(mock_config, "HOST_AGENT")
        
        # Thought part only
        thought_part = MagicMock(text="Thinking about solution...", thought=True, function_call=None)
        thought_part.model_dump.return_value = {}
        cand1 = MagicMock(content=MagicMock(parts=[thought_part]))
        resp1 = MagicMock(spec=types.GenerateContentResponse, candidates=[cand1])
        assert service.get_text_from_all_candidates(resp1) == [None]

        # Thought part + actual text part
        text_part = MagicMock(text="Final answer", thought=False, function_call=None)
        text_part.model_dump.return_value = {}
        cand2 = MagicMock(content=MagicMock(parts=[thought_part, text_part]))
        resp2 = MagicMock(spec=types.GenerateContentResponse, candidates=[cand2])
        assert service.get_text_from_all_candidates(resp2) == ["Final answer"]


# ============================================================================
# 3. MALFORMED & COMPLEX FUNCTION CALLS
# ============================================================================

def test_candidate_parsing_function_call_as_dict(mock_config):
    """
    Test when function_call is returned as a dict rather than an object with attributes.
    """
    with patch.object(GeminiService, "get_gemini_client"):
        service = GeminiService(mock_config, "HOST_AGENT")
        
        part = MagicMock(text=None, thought=False)
        part.function_call = {"name": "take_screenshot", "args": {"format": "png"}}
        part.model_dump.return_value = {}

        cand = MagicMock(content=MagicMock(parts=[part]))
        resp = MagicMock(spec=types.GenerateContentResponse, candidates=[cand])

        texts = service.get_text_from_all_candidates(resp)
        assert len(texts) == 1
        data = json.loads(texts[0])
        assert data["function_call"]["name"] == "take_screenshot"
        assert data["function_call"]["args"] == {"format": "png"}


def test_candidate_parsing_function_call_with_none_args(mock_config):
    """
    Test when function_call args is None.
    """
    with patch.object(GeminiService, "get_gemini_client"):
        service = GeminiService(mock_config, "HOST_AGENT")
        
        part = MagicMock(text=None, thought=False)
        part.function_call = types.FunctionCall(name="click_button", args=None)
        part.model_dump.return_value = {}

        cand = MagicMock(content=MagicMock(parts=[part]))
        resp = MagicMock(spec=types.GenerateContentResponse, candidates=[cand])

        texts = service.get_text_from_all_candidates(resp)
        assert len(texts) == 1
        data = json.loads(texts[0])
        assert data["function_call"]["name"] == "click_button"
        assert data["function_call"]["args"] == {}


def test_candidate_parsing_function_call_and_text_combined(mock_config):
    """
    Test candidate having both text and function call parts.
    """
    with patch.object(GeminiService, "get_gemini_client"):
        service = GeminiService(mock_config, "HOST_AGENT")
        
        part1 = MagicMock(text="Executing command:", thought=False, function_call=None)
        part1.model_dump.return_value = {}

        part2 = MagicMock(text=None, thought=False)
        part2.function_call = types.FunctionCall(name="run_cmd", args={"command": "dir"})
        part2.model_dump.return_value = {}

        cand = MagicMock(content=MagicMock(parts=[part1, part2]))
        resp = MagicMock(spec=types.GenerateContentResponse, candidates=[cand])

        texts = service.get_text_from_all_candidates(resp)
        assert len(texts) == 1
        assert "Executing command:\n{" in texts[0]
        assert '"run_cmd"' in texts[0]


def test_candidate_parsing_unhandled_part_types(mock_config):
    """
    Test candidate with non-text part types (e.g., inline data) to ensure logging and non-crash.
    """
    with patch.object(GeminiService, "get_gemini_client"):
        service = GeminiService(mock_config, "HOST_AGENT")
        
        part = MagicMock(text="Hello", thought=False, function_call=None)
        part.model_dump.return_value = {"inline_data": {"mime_type": "image/png"}}

        cand = MagicMock(content=MagicMock(parts=[part]))
        resp = MagicMock(spec=types.GenerateContentResponse, candidates=[cand])

        texts = service.get_text_from_all_candidates(resp)
        assert texts == ["Hello"]


# ============================================================================
# 4. FALLBACK & EXCEPTION RETRY STRESS TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_fallback_when_client_error_triggers_fallback_and_succeeds(mock_config):
    """
    Test attempt 0: ClientError 400 triggers fallback -> fallback API call succeeds.
    """
    with patch.object(GeminiService, "get_gemini_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        err_400 = errors.ClientError(code=400, response_json={"error": {"code": 400, "message": "Invalid tool schema"}})
        mock_response = create_mock_response("Success on retry")

        mock_client.models.generate_content.side_effect = [err_400, mock_response]

        service = GeminiService(mock_config, "HOST_AGENT")
        messages = [{"role": "user", "content": [{"type": "text", "text": "Retry test"}]}]

        result = await service.chat_completion(messages)

        assert mock_client.models.generate_content.call_count == 2
        assert result.responses == ["Success on retry"]


@pytest.mark.asyncio
async def test_exhaust_all_retries_raises_exception(mock_config):
    """
    Test when all retries fail with network errors, exception is raised.
    """
    with patch.object(GeminiService, "get_gemini_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.models.generate_content.side_effect = Exception("Persistent connection error")

        service = GeminiService(mock_config, "HOST_AGENT")
        messages = [{"role": "user", "content": [{"type": "text", "text": "Fail test"}]}]

        with pytest.raises(Exception):
            await service.chat_completion(messages)


# ============================================================================
# 5. MESSAGE FORMATTING & IMAGE ENCODING TESTS
# ============================================================================

def test_process_messages_with_system_and_user_text(mock_config):
    with patch.object(GeminiService, "get_gemini_client"):
        service = GeminiService(mock_config, "HOST_AGENT")
        messages = [
            {"role": "system", "content": "Act as a desktop agent"},
            {"role": "user", "content": [{"type": "text", "text": "Open notepad"}]}
        ]
        prompts = service.process_messages(messages)
        assert prompts == ["Your general instruction: Act as a desktop agent", "Open notepad"]


def test_base64_to_blob_invalid_url(mock_config):
    with patch.object(GeminiService, "get_gemini_client"):
        service = GeminiService(mock_config, "HOST_AGENT")
        with pytest.raises(ValueError, match="Invalid data URL format."):
            service.base64_to_blob("invalid_base64_string")
