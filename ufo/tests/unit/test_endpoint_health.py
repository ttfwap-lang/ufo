"""Behaviour of the shared-gx10 protections (ufo.llm.endpoint_health + llm_call).

The failure being guarded: a starved gx10 does not refuse connections, it hangs.
One LLM call used to sit through 5 attempts x 120 s, then the BACKUP agent (same
host:port) did it all again. These tests run the real OpenAI client and the real
get_completions() against small in-process HTTP servers that hang, 404 or answer
slowly, so the numbers asserted here are wall-clock reality, not mocks.
"""
import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from ufo.llm import AgentType, endpoint_health
from ufo.llm.endpoint_health import ENDPOINT_GATE, EndpointDown, EndpointGate


# ------------------------------------------------------------------ pure gate

class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_endpoint_key_collapses_local_aliases():
    k = endpoint_health.endpoint_key
    assert k("http://127.0.0.1:8000/v1") == "127.0.0.1:8000"
    assert k("http://localhost:8000/v1") == "127.0.0.1:8000"
    assert k("http://0.0.0.0:8000") == "127.0.0.1:8000"
    assert k("https://api.example.com/v1") == "api.example.com:443"
    assert k(None) is None and k("") is None


def test_gate_opens_after_threshold_and_recovers():
    clock = FakeClock()
    gate = EndpointGate(threshold=3, base_cooldown=10, max_cooldown=100, clock=clock)
    gate.check("a:1")                      # unknown endpoint: open for business
    assert not gate.record_failure("a:1", "e")
    assert not gate.record_failure("a:1", "e")
    assert gate.record_failure("a:1", "e")  # third consecutive failure trips it
    with pytest.raises(EndpointDown) as exc:
        gate.check("a:1")
    assert 0 < exc.value.retry_in <= 10
    clock.t += 11
    gate.check("a:1")                      # cooldown over: ONE probe is let through
    with pytest.raises(EndpointDown):
        gate.check("a:1")                  # ...everyone else still fails fast
    gate.record_success("a:1")
    gate.check("a:1")                      # closed again, counters reset
    assert not gate.record_failure("a:1", "e")


def test_hard_failure_opens_immediately_and_backoff_grows():
    clock = FakeClock()
    gate = EndpointGate(threshold=3, base_cooldown=10, max_cooldown=25, clock=clock)
    assert gate.record_failure("a:1", "hung", hard=True)
    assert 9 < gate.open_error("a:1").retry_in <= 10
    clock.t += 11
    gate.check("a:1")                      # half-open probe...
    assert gate.record_failure("a:1", "hung", hard=True)  # ...fails again
    assert 19 < gate.open_error("a:1").retry_in <= 20      # cooldown doubled
    clock.t += 21
    gate.check("a:1")
    gate.record_failure("a:1", "hung", hard=True)
    assert gate.open_error("a:1").retry_in <= 25            # capped


def test_endpoint_down_is_never_retryable_and_never_matches_text_rules():
    from ufo.llm.llm_call import _is_retryable_error

    class APITimeoutError(Exception):       # same class name the openai SDK raises
        pass

    gate = EndpointGate()
    gate.record_failure("127.0.0.1:8000", APITimeoutError("Request timed out."), hard=True)
    err = gate.open_error("127.0.0.1:8000")
    assert _is_retryable_error(err) is False
    text = str(err).lower()
    for word in ("timeout", "timed out", "overload", "capacity", "service unavailable"):
        assert word not in text


# --------------------------------------------------------------- fake server

