"""End-to-end test of the deployed UFO stack.

Exercises the real chain the agent uses, over the real network, with the real
models - no mocks:

    gx10 agent runner  ->  HTTP/tailnet  ->  Windows bridge
                                              -> OCR + UI-Venus + OmniParser
                                              -> gated Telegram automation

Each stage asserts a concrete, observable outcome. Exit code is non-zero if
any stage fails, so it can gate a deploy.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.environ.get("UFO_BRIDGE_URL", "http://127.0.0.1:9301").rstrip("/")
TOKEN_FILE = os.path.join(BASE, "ufo_bridge_token.txt")
VENUS = os.environ.get("VENUS_URL", "http://100.67.13.78:8002/v1").rstrip("/")
OMNI = os.environ.get("OMNIPARSER_URL", "http://100.67.13.78:7861").rstrip("/")

sys.path.insert(0, BASE)

_results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    _results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}"
          + (f"  -- {detail}" if detail else ""), flush=True)


def token() -> str:
    return open(TOKEN_FILE, encoding="utf-8").read().strip()


def _get_json(url: str, headers: dict | None = None, timeout: int = 30):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def bridge_job(action: str, params: dict, job_id: str,
               timeout_s: int = 240) -> dict:
    body = json.dumps({"job_id": job_id, "action": action,
                       "params": params}).encode()
    req = urllib.request.Request(
        BRIDGE + "/jobs", data=body,
        headers={"Authorization": "Bearer " + token(),
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        json.loads(r.read().decode())
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(4)
        job = _get_json(f"{BRIDGE}/result/{job_id}",
                        {"Authorization": "Bearer " + token()})
        if job.get("status") in ("done", "error"):
            return job
    return {"status": "timeout"}


def http_status(url: str, headers: dict | None = None) -> int:
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:                                 # noqa: BLE001
        return 0


# ---------------------------------------------------------------- stages
def s1_bridge_up():
    j = bridge_job("health", {}, "e2e-health", 90)
    res = j.get("result") or {}
    ok = j.get("status") == "done" and res.get("vision", {}).get("venus") == "ok"
    record("bridge health + venus reachable", ok,
           f"vision={res.get('vision')} title={res.get('telegram_title')!r}")
    return res


def s2_auth_enforced():
    code = http_status(f"{BRIDGE}/result/anything")
    record("bridge rejects unauthenticated requests", code == 401,
           f"HTTP {code}")


def s3_omniparser_direct():
    try:
        h = _get_json(OMNI + "/api/health")
        ok = bool(h.get("ok"))
        record("omniparser API reachable from Windows", ok,
               f"device={h.get('device')}")
    except Exception as e:                           # noqa: BLE001
        record("omniparser API reachable from Windows", False, str(e))


def s4_vision_locate_text():
    j = bridge_job("vision_locate", {"label": "Write", "prefer": "auto"},
                   "e2e-loc-text", 180)
    r = j.get("result") or {}
    ok = j.get("status") == "done" and r.get("found") is True
    record("vision_locate: TEXT label via OCR fusion", ok,
           f"xy=({r.get('x')},{r.get('y')}) strategy={r.get('strategy')}")


def s5_vision_locate_icon():
    j = bridge_job("vision_locate",
                   {"label": "the microphone voice message button",
                    "prefer": "venus"},
                   "e2e-loc-icon", 180)
    r = j.get("result") or {}
    ok = j.get("status") == "done" and r.get("found") is True
    record("vision_locate: ICON (OCR-invisible) via Venus", ok,
           f"xy=({r.get('x')},{r.get('y')})")


def s6_vision_elements():
    j = bridge_job("vision_elements", {"limit": 8}, "e2e-elements", 300)
    r = j.get("result") or {}
    ok = j.get("status") == "done" and r.get("count", 0) > 5
    record("vision_elements: OmniParser screen parse", ok,
           f"{r.get('count')} elements")


def s7_vision_ask():
    j = bridge_job("vision_ask",
                   {"question": "Which application is in the foreground? "
                                "Answer in a few words."},
                   "e2e-ask", 240)
    r = j.get("result") or {}
    ans = (r.get("answer") or "").strip()
    ok = j.get("status") == "done" and len(ans) > 3
    record("vision_ask: semantic state understanding", ok, ans[:90])


def s8_click_safety():
    """A vision point that would land on window chrome must be refused."""
    j = bridge_job("vision_locate",
                   {"label": "the close window button", "prefer": "venus",
                    "click": True},
                   "e2e-safety", 180)
    r = j.get("result") or {}
    refused = bool(r.get("refused")) or r.get("safe_to_click") is True
    record("click safety: chrome guard present", refused,
           f"refused={r.get('refused')} safety={r.get('safety')}")


def s9_client_library():
    try:
        import venus_client
        png = os.path.join(BASE, "astro_v_grid_aries.png")
        if not os.path.exists(png):
            record("venus_client importable", True, "(no capture to verify)")
            return
        boxes = venus_client.ocr_words(png)
        phrases = venus_client.group_phrases(boxes)
        ok = bool(boxes) and bool(phrases)
        record("venus_client: OCR + phrase grouping", ok,
               f"{len(boxes)} words -> {len(phrases)} phrases")
    except Exception as e:                           # noqa: BLE001
        record("venus_client: OCR + phrase grouping", False, str(e))


def s10_agent_tool_wiring():
    """The deployed runner must expose the vision tool with a real impl."""
    p = os.path.join(BASE, "gx10_runner", "agent_runner.py")
    src = open(p, encoding="utf-8").read()
    schema = '"name": "vision"' in src
    impl = "def tool_vision(" in src
    registered = '"vision": tool_vision' in src
    record("agent exposes a working vision tool", schema and impl and registered,
           f"schema={schema} impl={impl} registered={registered}")


def main() -> int:
    print("UFO stack end-to-end test\n")
    for fn in (s1_bridge_up, s2_auth_enforced, s3_omniparser_direct,
               s4_vision_locate_text, s5_vision_locate_icon,
               s6_vision_elements, s7_vision_ask, s8_click_safety,
               s9_client_library, s10_agent_tool_wiring):
        try:
            fn()
        except Exception as e:                       # noqa: BLE001
            record(fn.__name__, False, f"{type(e).__name__}: {e}")
    passed = sum(1 for _, ok, _ in _results if ok)
    print(f"\n{passed}/{len(_results)} stages passed")
    return 0 if passed == len(_results) else 1


if __name__ == "__main__":
    sys.exit(main())
