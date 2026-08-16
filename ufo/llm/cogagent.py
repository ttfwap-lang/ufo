import asyncio
import logging
from typing import Any, Optional

import requests

from ufo.llm.base import BaseService
from ufo.llm.llm_result import LLMResult

logger = logging.getLogger(__name__)


class CogAgentService(BaseService):
    def __init__(self, config, agent_type: str):
        self.config_llm = config[agent_type]
        self.config = config
        self.agent_type = agent_type
        self.max_retry = self.config["MAX_RETRY"]
        self.timeout = self.config["TIMEOUT"]
        self.max_tokens = 2048  # default max tokens for cogagent for now

    async def chat_completion(
        self,
        messages,
        n,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        **kwargs: Any,
    ) -> LLMResult:
        """
        Generate chat completions asynchronously based on given messages.
        Args:
            messages (list): A list of messages.
            n (int): The number of completions to generate.
            temperature (float, optional): The temperature for sampling.
            max_tokens (int, optional): The maximum number of tokens.
            top_p (float, optional): The cumulative probability.
            **kwargs: Additional keyword arguments.
        Returns:
            LLMResult: Structured LLM result.
        """
        temperature = (
            temperature if temperature is not None else self.config["TEMPERATURE"]
        )
        max_tokens = max_tokens if max_tokens is not None else self.config["MAX_TOKENS"]
        top_p = top_p if top_p is not None else self.config["TOP_P"]

        texts = []
        for i in range(n):
            image_base64 = None
            if self.config_llm.get("VISUAL_MODE", False):
                image_base64 = messages[1]["content"][-2]["image_url"]["url"].split(
                    "base64,"
                )[1]
            prompt = messages[0]["content"] + messages[1]["content"][-1]["text"]

            payload = {
                "model": self.config_llm["API_MODEL"],
                "prompt": prompt,
                "temperature": temperature,
                "top_p": top_p,
                "max_new_tokens": self.max_tokens,
            }
            if image_base64 is not None:
                payload["image"] = image_base64

            response = await asyncio.to_thread(
                requests.post,
                self.config_llm["API_BASE"] + "/chat/completions",
                json=payload,
                timeout=self.timeout,
            )
            if response.status_code == 200:
                resp_json = response.json()
                text = resp_json.get("text", "")
                texts.append(text)
            else:
                raise RuntimeError(
                    f"Failed to get completion with error code {response.status_code}: {response.text}",
                )

        if not texts:
            raise RuntimeError(f"CogAgentService generated no completions for model '{self.config_llm.get('API_MODEL')}'")

        return LLMResult(
            responses=texts,
            cost=0.0,
            prompt_tokens=0,
            completion_tokens=0,
            model=self.config_llm.get("API_MODEL", "cogagent"),
            api_type="cogagent",
            agent_type=self.agent_type if isinstance(self.agent_type, str) else getattr(self.agent_type, "value", str(self.agent_type)),
        )
