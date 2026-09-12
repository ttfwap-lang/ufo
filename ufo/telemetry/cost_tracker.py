"""
Token & Cost Telemetry — Real-time LLM cost tracking with daily budget enforcement.

Wraps the LLM router to intercept every API response and:
  1. Track token usage (input + output) per model per call
  2. Compute cost from the PRICES table in prices.yaml
  3. Enforce a hard daily budget — locks out Cloud APIs (Layer 2/3) when exceeded
  4. Persist daily cost logs for audit trail

The budget lockout is checked by llm_call.py BEFORE dispatching to cloud models.
Local models (Layer 1 via LiteLLM proxy) are always free and never locked out.

Config in system.yaml:
    TELEMETRY:
      ENABLED: true
      DAILY_BUDGET_USD: 50.0
      WARNING_THRESHOLD_PCT: 80
      LOG_EVERY_CALL: false
      PERSIST_PATH: "logs/telemetry"

Usage:
    
    from ufo.telemetry.cost_tracker import CostTracker

    tracker = CostTracker.get_instance()

    # After each LLM call:
        pass
    within_budget = tracker.record_usage(
        model="gpt-5.6-terra",
        api_type="openai",
        prompt_tokens=1500,
        completion_tokens=300,
    )
    if not within_budget:
        pass
        # Cloud APIs are locked — fall back to local or fail gracefully

    # Check before dispatching:
        pass
    if tracker.is_budget_exceeded():
        pass
        # Don't send to cloud, use local fallback
"""
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
logger = logging.getLogger(__name__)

class CallRecord(BaseModel):
    """Record of a single LLM API call."""
    timestamp: float = Field(default_factory=time.time)
    model: str = ''
    api_type: str = ''
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    cumulative_cost_usd: float = 0.0

class DailyBudgetState(BaseModel):
    """Current daily budget state."""
    date: str = Field(default='', description='YYYY-MM-DD')
    daily_budget_usd: float = Field(default=50.0)
    spent_today_usd: float = Field(default=0.0)
    total_tokens_in: int = Field(default=0)
    total_tokens_out: int = Field(default=0)
    total_calls: int = Field(default=0)
    budget_exceeded: bool = Field(default=False)
    warning_issued: bool = Field(default=False)

def _load_prices() -> Dict[str, Dict[str, float]]:
    """Load pricing from prices.yaml (via config loader) or return empty dict."""
    try:
        from ufo.config.config_loader import get_ufo_config
        cfg = get_ufo_config()
        prices = getattr(cfg, 'prices', None)
        if prices and isinstance(prices, dict):
            return prices
        if isinstance(cfg, dict) and 'PRICES' in cfg:
            return cfg['PRICES']
        raw = getattr(cfg, '_raw', None)
        if raw and isinstance(raw, dict):
            return raw.get('PRICES', {})
    except Exception:
        pass
    try:
        import yaml
        prices_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'ufo', 'prices.yaml')
        if os.path.exists(prices_path):
            with open(prices_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict):
                    return data.get('PRICES', {})
    except Exception:
        pass
    return {}

