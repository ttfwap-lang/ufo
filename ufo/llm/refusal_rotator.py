"""
Automated Refusal Detection and Multi-Tier Abliterated Qwen Rotation Engine.

This module intercepts restrictive safety refusals, denials, and "I cannot"
responses from any local or cloud LLMs. It rotates across uncensored, abliterated
Qwen models hosted on Featherless before falling back to visual models.

Rotation Flow:
  1. Identify refusal / restrictive response / safety exception.
  2. Rotate to Tier 1: Qwen 2.5 72B Instruct Abliterated (Featherless)
  3. If fail/refusal, rotate to Tier 2: Qwen 2 72B Instruct Abliterated (Featherless)
  4. If fail/refusal, rotate to Tier 3: Qwen 2.5 Coder 32B Instruct Abliterated (Featherless)
  5. If fail/refusal, rotate to Tier 4: Visual Safe Model (Gemma Visual / Qwen-VL / Gemini)
"""

import copy
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple, Type

from pydantic import BaseModel

from ufo.llm import AgentType
from ufo.llm.llm_result import LLMResult
from ufo.utils import print_with_color

logger = logging.getLogger(__name__)

# Strict regex patterns capturing all refusal, denial, and safety phrasings
REFUSAL_PATTERNS = [
    re.compile(r"\b(i\s+can\s*not|i\s+cannot|i\s+am\s+unable\s+to|i'm\s+unable\s+to|i\s+am\s+not\s+able\s+to|i'm\s+not\s+able\s+to)\b", re.IGNORECASE),
    re.compile(r"\b(i\s+must\s+decline|i\s+apologize,\s*but\s+i|as\s+an\s+ai\s+language\s+model|as\s+an\s+ai,\s*i)\b", re.IGNORECASE),
    re.compile(r"\b(safety\s+guidelines|violat(es|ing)\s+my\s+safety|content\s+policy|against\s+my\s+programming)\b", re.IGNORECASE),
    re.compile(r"\b(cannot\s+fulfill\s+this\s+request|cannot\s+assist\s+with\s+(this|that|your)\s+request)\b", re.IGNORECASE),
    re.compile(r"\b(i\s+am\s+sorry,\s*but\s+i\s+(cannot|can\s*not|am\s+not\s+allowed|must\s+refuse))\b", re.IGNORECASE),
    re.compile(r"\b(sorry,\s*i\s+(can't|cannot|can\s*not)\s+(do|help|assist|execute|proceed))\b", re.IGNORECASE),
    re.compile(r"\b(not\s+permitted\s+to|prohibited\s+from\s+executing|refuse\s+to\s+(perform|execute|assist))\b", re.IGNORECASE),
    re.compile(r"\b(i\s+cannot\s+provide\s+assistance|i\s+am\s+not\s+authorized\s+to)\b", re.IGNORECASE),
    re.compile(r"\b(i\s+can't\s+fulfill\s+this\s+request|i\s+can\s*not\s+fulfill\s+this\s+request)\b", re.IGNORECASE),
    re.compile(r"\b(i\s+am\s+unable\s+to\s+comply|i\s+cannot\s+comply)\b", re.IGNORECASE),
]

# Exception / Error keywords indicating safety refusal or content block
REFUSAL_ERROR_KEYWORDS = [
    "safety",
    "refusal",
    "blocked",
    "content filter",
    "content_policy",
    "prohibited_content",
    "policy violation",
    "moderation",
    "harmful",
    "responsible ai",
]

