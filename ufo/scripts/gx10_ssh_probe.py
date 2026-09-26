"""Measure what an SSH tunnel actually costs, per client.

Written because "the tunnel adds 62 ms" was believed for a while and was wrong
in its details. The 62 ms was real, but it was the *client's* fixed per-request
cost, not the network, not the address, not Nagle, not process priority. This
script reproduces the bisect so the claim can be re-checked instead of trusted:

  1. spin up a 1-byte TCP echo server on the box
  2. forward it with each ssh client, timing the round trip
  3. time the real model endpoint through the same clients

The echo arm has no HTTP and no model in the path, so a slow result there is
the transport's own doing. On 2026-09-26 that is what separated the clients:

    Git      OpenSSH 10.3p1 / OpenSSL 3.5.7     2.3 ms
    Windows  OpenSSH  9.5p2 / LibreSSL 3.8.2   63.0 ms

Run with the project venv:

    python scripts/gx10_ssh_probe.py
    python scripts/gx10_ssh_probe.py --user flak3dd --host gx10.local
"""
from __future__ import annotations

import argparse
import base64
import http.client
import json
import os
import socket
import statistics
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
KEY = os.path.expanduser("~/.ssh/id_ed25519_ufo_agent")
ECHO_PORT = 19999          # loopback-only echo server on the box
LOCAL_ECHO = 19000         # forwarded to ECHO_PORT
LOCAL_SLOW = 19001         # forwarded to the real model port
LOCAL_MODELS = 19002       # forwarded to the real model port

# A bare byte echo cannot be confused with HTTP framing, TLS or a model.
ECHO_SERVER = r"""
import socket, threading
def handle(c):
    while True:
        d = c.recv(65536)
        if not d:
            break
        c.sendall(d)
    c.close()
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", %d))
s.listen(16)
while True:
    c, _ = s.accept()
    threading.Thread(target=handle, args=(c,), daemon=True).start()
""" % ECHO_PORT

CANDIDATE_CLIENTS = [
    r"C:\Program Files\Git\usr\bin\ssh.exe",
    r"C:\Program Files\Git\cmd\ssh.exe",
    r"C:\Windows\System32\OpenSSH\ssh.exe",
]


def client_version(exe: str) -> str:
    try:
        p = subprocess.run([exe, "-V"], capture_output=True, text=True,
                           timeout=20)
        return (p.stderr or p.stdout or "").strip()
    except Exception as e:  # pragma: no cover - diagnostic path
        return f"<{type(e).__name__}: {e}>"


