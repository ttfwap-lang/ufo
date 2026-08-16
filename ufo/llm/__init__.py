# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from enum import Enum


from ufo.llm.llm_result import LLMResult


class AgentType(str, Enum):
    HOST = "HOST_AGENT"
    APP = "APP_AGENT"
    CONSTELLATION = "CONSTELLATION_AGENT"
    EVALUATION = "EVALUATION_AGENT"
    REASONING = "REASONING_AGENT"
    OPERATOR = "OPERATOR"
    PREFILL = "PREFILL_AGENT"
    FILTER = "FILTER_AGENT"
    BACKUP = "BACKUP_AGENT"


__all__ = ["AgentType", "LLMResult"]

