import pytest
from ufo.llm.llm_call import get_completions
from ufo.telemetry.cost_tracker import CostTracker, _load_prices


def test_load_prices_fallback_path():
    """Verify _load_prices resolves prices from prices.yaml."""
    prices = _load_prices()
    assert isinstance(prices, dict)
    assert len(prices) > 0
    assert "gemini/gemini-3.7-flash" in prices or "openai/gpt-4o" in prices


def test_cost_tracker_budget_enforcement():
    """Verify CostTracker tracks spend and trips budget exceeded."""
    CostTracker.reset_instance()
    tracker = CostTracker.get_instance()
    tracker._enabled = True
    tracker._state.daily_budget_usd = 0.10  # 10 cents budget
    tracker._state.spent_today_usd = 0.0
    tracker._state.budget_exceeded = False

    # Within budget call
    allowed = tracker.record_usage(
        model="gpt-4o",
        api_type="openai",
        prompt_tokens=100,
        completion_tokens=50,
    )
    assert allowed is True
    assert tracker.is_budget_exceeded() is False

    # Force large usage to exceed 10 cents
    allowed = tracker.record_usage(
        model="gpt-4o",
        api_type="openai",
        prompt_tokens=50000,
        completion_tokens=50000,
    )
    assert allowed is False
    assert tracker.is_budget_exceeded() is True
    assert tracker.is_cloud_allowed() is False
    CostTracker.reset_instance()


@pytest.mark.asyncio
async def test_budget_lockout_terminal_when_fallback_is_cloud():
    """Verify budget lockout raises immediately without dispatching when fallback is cloud."""
    import time
    CostTracker.reset_instance()
    tracker = CostTracker.get_instance()
    tracker._enabled = True
    tracker._state.date = time.strftime("%Y-%m-%d")
    tracker._state.daily_budget_usd = 10.0
    tracker._state.spent_today_usd = 100.0
    tracker._state.budget_exceeded = True

    configs = {
        "HOST_AGENT": {
            "API_TYPE": "openai",
            "API_MODEL": "gpt-4o",
            "API_KEY": "sk-cloud-test",
            "API_BASE": "https://api.openai.com/v1",
        },
        "BACKUP_AGENT": {
            "API_TYPE": "gemini",
            "API_MODEL": "gemini-3.7-flash",
            "API_KEY": "ai-cloud-test",
            "API_BASE": "https://generativelanguage.googleapis.com",
        },
    }

    with pytest.raises(RuntimeError, match="Daily LLM budget exceeded"):
        await get_completions(
            messages=[{"role": "user", "content": "hello"}],
            agent="HOST_AGENT",
            use_backup_engine=True,
            configs=configs,
        )

    CostTracker.reset_instance()


@pytest.mark.asyncio
async def test_budget_lockout_terminal_direct_call():
    """Verify direct use_backup_engine=False cloud call raises when budget is exceeded."""
    import time
    CostTracker.reset_instance()
    tracker = CostTracker.get_instance()
    tracker._enabled = True
    tracker._state.date = time.strftime("%Y-%m-%d")
    tracker._state.daily_budget_usd = 10.0
    tracker._state.spent_today_usd = 100.0
    tracker._state.budget_exceeded = True

    configs = {
        "HOST_AGENT": {
            "API_TYPE": "openai",
            "API_MODEL": "gpt-4o",
            "API_KEY": "sk-cloud-test",
            "API_BASE": "https://api.openai.com/v1",
        },
    }

    with pytest.raises(RuntimeError, match="Daily LLM budget exceeded"):
        await get_completions(
            messages=[{"role": "user", "content": "hello"}],
            agent="HOST_AGENT",
            use_backup_engine=False,
            configs=configs,
        )

    CostTracker.reset_instance()
