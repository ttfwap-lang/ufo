#!/usr/bin/env python3
"""llm_hub.py - one OpenAI-compatible endpoint that aggregates every model server
running on the Spark PLUS a curated set of Featherless cloud models, so any machine
on the LAN/tailnet auto-discovers them all from one base_url.

Local models: probes the known upstream ports, unions their /v1/models, routes each
request to the port that serves it. Models that are down drop out of the list.

Cloud models (Featherless): a fixed friendly-name -> real-id map, served only when
FEATHERLESS_API_KEY is set (via the systemd EnvironmentFile). Requests for these are
rewritten to the real Featherless id and forwarded with the key + a browser UA
(Featherless sits behind Cloudflare, which 1010-blocks default UAs). The key is
read from the environment ONLY - never hard-coded, logged, or returned.

Bind 0.0.0.0 so LAN + tailnet peers reach it; NO client auth (trusted home network
only). NOTE: exposing the cloud models here means any LAN peer can spend Featherless
quota - that is the operator's explicit choice.

    python3 llm_hub.py 4000
"""
import json
import os
import sys
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
UPSTREAM_PORTS = [int(p) for p in os.environ.get("LLM_HUB_UPSTREAMS", "8000 8002 8004 8005 8007").split()]
UPSTREAM_HOST = "127.0.0.1"

FEATHERLESS_KEY = os.environ.get("FEATHERLESS_API_KEY", "").strip()
FEATHERLESS_URL = "https://api.featherless.ai/v1/chat/completions"
# friendly name served by the hub -> real Featherless model id
REMOTE_MODELS = {
    "deepseek-v4-pro": "deepseek-ai/DeepSeek-V4-Pro",
    "deepseek-v4.1-flash": "deepseek-ai/DeepSeek-V4.1-Flash",
    "qwen3-coder-480b": "Qwen/Qwen3-Coder-480B-A35B-Instruct",
}
_lock = __import__("threading").Lock()
_map: dict[str, str] = {}
_map_ts = 0.0
_MAP_TTL = 15.0


def _probe():
    m = {}
    for port in UPSTREAM_PORTS:
        try:
            with urllib.request.urlopen(f"http://{UPSTREAM_HOST}:{port}/v1/models", timeout=2) as r:
                for e in json.loads(r.read()).get("data", []):
                    mid = e.get("id")
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

    def _all_ids(self):
        ids = set(_model_map().keys())
        if FEATHERLESS_KEY:
            ids |= set(REMOTE_MODELS.keys())
        return sorted(ids)

    def do_GET(self):
        p = self.path.rstrip("/")
        if p.endswith("/v1/models") or p.endswith("/models"):
            data = [{"id": i, "object": "model", "created": int(time.time()),
                     "owned_by": "featherless" if i in REMOTE_MODELS else "gx10"} for i in self._all_ids()]
            self._send(200, json.dumps({"object": "list", "data": data}).encode())
        elif p.endswith("/health") or self.path == "/":
            self._send(200, json.dumps({"status": "ok", "models": self._all_ids(),
                                        "cloud": bool(FEATHERLESS_KEY)}).encode())
        else:
            self._send(404, b'{"error":"not found"}')

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw)
            model = body.get("model", "")
        except Exception:
            body, model = {}, ""

        # cloud (Featherless) route
        if model in REMOTE_MODELS:
            if not FEATHERLESS_KEY:
                self._send(503, json.dumps({"error": {"message": "cloud models unavailable: FEATHERLESS_API_KEY not set", "type": "config"}}).encode())
                return
            body["model"] = REMOTE_MODELS[model]
            data = json.dumps(body).encode()
            req = urllib.request.Request(FEATHERLESS_URL, data=data, method="POST", headers={
                "Content-Type": "application/json", "User-Agent": "Mozilla/5.0",
                "Authorization": "Bearer " + FEATHERLESS_KEY})
            self._forward(req)
            return

        # local route
        mp = _model_map()
        target = mp.get(model) or _model_map(force=True).get(model)
        if not target:
            self._send(404, json.dumps({"error": {"message": f"model '{model}' not available. Have: {self._all_ids()}", "type": "model_not_found"}}).encode())
            return
        up = f"http://{target}{self.path if self.path.startswith('/v1') else '/v1/chat/completions'}"
        req = urllib.request.Request(up, data=raw, method="POST", headers={"Content-Type": "application/json"})
        self._forward(req)

    def _forward(self, req):
        try:
            with urllib.request.urlopen(req, timeout=900) as r:
                self.send_response(r.status)
                ct = r.headers.get("Content-Type", "application/json")
                self.send_header("Content-Type", ct)
                streaming = "chunked" in (r.headers.get("Transfer-Encoding") or "").lower() or "text/event-stream" in ct
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
                    b = r.read()
                    self.send_header("Content-Length", str(len(b)))
                    self.end_headers()
                    self.wfile.write(b)
        except urllib.error.HTTPError as e:
            b = e.read()
            self._send(e.code, b if b else json.dumps({"error": str(e)}).encode())
        except Exception as e:
            self._send(502, json.dumps({"error": {"message": str(e), "type": "bad_gateway"}}).encode())


if __name__ == "__main__":
    print(f"llm_hub on 0.0.0.0:{PORT}; local ports {UPSTREAM_PORTS}; "
          f"cloud={'on' if FEATHERLESS_KEY else 'off'} ({sorted(REMOTE_MODELS)}); "
          f"models now: {sorted(_model_map().keys())}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
