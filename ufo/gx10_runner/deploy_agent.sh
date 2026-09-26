#!/usr/bin/env bash
# Merge agent-runner settings into the runner .env (secrets are never echoed).
set -euo pipefail
RUNNER_DIR="${RUNNER_DIR:-${HOME}/ufo-tg-runner-bootstrap}"
cd "$RUNNER_DIR"

python3 - <<'PY'
import os
import re

path = ".env"
env = {}
if os.path.exists(path):
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()


def put(key, default=""):
    # An exported shell value wins, then an existing .env value, then the
    # conservative default.  This makes the script safe to re-run.
    value = os.environ.get(key)
    if value is None:
        value = env.get(key)
    env[key] = default if value is None or value == "" else value


# Local vLLM remains the default.  LLM_* aliases allow the same image to use
# Featherless without changing the Telegram runner code.
put("VLLM_URL", "http://172.17.0.1:8000/v1")
put("VLLM_MODEL", "qwen-abliterated")
put("LLM_BASE_URL", env.get("VLLM_URL", "http://172.17.0.1:8000/v1"))
put("LLM_MODEL", env.get("VLLM_MODEL", "qwen-abliterated"))
put("AGENT_MAX_TURNS", "8")
put("AGENT_HISTORY_TURNS", "8")
put("LLM_TIMEOUT", "180")
put("ALLOW_WEB", "0")

# BrowserAct is opt-in.  Set BROWSERACT_ENABLED=1 and ensure a browser identity
# already exists; the wrapper never creates or deletes BrowserAct identities.
put("BROWSERACT_ENABLED", "0")
put("BROWSERACT_CLI", "browser-act")
put("BROWSERACT_CLI_PATH", "")
put("BROWSERACT_BROWSER_ID", "")
put("BROWSERACT_TIMEOUT", "300")
put("BROWSERACT_COMMAND_TIMEOUT_SECONDS", env.get("BROWSERACT_TIMEOUT", "300"))
put("BROWSERACT_ALLOWED_DOMAINS", "")
put("BROWSERACT_REQUIRE_DOMAIN_ALLOWLIST", "0")
put("BROWSERACT_ALLOW_PRIVATE_NETWORKS", "0")
put("BROWSERACT_ALLOW_ABOUT_BLANK", "1")
put("BROWSERACT_AUTO_SELECT_SINGLE", "1")
put("BROWSERACT_ALLOW_STEALTH_EXTRACT", "0")
put("BROWSERACT_SKILL_VERSION", "")
for path_key in ("BROWSERACT_CLI_PATH", "BROWSERACT_CLI"):
    path_value = str(env.get(path_key, ""))
    if re.match(r"^[A-Za-z]:[\\/]", path_value) or "\\" in path_value:
        env[path_key] = "" if path_key == "BROWSERACT_CLI_PATH" else "browser-act"

# Preserve explicitly exported FEATHERLESS_API_KEY/BROWSERACT_API_KEY values,
# but never print or synthesize them here.
for secret_key in ("FEATHERLESS_API_KEY", "BROWSERACT_API_KEY", "LLM_API_KEY"):
    if secret_key in os.environ:
        env[secret_key] = os.environ[secret_key]

# Build the optional CLI into the image when the navigation arm is enabled.
# An explicit INSTALL_BROWSERACT value always wins.
if "INSTALL_BROWSERACT" not in os.environ and not env.get("INSTALL_BROWSERACT"):
    enabled = str(env.get("BROWSERACT_ENABLED", "0")).strip().lower()
    env["INSTALL_BROWSERACT"] = "1" if enabled in {"1", "true", "yes", "on"} else "0"
else:
    env["INSTALL_BROWSERACT"] = os.environ.get("INSTALL_BROWSERACT", env.get("INSTALL_BROWSERACT", "0"))

# Windows UFO/Venus bridge over the tailnet.
put("UFO_BRIDGE_URL", "http://100.113.176.84:9301")
put("UFO_BRIDGE_TOKEN_FILE", "/app/ufo_bridge_token.txt")
put("UFO_BRIDGE_JOB_TIMEOUT", "1800")

with open(path, "w", encoding="utf-8") as handle:
    for key, value in env.items():
        handle.write(f"{key}={value}\n")
print("env keys:", " ".join(sorted(env)))
PY

# Mount the bridge token into the container read-only when the deployment has
# one.  The runner reads it only for the authenticated bridge tool.
python3 - <<'PY'
from pathlib import Path

path = Path("docker-compose.yml")
text = path.read_text(encoding="utf-8")
if "ufo_bridge_token.txt" not in text:
    text = text.replace(
        "    volumes:\n      - runner-data:/data",
        "    volumes:\n      - runner-data:/data\n"
        "      - ./ufo_bridge_token.txt:/app/ufo_bridge_token.txt:ro",
    )
    path.write_text(text, encoding="utf-8")
print(path.read_text(encoding="utf-8"))
PY
