# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
LLM Call Module — Multi-tier routing with circuit breaker, retry middleware,
Pydantic schema validation, and Dead Letter Queue (DLQ) diagnostic persistence.

Architecture:
  1. Circuit Breaker: Tracks consecutive failures per agent. After FAILURE_THRESHOLD
     consecutive failures, routes directly to BACKUP_AGENT for RESET_TIMEOUT seconds.
  2. Retry Middleware: Catches 429 RateLimit, 503 Overload, and TimeoutError with
     exponential backoff before triggering fallback.
  3. Schema Validation: Optional Pydantic model validation on LLM responses with
     repair-prompt retry (max 2 attempts).
  4. Dead Letter Queue: On total fallback exhaustion, writes a diagnostic JSON snapshot.
"""

import asyncio
import logging
import threading
import time
from typing import Dict, Optional, Type

from pydantic import BaseModel, ValidationError

from ufo.llm import AgentType
from ufo.llm.base import BaseService
from ufo.llm.config_helper import get_agent_config
from ufo.llm.llm_result import LLMResult
from ufo.dlq.dead_letter_queue import record_dlq_event

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Circuit Breaker — Thread-safe module-level state
# ---------------------------------------------------------------------------

class _CircuitBreakerState:
    """
    Per-agent circuit breaker with 3-state machine:
      CLOSED   → Normal operation, failures counted
      OPEN     → All calls bypass to backup, timer running
      HALF-OPEN → After timeout, allow ONE probe call through
                  Success → CLOSED, Failure → OPEN (reset timer)
    """

    # States
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF-OPEN"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._states: Dict[str, str] = {}         # agent_type -> state
        self._failure_counts: Dict[str, int] = {}
        self._last_state_change: Dict[str, float] = {}
        self._half_open_trials: Dict[str, int] = {}
        self._threshold: int = 3
        self._reset_timeout: float = 300.0
        self._half_open_max_trials: int = 1
        self._fallback_agent: str = AgentType.BACKUP
        self._enabled: bool = True
        self._initialized: bool = False

    def _lazy_init(self) -> None:
        """Load config on first use to avoid import-time config dependency."""
        if self._initialized:
            return
        self._initialized = True
        try:
            from ufo.config.config_loader import get_ufo_config
            cfg = get_ufo_config()
            cb_cfg = getattr(cfg.system, "circuit_breaker", None)
            if cb_cfg and isinstance(cb_cfg, dict):
                self._enabled = cb_cfg.get("ENABLED", True)
                self._threshold = cb_cfg.get("FAILURE_THRESHOLD", 3)
                self._reset_timeout = float(cb_cfg.get("RESET_TIMEOUT_SECONDS", 300))
                self._half_open_max_trials = cb_cfg.get("HALF_OPEN_MAX_TRIALS", 1)
                self._fallback_agent = cb_cfg.get("FALLBACK_AGENT", AgentType.BACKUP)
        except Exception:
            pass  # Use defaults

    @property
    def fallback_agent(self) -> str:
        self._lazy_init()
        return self._fallback_agent

    def reset(self) -> None:
        """Reset all circuit breaker states."""
        with self._lock:
            self._states.clear()
            self._failure_counts.clear()
            self._last_state_change.clear()
            self._half_open_trials.clear()

    def _get_state(self, agent_type: str) -> str:
        return self._states.get(agent_type, self.CLOSED)

    def record_failure(self, agent_type: str) -> None:
        """Record a failure for the given agent type."""
        self._lazy_init()
        if not self._enabled:
            return

        with self._lock:
            state = self._get_state(agent_type)
            count = self._failure_counts.get(agent_type, 0) + 1
            self._failure_counts[agent_type] = count

            if state == self.HALF_OPEN:
                # Probe failed — snap back to OPEN, reset timer
                self._states[agent_type] = self.OPEN
                self._last_state_change[agent_type] = time.monotonic()
                self._half_open_trials[agent_type] = 0
                logger.warning(
                    f"Circuit breaker HALF-OPEN probe FAILED for {agent_type}. "
                    f"Returning to OPEN state."
                )
            elif count >= self._threshold:
                self._states[agent_type] = self.OPEN
                self._last_state_change[agent_type] = time.monotonic()
                self._half_open_trials[agent_type] = 0
                logger.warning(
                    f"Circuit breaker TRIPPED for {agent_type} after "
                    f"{count} consecutive failures. State → OPEN. "
                    f"Routing to backup for {self._reset_timeout}s."
                )

    def record_success(self, agent_type: str) -> None:
        """Reset failure count and state on success."""
        self._lazy_init()
        with self._lock:
            state = self._get_state(agent_type)
            if state == self.HALF_OPEN:
                logger.info(
                    f"Circuit breaker HALF-OPEN probe SUCCEEDED for {agent_type}. "
                    f"State → CLOSED."
                )

            self._failure_counts[agent_type] = 0
            self._states[agent_type] = self.CLOSED
            self._last_state_change.pop(agent_type, None)
            self._half_open_trials.pop(agent_type, None)

    def is_tripped(self, agent_type: str) -> bool:
        """
        Check if the breaker is currently blocking calls for this agent.

        Returns True if OPEN (should bypass to backup).
        Returns False if CLOSED or HALF-OPEN (allow call through).
        """
        self._lazy_init()
        if not self._enabled:
            return False

        with self._lock:
            state = self._get_state(agent_type)

            if state == self.CLOSED:
                return False

            if state == self.HALF_OPEN:
                trial_count = self._half_open_trials.get(agent_type, 0)
                if trial_count < self._half_open_max_trials:
                    self._half_open_trials[agent_type] = trial_count + 1
                    return False
                return True

            if state == self.OPEN:
                elapsed = time.monotonic() - self._last_state_change.get(agent_type, 0)
                if elapsed >= self._reset_timeout:
                    # Transition to HALF-OPEN — allow probe
                    self._states[agent_type] = self.HALF_OPEN
                    self._half_open_trials[agent_type] = 1
                    logger.info(
                        f"Circuit breaker entering HALF-OPEN for {agent_type} "
                        f"after {elapsed:.0f}s cooldown. Allowing probe call."
                    )
                    return False
                return True

            return False

    def get_state(self, agent_type: str) -> str:
        """Get current circuit breaker state for an agent (for diagnostics)."""
        self._lazy_init()
        with self._lock:
            return self._get_state(agent_type)


_circuit_breaker = _CircuitBreakerState()


# ---------------------------------------------------------------------------
# Retry Middleware — Handles transient API errors
# ---------------------------------------------------------------------------

_RETRYABLE_STATUS_CODES = {429, 503}
_DEFAULT_MAX_RETRIES = 3
_RETRY_BACKOFF = [1.0, 2.0, 4.0]  # Exponential backoff seconds


def _is_retryable_error(error: Exception) -> bool:
    """Check if an exception is retryable (429, 503, timeout, connection)."""
    # 1. Typed error checks for known SDKs
    try:
        import openai
        if isinstance(
            error,
            (
                openai.RateLimitError,
                openai.APITimeoutError,
                openai.APIConnectionError,
                openai.InternalServerError,
            ),
        ):
            return True
    except (ImportError, AttributeError):
        pass

    try:
        import anthropic
        if isinstance(
            error,
            (
                anthropic.RateLimitError,
                anthropic.APITimeoutError,
                anthropic.APIConnectionError,
                anthropic.InternalServerError,
            ),
        ):
            return True
    except (ImportError, AttributeError):
        pass

    # 2. Check for HTTP status codes on the error object
    status_code = getattr(error, "status_code", None) or getattr(error, "code", None)
    if status_code in {429, 500, 502, 503, 504}:
        return True

    # 3. Standard built-in network / timeout errors
    if isinstance(error, (TimeoutError, ConnectionError, asyncio.TimeoutError)):
        return True

    # 4. Fallback semantic string checks (unambiguous phrases only, no raw numeric substrings)
    error_str = str(error).lower()
    if "timeout" in error_str or "timed out" in error_str:
        return True
    if "rate limit" in error_str or "rate_limit" in error_str:
        return True
    if "overload" in error_str or "capacity" in error_str or "resource_exhausted" in error_str or "service unavailable" in error_str:
        return True

    return False


async def _retry_with_backoff(service: BaseService, messages: list, n: int) -> LLMResult:
    """
    Attempt service.chat_completion with retry on transient errors.
    Returns LLMResult on success, raises on exhaustion.
    """
    max_retries = getattr(service, "max_retry", _DEFAULT_MAX_RETRIES)
    if not isinstance(max_retries, int) or max_retries <= 0:
        max_retries = _DEFAULT_MAX_RETRIES

    last_error = None
    for attempt in range(max_retries):
        try:
            return await service.chat_completion(messages, n=n)
        except Exception as e:
            last_error = e
            if not _is_retryable_error(e):
                raise  # Non-retryable error, propagate immediately
            backoff = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
            logger.warning(
                f"Retryable error (attempt {attempt + 1}/{max_retries}): {e}. "
                f"Backing off {backoff}s..."
            )
            await asyncio.sleep(backoff)

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
# Public API — get_completion / get_completions (Async)
# ---------------------------------------------------------------------------

async def get_completion(
    messages,
    agent: str = AgentType.APP,
    use_backup_engine: bool = True,
    configs: Optional[dict] = None,
    response_schema: Optional[Type[BaseModel]] = None,
) -> LLMResult:
    """
    Get completion for the given messages asynchronously.
    :param messages: List of messages to be used for completion.
    :param agent: Type of agent.
    :param use_backup_engine: Flag indicating whether to use the backup engine.
    :param configs: Legacy configs dict. Empty = use new config system.
    :param response_schema: Optional Pydantic model to validate response against.
    :return: LLMResult containing the response, cost, tokens, and metadata.
    """
    if configs is None:
        configs = {}

    result = await get_completions(
        messages,
        agent=agent,
        use_backup_engine=use_backup_engine,
        n=1,
        configs=configs,
        response_schema=response_schema,
    )
    if not result.responses or result.responses[0] is None:
        raise RuntimeError(
            f"LLM service returned no response candidates for agent '{agent}'."
        )
    return result


async def get_completions(
    messages,
    agent: str = AgentType.APP,
    use_backup_engine: bool = True,
    n: int = 1,
    configs: Optional[dict] = None,
    response_schema: Optional[Type[BaseModel]] = None,
) -> LLMResult:
    """
    Get completions for the given messages asynchronously with circuit breaker,
    retry middleware, schema validation, and DLQ recording.

    :param messages: List of messages to be used for completion.
    :param agent: Type of agent.
    :param use_backup_engine: Flag indicating whether to use the backup engine.
    :param n: Number of completions to generate.
    :param configs: Legacy configs dict. Empty = use new config system.
    :param response_schema: Optional Pydantic model to validate response against.
    :return: LLMResult containing responses, cost, tokens, and metadata.
    """
    if configs is None:
        configs = {}

    # --- Resolve agent type ---
    if agent is None:
        agent_type = AgentType.APP
    elif agent in [
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
    elif str(agent).lower() == "prefill":
        agent_type = AgentType.PREFILL
    elif str(agent).lower() == "filter":
        agent_type = AgentType.FILTER
    else:
        raise ValueError(f"Agent {agent} not supported")

    fallback_target = _circuit_breaker.fallback_agent or AgentType.BACKUP

    # --- Circuit Breaker Check ---
    if _circuit_breaker.is_tripped(agent_type):
        if use_backup_engine and agent_type != fallback_target:
            logger.info(
                f"Circuit breaker active for {agent_type}. "
                f"Routing directly to {fallback_target}."
            )
            return await get_completions(
                messages,
                agent=fallback_target,
                use_backup_engine=False,
                n=n,
                configs=configs,
                response_schema=response_schema,
            )
        else:
            terminal_error = RuntimeError(
                f"Circuit breaker is OPEN for agent '{agent_type}' and fallback is unavailable "
                f"(use_backup_engine={use_backup_engine})."
            )
            record_dlq_event(
                agent_type=str(agent_type),
                messages=messages if isinstance(messages, list) else [],
                error=terminal_error,
                model="unknown",
                circuit_breaker_state=_circuit_breaker.get_state(agent_type),
                extra_meta={"trigger": "circuit_breaker_open_terminal"},
            )
            raise terminal_error

    # --- Resolve API config ---
    if not configs:
        agent_config = get_agent_config(agent_type)
        api_type = agent_config["API_TYPE"]
        api_model = agent_config["API_MODEL"]
    else:
        agent_config = configs[agent_type]
        api_type = configs[agent_type]["API_TYPE"]
        api_model = configs[agent_type]["API_MODEL"]

    from ufo.llm.endpoint import is_cloud_agent_config
    is_cloud = is_cloud_agent_config(agent_config)

    # --- Telemetry Budget Enforcement (Cloud only) ---
    if is_cloud:
        is_exceeded = False
        try:
            from ufo.telemetry.cost_tracker import CostTracker
            is_exceeded = CostTracker.get_instance().is_budget_exceeded()
        except Exception as e:
            logger.warning(f"[Telemetry] Budget check failed: {e}")

        if is_exceeded:
            logger.critical(
                f"[Telemetry] Daily budget exceeded. Locking out cloud agent '{agent_type}'."
            )
            if use_backup_engine and agent_type != fallback_target:
                # Check if fallback agent is non-cloud (local)
                fallback_config = None
                try:
                    fallback_config = get_agent_config(fallback_target) if not configs else configs.get(fallback_target)
                except Exception:
                    pass

                if fallback_config and not is_cloud_agent_config(fallback_config):
                    logger.info(
                        f"[Telemetry] Routing to non-cloud fallback agent '{fallback_target}'."
                    )
                    return await get_completions(
                        messages,
                        agent=fallback_target,
                        use_backup_engine=False,
                        n=n,
                        configs=configs,
                        response_schema=response_schema,
                    )
            # Terminal lockout: no non-cloud fallback available or direct non-fallback call
            terminal_error = RuntimeError(
                f"Daily LLM budget exceeded: cloud APIs locked out for agent '{agent_type}' "
                f"and no non-cloud fallback available."
            )
            record_dlq_event(
                agent_type=str(agent_type),
                messages=messages if isinstance(messages, list) else [],
                error=terminal_error,
                model=api_model,
                circuit_breaker_state=_circuit_breaker.get_state(agent_type),
                extra_meta={"trigger": "budget_exceeded_terminal"},
            )
            raise terminal_error

    # --- PII Redaction (Cloud only, on deep copy) ---
    dispatch_messages = messages
    if is_cloud and isinstance(messages, list):
        try:
            from ufo.security.pii_redactor import PIIRedactor
            redactor = PIIRedactor()
            if redactor.should_redact_for_model(is_cloud=True):
                import copy
                dispatch_messages = copy.deepcopy(messages)
                for msg in dispatch_messages:
                    if isinstance(msg, dict):
                        content = msg.get("content")
                        if isinstance(content, str):
                            msg["content"] = redactor.redact_string(content)
                        elif isinstance(content, list):
                            for part in content:
                                if isinstance(part, dict) and part.get("type") == "text":
                                    part_text = part.get("text", "")
                                    if isinstance(part_text, str):
                                        part["text"] = redactor.redact_string(part_text)
        except Exception as e:
            logger.warning(f"[Redactor] PII text redaction failed: {e}")
            dispatch_messages = messages

    # --- Execute with retry middleware ---
    try:
        api_type_lower = api_type.lower()
        service = BaseService.get_service(api_type_lower, agent_type, api_model.lower())
        if not service:
            raise ValueError(f"API_TYPE {api_type} not supported")

        result = await _retry_with_backoff(service, dispatch_messages, n)

        # --- Validate non-empty response before recording success / telemetry ---
        if not result.responses or result.responses[0] is None:
            raise RuntimeError(
                f"Provider returned empty or null response for model '{api_model}': {result.responses}"
            )

        # --- Telemetry Usage Recording ---
        try:
            from ufo.telemetry.cost_tracker import CostTracker
            CostTracker.get_instance().record_usage(
                model=result.model or api_model,
                api_type=result.api_type or api_type,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
            )
        except Exception as e:
            logger.warning(f"[Telemetry] Usage recording failed: {e}")

        # --- Circuit breaker success ---
        _circuit_breaker.record_success(agent_type)

        # --- Schema validation (if requested) ---
        if response_schema and result.responses:
            for attempt in range(_SCHEMA_VALIDATION_MAX_RETRIES):
                first_response = result.responses[0]
                if first_response is None or isinstance(first_response, dict):
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
                    repair_msg = dispatch_messages + [{
                        "role": "user",
                        "content": (
                            f"Your previous response failed schema validation: "
                            f"{validation_error}. Please fix the JSON to match "
                            f"the required schema and respond with ONLY valid JSON."
                        ),
                    }]
                    result = await _retry_with_backoff(service, repair_msg, n)
                else:
                    logger.warning(
                        f"Schema validation exhausted after "
                        f"{_SCHEMA_VALIDATION_MAX_RETRIES} attempts. "
                        f"Returning raw response."
                    )

        return result

    except Exception as e:
        # --- Circuit breaker failure ---
        _circuit_breaker.record_failure(agent_type)

        if use_backup_engine and agent_type != fallback_target:
            logger.error(f"The API request of {agent_type} failed: {e}.")
            logger.warning(f"Switching to use fallback agent: {fallback_target}...")
            return await get_completions(
                messages,
                agent=fallback_target,
                use_backup_engine=False,
                n=n,
                configs=configs,
                response_schema=response_schema,
            )
        else:
            # All fallbacks exhausted -> record DLQ event
            record_dlq_event(
                agent_type=agent_type,
                messages=messages if isinstance(messages, list) else [],
                error=e,
                model=api_model,
                circuit_breaker_state=_circuit_breaker.get_state(agent_type),
            )
            raise e
