# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import logging
import os
from typing import Any, Dict, List, Optional

from ufo.llm import response_format_override
from ufo.llm.llm_result import LLMResult
from ufo.llm.openai import BaseOpenAIService

logger = logging.getLogger(__name__)


class OllamaService(BaseOpenAIService):
    """
    A service class for Ollama models.
    """

    def __init__(self, config, agent_type: str):
        """
        Initialize the Ollama service.
        :param config: The configuration.
        :param agent_type: The agent type.
        """
        base_url = config[agent_type]["API_BASE"]
        config[agent_type]["API_KEY"] = "ollama"
        super().__init__(config, agent_type, "openai", f"{base_url}/v1")

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        n: int = 1,
        stream: bool = False,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        **kwargs: Any,
    ) -> LLMResult:
        """
        Generates completions for a given conversation using the Ollama API asynchronously.
        :param messages: The list of messages in the conversation.
        :param n: The number of completions to generate.
        :param stream: Whether to stream the API response.
        :param temperature: The temperature parameter for randomness in the output.
        :param max_tokens: The maximum number of tokens in the generated completion.
        :param top_p: The top-p parameter for nucleus sampling.
        :param kwargs: Additional keyword arguments to pass to the OpenAI API.
        :return: LLMResult containing responses, cost, token counts, and metadata.
        """
        return await super()._chat_completion(
            messages,
            stream=stream,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            response_format=response_format_override.current() or self._response_format(),
            **kwargs,
        )

    def _response_format(self) -> Dict[str, Any]:
        """Constrain decoding to UFO's agent response shape.

        Plain ``json_object`` mode lets the model pick its own keys (e.g. a
        LangChain-style ``action``/``action_input``), which UFO can't
        execute reliably. Ollama supports JSON-schema constrained decoding
        on ``/v1/chat/completions``; the schema below forces the
        ``function``/``arguments``/``status`` fields UFO actually reads.
        Set UFO_OLLAMA_JSON_SCHEMA=0 to fall back to plain json_object.
        """
        if os.environ.get("UFO_OLLAMA_JSON_SCHEMA", "1") == "0":
            return {"type": "json_object"}
        agent = str(getattr(self, "agent_type", "") or "").upper()
        if agent.startswith("HOST"):
            statuses = ["CONTINUE", "FINISH", "PENDING", "ASSIGN"]
            props = {
                "observation": {"type": "string"},
                "thought": {"type": "string"},
                "current_subtask": {"type": "string"},
                "message": {"type": "array", "items": {"type": "string"}},
                "questions": {"type": "array", "items": {"type": "string"}},
                "function": {"type": "string"},
                "arguments": {"type": "object"},
                "status": {"type": "string", "enum": statuses},
                "plan": {"type": "array", "items": {"type": "string"}},
                "comment": {"type": "string"},
            }
            required = ["thought", "function", "arguments", "status"]
        elif agent.startswith(("APP", "BACKUP")):
            statuses = ["CONTINUE", "FINISH", "FAIL", "PENDING", "SCREENSHOT", "CONFIRM"]
            # Matches the AppAgent prompt: "action" is a list of 1-4 steps
            # (one step when ACTION_SEQUENCE is off). An empty list is allowed
            # only for FINISH/FAIL-style replies.
            action_item = {
                "type": "object",
                "properties": {
                    "function": {"type": "string"},
                    "arguments": {"type": "object"},
                    "status": {"type": "string", "enum": statuses},
                },
                "required": ["function", "arguments", "status"],
            }
            props = {
                "observation": {"type": "string"},
                "thought": {"type": "string"},
                "action": {"type": "array", "items": action_item, "maxItems": 4},
                "status": {"type": "string", "enum": statuses},
                "plan": {"type": "array", "items": {"type": "string"}},
                "comment": {"type": "string"},
            }
            required = ["thought", "action", "status"]
        else:
            return {"type": "json_object"}
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "ufo_agent_response",
                "strict": True,
                "schema": {"type": "object", "properties": props, "required": required},
            },
        }
