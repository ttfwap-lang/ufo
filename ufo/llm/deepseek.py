from typing import Any, Dict, List, Optional

from ufo.llm.openai import BaseOpenAIService
from ufo.llm.llm_result import LLMResult


class DeepSeekService(BaseOpenAIService):
    """
    A service class for DeepSeek models.
    """

    def __init__(self, config, agent_type: str):
        """
        :param config: The configuration.
        :param agent_type: The agent type.
        """
        super().__init__(config, agent_type, "openai", "https://api.deepseek.com/v1")

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
        Generates completions for a given conversation using the DeepSeek thru OpenAI Chat API asynchronously.
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
            response_format={"type": "json_object"},
            **kwargs,
        )
