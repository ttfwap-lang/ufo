"""Guards on the startup auto-fallback in ufo.__main__.

Regression cover for a live run in which all 13 showcase tasks failed: a single
5s probe of a busy Ollama declared the local LLM dead, and the process then
switched to the cloud profile whose ANTHROPIC_API_KEY was unset, so every
request failed with 'unresolved environment variable'.
"""
import asyncio
import logging

import pytest

from ufo import __main__ as ufo_main


_real_sleep = asyncio.sleep


async def _no_delay(*_args, **_kwargs):
    """Skip the retry backoff without recursing into the patched asyncio.sleep."""
    await _real_sleep(0)


class _Recorder(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def text(self):
        return "\n".join(r.getMessage() for r in self.records)


@pytest.fixture
def logger_with_capture():
    logger = logging.getLogger("test_llm_fallback_guard")
    logger.setLevel(logging.DEBUG)
    logger.handlers = []
    rec = _Recorder()
    logger.addHandler(rec)
    return logger, rec


@pytest.fixture
def local_profile(monkeypatch):
    """A local ollama profile, so the probe path is actually exercised."""
    monkeypatch.setattr(
        ufo_main, "_probe_health_sync", lambda url, timeout: False, raising=False
    )
    import ufo.llm.config_helper as ch

    profile = {
        "HOST_AGENT": {
            "API_TYPE": "ollama",
            "API_BASE": "http://127.0.0.1:11434",
            "API_KEY": "",
        }
    }
    monkeypatch.setattr(
        ch, "resolve_backend_profile", lambda *a, **k: profile, raising=False
    )
    return profile


def test_no_failover_to_profile_with_unresolved_api_key(
    monkeypatch, logger_with_capture, local_profile
):
    logger, rec = logger_with_capture
    switched = []
    import ufo.llm.config_helper as ch

    monkeypatch.setattr(
        ch, "set_process_override", lambda sel: switched.append(sel) or True
    )
    monkeypatch.setattr(
        ufo_main, "_profile_unresolved_vars", lambda sel: {"ANTHROPIC_API_KEY"}
    )
    monkeypatch.setattr(asyncio, "sleep", _no_delay)

    asyncio.run(ufo_main._ensure_llm_reachable(logger))

    assert switched == [], "must not switch to a profile whose API key is unresolved"
    assert "ANTHROPIC_API_KEY" in rec.text()


def test_probe_retries_before_declaring_unreachable(
    monkeypatch, logger_with_capture, local_profile
):
    """Ollama reloading a model answers late; the first miss must not be fatal."""
    logger, rec = logger_with_capture
    calls = []

    def probe(url, timeout):
        calls.append(timeout)
        return len(calls) >= 3  # healthy on the third try

    monkeypatch.setattr(ufo_main, "_probe_health_sync", probe)
    monkeypatch.setattr(asyncio, "sleep", _no_delay)
    switched = []
    import ufo.llm.config_helper as ch

    monkeypatch.setattr(
        ch, "set_process_override", lambda sel: switched.append(sel) or True
    )

    asyncio.run(ufo_main._ensure_llm_reachable(logger))

    assert len(calls) == 3
    assert all(t >= 10.0 for t in calls), f"probe timeout too short: {calls}"
    assert switched == [], "a backend that answers on retry is not unreachable"


def test_cloud_profile_unresolved_vars_detected():
    """The real cloud profile has no keys set here, so it is not a safe target."""
    assert "ANTHROPIC_API_KEY" in ufo_main._profile_unresolved_vars("cloud")


def test_dgx_profile_is_usable():
    assert ufo_main._profile_unresolved_vars("dgx") == set()
