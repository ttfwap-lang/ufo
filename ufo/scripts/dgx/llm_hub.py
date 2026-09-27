#!/usr/bin/env python3
"""llm_hub.py - one OpenAI-compatible endpoint that aggregates every model server
running on the Spark, so any machine on the LAN/tailnet auto-discovers them.

WHY: the model servers bind 127.0.0.1 on the box and are otherwise reached on
scattered per-model tunnel ports (18000/18002/...). A coding tool wants ONE
base_url whose GET /v1/models lists everything available. This is that: it probes
the known upstream ports, unions their /v1/models, and routes each request to the
port that actually serves the requested model. Models that are down simply drop
out of the list ("all AVAILABLE llms, always"), and swapped-in ones appear with
no client change.

Bind 0.0.0.0 so LAN + tailnet peers reach it; there is NO auth (any header/key is
accepted and ignored) - it is meant for a trusted home network only. Do not route
this to the internet.

    python3 llm_hub.py 4000          # listen on 0.0.0.0:4000, probe default ports
    LLM_HUB_UPSTREAMS="8000 8002 8004 8005 8007" python3 llm_hub.py 4000
"""
import json
import os
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
UPSTREAM_PORTS = [int(p) for p in os.environ.get("LLM_HUB_UPSTREAMS", "8000 8002 8004 8005 8007").split()]
UPSTREAM_HOST = "127.0.0.1"
_lock = threading.Lock()
_map: dict[str, str] = {}          # model id -> "host:port"
_map_ts = 0.0
_MAP_TTL = 15.0                     # re-probe at most every 15 s


def _probe():
    """Build model-id -> upstream by asking each port's /v1/models."""
    m = {}
    for port in UPSTREAM_PORTS:
        base = f"http://{UPSTREAM_HOST}:{port}"
        try:
            with urllib.request.urlopen(base + "/v1/models", timeout=2) as r:
                for entry in json.loads(r.read()).get("data", []):
                    mid = entry.get("id")
                    if mid and mid not in m:
                        m[mid] = f"{UPSTREAM_HOST}:{port}"
        except Exception:
            continue
    return m


def _model_map(force=False):
    global _map, _map_ts
    with _lock:
        if force or (time.time() - _map_ts) > _MAP_TTL or not _map:
            fresh = _probe()
            if fresh:
                _map = fresh
            _map_ts = time.time()
        return dict(_map)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/v1/models") or self.path.rstrip("/").endswith("/models"):
            ids = sorted(_model_map().keys())
            data = [{"id": i, "object": "model", "created": int(time.time()), "owned_by": "gx10"} for i in ids]
            self._send(200, json.dumps({"object": "list", "data": data}).encode())
        elif self.path.rstrip("/").endswith("/health") or self.path == "/":
            self._send(200, json.dumps({"status": "ok", "models": sorted(_model_map().keys())}).encode())
        else:
            self._send(404, b'{"error":"not found"}')

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        try:
            model = json.loads(raw).get("model", "")
        except Exception:
            model = ""
        mp = _model_map()
        target = mp.get(model) or (mp.get(model, None) if model in mp else None)
        if not target:
            # unknown/absent model: re-probe once (it may have just swapped in)
            mp = _model_map(force=True)
            target = mp.get(model)
        if not target:
            self._send(404, json.dumps({"error": {
                "message": f"model '{model}' is not available on the Spark. Available: {sorted(mp.keys())}",
                "type": "model_not_found"}}).encode())
            return
        # forward (streaming pass-through) to the owning upstream
        up = f"http://{target}{self.path if self.path.startswith('/v1') else '/v1/chat/completions'}"
        req = urllib.request.Request(up, data=raw, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=900) as r:
                self.send_response(r.status)
                self.send_header("Content-Type", r.headers.get("Content-Type", "application/json"))
                te = (r.headers.get("Transfer-Encoding") or "").lower()
                streaming = "chunked" in te or "text/event-stream" in (r.headers.get("Content-Type") or "")
                if streaming:
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    while True:
                        chunk = r.read(4096)
                        if not chunk:
                            self.wfile.write(b"0\r\n\r\n")
                            break
                        self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                        self.wfile.flush()
                else:
                    body = r.read()
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
        except urllib.error.HTTPError as e:
            body = e.read()
            self._send(e.code, body if body else json.dumps({"error": str(e)}).encode())
        except Exception as e:
            self._send(502, json.dumps({"error": {"message": f"upstream {target}: {e}", "type": "bad_gateway"}}).encode())


if __name__ == "__main__":
    print(f"llm_hub on 0.0.0.0:{PORT}; upstreams {UPSTREAM_PORTS}; models now: {sorted(_model_map().keys())}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
