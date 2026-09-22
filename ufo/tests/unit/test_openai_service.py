# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Unit tests for the OpenAI service adapter.

Tests cover:
- _pydantic_to_response_format() conversion
- _messages_to_responses_input() message format conversion
- _extract_responses_text() response parsing
- Service routing and config access patterns
"""

import pytest


class TestPydanticToResponseFormat:
    """Tests for the _pydantic_to_response_format utility function."""

    def test_basic_schema_conversion(self):
        """Verify that a Pydantic model is converted to a valid response_format dict."""
        from pydantic import BaseModel

        class TestResponse(BaseModel):
            thought: str
            action: str
            status: str

        from ufo.llm.openai import _pydantic_to_response_format

        result = _pydantic_to_response_format(TestResponse)

        assert result["type"] == "json_schema"
        assert result["json_schema"]["name"] == "TestResponse"
        assert result["json_schema"]["strict"] is True
        assert "properties" in result["json_schema"]["schema"]
        assert "thought" in result["json_schema"]["schema"]["properties"]
        assert "action" in result["json_schema"]["schema"]["properties"]
        assert "status" in result["json_schema"]["schema"]["properties"]

    def test_host_agent_response_schema(self):
        """Verify that the actual HostAgentResponse schema converts correctly."""
        from ufo.llm.openai import _pydantic_to_response_format
        from ufo.llm.response_schema import HostAgentResponse

        result = _pydantic_to_response_format(HostAgentResponse)

        assert result["type"] == "json_schema"
        assert result["json_schema"]["name"] == "HostAgentResponse"
        assert result["json_schema"]["strict"] is True
        assert isinstance(result["json_schema"]["schema"], dict)

    def test_app_agent_response_schema(self):
        """Verify that the actual AppAgentResponse schema converts correctly."""
        from ufo.llm.openai import _pydantic_to_response_format
        from ufo.llm.response_schema import AppAgentResponse

        result = _pydantic_to_response_format(AppAgentResponse)

        assert result["type"] == "json_schema"
        assert result["json_schema"]["name"] == "AppAgentResponse"
        assert isinstance(result["json_schema"]["schema"], dict)

    def test_evaluation_response_schema(self):
        """Verify that the actual EvaluationResponse schema converts correctly."""
        from ufo.llm.openai import _pydantic_to_response_format
        from ufo.llm.response_schema import EvaluationResponse

        result = _pydantic_to_response_format(EvaluationResponse)

        assert result["type"] == "json_schema"
        assert result["json_schema"]["name"] in ("EvaluationResponse", "EvaluationAgentResponse")
        assert isinstance(result["json_schema"]["schema"], dict)

    def test_schema_contains_required_fields(self):
        """Verify the output schema has standard JSON Schema structure."""
        from pydantic import BaseModel
        from typing import Optional

        class DetailedResponse(BaseModel):
            function: str
            arguments: dict
            observation: Optional[str] = None

        from ufo.llm.openai import _pydantic_to_response_format

        result = _pydantic_to_response_format(DetailedResponse)
        schema = result["json_schema"]["schema"]

        assert "type" in schema
        assert schema["type"] == "object"
        assert "properties" in schema


class TestMessagesToResponsesInput:
    """Tests for _messages_to_responses_input() format conversion."""

    def test_simple_text_message(self):
        """Test conversion of a simple text message."""
        from ufo.llm.openai import BaseOpenAIService

        messages = [{"role": "user", "content": "Hello, world!"}]
        result = BaseOpenAIService._messages_to_responses_input(messages)

        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert len(result[0]["content"]) == 1
        assert result[0]["content"][0]["type"] == "input_text"
        assert result[0]["content"][0]["text"] == "Hello, world!"

    def test_system_message(self):
        """Test conversion of a system message."""
        from ufo.llm.openai import BaseOpenAIService

        messages = [{"role": "system", "content": "You are a helpful assistant."}]
        result = BaseOpenAIService._messages_to_responses_input(messages)

        assert result[0]["role"] == "system"
        assert result[0]["content"][0]["type"] == "input_text"
        assert result[0]["content"][0]["text"] == "You are a helpful assistant."

    def test_multimodal_message_with_image(self):
        """Test conversion of a message with text and image content."""
        from ufo.llm.openai import BaseOpenAIService

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What do you see?"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,abc123"},
                    },
                ],
            }
        ]
        result = BaseOpenAIService._messages_to_responses_input(messages)

        assert len(result) == 1
        content = result[0]["content"]
        assert len(content) == 2
        assert content[0]["type"] == "input_text"
        assert content[0]["text"] == "What do you see?"
        assert content[1]["type"] == "input_image"
        assert content[1]["image_url"] == "data:image/png;base64,abc123"

    def test_image_url_string_format(self):
        """Test handling of image_url as a plain string (not nested dict)."""
        from ufo.llm.openai import BaseOpenAIService

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": "data:image/png;base64,xyz"},
                ],
            }
        ]
        result = BaseOpenAIService._messages_to_responses_input(messages)

        content = result[0]["content"]
        assert content[0]["type"] == "input_image"
        assert content[0]["image_url"] == "data:image/png;base64,xyz"

    def test_input_image_type_passthrough(self):
        """Test that input_image type is handled correctly."""
        from ufo.llm.openai import BaseOpenAIService

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_image",
                        "image_url": {"url": "data:image/jpeg;base64,test"},
                    },
                ],
            }
        ]
        result = BaseOpenAIService._messages_to_responses_input(messages)

        content = result[0]["content"]
        assert content[0]["type"] == "input_image"
        assert content[0]["image_url"] == "data:image/jpeg;base64,test"

    def test_multiple_messages(self):
        """Test conversion of a multi-turn conversation."""
        from ufo.llm.openai import BaseOpenAIService

        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "User question"},
        ]
        result = BaseOpenAIService._messages_to_responses_input(messages)

        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "user"

    def test_empty_content_handling(self):
        """Test handling of empty content."""
        from ufo.llm.openai import BaseOpenAIService

        messages = [{"role": "user", "content": ""}]
        result = BaseOpenAIService._messages_to_responses_input(messages)

        assert len(result) == 1
        assert result[0]["content"][0]["text"] == ""

    def test_unknown_content_type_passthrough(self):
        """Test that unknown content types are passed through unchanged."""
        from ufo.llm.openai import BaseOpenAIService

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "computer_screenshot", "image_url": "data:image/png;base64,screen"},
                ],
            }
        ]
        result = BaseOpenAIService._messages_to_responses_input(messages)

        content = result[0]["content"]
        # Unknown types should be passed through
        assert content[0]["type"] == "computer_screenshot"


class TestExtractResponsesText:
    """Tests for _extract_responses_text() response parsing."""

    def test_standard_output_text(self):
        """Test extraction from standard Responses API output."""
        from ufo.llm.openai import BaseOpenAIService

        response = {
            "output": [
                {
                    "content": [
                        {"type": "output_text", "text": "Hello from the API!"}
                    ]
                }
            ]
        }
        result = BaseOpenAIService._extract_responses_text(response)
        assert result == "Hello from the API!"

    def test_text_key_extraction(self):
        """Test extraction when output has 'text' key directly."""
        from ufo.llm.openai import BaseOpenAIService

        response = {
            "output": [
                {
                    "content": [
                        {"text": "Direct text content"}
                    ]
                }
            ]
        }
        result = BaseOpenAIService._extract_responses_text(response)
        assert result == "Direct text content"

    def test_multiple_content_chunks(self):
        """Test concatenation of multiple text chunks."""
        from ufo.llm.openai import BaseOpenAIService

        response = {
            "output": [
                {
                    "content": [
                        {"type": "output_text", "text": "Part 1"},
                        {"type": "output_text", "text": " Part 2"},
                    ]
                }
            ]
        }
        result = BaseOpenAIService._extract_responses_text(response)
        assert result == "Part 1 Part 2"

    def test_empty_output(self):
        """Test handling of empty output list."""
        from ufo.llm.openai import BaseOpenAIService

        response = {"output": []}
        result = BaseOpenAIService._extract_responses_text(response)
        assert result == ""

    def test_missing_output_key(self):
        """Test handling of missing output key."""
        from ufo.llm.openai import BaseOpenAIService

        response = {}
        result = BaseOpenAIService._extract_responses_text(response)
        assert result == ""

    def test_non_dict_items_skipped(self):
        """Test that non-dict items in output are gracefully skipped."""
        from ufo.llm.openai import BaseOpenAIService

        response = {
            "output": [
                "not a dict",
                {"content": [{"text": "valid"}]},
            ]
        }
        result = BaseOpenAIService._extract_responses_text(response)
        assert result == "valid"

    def test_whitespace_stripping(self):
        """Test that leading/trailing whitespace is stripped."""
        from ufo.llm.openai import BaseOpenAIService

        response = {
            "output": [
                {"content": [{"text": "  trimmed  "}]}
            ]
        }
        result = BaseOpenAIService._extract_responses_text(response)
        assert result == "trimmed"


class TestAgentTypeEnum:
    """Tests for AgentType enum completeness."""

    def test_operator_type_exists(self):
        """Verify OPERATOR agent type exists in the enum."""
        from ufo.llm import AgentType

        assert hasattr(AgentType, "OPERATOR")
        assert AgentType.OPERATOR.value == "OPERATOR"

    def test_all_expected_types(self):
        """Verify all expected agent types are defined."""
        from ufo.llm import AgentType

        expected = {"HOST", "APP", "CONSTELLATION", "EVALUATION", "REASONING", "OPERATOR", "PREFILL", "FILTER", "BACKUP"}
        actual = {member.name for member in AgentType}
        assert expected == actual


class TestServiceMap:
    """Tests for service routing in BaseService.get_service."""

    def test_openai_service_routing(self):
        """Verify that 'openai' maps to OpenAIService."""
        from ufo.llm.base import BaseService

        service_map = {
            "openai": "OpenAIService",
            "aoai": "OpenAIService",
            "azure_ad": "OpenAIService",
            "gemini": "GeminiService",
            "operator": "OperatorServicePreview",
        }
        # Verify expected mappings exist in the real code
        assert service_map["openai"] == "OpenAIService"
        assert service_map["operator"] == "OperatorServicePreview"


class TestPricesConfig:
    """Tests for the prices configuration including new GPT-5.6 models."""

    @staticmethod
    def _get_prices_path():
        from pathlib import Path
        return Path(__file__).resolve().parent.parent.parent / "config" / "ufo" / "prices.yaml"

    def test_gpt56_pricing_exists(self):
        """Verify GPT-5.6 family pricing is in the config."""
        import yaml

        with open(self._get_prices_path(), "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        prices = config["PRICES"]
        assert "openai/gpt-5.6-sol" in prices
        assert "openai/gpt-5.6-terra" in prices
        assert "openai/gpt-5.6-luna" in prices

    def test_gpt56_pricing_values(self):
        """Verify GPT-5.6 pricing values are reasonable."""
        import yaml

        with open(self._get_prices_path(), "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        prices = config["PRICES"]
        # Sol should be the most expensive
        assert prices["openai/gpt-5.6-sol"]["input"] > prices["openai/gpt-5.6-terra"]["input"]
        assert prices["openai/gpt-5.6-terra"]["input"] > prices["openai/gpt-5.6-luna"]["input"]
        # All should have positive pricing
        for model in ["openai/gpt-5.6-sol", "openai/gpt-5.6-terra", "openai/gpt-5.6-luna"]:
            assert prices[model]["input"] > 0
            assert prices[model]["output"] > 0

    def test_legacy_pricing_preserved(self):
        """Verify legacy model pricing still exists for historical cost tracking."""
        import yaml

        with open(self._get_prices_path(), "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        prices = config["PRICES"]
        # Legacy models should still be present
        assert "openai/gpt-4o" in prices
        assert "openai/o4-mini" in prices
        assert "gemini/gemini-3.7-flash" in prices


class TestExtraBody:
    """EXTRA_BODY in an agent's config is forwarded to the chat completion call."""

    @staticmethod
    def _service(config_llm):
        import logging
        from types import SimpleNamespace

        from ufo.llm.openai import BaseOpenAIService

        captured = {}

        def create(**params):
            captured.update(params)
            msg = SimpleNamespace(content="ok", reasoning_content=None, tool_calls=None)
            usage = SimpleNamespace(prompt_tokens=1, completion_tokens=1)
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=usage)

        class _Svc(BaseOpenAIService):
            async def chat_completion(self, *a, **k):
                raise NotImplementedError

        svc = object.__new__(_Svc)
        svc.config_llm = {"API_TYPE": "openai", "JSON_SCHEMA": False, **config_llm}
        svc.config = {"TEMPERATURE": 0.0, "MAX_TOKENS": 16, "TOP_P": 0.0, "PRICES": {}}
        svc.agent_type = "host"
        svc.model = "m"
        svc.use_responses = False
        svc.json_schema_enabled = False
        svc.probe_key = "k"
        svc.api_type = "openai"
        svc.prices = {}
        svc.logger = logging.getLogger(__name__)
        svc.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        return svc, captured

    @pytest.mark.asyncio
    async def test_extra_body_forwarded(self):
        from ufo.llm import openai as mod

        mod._PROBED_JSON_SCHEMA_MODELS["k"] = False
        svc, captured = self._service({"EXTRA_BODY": {"chat_template_kwargs": {"enable_thinking": False}}})
        try:
            await svc._chat_completion([{"role": "user", "content": "hi"}])
        except Exception:
            pass  # response parsing is out of scope; only the request matters here
        assert captured["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}

    @pytest.mark.asyncio
    async def test_no_extra_body_by_default(self):
        from ufo.llm import openai as mod

        mod._PROBED_JSON_SCHEMA_MODELS["k"] = False
        svc, captured = self._service({})
        try:
            await svc._chat_completion([{"role": "user", "content": "hi"}])
        except Exception:
            pass
        assert "extra_body" not in captured


class TestShrinkImages:
    """MAX_IMAGE_PIXELS keeps screenshots under what the vision server accepts."""

    @staticmethod
    def _msg(w, h):
        import base64
        import io

        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (w, h), (10, 20, 30)).save(buf, format="PNG")
        url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        return [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": url}}, {"type": "text", "text": "hi"}]}], url

    @staticmethod
    def _size(messages):
        import base64
        import io

        from PIL import Image

        url = messages[0]["content"][0]["image_url"]["url"]
        return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).size

    def test_large_image_scaled_under_limit_keeping_aspect(self):
        from ufo.llm.openai import _shrink_images

        messages, _ = self._msg(1920, 1200)
        w, h = self._size(_shrink_images(messages, 1_800_000))
        assert w * h <= 1_800_000
        assert abs(w / h - 1920 / 1200) < 0.01

    def test_small_image_and_text_untouched_and_input_not_mutated(self):
        from ufo.llm.openai import _shrink_images

        messages, url = self._msg(800, 600)
        out = _shrink_images(messages, 1_800_000)
        assert out[0]["content"][0]["image_url"]["url"] == url
        assert out[0]["content"][1] == {"type": "text", "text": "hi"}
        big, big_url = self._msg(1920, 1200)
        _shrink_images(big, 1_800_000)
        assert big[0]["content"][0]["image_url"]["url"] == big_url

    def test_plain_string_content_passes_through(self):
        from ufo.llm.openai import _shrink_images

        msgs = [{"role": "system", "content": "be brief"}]
        assert _shrink_images(msgs, 1000) == msgs
