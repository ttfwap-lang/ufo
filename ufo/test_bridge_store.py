"""Regression tests for the bridge's job-store lifecycle.

These cover the two failure modes found during the review that would only
show up after the service had been running for a while:

  1. unbounded growth of JOBS (memory leak in a 24/7 service)
  2. readers observing a half-written job while the worker mutates it

Run: python test_bridge_store.py
"""
from __future__ import annotations

import importlib.util
import io
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.join(HERE, "ufo_bridge.py")


def load_bridge():
    spec = importlib.util.spec_from_file_location("ufo_bridge_t", BRIDGE)
    mod = importlib.util.module_from_spec(spec)
    src = io.open(BRIDGE, encoding="utf-8").read()
    # the module starts a server under __main__ only, so exec_module is safe;
    # it does create the token file, which is gitignored.
    spec.loader.exec_module(mod)
    return mod


def test_eviction():
    m = load_bridge()
    m.JOBS.clear()
    m.MAX_JOBS = 20
    # insert more than the cap, all finished
    for i in range(60):
        j = m._new_job(f"j{i}", "health", {})
        j["status"] = "done"
        j["created"] = time.time() + i          # ascending age
    m._evict_old_jobs()
    assert len(m.JOBS) <= m.MAX_JOBS, \
        f"store grew past the cap: {len(m.JOBS)} > {m.MAX_JOBS}"
    # the newest must survive, the oldest must be gone
    assert "j59" in m.JOBS, "newest job was evicted"
    assert "j0" not in m.JOBS, "oldest job was not evicted"
    print(f"  eviction OK: {len(m.JOBS)} retained (cap {m.MAX_JOBS}), "
          f"oldest dropped, newest kept")


def test_inflight_never_evicted():
    m = load_bridge()
    m.JOBS.clear()
    m.MAX_JOBS = 5
    running = m._new_job("keep-running", "health", {})
    running["status"] = "running"
    for i in range(30):
        j = m._new_job(f"done{i}", "health", {})
        j["status"] = "done"
    m._evict_old_jobs()
    assert "keep-running" in m.JOBS, \
        "a RUNNING job was evicted - a client would lose its result"
    assert len(m.JOBS) <= m.MAX_JOBS + 1, \
        f"store not bounded: {len(m.JOBS)}"
    print("  in-flight protection OK: running job survived eviction")


def test_snapshot_isolation():
    m = load_bridge()
    m.JOBS.clear()
    job = m._new_job("snap", "health", {})
    job["status"] = "running"
    snap = m._job_snapshot("snap")
    assert snap is not None and snap is not job, \
        "snapshot must be a copy, not the live dict"
    job["status"] = "done"
    assert snap["status"] == "running", \
        "mutating the job changed an existing snapshot (torn read)"
    assert m._job_snapshot("nope") is None, "unknown id must return None"
    print("  snapshot isolation OK: readers get an immutable copy")


def main() -> int:
    print("bridge job-store regression tests")
    failures = 0
    for fn in (test_eviction, test_inflight_never_evicted,
               test_snapshot_isolation):
        try:
            fn()
        except AssertionError as e:
            print(f"  FAIL {fn.__name__}: {e}")
            failures += 1
        except Exception as e:                       # noqa: BLE001
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
            failures += 1
    print("PASS" if not failures else f"{failures} FAILURE(S)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
