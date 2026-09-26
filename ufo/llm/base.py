# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import abc
from importlib import import_module
from typing import Dict, Optional

from ufo.config.config_loader import get_galaxy_config, get_ufo_config
from ufo.llm.config_helper import get_agent_config
from ufo.llm.llm_result import LLMResult


class BaseService(abc.ABC):
    @abc.abstractmethod
    def __init__(self, *args, **kwargs):
        pass

    @abc.abstractmethod
    async def chat_completion(self, *args, **kwargs) -> LLMResult:
        pass

    @staticmethod
    def get_service(
        name: str,
        agent_type: str,
        model_name: str = None,
        config: Optional[Dict] = None,
    ) -> "BaseService":
        """
        Get the service class based on the name.
        :param name: The name of the service.
        :param agent_type: The agent type (used to get appropriate config).
        :param model_name: The model name (used for custom service routing).
        :param config: Optional complete service config.  This is used by
            provider-specific fallback routes (for example Featherless
            refusal recovery) without changing the process-wide active route.
        :return: The service class.
        """
        service_map = {
            "openai": "OpenAIService",
            "aoai": "OpenAIService",
            "azure_ad": "OpenAIService",
            "qwen": "QwenService",
            "deepseek": "DeepSeekService",
            "ollama": "OllamaService",
            "gemini": "GeminiService",
            "claude": "ClaudeService",
            "custom": "CustomService",
            "operator": "OperatorServicePreview",
            "placeholder": "PlaceHolderService",
        }
        custom_service_map = {
            "llava": "LlavaService",
            "cogagent": "CogAgentService",
        }

        # Get agent-specific config using the new config system, unless a
        # caller supplied an isolated provider config (e.g. a fallback route).
        from ufo.llm import AgentType

        agent_type_key = (
            agent_type.value if hasattr(agent_type, "value") else agent_type
        )

        if config is not None:
            agent_config = config.get(agent_type_key, config.get(agent_type))
            if not isinstance(agent_config, dict):
                raise ValueError(f"Config for agent {agent_type!r} is missing")
            # Preserve the caller's complete top-level settings and fill only
            # the values expected by older service implementations.
            configs_dict = dict(config)
            configs_dict[agent_type_key] = agent_config
            configs_dict.setdefault("MAX_RETRY", 2)
            configs_dict.setdefault("TIMEOUT", 60)
            configs_dict.setdefault("PRICES", {})
            configs_dict.setdefault("TEMPERATURE", 0.0)
            configs_dict.setdefault("TOP_P", 0.0)
            configs_dict.setdefault("MAX_TOKENS", 2000)
        else:
            agent_config = get_agent_config(agent_type)

            # Get global configs (MAX_RETRY, TIMEOUT, PRICES, etc.) from the
            # appropriate source.  Constellation has a separate config tree.
            if agent_type == AgentType.CONSTELLATION:
                global_config = get_galaxy_config()
                system_config = global_config.constellation
            else:
                global_config = get_ufo_config()
                system_config = global_config.system

            # Wrap agent config in a dict keyed by agent_type for backward
            # compatibility. Services expect configs[agent_type][...].
            configs_dict = {
                agent_type_key: agent_config,
                "MAX_RETRY": getattr(system_config, "MAX_RETRY", getattr(system_config, "max_retry", 20)),
                "TIMEOUT": getattr(system_config, "TIMEOUT", getattr(system_config, "timeout", 60)),
                "PRICES": getattr(system_config, "PRICES", getattr(system_config, "prices", {})),
                "TEMPERATURE": getattr(system_config, "TEMPERATURE", getattr(system_config, "temperature", 0.0)),
                "TOP_P": getattr(system_config, "TOP_P", getattr(system_config, "top_p", 0.0)),
                "MAX_TOKENS": getattr(system_config, "MAX_TOKENS", getattr(system_config, "max_tokens", 2000)),
            }

        service_name = service_map.get(name, None)
        if service_name:
            if name in ["aoai", "azure_ad", "operator"]:
                module = import_module(".openai", package="ufo.llm")
            elif service_name == "CustomService":
                custom_model = "llava" if "llava" in model_name else model_name
                custom_service_name = custom_service_map.get(
                    "llava" if "llava" in custom_model else custom_model, None
                )
                if custom_service_name:
                    module = import_module("." + custom_model, package="ufo.llm")
                    service_name = custom_service_name
                else:
                    raise ValueError(f"Custom model {custom_model} not supported")
            else:
                module = import_module("." + name.lower(), package="ufo.llm")

            # Pass configs_dict with agent_type as key for backward compatibility
            return getattr(module, service_name)(configs_dict, agent_type=agent_type)
        else:
            raise ValueError(f"Service {name} not found.")

    def get_cost_estimator(
        self,
        api_type: str,
        model: str,
        prices: Dict[str, float],
        prompt_tokens: int,
        completion_tokens: int,
    ) -> float:
        """
        Calculates the cost estimate for using a specific model based on the number of prompt tokens and completion tokens.
        :param api_type: The type of api used.
        :param model: The name of the model.
        :param prices: A dictionary containing the prices for different models.
        :param prompt_tokens: The number of prompt tokens used.
        :param completion_tokens: The number of completion tokens used.
        :return: The estimated cost for using the model.
        """

        if api_type.lower() in {"openai", "featherless"}:
            name = str(api_type.lower() + "/" + model)
        elif api_type.lower() in ["aoai", "azure_ad"]:
            name = str("azure/" + model)
        elif api_type.lower() == "qwen":
            name = str("qwen/" + model)
        elif api_type.lower() == "deepseek":
            name = str("deepseek/" + model)
        elif api_type.lower() == "gemini":
            name = str("gemini/" + model)
        elif api_type.lower() == "claude":
            name = str("claude/" + model)
        else:
            name = model

        if name in prices:
            cost = (
                prompt_tokens * prices[name]["input"] / 1000
                + completion_tokens * prices[name]["output"] / 1000
            )
        else:
            return 0
        return cost
