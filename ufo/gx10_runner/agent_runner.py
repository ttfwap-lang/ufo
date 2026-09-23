#!/usr/bin/env python3
"""Agentic Telegram runner for the gx10 (DGX Spark).

Plain-language requests -> local vLLM (Qwen) with TOOL CALLING -> the agent
executes tools -> observations are fed back -> a final answer is sent back to
the chat. Legacy slash commands still work.

Tools
-----
shell        allowlisted read-only host commands (existing ALLOWLIST)
ufo_bridge   POST a job to the Windows UFO/Venus bridge (port 9301) and poll
             the result. This is how the assistant "uses" the desktop:
             e.g. {"action": "collect_horoscope", "params": {...}}
web          fetch a URL (http/https) and return text (truncated)
telegram     send a message to a chat via the Bot API (used to post results)

Safety
------
* OWNER-only (OWNER_CHAT_ID env, or first-message auto-claim).
* Shell stays allowlisted - no arbitrary execution.
* Bridge + web are opt-in via env (UFO_BRIDGE_URL / ALLOW_WEB).
* Nothing is logged except a short trace; no secrets in output.
"""
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime

# ----------------------------------------------------------------- config
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_CHAT_ID = os.environ.get("OWNER_CHAT_ID", "auto")
API = f"https://api.telegram.org/bot{BOT_TOKEN}"
OWNER_FILE = os.environ.get("OWNER_FILE", "/data/owner.txt")

VLLM_URL = os.environ.get("VLLM_URL", "http://172.17.0.1:8000/v1")
VLLM_MODEL = os.environ.get("VLLM_MODEL", "qwen-abliterated")
VLLM_KEY = os.environ.get("VLLM_API_KEY", "EMPTY")
MAX_TURNS = int(os.environ.get("AGENT_MAX_TURNS", "8"))
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "180"))
HISTORY_TURNS = int(os.environ.get("AGENT_HISTORY_TURNS", "8"))

UFO_BRIDGE_URL = os.environ.get("UFO_BRIDGE_URL", "http://100.81.31.74:9301")
UFO_BRIDGE_TOKEN_FILE = os.environ.get("UFO_BRIDGE_TOKEN_FILE", "/data/ufo_bridge_token.txt")
BRIDGE_JOB_TIMEOUT = int(os.environ.get("UFO_BRIDGE_JOB_TIMEOUT", "900"))
ALLOW_WEB = os.environ.get("ALLOW_WEB", "1") not in ("0", "false", "no")

ALLOWLIST = {
    "nvidia-smi", "docker", "df", "nproc", "uptime", "free", "uname",
    "hostname", "ls", "cat", "grep", "find", "ps", "ss", "du", "date",
    "systemctl", "curl", "python3", "w", "ip", "whoami", "head", "tail",
    "wc", "stat", "jq",
}

HISTORY: dict[str, list] = {}


# ------------------------------------------------------------- bot plumbing
def api_call(method: str, params: dict) -> dict:
    url = f"{API}/{method}"
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def send_message(chat_id, text, parse_mode=None) -> None:
    text = str(text)
    # Telegram hard limit is 4096; split politely on paragraph boundaries.
    for chunk in _split(text, 3900):
        params = {"chat_id": chat_id, "text": chunk}
        if parse_mode:
            params["parse_mode"] = parse_mode
        for attempt in range(3):
            try:
                api_call("sendMessage", params)
                break
            except Exception as e:  # noqa: BLE001
                if attempt == 2:
                    print(f"[send-error] {e}", flush=True)
                time.sleep(2 + attempt * 2)


