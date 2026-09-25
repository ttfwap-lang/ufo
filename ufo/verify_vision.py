"""Verify the vision path, waiting patiently for the model to be up.

Context: another agent is actively redeploying gx10's `full` model stack, which
restarts Venus every few minutes. A Venus load takes 5-6 minutes, so it is down
most of the time and any immediate test fails for reasons that have nothing to
do with the code under test. This waits for a genuine ready window and then
exercises the vision path once, so the result is meaningful either way.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = "http://127.0.0.1:9301"
VENUS = "http://100.67.13.78:18002/v1/models"
OMNI = "http://100.67.13.78:18061/api/health"
sys.path.insert(0, BASE)

WAIT_S = int(os.environ.get("UFO_VISION_WAIT", "900"))


def code(url: str, t: int = 8) -> int:
    try:
        with urllib.request.urlopen(url, timeout=t) as r:
            return r.status
    except Exception:
        return 0


def token() -> str:
    return open(os.path.join(BASE, "ufo_bridge_token.txt"), encoding="utf-8").read().strip()


def job(action: str, params: dict, jid: str, timeout_s: int = 300) -> dict:
    h = {"Authorization": "Bearer " + token(), "Content-Type": "application/json"}
    body = json.dumps({"job_id": jid, "action": action, "params": params}).encode()
    urllib.request.urlopen(
        urllib.request.Request(BRIDGE + "/jobs", data=body, headers=h), timeout=30).read()
    end = time.time() + timeout_s
    while time.time() < end:
        time.sleep(4)
        d = json.loads(urllib.request.urlopen(
            urllib.request.Request(f"{BRIDGE}/result/{jid}", headers=h), timeout=30).read())
        if d.get("status") in ("done", "error"):
            return d
    return {"status": "timeout"}


def main() -> int:
    print(f"Waiting up to {WAIT_S}s for a Venus ready window "
          f"(another agent is cycling the model stack)...\n")
    t0 = time.time()
    ready_at = None
    while time.time() - t0 < WAIT_S:
        c = code(VENUS)
        if c == 200:
            ready_at = time.time() - t0
            print(f"  Venus READY after {ready_at:.0f}s - running the vision stages now")
            break
        print(f"  t+{time.time()-t0:5.0f}s  venus HTTP {c}", flush=True)
        time.sleep(20)

    if ready_at is None:
        print("\nRESULT: Venus never became available in the window.")
        print("This is an availability problem on gx10, not a code failure.")
        print("The watchdog log will show whether the model is loading, "
              "being restarted, or hitting a memory abort.")
        return 2

    print(f"\nOmniParser: {code(OMNI)}")
    results = []

    # 1) icon grounding: OCR cannot see this control at all
    j = job("vision_locate",
            {"label": "the microphone voice message button", "prefer": "venus"},
            "vis-icon")
    r = j.get("result") or {}
    ok = bool(r.get("found"))
    results.append(("ICON grounding via Venus (OCR-invisible control)", ok,
                    f"xy=({r.get('x')},{r.get('y')}) engine={r.get('engine')}"
                    if ok else str(r.get("note") or j.get("error"))[:90]))
    # must NOT have landed in the window chrome
    if ok:
        safe = not (0 <= (r.get("y") or 0) < 42)
        results.append(("  -> point is outside the title-bar band", safe,
                        f"y={r.get('y')}"))

    # 2) text grounding through the OCR/Venus fusion
    j = job("vision_locate", {"label": "Write", "prefer": "auto"}, "vis-text")
    r = j.get("result") or {}
    results.append(("TEXT grounding via OCR fusion", bool(r.get("found")),
                    f"xy=({r.get('x')},{r.get('y')}) strategy={r.get('strategy')}"))

    # 3) semantic question
    j = job("vision_ask",
            {"question": "Name the application shown in the window title bar. "
                         "Answer with just the name."},
            "vis-ask")
    r = j.get("result") or {}
    ans = (r.get("answer") or "").strip()
    results.append(("Semantic read of the screen", len(ans) > 2, ans[:80]))

    # 4) OmniParser enumeration
    j = job("vision_elements", {"limit": 5}, "vis-elems")
    r = j.get("result") or {}
    results.append(("OmniParser element enumeration", (r.get("count") or 0) > 3,
                    f"{r.get('count')} elements"))

    # 5) bridge's own view of model health
    j = job("health", {}, "vis-health")
    vis = ((j.get("result") or {}).get("vision") or {})
    results.append(("Bridge sees both models", vis.get("venus") == "ok",
                    json.dumps(vis)))

    print()
    passed = 0
    for name, ok, detail in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        if detail:
            print(f"         {detail}")
        passed += bool(ok)
    print(f"\n{passed}/{len(results)} vision checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
