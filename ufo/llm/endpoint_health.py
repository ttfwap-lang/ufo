"""
Endpoint-level health, admission control and model-name discovery for local
model servers (the gx10 behind its SSH tunnel, LiteLLM, llama-server, ...).

Why this exists
---------------
The gx10 is one shared box. When it is starved (unified memory oversubscribed,
sshd not answering) it does not refuse connections, it *hangs*. Every layer
above then multiplied the damage:

  * timeouts were retried 5x at 120 s each (~10 min per call);
  * the fallback agent (BACKUP_AGENT) points at the very same endpoint, so the
    whole ladder ran twice (~21 min for one LLM call);
  * the circuit breaker is per *agent type*, so HOST, APP, EVALUATION... each
    had to rediscover the same dead box separately;
  * every process queued into the server's 1-8 decode slots, so requests timed
    out in the *server's* queue and were then retried, adding more load.

This module fixes that with three small, dependency-free pieces:

  EndpointGate      breaker keyed by host:port, shared by every agent in the
                    process. Opens after a failed liveness probe (or repeated
                    failures) and then fails calls *instantly* with EndpointDown.
  inflight_limiter  process-wide cap on concurrent requests per endpoint, so
                    load queues on the client instead of timing out server-side.
  discover_model    asks /v1/models what the server actually serves, so a stale
                    API_MODEL (llama.cpp name vs vLLM served-model-name) heals
                    instead of failing every request with 404.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class EndpointDown(RuntimeError):
    """A model endpoint is known to be unresponsive; the call was not attempted.

    Deliberately NOT retryable: retrying is exactly what makes a hung box worse.
    The message avoids the words 'timeout' / 'overload' / 'capacity' so that the
    text-matching in llm_call._is_retryable_error can never misclassify it.
    """

    def __init__(self, key: str, detail: str, retry_in: float) -> None:
        self.key = key
        self.retry_in = max(0.0, retry_in)
        super().__init__(
            f"model endpoint {key} is unresponsive ({detail}); "
            f"calls are refused for another {self.retry_in:.0f}s instead of hanging"
        )


def endpoint_key(api_base: Optional[str]) -> Optional[str]:
    """Normalise an api_base to 'host:port' (localhost aliases collapse together)."""
    if not api_base or not isinstance(api_base, str):
        return None
    parsed = urllib.parse.urlparse(api_base if "://" in api_base else f"http://{api_base}")
    host = (parsed.hostname or "").lower()
    if not host:
        return None
    if host in ("localhost", "0.0.0.0", "::1"):
        host = "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return f"{host}:{port}"


def is_timeout_error(error: Optional[BaseException]) -> bool:
    if error is None:
        return False
    names = {c.__name__ for c in type(error).__mro__}
    return bool(names & {"APITimeoutError", "TimeoutException", "TimeoutError", "ReadTimeout", "ConnectTimeout"})


def is_endpoint_failure(error: BaseException) -> bool:
    """True for failures that say 'the server is not answering' rather than
    'this request was bad' (4xx, schema, refusal...)."""
    if isinstance(error, EndpointDown):
        return False
    names = {c.__name__ for c in type(error).__mro__}
    if names & {"APITimeoutError", "APIConnectionError", "InternalServerError", "ConnectError",
                "ReadError", "RemoteProtocolError", "ConnectionError", "TimeoutError",
                "TimeoutException", "ReadTimeout", "ConnectTimeout"}:
        return True
    status = getattr(error, "status_code", None)
    return status in (500, 502, 503, 504)


def _label(error: BaseException | str) -> str:
    """Short human label for a failure. Never the raw class name: 'APITimeoutError'
    would put the word 'timeout' into a message that text-matching retry rules
    scan for."""
    if isinstance(error, str):
        return error
    if is_timeout_error(error):
        return "no reply"
    names = {c.__name__ for c in type(error).__mro__}
    if names & {"APIConnectionError", "ConnectError", "ConnectionError", "RemoteProtocolError", "ReadError"}:
        return "connection failed"
    return "server error"


@dataclass
class _EndpointState:
    failures: int = 0
    opened_at: float = 0.0
    cooldown: float = 0.0
    trips: int = 0
    last_error: str = ""
    half_open_ticket: bool = False


class EndpointGate:
    """Breaker keyed by endpoint. Thread-safe; cheap enough to call per attempt."""

    def __init__(
        self,
        threshold: int = 3,
        base_cooldown: float = 15.0,
        max_cooldown: float = 120.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.threshold = threshold
        self.base_cooldown = base_cooldown
        self.max_cooldown = max_cooldown
        self._clock = clock
        self._lock = threading.Lock()
        self._states: Dict[str, _EndpointState] = {}

    def check(self, key: str) -> None:
        """Raise EndpointDown if the endpoint is open. After the cooldown exactly
        one caller is let through as the half-open probe; the rest keep failing
        fast until that probe reports back."""
        with self._lock:
            st = self._states.get(key)
            if st is None or st.cooldown == 0.0:
                return
            remaining = st.cooldown - (self._clock() - st.opened_at)
            if remaining > 0:
                raise EndpointDown(key, st.last_error or "recent failures", remaining)
            if st.half_open_ticket:
                raise EndpointDown(key, "recovery probe in flight", 1.0)
            st.half_open_ticket = True

    def record_success(self, key: str) -> None:
        with self._lock:
            st = self._states.get(key)
            if st is None:
                return
            if st.cooldown:
                logger.info("Endpoint %s recovered after %d trip(s).", key, st.trips)
            self._states[key] = _EndpointState()

    def record_failure(self, key: str, error: BaseException | str, hard: bool = False) -> bool:
        """Count a failure. `hard` (liveness probe failed) opens immediately.
        Returns True if the gate is now open."""
        with self._lock:
            st = self._states.setdefault(key, _EndpointState())
            st.failures += 1
            st.last_error = _label(error)
            st.half_open_ticket = False
            if hard or st.failures >= self.threshold or st.cooldown:
                st.cooldown = min(self.base_cooldown * (2 ** st.trips), self.max_cooldown)
                st.trips += 1
                st.opened_at = self._clock()
                logger.warning(
                    "Endpoint %s marked unresponsive (%s); failing fast for %.0fs.",
                    key, st.last_error, st.cooldown,
                )
                return True
            return False

    def open_error(self, key: str) -> Optional[EndpointDown]:
        """An EndpointDown describing the current open state, or None if closed."""
        with self._lock:
            st = self._states.get(key)
            if not st or not st.cooldown:
                return None
            remaining = st.cooldown - (self._clock() - st.opened_at)
            if remaining <= 0:
                return None
            return EndpointDown(key, st.last_error or "recent failures", remaining)

    def is_open(self, key: str) -> bool:
        with self._lock:
            st = self._states.get(key)
            return bool(st and st.cooldown and (self._clock() - st.opened_at) < st.cooldown)

    def reset(self) -> None:
        with self._lock:
            self._states.clear()


ENDPOINT_GATE = EndpointGate()

# How long the liveness probe waits before declaring the server hung. A healthy
# server (even a busy vLLM) answers GET /models in milliseconds.
PROBE_TIMEOUT = 3.0


# --------------------------------------------------------------------------- probe

def probe_sync(api_base: str, timeout: float = 3.0, api_key: Optional[str] = None) -> bool:
    """Is the server answering at all? Any HTTP response counts (401/404 too);
    only a connection error or no reply within `timeout` means down. Sync so it
    can run in a worker thread without needing an event loop."""
    url = api_base.rstrip("/") + "/models"
    req = urllib.request.Request(url, method="GET")
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


# ------------------------------------------------------------- admission control

_limiters: Dict[str, threading.BoundedSemaphore] = {}
_limiters_lock = threading.Lock()


def max_inflight() -> int:
    try:
        return max(1, int(os.environ.get("UFO_LLM_MAX_INFLIGHT", "4")))
    except ValueError:
        return 4


def inflight_limiter(api_base: Optional[str]) -> Optional[threading.BoundedSemaphore]:
    """One semaphore per local endpoint. Returns None for cloud endpoints, which
    have their own rate limiting and no shared decode slots to protect."""
    from ufo.llm.endpoint import is_local_endpoint

    key = endpoint_key(api_base)
    if not key or not is_local_endpoint(api_base=api_base):
        return None
    with _limiters_lock:
        sem = _limiters.get(key)
        if sem is None:
            sem = _limiters[key] = threading.BoundedSemaphore(max_inflight())
        return sem


# ------------------------------------------------------------ model discovery

_ALIAS_LOCK = threading.Lock()
_ALIASES: Dict[tuple, str] = {}
_LISTINGS: Dict[str, tuple] = {}  # key -> (expires_at, [ids])
_LISTING_TTL_OK = 60.0
_LISTING_TTL_FAIL = 10.0


def list_models(api_base: str, api_key: Optional[str] = None, timeout: float = 3.0) -> List[str]:
    """Model ids the server reports on /models. Cached briefly, never raises."""
    key = endpoint_key(api_base) or api_base
    now = time.monotonic()
    with _ALIAS_LOCK:
        cached = _LISTINGS.get(key)
        if cached and cached[0] > now:
            return list(cached[1])
    ids: List[str] = []
    try:
        req = urllib.request.Request(api_base.rstrip("/") + "/models", method="GET")
        if api_key:
            req.add_header("Authorization", f"Bearer {api_key}")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload: Any = json.loads(resp.read().decode("utf-8", "replace"))
        ids = [str(m["id"]) for m in payload.get("data", []) if isinstance(m, dict) and "id" in m]
    except Exception as exc:
        logger.debug("model listing for %s failed: %s", key, exc)
    with _ALIAS_LOCK:
        _LISTINGS[key] = (now + (_LISTING_TTL_OK if ids else _LISTING_TTL_FAIL), ids)
    return ids


def discover_model(api_base: str, configured: str, api_key: Optional[str] = None) -> Optional[str]:
    """The name to use instead of `configured`, or None if `configured` is right
    or the answer is ambiguous. Only unambiguous corrections are made: the server
    serves exactly one model, or matches `configured` case-insensitively."""
    ids = list_models(api_base, api_key)
    if not ids or configured in ids:
        return None
    lowered = {i.lower(): i for i in ids}
    if configured.lower() in lowered:
        return lowered[configured.lower()]
    if len(ids) == 1:
        return ids[0]
    return None


def remember_alias(api_base: str, configured: str, served: str) -> None:
    with _ALIAS_LOCK:
        _ALIASES[(endpoint_key(api_base), configured)] = served


def resolve_alias(api_base: str, configured: str) -> str:
    """Cheap dict lookup used at service construction (no network)."""
    with _ALIAS_LOCK:
        return _ALIASES.get((endpoint_key(api_base), configured), configured)


def reset_caches() -> None:
    """For tests."""
    ENDPOINT_GATE.reset()
    with _ALIAS_LOCK:
        _ALIASES.clear()
        _LISTINGS.clear()
    with _limiters_lock:
        _limiters.clear()