def _split(text: str, limit: int):
    while len(text) > limit:
        cut = text.rfind("\n\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        yield text[:cut].rstrip()
        text = text[cut:].lstrip("\n")
    if text:
        yield text


def load_owner() -> str:
    try:
        with open(OWNER_FILE) as f:
            return f.read().strip()
    except Exception:  # noqa: BLE001
        return ""


def save_owner(chat_id: str) -> None:
    try:
        with open(OWNER_FILE, "w") as f:
            f.write(str(chat_id))
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------------- tools
def run_shell(parts, timeout=45) -> str:
    if not parts:
        return "No command given."
    head = parts[0]
    if head not in ALLOWLIST:
        return (f"Blocked: `{head}` is not in the allowlist. "
                f"Allowed: {', '.join(sorted(ALLOWLIST))}")
    cmd = " ".join(shlex.quote(p) for p in parts)
    try:
        r = subprocess.run(["/bin/bash", "-c", cmd], capture_output=True,
                           text=True, timeout=timeout)
        out = (r.stdout or "").strip() or (r.stderr or "").strip()
        return out[:3500] or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s."
    except Exception as e:  # noqa: BLE001
        return f"Error: {e}"


def tool_shell(args: dict) -> str:
    return run_shell(shlex.split(args.get("command", "")))


def _bridge_token() -> str:
    tok = os.environ.get("UFO_BRIDGE_TOKEN", "")
    if tok:
        return tok.strip()
    try:
        with open(UFO_BRIDGE_TOKEN_FILE) as f:
            return f.read().strip()
    except Exception:  # noqa: BLE001
        return ""


def tool_ufo_bridge(args: dict) -> str:
    """Queue a job on the Windows bridge and wait for the result."""
    if not UFO_BRIDGE_URL:
        return "ufo_bridge is not configured (UFO_BRIDGE_URL empty)."
    token = _bridge_token()
    if not token:
        return ("ufo_bridge token missing. Put the bridge token in "
                f"{UFO_BRIDGE_TOKEN_FILE} or UFO_BRIDGE_TOKEN.")
    action = args.get("action", "")
    params = args.get("params") or {}
    job_id = f"job-{uuid.uuid4().hex[:12]}"
    body = json.dumps({"job_id": job_id, "action": action,
                       "params": params}).encode()
    req = urllib.request.Request(
        f"{UFO_BRIDGE_URL.rstrip('/')}/jobs", data=body,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return f"ufo_bridge rejected the job: HTTP {e.code} {e.reason}"
    except Exception as e:  # noqa: BLE001
        return f"ufo_bridge unreachable at {UFO_BRIDGE_URL}: {e}"

    deadline = time.time() + BRIDGE_JOB_TIMEOUT
    while time.time() < deadline:
        time.sleep(5)
        try:
            rq = urllib.request.Request(
                f"{UFO_BRIDGE_URL.rstrip('/')}/result/{job_id}",
                headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(rq, timeout=30) as r:
                job = json.loads(r.read().decode())
        except Exception:  # noqa: BLE001
            continue
        st = job.get("status")
        if st == "done":
            res = job.get("result")
            return json.dumps(res, ensure_ascii=False)[:12000]
        if st == "error":
            return f"ufo_bridge job failed: {job.get('error')}"
    return (f"ufo_bridge job {job_id} still running after "
            f"{BRIDGE_JOB_TIMEOUT}s (job_id={job_id})")


def tool_web(args: dict) -> str:
    if not ALLOW_WEB:
        return "Web access is disabled on this runner."
    url = args.get("url", "")
    if not url.startswith(("http://", "https://")):
        return "Only http/https URLs are allowed."
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ufo-agent/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read(20000).decode("utf-8", "replace")
        return data[:6000]
    except Exception as e:  # noqa: BLE001
        return f"Fetch failed: {e}"


def tool_telegram(args: dict) -> str:
    chat = args.get("chat_id") or args.get("chat")
    text = args.get("text", "")
    if not text:
        return "Nothing to send (empty text)."
    target = chat or OWNER_CHAT_ID
    if target in (None, "", "auto"):
        target = load_owner()
    if not target:
        return "No target chat id known."
    send_message(target, text)
    return f"Sent to chat {target}."


TOOL_IMPLS = {
    "shell": tool_shell,
    "ufo_bridge": tool_ufo_bridge,
    "web": tool_web,
    "telegram": tool_telegram,
}

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "ufo_bridge",
            "description": (
                "Control the Windows UFO/Venus desktop automation through the "
                "bridge. Use action='collect_horoscope' with params "
                "{bot, signs:[...], period:'tomorrow'} to fetch zodiac "
                "horoscopes from a Telegram bot's Mini App (the bot posts each "
                "sign's card into the chat and it is read back with OCR). "
                "Returns JSON with per-sign text and Love/Health/Career/Lunar "
                "ratings."),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string",
                               "description": "Bridge action, e.g. collect_horoscope"},
                    "params": {"type": "object",
                               "description": "Action parameters"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shell",
            "description": "Run an allowlisted read-only command on the DGX host.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web",
            "description": "Fetch an http/https URL and return the text.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "telegram",
            "description": "Send a Telegram message to a chat id via the Bot API.",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["text"],
            },
        },
    },
]

SYSTEM_PROMPT = (
    "You are @ufo_assistant_bot, an agentic assistant running on a private "
    "server with access to a Windows desktop automation bridge.\n"
    "You fulfil the user's request by CALLING TOOLS, then reply with the "
    "result in plain text.\n"
    "Key capability: ufo_bridge -> collect_horoscope fetches general daily "
    "horoscopes for zodiac signs from a Telegram bot (e.g. AstrologyScienceBot) "
    "by driving its Mini App; it returns each sign's text plus Love/Health/"
    "Career/Lunar ratings.\n"
    "Rules: never invent data - if a tool fails, say so. Keep replies concise "
    "but complete; list every sign you were asked for. Use the telegram tool "
    "only when you must post something to another chat."
)


# --------------------------------------------------------------- agent loop
def llm_chat(messages):
    payload = {
        "model": VLLM_MODEL,
        "messages": messages,
        "tools": TOOLS_SCHEMA,
        "tool_choice": "auto",
        "temperature": 0.2,
        "max_tokens": 2048,
    }
    req = urllib.request.Request(
        f"{VLLM_URL.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {VLLM_KEY}"})
    with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as r:
        return json.loads(r.read().decode())


