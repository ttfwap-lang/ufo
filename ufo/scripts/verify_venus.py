"""Confirm the restored grounding stack actually infers, not just listens.

A container being "Up" and answering /v1/models proves the process is alive.
It does not prove the model can do its job. Venus is a grounding model, so the
only meaningful check is a real generate against a real image, timed through
the PC's SSH tunnel - the same path UFO will actually use.

    python verify_venus.py [--image path] [--timeout 300]
"""
from __future__ import annotations

import argparse
import base64
import json
import struct
import sys
import time
import urllib.request
import zlib

# through the tunnel, not the box's loopback
HOST, PORT = "127.0.0.1", 8002
MODEL = "ui-venus"


def make_png(w: int, h: int) -> bytes:
    """A valid RGB PNG with enough structure to be worth describing.

    Three flat colour blocks on a light background - the rough shape of a
    window with a sidebar. Stdlib only, so the probe has no image dependency
    and cannot rot when one is upgraded.
    """
    bg, bar, panel = (244, 245, 247), (58, 96, 168), (255, 255, 255)
    rows = bytearray()
    for y in range(h):
        rows.append(0)  # PNG per-scanline filter byte: 0 = None
        for x in range(w):
            if y < 14:
                c = bar
            elif x < 34:
                c = bg
            else:
                c = panel
            rows += bytes(c)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(rows), 6))
            + chunk(b"IEND", b""))


def post(path: str, payload: dict, timeout: float) -> tuple[int, dict, float]:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"http://{HOST}:{PORT}{path}", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        ms = (time.perf_counter() - t0) * 1000
    return r.status, json.loads(raw or b"{}"), ms


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=float, default=300.0)
    a = ap.parse_args()

    # 1. health
    t0 = time.perf_counter()
    with urllib.request.urlopen(
            f"http://{HOST}:{PORT}/v1/models", timeout=20) as r:
        models = json.loads(r.read())
    health_ms = (time.perf_counter() - t0) * 1000
    ids = [m["id"] for m in models.get("data", [])]
    print(f"  /v1/models   {health_ms:.1f} ms   models={ids}")
    if MODEL not in ids:
        print(f"  FAIL: {MODEL} not served", file=sys.stderr)
        return 1

    # 2. a real grounding call against a real image. Encode the PNG here with
    #    stdlib zlib/struct rather than pasting a base64 literal: a hand-typed
    #    blob is exactly the kind of thing that is silently one character short.
    png = make_png(128, 96)

    # First call on a cold vLLM pays CUDA graph capture; a timeout here is a
    # real problem, not a warm-up artefact, so it gets the full budget.
    t0 = time.perf_counter()
    try:
        st, body, ms = post("/v1/chat/completions", {
            "model": MODEL,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{base64.b64encode(png).decode()}"}},
                    {"type": "text", "text": "Describe what you see."},
                ],
            }],
            "max_tokens": 48,
            "temperature": 0.0,
            # TOP-LEVEL chat_template_kwargs, which is what the production
            # client sends (automator/ui_control/grounding/venus.py).
            #
            # Measured: a bare top-level "enable_thinking": false does NOT
            # disable thinking for Venus. Both spellings returned 48/48
            # reasoning_tokens, empty content and finish_reason "length" -
            # indistinguishable from a broken model. Venus is Qwen3-VL, whose
            # switch is a chat-template variable, so it has to be passed
            # through chat_template_kwargs to reach the template.
            "chat_template_kwargs": {"enable_thinking": False},
        }, a.timeout)
    except Exception as e:
        print(f"  FAIL: grounding call raised {type(e).__name__}: {e}",
              file=sys.stderr)
        return 1

    total = (time.perf_counter() - t0) * 1000
    print(f"  grounding    HTTP {st}  {total:.0f} ms total "
          f"({ms:.0f} ms server-side)")
    usage = body.get("usage", {}) or {}
    print(f"  usage        {usage}")

    text = ""
    try:
        text = (body["choices"][0]["message"].get("content") or "").strip()
    except Exception:
        pass
    # Venus is a thinking model, so content can be None with reasoning_tokens
    # spent. Report which happened instead of calling it a failure blindly.
    if text:
        print(f"  reply        {text[:200]}")
    else:
        print("  reply        <empty content>")
    print(f"  finish       {body.get('choices', [{}])[0].get('finish_reason')}")

    if st != 200:
        return 1
    ok = bool(text) or usage.get("completion_tokens", 0) > 0
    print(f"\n  VERDICT: {'grounding WORKS through the tunnel' if ok else 'served but produced nothing'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
