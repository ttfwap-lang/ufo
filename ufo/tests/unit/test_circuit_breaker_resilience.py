# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Unit tests for thread-safe Circuit Breaker resilience logic in llm_call.
"""

import time
from ufo.llm.llm_call import _CircuitBreakerState


def test_circuit_breaker_initial_state():
    """Verify circuit breaker starts in CLOSED state."""
    cb = _CircuitBreakerState()
    assert cb.is_tripped("HOST_AGENT") is False
    assert cb.get_state("HOST_AGENT") == cb.CLOSED


def test_circuit_breaker_trips_to_open_after_threshold():
    """Verify circuit breaker transitions to OPEN after consecutive failures threshold."""
    cb = _CircuitBreakerState()
    cb._initialized = True
    cb._threshold = 3
    cb._reset_timeout = 60

    cb.record_failure("HOST_AGENT")
    assert cb.is_tripped("HOST_AGENT") is False
    cb.record_failure("HOST_AGENT")
    assert cb.is_tripped("HOST_AGENT") is False
    cb.record_failure("HOST_AGENT")
    assert cb.is_tripped("HOST_AGENT") is True
    assert cb.get_state("HOST_AGENT") == cb.OPEN


def test_circuit_breaker_half_open_transition_and_probe():
    """Verify circuit breaker transitions to HALF-OPEN after reset timeout."""
    cb = _CircuitBreakerState()
    cb._initialized = True
    cb._threshold = 2
    cb._reset_timeout = 0.1  # 100ms for testing
    cb._half_open_max_trials = 1

    cb.record_failure("HOST_AGENT")
    cb.record_failure("HOST_AGENT")
    assert cb.is_tripped("HOST_AGENT") is True

    # Sleep past reset timeout
    time.sleep(0.15)

    # First probe trial is admitted (is_tripped returns False)
    assert cb.is_tripped("HOST_AGENT") is False
    assert cb.get_state("HOST_AGENT") == cb.HALF_OPEN

    # Subsequent probe beyond half_open_max_trials is blocked
    assert cb.is_tripped("HOST_AGENT") is True


def test_circuit_breaker_success_resets_to_closed():
    """Verify success in HALF-OPEN state resets breaker to CLOSED."""
    cb = _CircuitBreakerState()
    cb._initialized = True
    cb._threshold = 2
    cb._reset_timeout = 0.1
    cb._half_open_max_trials = 1

    cb.record_failure("HOST_AGENT")
    cb.record_failure("HOST_AGENT")
    assert cb.is_tripped("HOST_AGENT") is True

    time.sleep(0.15)
    assert cb.is_tripped("HOST_AGENT") is False  # Admitted trial

    # Record success
    cb.record_success("HOST_AGENT")
    assert cb.get_state("HOST_AGENT") == cb.CLOSED
    assert cb.is_tripped("HOST_AGENT") is False


def test_is_retryable_error_does_not_match_incidental_substrings():
    """Verify _is_retryable_error does not match incidental numbers like '429' in non-retryable messages."""
    from ufo.llm.llm_call import _is_retryable_error

    # Non-retryable error containing incidental 429 substring
    err = ValueError("Invalid argument count 429 in parse schema")
    assert _is_retryable_error(err) is False

    err2 = RuntimeError("Processed item 429 of 500 failed validation")
    assert _is_retryable_error(err2) is False

    # Structured status code 429 is retryable
    class MockHttpError(Exception):
        def __init__(self, status_code):
            self.status_code = status_code

    assert _is_retryable_error(MockHttpError(429)) is True
    assert _is_retryable_error(MockHttpError(503)) is True
    assert _is_retryable_error(MockHttpError(400)) is False

    # Semantic timeout/rate limit phrases are retryable
    assert _is_retryable_error(RuntimeError("Rate limit exceeded")) is True
    assert _is_retryable_error(RuntimeError("Connection timed out")) is True
    assert _is_retryable_error(RuntimeError("Resource_exhausted")) is True


import pytest


@pytest.mark.asyncio
async def test_open_circuit_breaker_blocks_when_fallback_unavailable():
    """Verify get_completions raises and does not dispatch when circuit is OPEN and no fallback is available."""
    from ufo.llm.llm_call import get_completions, _circuit_breaker

    _circuit_breaker.reset()
    _circuit_breaker._initialized = True
    _circuit_breaker._threshold = 1
    _circuit_breaker._reset_timeout = 60

    # Trip the breaker for BACKUP_AGENT
    _circuit_breaker.record_failure("BACKUP_AGENT")
    assert _circuit_breaker.is_tripped("BACKUP_AGENT") is True

    # When BACKUP_AGENT is called with use_backup_engine=False, it should raise immediately
    with pytest.raises(RuntimeError, match="Circuit breaker is OPEN"):
        await get_completions(
            messages=[{"role": "user", "content": "hi"}],
            agent="BACKUP_AGENT",
            use_backup_engine=False,
            configs={
                "BACKUP_AGENT": {
                    "API_TYPE": "openai",
                    "API_MODEL": "gpt-4o",
                    "API_KEY": "sk-test",
                    "API_BASE": "https://api.openai.com/v1",
                }
            },
        )

    _circuit_breaker.reset()


@pytest.mark.asyncio
async def test_open_circuit_breaker_records_dlq_before_raising():
    """Verify circuit-open terminal failures record a DLQ snapshot before raising."""
    from unittest.mock import patch
    from ufo.llm.llm_call import get_completions, _circuit_breaker

    _circuit_breaker.reset()
    _circuit_breaker._initialized = True
    _circuit_breaker._threshold = 1
    _circuit_breaker._reset_timeout = 60

    # Trip the breaker for BACKUP_AGENT
    _circuit_breaker.record_failure("BACKUP_AGENT")
    assert _circuit_breaker.is_tripped("BACKUP_AGENT") is True

    with patch("ufo.llm.llm_call.record_dlq_event") as mock_dlq:
        with pytest.raises(RuntimeError, match="Circuit breaker is OPEN"):
            await get_completions(
                messages=[{"role": "user", "content": "hi"}],
                agent="BACKUP_AGENT",
                use_backup_engine=False,
                configs={
                    "BACKUP_AGENT": {
                        "API_TYPE": "openai",
                        "API_MODEL": "gpt-4o",
                        "API_KEY": "sk-test",
                        "API_BASE": "https://api.openai.com/v1",
                    }
                },
            )

        # DLQ must have been called exactly once with circuit_breaker_open_terminal trigger
        mock_dlq.assert_called_once()
        call_kwargs = mock_dlq.call_args[1] if mock_dlq.call_args[1] else {}
        # If called with positional args, use call_args[0]
        if not call_kwargs:
            call_kwargs = mock_dlq.call_args
        assert mock_dlq.call_args[1].get("extra_meta", {}).get("trigger") == "circuit_breaker_open_terminal"

    _circuit_breaker.reset()
