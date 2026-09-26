"""End-to-end latency/throughput probe of the PC -> SSH tunnel -> gx10 path. Read-only: sends small
generated requests, never touches the desktop. Run with the project venv:

    python scripts/gx10_e2e_probe.py [--image path.png] [--model qwen-abliterated]

Measures, in order: LAN RTT, HTTP latency through the tunnel (reused vs new connection), raw ssh
bandwidth (up/down), then real model requests (text, image PNG vs JPEG, prefix-cache reuse,
4 concurrent). Numbers are wall-clock from this PC.
"""
import argparse
import base64
import http.client
import io
import json
import os
import re
import statistics
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

HOST = os.environ.get("UFO_GX10_ADDR", "192.168.4.103")
KEY = os.path.expanduser(r"~\.ssh\id_ed25519_ufo_agent")


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))]


def line(label, xs, unit="ms"):
    print(f"  {label:38s} min {min(xs):7.1f}  median {statistics.median(xs):7.1f}  p95 {pct(xs, .95):7.1f}  max {max(xs):7.1f} {unit}")


def ping():
    print("== LAN RTT (ICMP, 30 packets)")
    out = subprocess.run(["ping", "-n", "30", HOST], capture_output=True, text=True).stdout
    times = [float(m) for m in re.findall(r"time[=<](\d+)ms", out)]
    loss = re.search(r"\((\d+)% loss\)", out)
    if times:
        line("ping " + HOST, times)
    print(f"  loss: {loss.group(1) + '%' if loss else '?'}")


def tunnel_latency():
    print("== HTTP through the tunnel :8000 GET /v1/models")
    conn = http.client.HTTPConnection("127.0.0.1", 8000, timeout=10)
    reused = []
    for _ in range(40):
        t0 = time.perf_counter()
        conn.request("GET", "/v1/models"); conn.getresponse().read()
        reused.append((time.perf_counter() - t0) * 1000)
    conn.close()
    new = []
    for _ in range(20):
        t0 = time.perf_counter()
        c = http.client.HTTPConnection("127.0.0.1", 8000, timeout=10)
        c.request("GET", "/v1/models"); c.getresponse().read(); c.close()
        new.append((time.perf_counter() - t0) * 1000)
    line("keep-alive (steady state)", reused[1:])
    line("new connection each call", new)


