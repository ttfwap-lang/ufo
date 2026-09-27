"""bench_client.py <base_url> <model> <label> - measure prefix-cache reuse and throughput.

Staged for scripts/dgx/bench_engine.sh. Compares a modern engine (vLLM/SGLang) against
the llama.cpp 42B baseline. The headline number is turn 3: a mid-history EDIT. llama.cpp
re-prefills the whole prompt (~75-95 s / 47k tokens on the hybrid arch); an engine with
real prefix caching should reuse the unchanged prefix before the edit point.
"""
import json
import sys
import time
import urllib.request

BASE, MODEL, LABEL = sys.argv[1], sys.argv[2], sys.argv[3]


def chat(messages, max_tokens=8, extra=None):
    body = {"model": MODEL, "max_tokens": max_tokens, "temperature": 0.0, "messages": messages}
    if extra:
        body.update(extra)
    req = urllib.request.Request(BASE.rstrip("/") + "/chat/completions",
                                 json.dumps(body).encode(), {"Content-Type": "application/json"})
    t = time.time()
    d = json.loads(urllib.request.urlopen(req, timeout=900).read())
    return d, time.time() - t


# Build a ~47k-token history so cold prefill is clearly measurable.
history = "You are a coding agent.\n" + " ".join(
    f"def f{i}(x): return x*{i}  # helper {i}" for i in range(2200))
m1 = [{"role": "system", "content": history}, {"role": "user", "content": "What does f7 return for x=3?"}]

print(f"engine={LABEL} model={MODEL}")
d, s = chat(m1)
u = d.get("usage", {})
print(f"turn 1 (cold):         prompt_tokens={u.get('prompt_tokens')}  {s:.1f}s")

m2 = m1 + [{"role": "assistant", "content": "21"}, {"role": "user", "content": "And f9 for x=2?"}]
d, s = chat(m2)
u = d.get("usage", {})
cached = u.get("prompt_tokens_details", {}).get("cached_tokens") if isinstance(u.get("prompt_tokens_details"), dict) else None
print(f"turn 2 (append):       prompt_tokens={u.get('prompt_tokens')}  cached={cached}  {s:.1f}s   <- append-only reuse")

# Turn 3: edit a token ~80% into the history, then ask again. THE key test.
m3 = [{"role": "system", "content": history.replace("helper 1800 ", "helper eighteen-hundred ", 1)}] + m2[1:]
d, s = chat(m3)
u = d.get("usage", {})
cached = u.get("prompt_tokens_details", {}).get("cached_tokens") if isinstance(u.get("prompt_tokens_details"), dict) else None
print(f"turn 3 (edit @ ~80%):  prompt_tokens={u.get('prompt_tokens')}  cached={cached}  {s:.1f}s   <- vs llama.cpp full reprefill")

# Raw single-stream throughput on a fresh short prompt.
d, s = chat([{"role": "user", "content": "Write a 200-word paragraph about rivers."}], max_tokens=400)
u = d.get("usage", {})
ct = u.get("completion_tokens", 0)
print(f"throughput:            {ct} tok in {s:.1f}s = {ct / s:.1f} tok/s   (llama.cpp baseline ~33 tok/s)")
print("baseline recap: llama.cpp 42B ~33 tok/s; append reuse ~1s; mid-history edit = FULL reprefill.")
