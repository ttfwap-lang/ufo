import json
import os
import urllib.request

base = os.environ.get("VLLM_URL", "http://172.17.0.1:8000/v1").rstrip("/")

payload = {
    "model": os.environ.get("VLLM_MODEL", "qwen-abliterated"),
    "messages": [{"role": "user",
                  "content": "Reply with exactly: BRIDGE_OK"}],
    "max_tokens": 512,
    "temperature": 0.1,
}
req = urllib.request.Request(
    base + "/chat/completions", data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json", "Authorization": "Bearer EMPTY"})
with urllib.request.urlopen(req, timeout=120) as r:
    d = json.loads(r.read().decode())
choice = d["choices"][0]
msg = choice["message"]
print("finish_reason:", choice.get("finish_reason"))
print("keys:", list(msg.keys()))
print("content:", repr((msg.get("content") or "")[:200]))
print("reasoning:", repr((msg.get("reasoning_content") or "")[:200]))
print("usage:", d.get("usage"))
