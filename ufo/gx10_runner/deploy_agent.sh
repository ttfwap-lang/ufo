# Append/merge agent-runner settings into the runner .env (no secrets echoed).
set -e
cd ~/ufo-tg-runner-bootstrap

python3 - <<'PY'
import os

path = ".env"
env = {}
if os.path.exists(path):
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

env.update({
    # local vLLM (Qwen) - host gateway because the compose uses the default
    # bridge network; override with VLLM_URL if the network changes.
    "VLLM_URL": os.environ.get("VLLM_URL", "http://172.17.0.1:8000/v1"),
    "VLLM_MODEL": os.environ.get("VLLM_MODEL", "qwen-abliterated"),
    "AGENT_MAX_TURNS": "8",
    "AGENT_HISTORY_TURNS": "8",
    "ALLOW_WEB": "1",
    # Windows UFO/Venus bridge over the tailnet
    "UFO_BRIDGE_URL": os.environ.get("UFO_BRIDGE_URL", "http://100.81.31.74:9301"),
    "UFO_BRIDGE_TOKEN_FILE": "/app/ufo_bridge_token.txt",
    "UFO_BRIDGE_JOB_TIMEOUT": "1800",
})

with open(path, "w") as f:
    for k, v in env.items():
        f.write(f"{k}={v}\n")
print("env keys:", " ".join(sorted(env)))
PY

# mount the bridge token into the container read-only
python3 - <<'PY'
import re
p = "docker-compose.yml"
s = open(p).read()
if "ufo_bridge_token.txt" not in s:
    s = s.replace("    volumes:\n      - runner-data:/data",
                  "    volumes:\n      - runner-data:/data\n"
                  "      - ./ufo_bridge_token.txt:/app/ufo_bridge_token.txt:ro")
    open(p, "w").write(s)
print(open(p).read())
PY