def start_tunnel(exe: str, forwards: list[tuple[int, int]], host: str, user: str):
    args = [exe, "-N", "-T", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
            "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=4",
            "-o", "ConnectTimeout=15", "-i", KEY]
    for local, remote in forwards:
        args += ["-L", f"{local}:127.0.0.1:{remote}"]
    args.append(f"{user}@{host}")
    return subprocess.Popen(args, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def echo_rtt(port: int, n: int = 40) -> list[float]:
    s = socket.create_connection(("127.0.0.1", port), timeout=20)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    xs = []
    for _ in range(n):
        t0 = time.perf_counter()
        s.sendall(b"x")
        s.recv(1)
        xs.append((time.perf_counter() - t0) * 1000.0)
    s.close()
    return xs


def models_latency(port: int, path: str, n: int = 30) -> list[float]:
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    xs = []
    for i in range(n + 3):
        try:
            t0 = time.perf_counter()
            c.request("GET", path)
            r = c.getresponse()
            r.read()
            if i >= 3:
                xs.append((time.perf_counter() - t0) * 1000.0)
        except Exception:
            try:
                c.close()
            except Exception:
                pass
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    c.close()
    return xs


def stats(xs: list[float]) -> str:
    if not xs:
        return "no samples"
    s = sorted(xs)
    p90 = s[min(len(s) - 1, int(len(s) * 0.9))]
    return (f"min {s[0]:7.2f}  med {statistics.median(s):7.2f}  "
            f"p90 {p90:7.2f}  max {s[-1]:7.2f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="gx10.local")
    ap.add_argument("--user", default="flak3dd")
    ap.add_argument("--model-port", type=int, default=8000)
    ap.add_argument("--path", default="/v1/models")
    a = ap.parse_args()

    if not os.path.exists(KEY):
        print(f"missing key {KEY}", file=sys.stderr)
        return 2

    clients = [c for c in CANDIDATE_CLIENTS if os.path.exists(c)]
    if not clients:
        print("no ssh client found", file=sys.stderr)
        return 2

    print("== putting the echo server on the box (loopback only) ==")
    b64 = base64.b64encode(ECHO_SERVER.encode()).decode()
    # The redirections are load-bearing, not tidiness. `&` alone leaves the
    # backgrounded python holding ssh's stdout open, so ssh waits for an EOF
    # that never arrives and the whole call blocks until it times out (which is
    # exactly what happened the first time this ran). Sending the background
    # process's stdout/stderr to /dev/null lets the foreground `echo` close the
    # channel and ssh return immediately.
    r = subprocess.run([clients[0], "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
                        "-i", KEY, f"{a.user}@{a.host}",
                        f"echo {b64} | base64 -d | nohup python3 "
                        f">/dev/null 2>&1 & sleep 1; echo started"],
                       capture_output=True, text=True, timeout=60)
    print("  " + (r.stdout or r.stderr).strip())

    try:
        _measure_all(clients, a)
    finally:
        # Runs on the failure path too. A probe that dies halfway through and
        # leaves a listener on a shared box is worse than no probe at all.
        print("\n== stopping the echo server on the box ==")
        stop_echo(a.host, a.user, clients[0])
    return 0


def _measure_all(clients: list[str], a) -> None:
    results = []
    for exe in clients:
        print(f"\n== {exe}\n   {client_version(exe)}")
        p = start_tunnel(exe, [(LOCAL_ECHO, ECHO_PORT),
                               (LOCAL_SLOW, a.model_port),
                               (LOCAL_MODELS, a.model_port)], a.host, a.user)
        try:
            time.sleep(7)
            if p.poll() is not None:
                print(f"   tunnel exited immediately (code {p.returncode}) - "
                      "client unusable in this context")
                results.append((exe, None, None))
                continue
            echo = echo_rtt(LOCAL_ECHO)
            models = models_latency(LOCAL_MODELS, a.path)
            print(f"   1-byte echo RTT   {stats(echo)}")
            print(f"   GET {a.path:<12} {stats(models)}")
            results.append((exe, echo, models))
        finally:
            p.terminate()
            try:
                p.wait(timeout=10)
            except Exception:
                p.kill()

    ok = [r for r in results if r[1]]
    if len(ok) >= 2:
        best = min(ok, key=lambda r: statistics.median(r[1]))
        worst = max(ok, key=lambda r: statistics.median(r[1]))
        bm, wm = statistics.median(best[1]), statistics.median(worst[1])
        print(f"\n== verdict")
        print(f"   fastest: {best[0]}  ({bm:.2f} ms per forwarded round trip)")
        print(f"   slowest: {worst[0]}  ({wm:.2f} ms)")
        print(f"   the slow client adds a fixed {wm - bm:.1f} ms to EVERY forwarded "
              f"request ({wm / bm:.0f}x).")
        print("   That is a per-request constant, so it dominates small calls and "
              "disappears into the noise on long generations -")
        print("   measure it on the echo arm, not on a 64-token completion.")


def stop_echo(host: str, user: str, exe: str) -> None:
    """Take the echo server back off the box.

    The gx10 is shared, so a diagnostic that leaves a listener behind is a
    diagnostic that quietly becomes the next person's mystery. Match on the
    bind port rather than on a script name: `pkill -f python3` would take out
    every other python on the machine, including the vLLM engine.
    """
    script = (
        f"for pid in $(ss -ltnp 2>/dev/null | grep '127.0.0.1:{ECHO_PORT} ' "
        f"| grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u); do "
        f"kill $pid 2>/dev/null && echo killed $pid; done; "
        f"echo remaining=$(ss -ltn 2>/dev/null | grep -c ':{ECHO_PORT} ')"
    )
    try:
        subprocess.run([exe, "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
                        "-i", KEY, f"{user}@{host}", script],
                       capture_output=True, text=True, timeout=45)
    except Exception as e:
        print(f"  (could not stop the echo server: {e})", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