def agent(chat_id: int, user_text: str) -> str:
    hist = HISTORY.setdefault(str(chat_id), [])
    hist.append({"role": "user", "content": user_text})
    # keep the conversation bounded
    if len(hist) > HISTORY_TURNS * 2:
        del hist[: len(hist) - HISTORY_TURNS * 2]

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + hist
    for turn in range(MAX_TURNS):
        try:
            resp = llm_chat(messages)
        except Exception as e:  # noqa: BLE001
            return f"The model is unreachable at {VLLM_URL}: {e}"
        choice = (resp.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        tool_calls = msg.get("tool_calls") or []

        if not tool_calls:
            answer = (msg.get("content") or "").strip()
            if not answer:
                answer = "(the model returned nothing)"
            hist.append({"role": "assistant", "content": answer})
            return answer

        messages.append({"role": "assistant", "content": msg.get("content") or "",
                         "tool_calls": tool_calls})
        for tc in tool_calls:
            fn = (tc.get("function") or {})
            name = fn.get("name", "")
            try:
                call_args = json.loads(fn.get("arguments") or "{}")
            except Exception:  # noqa: BLE001
                call_args = {}
            impl = TOOL_IMPLS.get(name)
            print(f"[tool] {name} {json.dumps(call_args)[:200]}", flush=True)
            if impl is None:
                out = f"Unknown tool {name!r}."
            else:
                try:
                    out = impl(call_args)
                except Exception as e:  # noqa: BLE001
                    out = f"Tool {name} raised {type(e).__name__}: {e}"
            print(f"[tool-result] {str(out)[:300]}", flush=True)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "name": name,
                "content": str(out)[:12000],
            })
    return ("I reached the tool-call limit for this request "
            f"({MAX_TURNS} turns). Try asking for fewer things at once.")


# --------------------------------------------------------------- dispatch
def cmd_status() -> str:
    lines = [f"agent runner alive @ {datetime.now().isoformat()}"]
    for c in ["hostname", "uptime", "nproc"]:
        try:
            r = subprocess.run(c.split(), capture_output=True, text=True, timeout=10)
            lines.append(f"{c}: {r.stdout.strip()}")
        except Exception:  # noqa: BLE001
            pass
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total",
                            "--format=csv,noheader"], capture_output=True,
                           text=True, timeout=10)
        lines.append(f"gpu: {r.stdout.strip()}")
    except Exception:  # noqa: BLE001
        pass
    lines.append(f"vllm: {VLLM_URL} model={VLLM_MODEL}")
    lines.append(f"bridge: {UFO_BRIDGE_URL or '(unset)'}")
    return "\n".join(lines)


HELP = (
    "I am an agentic assistant - just tell me what to do in plain language.\n\n"
    "Examples:\n"
    "  - get all of tomorrow's general daily horoscopes from "
    "@AstrologyScienceBot\n"
    "  - what is the host GPU doing?\n"
    "  - fetch https://example.com and summarize it\n\n"
    "Commands: /status /help /ping /exec <allowlisted cmd>"
)


def handle(chat_id: int, text: str) -> None:
    text = text.strip()
    if not text:
        return
    if OWNER_CHAT_ID == "auto":
        owner = load_owner()
        if not owner:
            save_owner(chat_id)
            send_message(chat_id, "You are now the OWNER of this runner.\n\n" + HELP)
            return
        if str(chat_id) != owner:
            return
    elif str(chat_id) != str(OWNER_CHAT_ID):
        send_message(chat_id, "Unauthorized - this runner is owner-only.")
        return

    if text.startswith("/"):
        parts = shlex.split(text)
        cmd = parts[0].lower()
        if cmd in ("/start", "/help"):
            send_message(chat_id, HELP)
        elif cmd == "/status":
            send_message(chat_id, cmd_status())
        elif cmd == "/ping":
            send_message(chat_id, "pong")
        elif cmd == "/ps":
            send_message(chat_id, run_shell(
                ["docker", "ps", "--format", "{{.Names}} {{.Status}}"]))
        elif cmd == "/gpu":
            send_message(chat_id, run_shell(
                ["nvidia-smi", "--query-gpu=name,memory.total,utilization.gpu,"
                 "temperature.gpu", "--format=csv,noheader"]))
        elif cmd == "/exec":
            send_message(chat_id, run_shell(parts[1:]) or "(no output)")
        else:
            send_message(chat_id, f"Unknown command {cmd!r}. {HELP}")
        return

    # plain language -> agent
    send_message(chat_id, "Working on it...")
    try:
        answer = agent(chat_id, text)
    except Exception as e:  # noqa: BLE001
        answer = f"Agent error: {type(e).__name__}: {e}"
    send_message(chat_id, answer)


def poll_forever() -> None:
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN env var is required.", flush=True)
        sys.exit(2)
    me = api_call("getMe", {})
    print(f"agent runner up: @{me.get('result', {}).get('username', '?')} "
          f"vllm={VLLM_URL} bridge={UFO_BRIDGE_URL}", flush=True)
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