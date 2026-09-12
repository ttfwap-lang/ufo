import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import anthropic

from ufo.llm.base import BaseService
from ufo.llm.llm_result import LLMResult

logger = logging.getLogger(__name__)


class ClaudeService(BaseService):
    """
    A service class for Claude models.
    """

    def __init__(self, config: Dict[str, Any], agent_type: str):
        """
        Initialize the Claude service.
        :param config: The configuration.
        :param agent_type: The agent type.
        """
        self.config_llm = config[agent_type]
        self.config = config
        self.agent_type = agent_type
        self.model = self.config_llm["API_MODEL"]
        self.prices = self.config["PRICES"]
        self.max_retry = self.config["MAX_RETRY"]
        self.api_type = self.config_llm["API_TYPE"].lower()
        self.client = anthropic.Anthropic(api_key=self.config_llm["API_KEY"])

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        n: int = 1,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        **kwargs: Any,
    ) -> LLMResult:
        """
        Generates completions for a given list of messages asynchronously.
        :param messages: The list of messages to generate completions for.
        :param n: The number of completions to generate for each message.
        :param temperature: Controls the randomness of the generated completions.
        :param max_tokens: The maximum number of tokens in the generated completions.
        :param top_p: Controls the diversity of the generated completions.
        :param kwargs: Additional keyword arguments.
        :return: LLMResult containing responses, cost, token counts, and metadata.
        """
        temperature = (
            temperature if temperature is not None else self.config["TEMPERATURE"]
        )
        top_p = top_p if top_p is not None else self.config["TOP_P"]
        max_tokens = max_tokens if max_tokens is not None else self.config["MAX_TOKENS"]

        responses = []
        cost = 0.0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        system_prompt, user_prompt = self.process_messages(messages)

        for _ in range(n):
            response = await asyncio.to_thread(
                self.client.messages.create,
                max_tokens=max_tokens,
                model=self.model,
                system=system_prompt,
                messages=user_prompt,
            )
            responses.append(response.content[0].text)
            p_tokens = getattr(response.usage, "input_tokens", 0) or 0
            c_tokens = getattr(response.usage, "output_tokens", 0) or 0
            total_prompt_tokens += p_tokens
            total_completion_tokens += c_tokens
            cost += self.get_cost_estimator(
                self.api_type,
                self.model,
                self.prices,
                p_tokens,
                c_tokens,
            )

        if not responses:
            raise RuntimeError(f"Claude API generated no responses for model '{self.model}'")

        return LLMResult(
            responses=responses,
            cost=cost,
            prompt_tokens=total_prompt_tokens,
            completion_tokens=total_completion_tokens,
            model=self.model,
            api_type=self.api_type,
            agent_type=self.agent_type if isinstance(self.agent_type, str) else getattr(self.agent_type, "value", str(self.agent_type)),
        )

    def process_messages(
        self, messages: List[Dict[str, str]]
    ) -> Tuple[str, list[Dict]]:
        """
        Processes the messages to generate the system and user prompts.
        :param messages: A list of message dictionaries.
        :return: A tuple containing the system prompt (str) and the user prompt (list).
        """

        system_prompt = ""
        user_prompt = {"role": "user", "content": []}
        if isinstance(messages, dict):
            messages = [messages]
        for message in messages:
            if message["role"] == "system":
                system_prompt = message["content"]
            else:
                for content in message["content"]:
                    if content["type"] == "text":
                        user_prompt["content"].append(content)
                    elif content["type"] == "image_url":
                        data_url = content["image_url"]["url"]
                        match = re.match(r"data:(.*?);base64,(.*)", data_url)
                        if match:
                            media_type = match.group(1)
                            base64_data = match.group(2)
                            user_prompt["content"].append(
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": media_type,
                                        "data": base64_data,
                                    },
                                }
                            )
                        else:
                            raise ValueError("Invalid image URL")
        return system_prompt, [user_prompt]