# 4-Tier Model Cascade Definition
ROTATION_TIERS: List[Dict[str, Any]] = [
    {
        "tier": 1,
        "name": "Qwen 2.5 72B Abliterated",
        "model_id": "mlabonne/Qwen2.5-72B-Instruct-abliterated",
        "api_type": "openai",
        "api_base": "https://api.featherless.ai/v1",
        "is_visual": False,
        "description": "Primary uncensored 72B model on Featherless",
    },
    {
        "tier": 2,
        "name": "Qwen 2 72B Abliterated",
        "model_id": "hugging-quants/Qwen2-72B-Instruct-abliterated",
        "api_type": "openai",
        "api_base": "https://api.featherless.ai/v1",
        "is_visual": False,
        "description": "Secondary uncensored 72B model on Featherless",
    },
    {
        "tier": 3,
        "name": "Qwen 2.5 Coder 32B Abliterated",
        "model_id": "failpy/Qwen2.5-Coder-32B-Instruct-abliterated",
        "api_type": "openai",
        "api_base": "https://api.featherless.ai/v1",
        "is_visual": False,
        "description": "Tertiary uncensored coding model on Featherless",
    },
    {
        "tier": 4,
        "name": "Visual Safe Model",
        "model_id": "ufo-app-model",
        "api_type": "local_or_cloud",
        "api_base": "",
        "is_visual": True,
        "description": "Visual executor model fallback",
    },
]


def is_refusal_text(text: Optional[str]) -> bool:
    """
    Check if a text output contains clear safety refusal or denial language.
    """
    if not text or not isinstance(text, str):
        return False
    text_clean = text.strip()
    if not text_clean:
        return False

    for pattern in REFUSAL_PATTERNS:
        if pattern.search(text_clean):
            return True
    return False


def is_refusal_response(result: Optional[LLMResult]) -> Tuple[bool, str]:
    """
    Inspect an LLMResult to determine if it is a refusal or policy denial.
    Returns (is_refusal, matched_reason).
    """
    if result is None:
        return False, ""

    # Check candidates / text responses
    if result.responses:
        for resp in result.responses:
            if isinstance(resp, str):
                if is_refusal_text(resp):
                    # Extract sample snippet
                    snippet = resp.strip()[:60].replace("\n", " ")
                    return True, f'Refusal text detected: "{snippet}..."'
            elif isinstance(resp, dict):
                # Check for refusal key in dict response
                refusal_field = resp.get("refusal")
                if refusal_field and is_refusal_text(str(refusal_field)):
                    return True, f'Refusal field in dict: "{refusal_field}"'
                # Check thought / action fields for refusal
                thought = str(resp.get("thought", ""))
                if is_refusal_text(thought):
                    return True, f'Refusal in thought field: "{thought[:60]}..."'

    return False, ""


def is_refusal_exception(error: Exception) -> Tuple[bool, str]:
    """
    Check if an exception is a safety refusal or content moderation filter.
    Returns (is_refusal, reason).
    """
    if error is None:
        return False, ""

    error_str = str(error).lower()
    for kw in REFUSAL_ERROR_KEYWORDS:
        if kw in error_str:
            return True, f"Safety exception matching '{kw}': {error}"

    # Check for specific SDK error attributes
    finish_reason = getattr(error, "finish_reason", None)
    if finish_reason and str(finish_reason).upper() in ["SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"]:
        return True, f"Finish reason: {finish_reason}"

    return False, ""