class FakeModelServer:
    """OpenAI-compatible stub. Modes: ok | hang | slow_chat | wrong_model_404."""

    def __init__(self, mode="ok", served="served-model", chat_delay=0.0):
        self.mode, self.served, self.chat_delay = mode, served, chat_delay
        self.chat_posts = 0
        self.model_gets = 0
        self.not_found = 0
        self.inflight = 0
        self.max_inflight = 0
        self.lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _send(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                with outer.lock:
                    outer.model_gets += 1
                if outer.mode == "hang":
                    time.sleep(30)
                    return
                self._send(200, {"object": "list", "data": [{"id": outer.served, "object": "model"}]})

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(length) or b"{}")
                with outer.lock:
                    outer.chat_posts += 1
                    outer.inflight += 1
                    outer.max_inflight = max(outer.max_inflight, outer.inflight)
                try:
                    if outer.mode == "hang":
                        time.sleep(30)
                        return
                    if outer.mode == "wrong_model_404" and req.get("model") != outer.served:
                        with outer.lock:
                            outer.not_found += 1
                        self._send(404, {"error": {"message": f"The model `{req.get('model')}` does not exist.",
                                                   "type": "NotFoundError", "code": 404}})
                        return
                    if outer.chat_delay:
                        time.sleep(outer.chat_delay)
                    if outer.mode == "slow_chat":
                        time.sleep(30)
                        return
                    self._send(200, {
                        "id": "x", "object": "chat.completion", "created": 0, "model": req.get("model", ""),
                        "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"},
                                     "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                    })
                finally:
                    with outer.lock:
                        outer.inflight -= 1

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def stack(monkeypatch):
    """Patch config lookup + side effects so get_completions() runs for real
    against a fake server, and clean every cache between tests."""
    import ufo.llm.base as base
    import ufo.llm.llm_call as llm_call
    from ufo.llm.openai import BaseOpenAIService

    endpoint_health.reset_caches()
    llm_call._circuit_breaker.reset()
    BaseOpenAIService.get_openai_client.cache_clear()
    monkeypatch.setattr(endpoint_health, "PROBE_TIMEOUT", 0.5)
    monkeypatch.setattr(llm_call, "record_dlq_event", lambda **kw: None)

    import ufo.telemetry.cost_tracker as ct
    monkeypatch.setattr(ct.CostTracker, "get_instance",
                        classmethod(lambda cls: SimpleNamespace(record_usage=lambda **k: None,
                                                                is_budget_exceeded=lambda: False)))
    servers = []

    def build(server, timeout=1, model="wrong-name"):
        cfg = {"API_TYPE": "openai", "API_BASE": server.base, "API_KEY": "sk-local",
               "API_MODEL": model, "REASONING_MODEL": False, "VISUAL_MODE": False,
               "REFUSAL_ROTATION": False}
        agents = {a.value: dict(cfg) for a in (AgentType.HOST, AgentType.APP, AgentType.BACKUP)}
        system = SimpleNamespace(MAX_RETRY=3, TIMEOUT=timeout, PRICES={}, TEMPERATURE=0.0,
                                 TOP_P=0.0, MAX_TOKENS=50)
        monkeypatch.setattr(base, "get_agent_config", lambda a: agents[getattr(a, "value", a)])
        monkeypatch.setattr(llm_call, "get_agent_config", lambda a: agents[getattr(a, "value", a)])
        monkeypatch.setattr(base, "get_ufo_config", lambda: SimpleNamespace(system=system))
        monkeypatch.setattr(llm_call._circuit_breaker, "_lazy_init", lambda: None)
        return agents

    def make_server(**kw):
        s = FakeModelServer(**kw)
        servers.append(s)
        return s

    yield SimpleNamespace(build=build, server=make_server, llm_call=llm_call)
    for s in servers:
        s.close()
    endpoint_health.reset_caches()
    BaseOpenAIService.get_openai_client.cache_clear()


MSGS = [{"role": "user", "content": "ping"}]


# ------------------------------------------------------------------- e2e

def test_hung_server_fails_once_then_instantly_and_backup_is_not_tried(stack):
    """Hung box + BACKUP on the same host:port. Before: ~21 min for one call.
    Now: one client timeout, then every further call (any agent) is instant."""
    srv = stack.server(mode="hang")
    stack.build(srv, timeout=1)

    t0 = time.monotonic()
    with pytest.raises(EndpointDown):
        asyncio.run(stack.llm_call.get_completions(MSGS, agent=AgentType.HOST))
    first = time.monotonic() - t0
    assert first < 5.0, f"first failure took {first:.1f}s"
    assert srv.chat_posts == 1, "BACKUP (same endpoint) or a retry hit the hung box"

    t0 = time.monotonic()
    for agent in (AgentType.HOST, AgentType.APP, AgentType.BACKUP):   # other agents too
        with pytest.raises(EndpointDown):
            asyncio.run(stack.llm_call.get_completions(MSGS, agent=agent))
    assert time.monotonic() - t0 < 0.5
    assert srv.chat_posts == 1


def test_slow_but_alive_server_is_not_retried_five_times(stack):
    """Server answers /models but chat exceeds the timeout (overloaded, not dead):
    a timeout gets one retry, not four, so we do not pile load onto it."""
    srv = stack.server(mode="slow_chat")
    stack.build(srv, timeout=1)
    with pytest.raises(Exception):
        asyncio.run(stack.llm_call.get_completions(MSGS, agent=AgentType.HOST, use_backup_engine=False))
    assert srv.chat_posts == 2


def test_stale_model_name_heals_from_v1_models(stack):
    srv = stack.server(mode="wrong_model_404", served="qwen-abliterated")
    stack.build(srv, model="qwen38-27b-turbo")
    result = asyncio.run(stack.llm_call.get_completions(MSGS, agent=AgentType.HOST, use_backup_engine=False))
    assert result.responses == ["hi"]
    assert srv.not_found == 1
    # remembered: the next call (fresh service) goes straight to the served name
    result = asyncio.run(stack.llm_call.get_completions(MSGS, agent=AgentType.APP, use_backup_engine=False))
    assert result.responses == ["hi"]
    assert srv.not_found == 1


def test_discovery_is_conservative(stack):
    srv = stack.server(mode="ok", served="only-model")
    assert endpoint_health.discover_model(srv.base, "configured-but-wrong") == "only-model"
    endpoint_health.reset_caches()
    assert endpoint_health.discover_model(srv.base, "only-model") is None       # already right
    endpoint_health.reset_caches()
    assert endpoint_health.discover_model(srv.base, "ONLY-MODEL") == "only-model"  # case only
    endpoint_health.reset_caches()
    srv.served = "x"
    dead = endpoint_health.discover_model("http://127.0.0.1:1/v1", "anything")
    assert dead is None                                                          # dead port: never guesses


def test_inflight_cap_queues_on_the_client_not_the_server(stack, monkeypatch):
    monkeypatch.setenv("UFO_LLM_MAX_INFLIGHT", "2")
    endpoint_health.reset_caches()
    srv = stack.server(mode="ok", served="wrong-name", chat_delay=0.25)
    stack.build(srv, timeout=20)

    async def burst():
        return await asyncio.gather(*[
            stack.llm_call.get_completions(MSGS, agent=AgentType.HOST, use_backup_engine=False)
            for _ in range(8)])

    results = asyncio.run(burst())
    assert all(r.responses == ["hi"] for r in results)
    assert srv.chat_posts == 8
    assert srv.max_inflight <= 2, f"server saw {srv.max_inflight} concurrent requests"


def test_gate_only_applies_to_local_endpoints():
    """Cloud endpoints keep their own rate-limit handling and get no limiter."""
    assert endpoint_health.inflight_limiter("https://api.anthropic.com/v1") is None
    assert endpoint_health.inflight_limiter("http://127.0.0.1:8000/v1") is not None
