import functools
import base64
import json
import logging
import re
import time
import random
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import types, errors
from google.genai.types import GenerateContentConfig, Part, GenerateContentResponse

from ufo.llm.base import BaseService

from ufo.llm.response_schema import (
    AppAgentResponse,
    EvaluationResponse,
    HostAgentResponse,
)
from ufo.llm import AgentType

logger = logging.getLogger(__name__)


class GeminiService(BaseService):
    """
    A service class for Gemini models.
    """

    def __init__(self, config: Dict[str, Any], agent_type: str):
        """
        Initialize the Gemini service.
        :param config: The configuration.
        :param agent_type: The agent type.
        """
        self.config_llm = config[agent_type]
        self.config = config
        self.model = self.config_llm["API_MODEL"]
        self.prices = self.config["PRICES"]
        self.max_retry = self.config["MAX_RETRY"]
        self.api_type = self.config_llm["API_TYPE"].lower()
        self.client = GeminiService.get_gemini_client(
            api_key=self.config_llm["API_KEY"],
        )
        self.agent_type = agent_type
        self.json_schema_enabled = self.config_llm.get("JSON_SCHEMA", False)

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        n: int = 1,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        **kwargs: Any,
    ) -> Any:
        """
        Generates completions for a given list of messages.
        :param messages: The list of messages to generate completions for.
        :param n: The number of completions to generate for each message.
        :param temperature: Controls the randomness of the generated completions. Higher values (e.g., 0.8) make the completions more random, while lower values (e.g., 0.2) make the completions more focused and deterministic. If not provided, the default value from the model configuration will be used.
        :param max_tokens: The maximum number of tokens in the generated completions. If not provided, the default value from the model configuration will be used.
        :param top_p: Controls the diversity of the generated completions. Higher values (e.g., 0.8) make the completions more diverse, while lower values (e.g., 0.2) make the completions more focused. If not provided, the default value from the model configuration will be used.
        :param kwargs: Additional keyword arguments to be passed to the underlying completion method.
        :return: A list of generated completions for each message and the estimated cost.
        """

        temperature = (
            temperature if temperature is not None else self.config["TEMPERATURE"]
        )
        top_p = top_p if top_p is not None else self.config["TOP_P"]
        max_tokens = max_tokens if max_tokens is not None else self.config["MAX_TOKENS"]

        processed_messages = self.process_messages(messages)

        model_lower = self.model.lower()
        is_computer_use_model = any(
            tag in model_lower
            for tag in ("computer-use", "computer_use", "computeruse", "cua", "computer")
        )
        use_computer_use = is_computer_use_model

        # Default parameters from OpenAI
        # Ref: _calculate_retry_timeout from https://github.com/openai/openai-python/blob/main/src/openai/_base_client.py
        initial_delay = 0.5
        max_delay = 8.0
        jitter_factor = 0.25

        response = None
        cost = 0.0
        last_error = None

        for attempt in range(self.max_retry):
            genai_config_args: Dict[str, Any] = {
                "max_output_tokens": max_tokens,
                "temperature": temperature,
                "top_p": top_p,
            }

            if use_computer_use:
                genai_config_args["tools"] = [
                    types.Tool(
                        computer_use=types.ComputerUse(
                            environment=types.Environment.ENVIRONMENT_DESKTOP
                        )
                    )
                ]
            else:
                genai_config_args["response_mime_type"] = "application/json"
                if self.json_schema_enabled:
                    response_format = {
                        AgentType.HOST: HostAgentResponse,
                        AgentType.APP: AppAgentResponse,
                        AgentType.EVALUATION: EvaluationResponse,
                    }.get(self.agent_type, None)
                    if response_format:
                        genai_config_args["response_schema"] = response_format

            genai_config = GenerateContentConfig(**genai_config_args)

            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=processed_messages,
                    config=genai_config,
                )
                usage = getattr(response, "usage_metadata", None)
                prompt_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
                completion_tokens = (
                    getattr(usage, "candidates_token_count", 0) if usage else 0
                )
                cost = self.get_cost_estimator(
                    self.api_type,
                    self.model,
                    self.prices,
                    prompt_tokens,
                    completion_tokens,
                )
                break
            except Exception as e:
                last_error = e
                err_str = str(e).upper()
                is_client_error = (
                    isinstance(e, (errors.ClientError, errors.APIError))
                    or getattr(e, "code", None) in (400, 403, 404)
                    or any(
                        code_str in err_str
                        for code_str in (
                            "400",
                            "403",
                            "404",
                            "INVALID_ARGUMENT",
                            "FORBIDDEN",
                            "INVALID_OPTION",
                            "UNKNOWN_OPTION",
                            "UNSUPPORTED",
                            "NOT_FOUND",
                            "PERMISSION_DENIED",
                        )
                    )
                )
                if use_computer_use and is_client_error:
                    logger.warning(
                        f"ClientError ({getattr(e, 'code', 'N/A')}) encountered with computer_use tools: {e}. "
                        "Stripping tools parameter, restoring application/json response mode, and retrying..."
                    )
                    use_computer_use = False
                    try:
                        fallback_config_args: Dict[str, Any] = {
                            "max_output_tokens": max_tokens,
                            "temperature": temperature,
                            "top_p": top_p,
                            "response_mime_type": "application/json",
                        }
                        if self.json_schema_enabled:
                            response_format = {
                                AgentType.HOST: HostAgentResponse,
                                AgentType.APP: AppAgentResponse,
                                AgentType.EVALUATION: EvaluationResponse,
                            }.get(self.agent_type, None)
                            if response_format:
                                fallback_config_args["response_schema"] = response_format

                        fallback_config = GenerateContentConfig(**fallback_config_args)
                        response = self.client.models.generate_content(
                            model=self.model,
                            contents=processed_messages,
                            config=fallback_config,
                        )
                        usage = getattr(response, "usage_metadata", None)
                        prompt_tokens = (
                            getattr(usage, "prompt_token_count", 0) if usage else 0
                        )
                        completion_tokens = (
                            getattr(usage, "candidates_token_count", 0) if usage else 0
                        )
                        cost = self.get_cost_estimator(
                            self.api_type,
                            self.model,
                            self.prices,
                            prompt_tokens,
                            completion_tokens,
                        )
                        break
                    except Exception as retry_e:
                        e = retry_e
                        last_error = retry_e

                # Calculate backoff with jitter
                delay = min(initial_delay * (2**attempt), max_delay)
                jitter = random.uniform(-jitter_factor * delay, 0)
                sleep_time = delay + jitter
                logger.warning(
                    f"Error during Gemini API request, attempt {attempt+1}/{self.max_retry}: {e}. "
                    f"Retrying in {sleep_time:.2f}s..."
                )
                time.sleep(sleep_time)

        if response is None:
            logger.error(
                f"Gemini API request failed after {self.max_retry} attempts for model '{self.model}'. "
                f"Last error: {last_error}. Returning empty response for graceful degradation."
            )
            return [], 0.0

        return self.get_text_from_all_candidates(response), cost

    def process_messages(self, messages: List[Dict[str, str]]) -> List[str]:
        """
        Process the given messages and extract prompts from them.
        :param messages: The messages to process.
        :return: A list of prompts extracted from the messages.
        """

        prompt_contents = []

        if isinstance(messages, dict):
            messages = [messages]
        for message in messages:
            if message["role"] == "system":
                prompt = f"Your general instruction: {message['content']}"
                prompt_contents.append(prompt)
            else:
                for content in message["content"]:
                    if content["type"] == "text":
                        prompt = content["text"]
                        prompt_contents.append(prompt)
                    elif content["type"] == "image_url":
                        prompt = self.base64_to_blob(content["image_url"]["url"])
                        prompt_contents.append(
                            Part.from_bytes(
                                data=prompt["data"], mime_type=prompt["mime_type"]
                            )
                        )
        return prompt_contents

    def base64_to_blob(self, base64_str: str) -> Dict[str, str]:
        """
        Converts a base64 encoded image string to MIME type and binary data.
        :param base64_str: The base64 encoded image string.
        :return: A dictionary containing the MIME type and binary data.
        """

        match = re.match(
            r"data:(?P<mime_type>image/.+?);base64,(?P<base64_string>.+)", base64_str
        )

        if match:
            mime_type = match.group("mime_type")
            base64_string = match.group("base64_string")
        else:
            print("Error: Could not parse the data URL.")
            raise ValueError("Invalid data URL format.")

        return {"mime_type": mime_type, "data": base64.b64decode(base64_string)}

    def get_text_from_all_candidates(
        self, response: GenerateContentResponse
    ) -> List[Optional[str]]:
        """
        Extracts the concatenated text content from each candidate in the response,
        including function_call parts returned by computer-use models.

        Args:
            response: The GenerateContentResponse object from the Gemini API call.

        Returns:
            A list where each element is the concatenated text from a candidate,
            or None if a candidate has no text or function_call parts.
        """
        all_texts = []
        if not response or not getattr(response, "candidates", None):
            logger.warning("Response object does not contain candidates.")
            return all_texts

        for i, candidate in enumerate(response.candidates):
            candidate_text: str = ""
            any_content_found: bool = False
            non_text_parts_found: List[str] = []

            if not candidate or not candidate.content or not candidate.content.parts:
                # Handle cases where a candidate might be empty (e.g., safety blocked)
                logger.warning(
                    f"Candidate {i} has no content or parts. Finish Reason: {getattr(candidate, 'finish_reason', 'N/A')}"
                )
                all_texts.append(None)
                continue

            for part in candidate.content.parts:
                # Check for non-text/non-function_call parts
                part_dump = (
                    part.model_dump(exclude={"text", "thought", "function_call"})
                    if hasattr(part, "model_dump")
                    else {}
                )
                for field_name, field_value in part_dump.items():
                    if field_value is not None:
                        if field_name not in non_text_parts_found:
                            non_text_parts_found.append(field_name)

                # Check text part
                if isinstance(part.text, str) and part.text:
                    if isinstance(part.thought, bool) and part.thought:
                        continue
                    any_content_found = True
                    candidate_text += part.text

                # Check function_call part (for computer_use preview model)
                function_call = getattr(part, "function_call", None)
                if function_call is not None:
                    if isinstance(function_call, dict):
                        fc_name = function_call.get("name")
                        fc_args = function_call.get("args")
                    else:
                        fc_name = getattr(function_call, "name", None)
                        fc_args = getattr(function_call, "args", None)

                    if fc_name is not None or fc_args is not None:
                        any_content_found = True
                        fc_dict = {
                            "name": fc_name,
                            "args": fc_args if fc_args is not None else {},
                        }
                        fc_json = json.dumps({"function_call": fc_dict})
                        if candidate_text and not candidate_text.endswith("\n"):
                            candidate_text += "\n"
                        candidate_text += fc_json

            if non_text_parts_found:
                logger.warning(
                    f"Candidate {i}: Contains unhandled non-text parts: {non_text_parts_found}."
                )

            all_texts.append(candidate_text if any_content_found else None)

        return all_texts

    @functools.lru_cache()
    @staticmethod
    def get_gemini_client(api_key: str) -> genai.Client:
        """
        Create a Gemini client using the provided API key.
        :param api_key: The API key for authentication.
        :return: A Gemini client instance.
        """
        return genai.Client(api_key=api_key)

