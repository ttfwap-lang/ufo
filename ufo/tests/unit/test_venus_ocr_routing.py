"""venus_client.ocr_words is THE OCR entry point: service first, PowerShell last.

The bridge, astro_collect and venus_client each used to spawn `powershell
ocr_shot.ps1` per call (0.65-0.74 s). They now share one path that asks the
resident WinRT service (~0.15 s) and only falls back to PowerShell if it cannot.
These tests pin the routing rules that make that safe.
"""
import json
import time

import pytest

from ufo import venus_client as v


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    v.clear_caches()
    monkeypatch.setattr(v, "_ocr_service_down_until", 0.0)
    png = tmp_path / "s.png"
    png.write_bytes(b"\x89PNG fake")
    return png


class _Resp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _service_returns(monkeypatch, words):
    import urllib.request as ur

    calls = []

    def fake(req, timeout=None):
        calls.append(req.full_url)
        return _Resp({"words": words})

    monkeypatch.setattr(ur, "urlopen", fake)
    return calls


def _no_powershell(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("PowerShell must not run when the service answered")

    monkeypatch.setattr(v.subprocess, "run", boom)


def test_service_answer_is_used_and_powershell_is_not_spawned(_clean, monkeypatch):
    calls = _service_returns(monkeypatch, [[10, 20, 30, 12, "Hello"]])
    _no_powershell(monkeypatch)
    assert v.ocr_words(str(_clean)) == [(10, 20, 30, 12, "Hello")]
    assert calls and calls[0].endswith("/api/ocr")


def test_quote_wrapping_is_normalised_like_the_powershell_path(_clean, monkeypatch):
    _service_returns(monkeypatch, [[1, 2, 3, 4, "'quoted'"]])
    assert v.ocr_words(str(_clean))[0][4] == "quoted"


def test_falls_back_to_powershell_when_the_service_is_down(_clean, monkeypatch):
    import urllib.request as ur

    def refuse(req, timeout=None):
        raise ConnectionRefusedError

    monkeypatch.setattr(ur, "urlopen", refuse)

    class P:
        stdout = b"WORD [  5,   6   7x   8] Fallback\n"

    monkeypatch.setattr(v.subprocess, "run", lambda *a, **k: P())
    assert v.ocr_words(str(_clean)) == [(5, 6, 7, 8, "Fallback")]


def test_dead_service_is_skipped_for_a_while_not_retried_every_call(_clean, monkeypatch):
    import urllib.request as ur

    attempts = []

    def refuse(req, timeout=None):
        attempts.append(1)
        raise ConnectionRefusedError

    monkeypatch.setattr(ur, "urlopen", refuse)

    class P:
        stdout = b"WORD [  1,   1   1x   1] a\n"

    monkeypatch.setattr(v.subprocess, "run", lambda *a, **k: P())
    v.ocr_words(str(_clean))
    v.clear_caches()
    v.ocr_words(str(_clean))
    assert len(attempts) == 1  # second call did not touch the dead service


def test_empty_result_is_not_cached_so_a_retry_really_reruns_ocr(_clean, monkeypatch):
    calls = _service_returns(monkeypatch, [])
    assert v.ocr_words(str(_clean)) == []
    assert v.ocr_words(str(_clean)) == []
    assert len(calls) == 2  # asked twice: the empty answer was not memoised


def test_non_empty_result_is_cached_per_file_version(_clean, monkeypatch):
    calls = _service_returns(monkeypatch, [[1, 1, 1, 1, "x"]])
    v.ocr_words(str(_clean))
    v.ocr_words(str(_clean))
    assert len(calls) == 1
    time.sleep(0.01)
    _clean.write_bytes(b"\x89PNG changed bytes")  # new mtime/size -> new key
    v.ocr_words(str(_clean))
    assert len(calls) == 2
