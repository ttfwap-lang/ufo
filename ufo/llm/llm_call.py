# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
LLM Call Module — Multi-tier routing with circuit breaker, retry middleware,
and optional Pydantic schema validation.

Architecture:
  1. Circuit Breaker: Tracks consecutive failures per agent. After FAILURE_THRESHOLD
     consecutive failures, routes directly to BACKUP_AGENT for RESET_TIMEOUT seconds.
  2. Retry Middleware: Catches 429 RateLimit, 503 Overload, and TimeoutError with
     exponential/linear backoff before triggering fallback.
  3. Schema Validation: Optional Pydantic model validation on LLM responses with
     repair-prompt retry (max 2 attempts).
"""

import logging
import time
from typing import Any, Dict, Optional, Tuple, Type

from pydantic import BaseModel, ValidationError

from ufo.llm import AgentType
from .base import BaseService
from .config_helper import get_agent_config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Circuit Breaker — Module-level state (resets on process restart)
# ---------------------------------------------------------------------------

class _CircuitBreakerState:
    """Per-agent circuit breaker tracking."""

    def __init__(self) -> None:
        self._failure_counts: Dict[str, int] = {}
        self._tripped_at: Dict[str, float] = {}
        self._threshold: int = 3
        self._reset_timeout: float = 300.0
        self._enabled: bool = True
        self._initialized: bool = False

    def _lazy_init(self) -> None:
        """Load config on first use to avoid import-time config dependency."""
        if self._initialized:
            return
        self._initialized = True
        try:
            from config.config_loader import get_ufo_config
            cfg = get_ufo_config()
            cb_cfg = getattr(cfg.system, "circuit_breaker", None)
            if cb_cfg and isinstance(cb_cfg, dict):
                self._enabled = cb_cfg.get("ENABLED", True)
                self._threshold = cb_cfg.get("FAILURE_THRESHOLD", 3)
                self._reset_timeout = float(cb_cfg.get("RESET_TIMEOUT_SECONDS", 300))
        except Exception:
            pass  # Use defaults

    def record_failure(self, agent_type: str) -> None:
        """Record a failure for the given agent type."""
        self._lazy_init()
        if not self._enabled:
            return
        count = self._failure_counts.get(agent_type, 0) + 1
        self._failure_counts[agent_type] = count
        if count >= self._threshold:
            self._tripped_at[agent_type] = time.monotonic()
            logger.warning(
                f"Circuit breaker TRIPPED for {agent_type} after "
                f"{count} consecutive failures. Routing to backup for "
                f"{self._reset_timeout}s."
            )

    def record_success(self, agent_type: str) -> None:
        """Reset failure count on success."""
        self._lazy_init()
        self._failure_counts[agent_type] = 0
        self._tripped_at.pop(agent_type, None)

    def is_tripped(self, agent_type: str) -> bool:
        """Check if the breaker is currently tripped for this agent."""
        self._lazy_init()
        if not self._enabled:
            return False
        tripped_time = self._tripped_at.get(agent_type)
        if tripped_time is None:
            return False
        elapsed = time.monotonic() - tripped_time
        if elapsed >= self._reset_timeout:
            # Auto-reset after cooldown
            logger.info(
                f"Circuit breaker RESET for {agent_type} after "
                f"{elapsed:.0f}s cooldown."
            )
            self._failure_counts[agent_type] = 0
            self._tripped_at.pop(agent_type, None)
            return False
        return True


_circuit_breaker = _CircuitBreakerState()


# ---------------------------------------------------------------------------
# Retry Middleware — Handles transient API errors
# ---------------------------------------------------------------------------

_RETRYABLE_STATUS_CODES = {429, 503}
_MAX_RETRIES = 3
_RETRY_BACKOFF = [1.0, 2.0, 4.0]  # Exponential backoff seconds


def _is_retryable_error(error: Exception) -> bool:
    """Check if an exception is retryable (429, 503, timeout)."""
    error_str = str(error).lower()

    # Check for HTTP status codes in error message
    for code in _RETRYABLE_STATUS_CODES:
        if str(code) in error_str:
            return True

    # Check for timeout errors
    if isinstance(error, (TimeoutError, ConnectionError)):
        return True
    if "timeout" in error_str or "timed out" in error_str:
        return True
    if "rate" in error_str and "limit" in error_str:
        return True
    if "overload" in error_str or "capacity" in error_str:
        return True

    return False


def _retry_with_backoff(service: BaseService, messages: list, n: int) -> Tuple[list, float]:
    """
    Attempt service.chat_completion with retry on transient errors.
    Returns (responses, cost) on success, raises on exhaustion.
    """
    last_error = None
    for attempt in range(_MAX_RETRIES):
        try:
            response, cost = service.chat_completion(messages, n)
            return response, cost
        except Exception as e:
            last_error = e
            if not _is_retryable_error(e):
                raise  # Non-retryable error, propagate immediately
            backoff = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
            logger.warning(
                f"Retryable error (attempt {attempt + 1}/{_MAX_RETRIES}): {e}. "
                f"Backing off {backoff}s..."
            )
            time.sleep(backoff)

    # All retries exhausted
    raise last_error  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Schema Validation — Optional Pydantic response validation with retry
# ---------------------------------------------------------------------------

_SCHEMA_VALIDATION_MAX_RETRIES = 2


def _validate_response_schema(
    response: str,
    schema: Type[BaseModel],
) -> Optional[str]:
    """
    Validate a response string against a Pydantic schema.
    Returns None on success, or an error message on failure.
    """
    try:
        import json as _json
        parsed = _json.loads(response)
        schema.model_validate(parsed)
        return None
    except ValidationError as e:
        return f"Schema validation failed: {e}"
    except Exception as e:
        return f"Response parsing failed: {e}"


# ---------------------------------------------------------------------------
# Public API — get_completion / get_completions
# ---------------------------------------------------------------------------

def get_completion(
    messages,
    agent: str = AgentType.APP,
    use_backup_engine: bool = True,
    configs: Optional[dict] = None,
    response_schema: Optional[Type[BaseModel]] = None,
) -> Tuple[str, float]:
    """
    Get completion for the given messages.
    :param messages: List of messages to be used for completion.
    :param agent: Type of agent.
    :param use_backup_engine: Flag indicating whether to use the backup engine.
    :param configs: Legacy configs dict. Empty = use new config system.
    :param response_schema: Optional Pydantic model to validate response against.
    :return: A tuple containing the completion response and the cost.
    """
    if configs is None:
        configs = {}

    responses, cost = get_completions(
        messages, agent=agent, use_backup_engine=use_backup_engine, n=1,
        configs=configs, response_schema=response_schema,
    )
    if not responses or responses[0] is None:
        raise RuntimeError(
            f"LLM service returned no response candidates for agent '{agent}'."
        )
    return responses[0], cost


def get_completions(
    messages,
    agent: str = AgentType.APP,
    use_backup_engine: bool = True,
    n: int = 1,
    configs: Optional[dict] = None,
    response_schema: Optional[Type[BaseModel]] = None,
) -> Tuple[list, float]:
    """
    Get completions for the given messages with circuit breaker, retry middleware,
    and optional Pydantic schema validation.

    :param messages: List of messages to be used for completion.
    :param agent: Type of agent.
    :param use_backup_engine: Flag indicating whether to use the backup engine.
    :param n: Number of completions to generate.
    :param configs: Legacy configs dict. Empty = use new config system.
    :param response_schema: Optional Pydantic model to validate response against.
    :return: A tuple containing the completion responses and the cost.
    """
    if configs is None:
        configs = {}

    # --- Resolve agent type ---
    if agent in [
        AgentType.HOST,
        AgentType.APP,
        AgentType.OPERATOR,
        AgentType.BACKUP,
        AgentType.CONSTELLATION,
        AgentType.REASONING,
    ]:
        agent_type = agent
    elif agent == AgentType.EVALUATION:
        if configs and AgentType.EVALUATION not in configs:
            agent_type = AgentType.APP
        elif not configs:
            try:
                get_agent_config(AgentType.EVALUATION)
                agent_type = AgentType.EVALUATION
            except (ValueError, AttributeError):
                agent_type = AgentType.APP
        else:
            agent_type = AgentType.EVALUATION
    elif agent.lower() == "prefill":
        agent_type = AgentType.PREFILL
    elif agent.lower() == "filter":
        agent_type = AgentType.FILTER
    else:
        raise ValueError(f"Agent {agent} not supported")

    # --- Circuit Breaker Check ---
    if _circuit_breaker.is_tripped(agent_type):
        if use_backup_engine and agent_type != AgentType.BACKUP:
            logger.info(
                f"Circuit breaker active for {agent_type}. "
                f"Routing directly to BACKUP_AGENT."
            )
            return get_completions(
                messages, agent=AgentType.BACKUP,
                use_backup_engine=False, n=n, configs=configs,
                response_schema=response_schema,
            )

    # --- Resolve API config ---
    if not configs:
        agent_config = get_agent_config(agent_type)
        api_type = agent_config["API_TYPE"]
        api_model = agent_config["API_MODEL"]
    else:
        api_type = configs[agent_type]["API_TYPE"]
        api_model = configs[agent_type]["API_MODEL"]

    # --- Execute with retry middleware ---
    try:
        api_type_lower = api_type.lower()
        service = BaseService.get_service(api_type_lower, agent_type, api_model.lower())
        if not service:
            raise ValueError(f"API_TYPE {api_type} not supported")

        response, cost = _retry_with_backoff(service, messages, n)

        # --- Circuit breaker success ---
        _circuit_breaker.record_success(agent_type)

        # --- Schema validation (if requested) ---
        if response_schema and response:
            for attempt in range(_SCHEMA_VALIDATION_MAX_RETRIES):
                first_response = response[0] if isinstance(response, list) else response
                if first_response is None:
                    break
                validation_error = _validate_response_schema(
                    str(first_response), response_schema
                )
                if validation_error is None:
                    break  # Valid
                if attempt < _SCHEMA_VALIDATION_MAX_RETRIES - 1:
                    logger.warning(
                        f"Schema validation attempt {attempt + 1} failed: "
                        f"{validation_error}. Retrying with repair prompt..."
                    )
                    repair_msg = messages + [{
                        "role": "user",
                        "content": (
                            f"Your previous response failed schema validation: "
                            f"{validation_error}. Please fix the JSON to match "
                            f"the required schema and respond with ONLY valid JSON."
                        ),
                    }]
                    response, cost = _retry_with_backoff(service, repair_msg, n)
                else:
                    logger.warning(
                        f"Schema validation exhausted after "
                        f"{_SCHEMA_VALIDATION_MAX_RETRIES} attempts. "
                        f"Returning raw response."
                    )

        return response, cost

    except Exception as e:
        # --- Circuit breaker failure ---
        _circuit_breaker.record_failure(agent_type)

        if use_backup_engine:
            logger.error(f"The API request of {agent_type} failed: {e}.")
            logger.warning("Switching to use the backup engine...")
            return get_completions(
                messages,
                agent=AgentType.BACKUP,
                use_backup_engine=False,
                n=n,
                configs=configs,
                response_schema=response_schema,
            )
        else:
            raise e
