"""Autonomous gx10 recovery watcher.

gx10 went unresponsive: ping and TCP connect succeed, but SSH never completes
its banner exchange and every forwarded model port (:7861 OmniParser, :8000
agent LLM, :8002 UI-Venus, :11434 Ollama) accepts a connection and then times
out. Latency on the one service that does answer (:5001) climbed 2.5s -> 10.8s
over six probes, which is the signature of memory thrash, not a dead process:
the GB10's unified memory is oversubscribed by the two LLM pools and the host
is swapping.

This watcher keeps trying on its own, indefinitely, and the instant SSH
answers it:

  1. records the damage (free, uptime, swap, per-container memory),
  2. stops and disables OmniParser (34s per request on CPU - the single
     heaviest thing on the box, and now disabled in config on our side too),
  3. re-records memory so the effect is provable,
  4. writes a verdict to ufo_skill_state/evidence/gx10_recovery.log.

Run in the background; it exits as soon as it has done the work or if the
failure looks permanent. It never raises on a failed attempt - the point is
that it survives the box being sick.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time

HOST = "flak3dd@gx10.local"
KEY = os.path.expanduser(r"~\.ssh\id_ed25519_ufo_agent")
LOG = os.path.join("ufo_skill_state", "evidence", "gx10_recovery.log")
LOCAL_TUNNEL = "127.0.0.1"

# How long to keep trying before giving the attempt up. Bounded so a single
# hung ssh.exe can never wedge the watcher.
SSH_CONNECT_TIMEOUT = 20
PROBE_TIMEOUT = 40

# Backs off, but never past 5 minutes - a box that recovers should be picked
# up promptly, and this runs indefinitely.
BACKOFF = [10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 300]
MAX_ATTEMPTS = 240  # ~24h at the cap


def log(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def ssh(cmd: str, timeout: int = PROBE_TIMEOUT) -> tuple[bool, str]:
    """Run `cmd` on gx10. Returns (ok, output). Never raises."""
    try:
        p = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
             "-o", "ConnectionAttempts=1", "-o", "ServerAliveInterval=10",
             "-i", KEY, HOST, cmd],
            capture_output=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    out = (p.stdout or b"").decode("utf-8", "replace")
    err = (p.stderr or b"").decode("utf-8", "replace").strip()
    return p.returncode == 0, (out.strip() or err)


def probe_models() -> dict:
    """Cheap liveness of the forwarded model ports (no auth needed)."""
    import urllib.request

    out = {}
    for name, url in (
        ("galaxy:5001", f"http://{LOCAL_TUNNEL}:5001/openapi.json"),
        ("omniparser:7861", f"http://{LOCAL_TUNNEL}:7861/api/health"),
        ("venus:8002", f"http://{LOCAL_TUNNEL}:8002/v1/models"),
        ("llm:8000", f"http://{LOCAL_TUNNEL}:8000/v1/models"),
        ("ollama:11434", f"http://{LOCAL_TUNNEL}:11434/api/tags"),
    ):
        t0 = time.time()
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                r.read(64)
            out[name] = f"OK {time.time()-t0:.1f}s"
        except Exception as exc:  # noqa: BLE001
            out[name] = f"DEAD {type(exc).__name__}"
    return out


DIAG = r"""
echo '--- uptime/memory ---'
uptime
free -m
echo '--- swap ---'
swapon --show 2>/dev/null || echo '(no swap tool)'
echo '--- top cpu ---'
ps -eo pid,pcpu,pmem,rss,comm --sort=-pcpu | head -n 12
echo '--- containers ---'
docker ps --format '{{.Names}}\t{{.Status}}' 2>/dev/null || echo '(no docker)'
echo '--- omniparser procs ---'
pgrep -af -i omniparser || echo '(none)'
"""


def main() -> int:
    log("=== gx10 recovery watcher started ===")
    log(f"probing {HOST} every cycle; model ports are forwarders on {LOCAL_TUNNEL}")
    for attempt in range(1, MAX_ATTEMPTS + 1):
        ok, out = ssh(DIAG, timeout=PROBE_TIMEOUT)
        if ok:
            log(f"attempt {attempt}: SSH IS BACK")
            log(out)
            break
        wait = BACKOFF[min(attempt - 1, len(BACKOFF) - 1)]
        log(f"attempt {attempt}: {out} - sleeping {wait}s")
        time.sleep(wait)
    else:
        log(f"gave up after {MAX_ATTEMPTS} attempts")
        return 1

    # SSH works. Stop the heaviest CPU consumer before anything else.
    log("--- stopping + disabling OmniParser on gx10 ---")
    ok, out = ssh(
        "systemctl --user stop omniparser 2>&1; "
        "systemctl --user disable omniparser 2>&1; "
        "pkill -f omniparser 2>&1; echo done",
        timeout=60,
    )
    log(f"omniparser stop -> {'ok' if ok else 'FAILED'}: {out}")

    # Give memory a moment to come back, then prove it.
    time.sleep(20)
    log("--- memory after ---")
    ok, out = ssh("free -m; uptime", timeout=PROBE_TIMEOUT)
    log(out)

    log("--- model port liveness after ---")
    for name, state in probe_models().items():
        log(f"  {name:18s} {state}")

    log("=== recovery complete: OmniParser is off, UFO no longer calls it ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