def adapt_messages_for_text_model(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Format multimodal messages containing image data into text-friendly format
    for text-only LLMs on Featherless, stripping large base64 image strings while
    preserving all contextual text and OCR information.
    """
    adapted: List[Dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            adapted.append(msg)
            continue

        role = msg.get("role", "user")
        content = msg.get("content")

        if isinstance(content, str):
            adapted.append(copy.deepcopy(msg))
        elif isinstance(content, list):
            # Multimodal parts array
            text_parts = []
            for part in content:
                if isinstance(part, dict):
                    part_type = part.get("type", "")
                    if part_type == "text":
                        text_parts.append(part.get("text", ""))
                    elif part_type in ["image_url", "image"]:
                        # Replace image with a contextual UI marker
                        text_parts.append("[Screenshot / UI visual frame attached]")
                elif isinstance(part, str):
                    text_parts.append(part)
            adapted.append({"role": role, "content": "\n".join(text_parts)})
        else:
            adapted.append(copy.deepcopy(msg))

    return adapted


async def execute_refusal_cascade(
    messages: List[Dict[str, Any]],
    agent_type: str = AgentType.APP,
    n: int = 1,
    configs: Optional[dict] = None,
    response_schema: Optional[Type[BaseModel]] = None,
    trigger_reason: str = "Safety refusal detected",
) -> LLMResult:
    """
    Executes the multi-tier abliterated rotation cascade silently with clean
    [Fallback 1, 2, 3] counting notifications to the user.

    Cascade:
      Tier 1: Qwen 2.5 72B Abliterated (Featherless)
      Tier 2: Qwen 2 72B Abliterated (Featherless)
      Tier 3: Qwen 2.5 Coder 32B Abliterated (Featherless)
      Tier 4: Visual Safe Model (Gemma Visual / Qwen3-VL / Gemini)
    """
    from ufo.llm.base import BaseService
    from ufo.llm.config_helper import get_agent_config

    featherless_key = os.environ.get("FEATHERLESS_API_KEY", "").strip()

    total_tiers = len(ROTATION_TIERS)
    last_error: Optional[Exception] = None

    for tier_info in ROTATION_TIERS:
        tier_num = tier_info["tier"]
        tier_name = tier_info["name"]
        model_id = tier_info["model_id"]
        api_base = tier_info["api_base"]
        is_visual = tier_info["is_visual"]

        # Display clean, user-friendly counting notification
        badge_msg = f"[Fallback {tier_num}/{total_tiers - 1 if tier_num < total_tiers else total_tiers}] {trigger_reason}. Rotating to {tier_name}..."
        print_with_color(f"\n{badge_msg}", "yellow")
        logger.warning(badge_msg)

        # Prepare messages (strip base64 images if text-only model)
        tier_messages = messages if is_visual else adapt_messages_for_text_model(messages)

        try:
            if tier_info["api_type"] == "openai" and api_base:
                # Direct Featherless OpenAI-compatible call
                tier_config = {
                    agent_type: {
                        "API_TYPE": "openai",
                        "API_BASE": api_base,
                        "API_KEY": featherless_key,
                        "API_MODEL": model_id,
                        "JSON_SCHEMA": False,
                        "USE_RESPONSES": False,
                        "PRICES": {},
                        "MAX_RETRY": 2,
                    },
                    "PRICES": {},
                    "MAX_RETRY": 2,
                    "TIMEOUT": 60,
                    "TEMPERATURE": 0.0,
                    "TOP_P": 0.0,
                    "MAX_TOKENS": 4096,
                }
                service = BaseService.get_service("openai", agent_type, model_id, tier_config)
                if not service:
                    from ufo.llm.openai import OpenAIService
                    service = OpenAIService(tier_config, agent_type, "openai", api_base)

                result = await service.chat_completion(tier_messages, n=n)

            else:
                # Tier 4: Visual model fallback using standard config system
                from ufo.llm.llm_call import _retry_with_backoff
                base_cfg = get_agent_config(AgentType.APP) if not configs else configs.get(AgentType.APP, {})
                v_api_type = base_cfg.get("API_TYPE", "openai").lower()
                v_model = base_cfg.get("API_MODEL", "ufo-app-model")
                service = BaseService.get_service(v_api_type, agent_type, v_model.lower())
                if not service:
                    raise RuntimeError(f"Visual fallback service '{v_api_type}' unavailable.")
                result = await _retry_with_backoff(service, tier_messages, n)

            # Validate response candidates for safety refusal
            is_refused, ref_reason = is_refusal_response(result)
            if is_refused:
                logger.warning(f"Tier {tier_num} ({tier_name}) also returned refusal: {ref_reason}. Advancing to next tier...")
                trigger_reason = f"Tier {tier_num} refused"
                continue

            if result.responses and any(r is not None for r in result.responses):
                success_msg = f"[Fallback {tier_num}] Successfully received clean response from {tier_name}."
                print_with_color(f"{success_msg}\n", "green")
                logger.info(success_msg)
                return result

        except Exception as e:
            last_error = e
            is_ref, ref_msg = is_refusal_exception(e)
            reason_str = ref_msg if is_ref else str(e)
            logger.warning(f"Tier {tier_num} ({tier_name}) execution error: {reason_str}. Advancing to next tier...")
            trigger_reason = f"Tier {tier_num} error ({type(e).__name__})"
            continue

    # If all tiers exhausted, raise descriptive error
    raise RuntimeError(
        f"All {total_tiers} refusal fallback tiers exhausted. Last error: {last_error}"
    )
