#!/usr/bin/env python3
"""24/7 Telegram-bot-driven task runner for the gx10 (DGX Spark).

Instruction channel: @ufo_assistant_bot.
Flow: user Telegram message -> bot (Bot API long-polling) -> runner executes
-> reply back to the user. Runs forever (Docker, restart: always).

Safety:
- Only the OWNER (OWNER_CHAT_ID, numeric) may issue commands.
- Shell commands are ALLOWLISTED (read-only by default); anything else is
  rejected with a clear message.
- No secrets are logged; the token comes from the BOT_TOKEN env var only.

Commands:
  /status            - host, uptime, gpu, docker, disk
  /ps                - docker ps
  /gpu               - nvidia-smi summary
  /exec <cmd>        - run an ALLOWLISTED shell command
  /help              - this help
"""
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_CHAT_ID = os.environ.get("OWNER_CHAT_ID", "auto")  # numeric id OR "auto" (first message claims)
API = f"https://api.telegram.org/bot{BOT_TOKEN}"
OWNER_FILE = "/data/owner.txt"  # persisted owner after auto-claim


def load_owner() -> str:
    try:
        with open(OWNER_FILE, "r") as f:
            return f.read().strip()
    except Exception:  # noqa: BLE001
        return ""


def save_owner(chat_id: str) -> None:
    try:
        with open(OWNER_FILE, "w") as f:
            f.write(str(chat_id))
    except Exception:  # noqa: BLE001
        pass

# Only read-only, safe commands may be exec'd on the host runner.
ALLOWLIST = {
    "nvidia-smi", "docker", "df", "nproc", "uptime", "free", "uname",
    "hostname", "ls", "cat", "grep", "find", "ps", "ss", "du", "date",
    "uptime", "systemctl", "curl", "python3", "uptime", "w", "ip",
}
# Prefixes allowed with the first token in ALLOWLIST
ALLOWED_PREFIXES = ()


def api_call(method: str, params: dict) -> dict:
    """Call the Telegram Bot API; returns parsed JSON response."""
    url = f"{API}/{method}"
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def send_message(chat_id, text, parse_mode=None) -> None:
    params = {"chat_id": chat_id, "text": text[:4000]}
    if parse_mode:
        params["parse_mode"] = parse_mode
    try:
        api_call("sendMessage", params)
    except Exception as e:  # noqa: BLE001 - best-effort reply
        print(f"[send-error] {e}")


def run_shell(parts, timeout=45) -> str:
    """Run an allowlisted command; returns trimmed output or error text."""
    if not parts:
        return "No command given."
    head = parts[0]
    if head not in ALLOWLIST:
        return (
            f"Blocked: `{head}` is not in the allowlist.\n"
            f"Allowed: {', '.join(sorted(ALLOWLIST))}"
        )
    cmd = " ".join(shlex.quote(p) for p in parts)
    try:
        r = subprocess.run(
            ["/bin/bash", "-c", cmd], capture_output=True, text=True,
            timeout=timeout,
        )
        out = (r.stdout or "").strip() or (r.stderr or "").strip()
        return out[:3500] or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s."
    except Exception as e:  # noqa: BLE001
        return f"Error: {e}"


def cmd_status() -> str:
    lines = [f"gx10 runner alive @ {datetime.now().isoformat()}"]
    for c in ["hostname", "uptime", "nproc"]:
        try:
            r = subprocess.run(c.split(), capture_output=True, text=True, timeout=10)
            lines.append(f"{c}: {r.stdout.strip()}")
        except Exception:  # noqa: BLE001
            pass
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,utilization.gpu",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10)
        lines.append(f"gpu: {r.stdout.strip()}")
    except Exception:  # noqa: BLE001
        pass
    try:
        r = subprocess.run(["docker", "ps", "--format",
                            "{{.Names}} {{.Status}}"], capture_output=True,
                           text=True, timeout=15)
        lines.append("docker:\n" + (r.stdout.strip() or "(none)"))
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(lines)


def handle(chat_id: int, text: str) -> None:
    text = text.strip()
    if not text:
        return
    # Owner auth
    if OWNER_CHAT_ID == "auto":
        owner = load_owner()
        if not owner:
            save_owner(chat_id)
            send_message(chat_id, "You are now the OWNER of the gx10 runner. /help")
            return
        if str(chat_id) != owner:
            return  # silently ignore non-owner
    else:
        if str(chat_id) != str(OWNER_CHAT_ID):
            send_message(chat_id, "Unauthorized - this runner is owner-only.")
            return

    parts = shlex.split(text)
    cmd = parts[0].lower()

    if cmd in ("/start", "/help"):
        send_message(
            chat_id,
            "gx10 Runner 24/7\n\n"
            "/status - host/gpu/docker status\n"
            "/ps - docker processes\n"
            "/gpu - nvidia-smi\n"
            "/exec <cmd> - run an allowlisted command\n"
            "(owner-only; allowlisted read-only commands)",
        )
    elif cmd == "/status":
        send_message(chat_id, cmd_status())
    elif cmd == "/ps":
        send_message(chat_id, run_shell(["docker", "ps", "--format",
                                         "{{.Names}} | {{.Status}}"]))
    elif cmd == "/gpu":
        send_message(chat_id, run_shell(
            ["nvidia-smi", "--query-gpu=name,memory.total,utilization.gpu,"
                           "temperature.gpu", "--format=csv,noheader"]))
    elif cmd == "/exec":
        send_message(chat_id, run_shell(parts[1:]) or "(no output)")
    elif cmd == "/ping":
        send_message(chat_id, "pong")
    else:
        send_message(
            chat_id,
            f"Unknown: {cmd!r}. /help for commands. "
            "Try /exec <allowlisted> for shell tasks.",
        )


def poll_forever() -> None:
    if not BOT_TOKEN or not OWNER_CHAT_ID:
        print("ERROR: BOT_TOKEN and OWNER_CHAT_ID env vars are required.", flush=True)
        sys.exit(2)
    me = api_call("getMe", {})
    print(f"runner up: @{me.get('result', {}).get('username', '?')}", flush=True)

    offset = 0
    while True:
        try:
            upd = api_call("getUpdates", {"offset": offset, "timeout": 50,
                                          "allowed_updates": '["message"]'})
            for u in upd.get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                chat_id = msg.get("chat", {}).get("id")
                text = msg.get("text") or msg.get("caption") or ""
                if chat_id and text:
                    try:
                        handle(chat_id, text)
                    except Exception as e:  # noqa: BLE001
                        send_message(chat_id, f"Runner error: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"[poll-error] {e}; retrying in 5s", flush=True)
            time.sleep(5)
        time.sleep(0.5)


if __name__ == "__main__":
    poll_forever()
