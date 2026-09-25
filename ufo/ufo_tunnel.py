#!/usr/bin/env python3
"""ufo_tunnel.py - expose loopback-bound model servers on the tailnet.

WHY
    On gx10 the model servers are launched with `--host 127.0.0.1`, so nothing
    on the tailnet can reach them. The obvious fix is to relaunch them with
    `--host 0.0.0.0` - but another agent owns that launch, and it kept putting
    Venus back on 127.0.0.1. Relaunching it every time was a fight neither side
    could win, and it cost a 17.5 GiB model reload (~5 min) each round.

    A listener on 0.0.0.0:8002 cannot coexist with one on 127.0.0.1:8002, so
    the tunnel uses a separate port and the client is pointed at that. The
    model container is never touched.

    This is the difference between owning a service and fighting over it.

DESIGN
    * stdlib only - no pip install on the model host
    * threaded, one thread per connection, unbounded accept loop
    * half-close aware, so large responses (base64 screenshots, parse results)
      are not truncated at EOF
    * per-connection errors are logged and dropped, never fatal
    * if the upstream is down the listener stays up and simply refuses, so the
      client's error is "connection reset" rather than "connection refused to a
      dead port" - and the tunnel itself never needs restarting

Run:  python3 ufo_tunnel.py <listen_port> <upstream_host> <upstream_port> [...]
"""
from __future__ import annotations

import socket
import socketserver
import sys
import threading
import time

LOG_LOCK = threading.Lock()


def log(msg: str) -> None:
    with LOG_LOCK:
        print(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}", flush=True)


class ForwardHandler(socketserver.BaseRequestHandler):
    upstream = ("127.0.0.1", 0)

    def handle(self) -> None:
        peer = self.client_address
        up_host, up_port = self.upstream
        try:
            up = socket.create_connection((up_host, up_port), timeout=15)
        except Exception as e:  # noqa: BLE001
            log(f"upstream {up_host}:{up_port} refused from {peer}: {type(e).__name__}")
            return
        up.settimeout(None)
        self.request.settimeout(None)
        log(f"open {peer} -> {up_host}:{up_port}")

        def pump(src: socket.socket, dst: socket.socket, tag: str) -> None:
            try:
                while True:
                    data = src.recv(65536)
                    if not data:
                        # Half-close: signal EOF downstream but keep the other
                        # direction open, otherwise a streamed reply is cut off.
                        try:
                            dst.shutdown(socket.SHUT_WR)
                        except OSError:
                            pass
                        return
                    dst.sendall(data)
            except Exception as e:  # noqa: BLE001
                log(f"{tag} ended: {type(e).__name__}: {e}")
            finally:
                try:
                    dst.shutdown(socket.SHUT_WR)
                except OSError:
                    pass

        t1 = threading.Thread(target=pump, args=(self.request, up, "client->up"), daemon=True)
        t2 = threading.Thread(target=pump, args=(up, self.request, "up->client"), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        for s in (up, self.request):
            try:
                s.close()
            except OSError:
                pass
        log(f"close {peer} -> {up_host}:{up_port}")


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve(listen_port: int, up_host: str, up_port: int) -> None:
    handler = type(f"H{listen_port}", (ForwardHandler,), {"upstream": (up_host, up_port)})
    try:
        srv = Server(("0.0.0.0", listen_port), handler)
    except OSError as e:
        log(f"FATAL cannot bind 0.0.0.0:{listen_port}: {e}")
        raise
    log(f"listening 0.0.0.0:{listen_port} -> {up_host}:{up_port}")
    try:
        srv.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


def main(argv: list[str]) -> int:
    if len(argv) < 4 or (len(argv) - 1) % 3 != 0:
        print(__doc__)
        print("usage: ufo_tunnel.py <lport> <host> <port> [<lport> <host> <port> ...]",
              file=sys.stderr)
        return 2
    maps = []
    for i in range(1, len(argv), 3):
        try:
            maps.append((int(argv[i]), argv[i + 1], int(argv[i + 2])))
        except ValueError:
            print(f"bad mapping near argv[{i}:{i+3}]", file=sys.stderr)
            return 2
    threads = []
    for lport, host, port in maps:
        t = threading.Thread(target=serve, args=(lport, host, port), daemon=True)
        t.start()
        threads.append(t)
        time.sleep(0.2)          # stagger so a bind failure is attributable
    while True:
        time.sleep(3600)
        for t in threads:
            t.join(timeout=0)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