def ssh_bw(cipher=None, mb=16):
    base = ["ssh.exe", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-i", KEY]
    if cipher:
        base += ["-c", cipher]
    base.append(f"flak3dd@{HOST}")
    data = os.urandom(mb * 1024 * 1024)
    t0 = time.perf_counter()
    subprocess.run(base + ["cat > /dev/null"], input=data, capture_output=True, timeout=120)
    up = mb / (time.perf_counter() - t0)
    t0 = time.perf_counter()
    r = subprocess.run(base + [f"head -c {mb * 1024 * 1024} /dev/zero"], capture_output=True, timeout=120)
    down = len(r.stdout) / 1048576 / (time.perf_counter() - t0)
    return up, down


def bandwidth():
    print("== ssh bandwidth, 16 MB incl. connection setup (MB/s)")
    for c in (None, "aes128-gcm@openssh.com"):
        try:
            up, down = ssh_bw(c)
            print(f"  cipher {c or 'default(chacha20)':26s} up {up:6.1f}  down {down:6.1f}")
        except Exception as e:
            print(f"  cipher {c}: ERROR {e}")


def metrics():
    try:
        c = http.client.HTTPConnection("127.0.0.1", 8000, timeout=10)
        c.request("GET", "/metrics"); txt = c.getresponse().read().decode()
        g = lambda k: sum(float(x.split()[-1]) for x in txt.splitlines() if x.startswith(k))
        return g("vllm:prefix_cache_hits_total"), g("vllm:prefix_cache_queries_total")
    except Exception:
        return None, None


def stream_chat(model, messages, max_tokens=120):
    body = json.dumps({"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0,
                       "stream": True, "stream_options": {"include_usage": True},
                       "chat_template_kwargs": {"enable_thinking": False}}).encode()
    c = http.client.HTTPConnection("127.0.0.1", 8000, timeout=180)
    t0 = time.perf_counter()
    c.request("POST", "/v1/chat/completions", body, {"Content-Type": "application/json", "Authorization": "Bearer sk-local"})
    r = c.getresponse()
    ttft, toks, prompt = None, 0, 0
    for raw in r:
        if not raw.startswith(b"data: ") or raw.strip() == b"data: [DONE]":
            continue
        d = json.loads(raw[6:])
        if d.get("usage"):
            toks, prompt = d["usage"]["completion_tokens"], d["usage"]["prompt_tokens"]
        for ch in d.get("choices", []):
            if ch.get("delta", {}).get("content") and ttft is None:
                ttft = time.perf_counter() - t0
    total = time.perf_counter() - t0
    c.close()
    return ttft or total, total, prompt, toks, len(body)


def img_b64(path, fmt, size=None):
    from PIL import Image
    im = Image.open(path).convert("RGB")
    if size:
        im = im.resize(size)
    buf = io.BytesIO()
    if fmt == "png":
        im.save(buf, "PNG")
    else:
        im.save(buf, "JPEG", quality=85)
    mime = "png" if fmt == "png" else "jpeg"
    return f"data:image/{mime};base64," + base64.b64encode(buf.getvalue()).decode(), len(buf.getvalue())


def model_requests(model, image):
    print("== model requests through the tunnel (GPU is SHARED with whatever else runs on the box)")
    text = [{"role": "user", "content": "Write the numbers 1 to 60 separated by commas."}]
    stream_chat(model, text, 20)                                             # warm-up
    rs = [stream_chat(model, text) for _ in range(3)]
    print(f"  text, 3 runs        : TTFT {statistics.median(r[0] for r in rs)*1000:6.0f} ms  total {statistics.median(r[1] for r in rs):5.2f}s  "
          f"decode {statistics.median(r[3]/max(r[1]-r[0], 1e-6) for r in rs):5.0f} tok/s")
    if not image:
        return
    for fmt in ("png", "jpeg"):
        url, raw = img_b64(image, fmt, (1920, 1080))
        msgs = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": url}},
                                             {"type": "text", "text": "List the visible headings, briefly."}]}]
        h0, q0 = metrics()
        first = stream_chat(model, [dict(msgs[0], content=list(msgs[0]["content"]))], 80)
        second = stream_chat(model, msgs, 80)                                # identical -> prefix cache?
        h1, q1 = metrics()
        print(f"  image {fmt.upper():4s} {raw/1024:6.0f} KB (request {first[4]/1024:6.0f} KB, {first[2]} prompt tokens)")
        print(f"      1st: TTFT {first[0]*1000:6.0f} ms total {first[1]:5.2f}s   identical repeat: TTFT {second[0]*1000:6.0f} ms total {second[1]:5.2f}s")
        if h0 is not None:
            print(f"      prefix cache: +{h1-h0:.0f} hits / +{q1-q0:.0f} queried tokens across the two requests")
    url, _ = img_b64(image, "jpeg", (1920, 1080))
    def one(i):
        m = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": url}},
                                          {"type": "text", "text": f"Describe region {i} in one sentence."}]}]
        return stream_chat(model, m, 60)
    t0 = time.perf_counter()
    with ThreadPoolExecutor(4) as ex:
        rs = list(ex.map(one, range(4)))
    wall = time.perf_counter() - t0
    print(f"  4 concurrent image requests: wall {wall:.2f}s  slowest TTFT {max(r[0] for r in rs)*1000:.0f} ms  aggregate {sum(r[3] for r in rs)/wall:.0f} tok/s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=None)
    ap.add_argument("--model", default="qwen-abliterated")
    ap.add_argument("--skip-bw", action="store_true")
    a = ap.parse_args()
    ping()
    tunnel_latency()
    if not a.skip_bw:
        bandwidth()
    model_requests(a.model, a.image)
