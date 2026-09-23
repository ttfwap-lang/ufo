import json
import os
import urllib.request

base = os.environ.get("VLLM_URL", "http://172.17.0.1:8000/v1").rstrip("/")
try:
    with urllib.request.urlopen(base + "/models", timeout=15) as r:
        data = json.loads(r.read().decode())
    ids = [m.get("id") for m in data.get("data", [])]
    print("models:", ids)
except Exception as e:
    print("models FAIL:", type(e).__name__, e)

# tool-calling smoke test (the whole point of the runner)
payload = {
    "model": os.environ.get("VLLM_MODEL", "qwen-abliterated"),
    "messages": [{"role": "user",
                  "content": "What is the capital of France? Answer in one word."}],
    "max_tokens": 32,
    "temperature": 0.1,
}
try:
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer EMPTY"})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read().decode())
    msg = d["choices"][0]["message"]
    print("llm reply:", (msg.get("content") or "")[:120])
except Exception as e:
    print("chat FAIL:", type(e).__name__, e)
