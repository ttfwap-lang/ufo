"""Can the box's own forward replace the SSH tunnel?

The box runs /home/flak3dd/ufo-watchdog/ufo_tunnel.py, which listens on
0.0.0.0:18000/18002/18061 and forwards to its own loopback :8000/:8002/:7861.
From the PC that is directly reachable over the LAN and over Tailscale, which
would make the whole SSH hop - and its 60 ms relay cost, its keepalive, its
MaxStartups lockout hazard and its headless-client crashes - unnecessary.

A single-request latency comparison flatters it. The thing that decides
whether it can be trusted is CONCURRENCY: the SSH tunnel hands each connection
to a real sshd, while this is one Python process. If it serialises, it is a
trap exactly when the box is busy, which is when latency matters.

    python scripts/gx10_direct_vs_tunnel.py
"""
from __future__ import annotations

import argparse
import http.client
import json
import statistics
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

# box-side ufo_tunnel.py forwards -> the port we actually want
DIRECT = [("192.168.4.103", 18000, "vLLM")]
VENUS_DIRECT = [("192.168.4.103", 18002, "Venus")]
OMNI_DIRECT = [("192.168.4.103", 18061, "OmniParser")]

VIA_TUNNEL = [("127.0.0.1", 8000, "vLLM")]
VENUS_TUNNEL = [("127.0.0.1", 8002, "Venus")]
OMNI_TUNNEL = [("127.0.0.1", 7861, "OmniParser")]


def get(host: str, port: int, path: str, timeout: float = 30.0) -> tuple[float, int]:
    """One keep-alive-free request. Returns (ms, status)."""
    t0 = time.perf_counter()
    try:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.request("GET", path)
        resp = conn.getresponse()
        resp.read()
        conn.close()
        return (time.perf_counter() - t0) * 1000.0, resp.status
    except Exception as e:
        return (time.perf_counter() - t0) * 1000.0, f"ERR {type(e).__name__}"


def serial_baseline(host: str, port: int, path: str, n: int = 20) -> float | None:
    xs = []
    for _ in range(n + 2):
        ms, st = get(host, port, path)
        if st == 200:
            xs.append(ms)
    return statistics.median(xs) if xs else None


def concurrent(host: str, port: int, path: str, workers: int) -> tuple[float, float, int]:
    """Fire `workers` requests at once. Returns (median ms, p90 ms, ok count)."""
    with ThreadPoolExecutor(max_workers=workers) as ex:
        out = list(ex.map(lambda _: get(host, port, path), range(workers)))
    ok = [ms for ms, st in out if st == 200]
    if not ok:
        return float("nan"), float("nan"), 0
    ok.sort()
    p90 = ok[min(len(ok) - 1, int(len(ok) * 0.9))]
    return statistics.median(ok), p90, len(ok)


def report(name: str, direct, tunnel, path: str) -> None:
    print(f"\n== {name}   (GET {path})")
    print(f"   {'path':<34} {'serial':>9} {'x8 med':>9} {'x8 p90':>9} {'ok':>4}")
    for label, (h, p, _svc) in (("box forward (direct LAN)", direct),
                                ("ssh tunnel", tunnel)):
        base = serial_baseline(h, p, path)
        med, p90, ok = concurrent(h, p, path, 8)
        bs = f"{base:8.2f} " if base else "     n/a "
        print(f"   {label:<34} {bs} {med:8.2f} {p90:8.2f} {ok:>4}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="192.168.4.103")
    a = ap.parse_args()
    DIRECT[0] = (a.host, DIRECT[0][1], "vLLM")
    VENUS_DIRECT[0] = (a.host, VENUS_DIRECT[0][1], "Venus")
    OMNI_DIRECT[0] = (a.host, OMNI_DIRECT[0][1], "OmniParser")

    report("vLLM  :8000", DIRECT[0], VIA_TUNNEL[0], "/v1/models")
    report("Venus  :8002", VENUS_DIRECT[0], VENUS_TUNNEL[0], "/health")
    report("OmniParser :7861", OMNI_DIRECT[0], OMNI_TUNNEL[0], "/api/health")
    print("\nNote: if the direct path degrades under x8 while the tunnel does not,")
    print("it serialises, and a single Python forwarder must not be put on the")
    print("hot path. Measure before switching.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