class CostTracker:
    """
    Thread-safe LLM cost tracker with daily budget enforcement.

    Singleton — use CostTracker.get_instance() to get the shared instance.
    """
    _instance: Optional['CostTracker'] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._state = DailyBudgetState()
        self._prices: Dict[str, Dict[str, float]] = {}
        self._enabled: bool = True
        self._warning_pct: float = 80.0
        self._log_every_call: bool = False
        self._persist_path: str = 'logs/telemetry'
        self._call_history: List[CallRecord] = []
        self._state_lock = threading.Lock()
        self._load_config()

    @classmethod
    def get_instance(cls) -> 'CostTracker':
        """Get or create the singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton (for testing)."""
        with cls._lock:
            cls._instance = None

    def _load_config(self) -> None:
        """Load telemetry config from system.yaml and prices from prices.yaml."""
        self._prices = _load_prices()
        try:
            from ufo.config.config_loader import get_ufo_config
            cfg = get_ufo_config()
            t_cfg = getattr(cfg.system, 'telemetry', None)
            if t_cfg and isinstance(t_cfg, dict):
                self._enabled = t_cfg.get('ENABLED', True)
                self._state.daily_budget_usd = float(t_cfg.get('DAILY_BUDGET_USD', 50.0))
                self._warning_pct = float(t_cfg.get('WARNING_THRESHOLD_PCT', 80.0))
                self._log_every_call = t_cfg.get('LOG_EVERY_CALL', False)
                self._persist_path = t_cfg.get('PERSIST_PATH', 'logs/telemetry')
        except Exception as e:
            logger.debug(f'Using default telemetry config: {e}')

    def record_usage(self, model: str, api_type: str, prompt_tokens: int, completion_tokens: int) -> bool:
        """
        Record a completed LLM call and check budget.

        Must be called in llm_call.py AFTER every successful API response.

        :param model: Model name (e.g., "gpt-5.6-terra").
        :param api_type: API type (e.g., "openai", "gemini").
        :param prompt_tokens: Input token count.
        :param completion_tokens: Output token count.
        :return: True if within budget, False if budget exceeded (cloud locked).
        """
        if not self._enabled:
            return True
        with self._state_lock:
            self._ensure_daily_reset()
            cost = self._compute_cost(model, api_type, prompt_tokens, completion_tokens)
            self._state.total_tokens_in += prompt_tokens
            self._state.total_tokens_out += completion_tokens
            self._state.spent_today_usd += cost
            self._state.total_calls += 1
            record = CallRecord(model=model, api_type=api_type, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, cost_usd=cost, cumulative_cost_usd=self._state.spent_today_usd)
            self._call_history.append(record)
            if self._log_every_call:
                logger.debug(f'[Telemetry] {api_type}/{model}: ${cost:.4f} (today: ${self._state.spent_today_usd:.2f}/${self._state.daily_budget_usd:.2f})')
            pct = self._state.spent_today_usd / self._state.daily_budget_usd * 100
            if pct >= self._warning_pct and (not self._state.warning_issued):
                self._state.warning_issued = True
                logger.warning(f'[Telemetry] Budget warning: {pct:.0f}% of daily budget used (${self._state.spent_today_usd:.2f}/${self._state.daily_budget_usd:.2f})')
            if self._state.spent_today_usd >= self._state.daily_budget_usd:
                if not self._state.budget_exceeded:
                    self._state.budget_exceeded = True
                    logger.critical(f'[Telemetry] DAILY BUDGET EXCEEDED: ${self._state.spent_today_usd:.2f} >= ${self._state.daily_budget_usd:.2f}. Cloud APIs LOCKED. Local models only.')
                    self._persist_daily_log()
                return False
            return True

    def is_budget_exceeded(self) -> bool:
        """Check if the daily budget has been exceeded (thread-safe)."""
        if not self._enabled:
            return False
        with self._state_lock:
            self._ensure_daily_reset()
            return self._state.budget_exceeded

    def is_cloud_allowed(self) -> bool:
        """Check if cloud API calls are currently allowed."""
        return not self.is_budget_exceeded()

    def get_state(self) -> DailyBudgetState:
        """Get a snapshot of current budget state."""
        with self._state_lock:
            self._ensure_daily_reset()
            return self._state.model_copy()

    def get_remaining_budget(self) -> float:
        """Get remaining daily budget in USD."""
        with self._state_lock:
            self._ensure_daily_reset()
            return max(0.0, self._state.daily_budget_usd - self._state.spent_today_usd)

    def get_call_count(self) -> int:
        """Get total calls made today."""
        with self._state_lock:
            self._ensure_daily_reset()
            return self._state.total_calls

    def _compute_cost(self, model: str, api_type: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Compute cost for a call using the loaded pricing table."""
        key = f'{api_type}/{model}'
        if key in self._prices:
            rates = self._prices[key]
            return prompt_tokens / 1000.0 * rates.get('input', 0.0) + completion_tokens / 1000.0 * rates.get('output', 0.0)
        key_lower = key.lower()
        for price_key, rates in self._prices.items():
            if price_key.lower() == key_lower:
                return prompt_tokens / 1000.0 * rates.get('input', 0.0) + completion_tokens / 1000.0 * rates.get('output', 0.0)
        for price_key, rates in self._prices.items():
            if model in price_key or price_key.endswith(f'/{model}'):
                return prompt_tokens / 1000.0 * rates.get('input', 0.0) + completion_tokens / 1000.0 * rates.get('output', 0.0)
        logger.debug(f'[Telemetry] No pricing for {key}. Assuming $0.00.')
        return 0.0

    def _ensure_daily_reset(self) -> None:
        """Reset counters if the date has changed."""
        today = time.strftime('%Y-%m-%d')
        if self._state.date != today:
            if self._state.date and self._state.total_calls > 0:
                self._persist_daily_log()
            self._state.date = today
            self._state.spent_today_usd = 0.0
            self._state.total_tokens_in = 0
            self._state.total_tokens_out = 0
            self._state.total_calls = 0
            self._state.budget_exceeded = False
            self._state.warning_issued = False
            self._call_history.clear()
            logger.info(f'[Telemetry] Daily reset. Budget: ${self._state.daily_budget_usd:.2f}')

    def _persist_daily_log(self) -> None:
        """Persist daily cost log to disk for audit trail."""
        try:
            os.makedirs(self._persist_path, exist_ok=True)
            log_file = os.path.join(self._persist_path, f'cost_{self._state.date}.json')
            log_data = {'date': self._state.date, 'daily_budget_usd': self._state.daily_budget_usd, 'spent_today_usd': self._state.spent_today_usd, 'total_tokens_in': self._state.total_tokens_in, 'total_tokens_out': self._state.total_tokens_out, 'total_calls': self._state.total_calls, 'budget_exceeded': self._state.budget_exceeded, 'calls': [r.model_dump() for r in self._call_history[-100:]]}
            with open(log_file, 'w', encoding='utf-8') as f:
                json.dump(log_data, f, indent=2)
            logger.info(f'[Telemetry] Daily log persisted: {log_file}')
        except Exception as e:
            logger.warning(f'[Telemetry] Failed to persist daily log: {e}')
