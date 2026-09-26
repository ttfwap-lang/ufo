#!/usr/bin/env python3
"""Agentic Telegram runner for the gx10 (DGX Spark).

Plain-language requests -> local vLLM (Qwen) with TOOL CALLING -> the agent
executes tools -> observations are fed back -> a final answer is sent back to
the chat. Legacy slash commands still work.

Tools
-----
host_status  fixed, read-only DGX health commands (GPU, disk, containers)
ufo_bridge   POST a job to the Windows UFO/Venus bridge (port 9301) and poll
             the result. This is how the assistant "uses" the desktop:
             e.g. {"action": "collect_horoscope", "params": {...}}
web          fetch a URL (http/https) and return text (truncated)
telegram     send a message to the owner chat via the Bot API

Safety
------
* OWNER-only (OWNER_CHAT_ID env, or first-message auto-claim).
* No model-facing shell tool; host status uses fixed-argv handlers only.
* Bridge + web are opt-in via env (UFO_BRIDGE_URL / ALLOW_WEB).
* Nothing is logged except a short trace; no secrets in output.
"""
import atexit
import ipaddress
import json
import os
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime

try:  # Package import when loaded as ufo.gx10_runner.agent_runner.
    from .browseract_navigation import (
        BrowserActError,
        BrowserActNavigator,
    )
    from .browseract_navigation import (
        is_mutation as is_browseract_mutation,
    )
except ImportError:  # Script import when run as gx10_runner/agent_runner.py.
    try:
        from browseract_navigation import (
            BrowserActError,
            BrowserActNavigator,
        )
        from browseract_navigation import (
            is_mutation as is_browseract_mutation,
        )
    except ImportError:  # Optional until the BrowserAct image extra is enabled.
        BrowserActError = RuntimeError
        BrowserActNavigator = None
        is_browseract_mutation = None


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", "disabled", ""}


def _env_int(name: str, default: int, *, minimum: int = 1, maximum: int = 300) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


# ----------------------------------------------------------------- config
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_CHAT_ID = os.environ.get("OWNER_CHAT_ID", "auto")
API = f"https://api.telegram.org/bot{BOT_TOKEN}"
OWNER_FILE = os.environ.get("OWNER_FILE", "/data/owner.txt")

# Generic provider settings.  VLLM_* remain supported aliases so existing
# deployments keep working; set LLM_BASE_URL=https://api.featherless.ai/v1,
# LLM_API_KEY=$FEATHERLESS_API_KEY, and a Qwen 3 model to use Featherless.
VLLM_URL = os.environ.get("VLLM_URL") or "http://172.17.0.1:8000/v1"
VLLM_MODEL = os.environ.get("VLLM_MODEL") or "qwen-abliterated"
VLLM_KEY = os.environ.get("VLLM_API_KEY") or "EMPTY"
LLM_BASE_URL = os.environ.get("LLM_BASE_URL") or VLLM_URL
if os.environ.get("LLM_MODEL") or os.environ.get("FEATHERLESS_MODEL"):
    LLM_MODEL = os.environ.get("LLM_MODEL") or os.environ.get("FEATHERLESS_MODEL")
elif "featherless.ai" in LLM_BASE_URL.lower():
    LLM_MODEL = "Qwen/Qwen3.8-Flash-Next"
else:
    LLM_MODEL = VLLM_MODEL
if "featherless.ai" in LLM_BASE_URL.lower():
    LLM_API_KEY = (
        os.environ.get("LLM_API_KEY")
        or os.environ.get("FEATHERLESS_API_KEY")
        or os.environ.get("VLLM_API_KEY")
        or "EMPTY"
    )
else:
    LLM_API_KEY = (
        os.environ.get("LLM_API_KEY")
        or os.environ.get("VLLM_API_KEY")
        or os.environ.get("FEATHERLESS_API_KEY")
        or VLLM_KEY
    )
if LLM_API_KEY.startswith("$"):
    reference = LLM_API_KEY[2:-1] if LLM_API_KEY.startswith("${") and LLM_API_KEY.endswith("}") else LLM_API_KEY[1:]
    LLM_API_KEY = os.environ.get(reference, "")
MAX_TURNS = _env_int("AGENT_MAX_TURNS", 8, minimum=1, maximum=100)
LLM_TIMEOUT = _env_int("LLM_TIMEOUT", 180, minimum=10, maximum=600)
HISTORY_TURNS = _env_int("AGENT_HISTORY_TURNS", 8, minimum=1, maximum=100)

BROWSERACT_ENABLED = _env_bool("BROWSERACT_ENABLED", False)
BROWSERACT_CLI = os.environ.get("BROWSERACT_CLI_PATH") or os.environ.get("BROWSERACT_CLI") or "browser-act"
if len(BROWSERACT_CLI) >= 3 and BROWSERACT_CLI[1] == ":" and BROWSERACT_CLI[2] in "\\/":
    BROWSERACT_CLI = "browser-act"
BROWSERACT_BROWSER_ID = os.environ.get("BROWSERACT_BROWSER_ID", "")
BROWSERACT_TIMEOUT = _env_int(
    "BROWSERACT_COMMAND_TIMEOUT_SECONDS",
    _env_int("BROWSERACT_TIMEOUT", 300, minimum=30, maximum=300),
    minimum=30,
    maximum=300,
)
BROWSERACT_MAX_INPUT_CHARS = _env_int("BROWSERACT_MAX_INPUT_CHARS", 10_000, minimum=1, maximum=100_000)
BROWSERACT_MAX_OUTPUT_CHARS = _env_int(
    "BROWSERACT_MAX_OUTPUT_CHARS", 30_000, minimum=1_000, maximum=500_000
)
BROWSERACT_MAX_STATE_CHARS = _env_int(
    "BROWSERACT_MAX_STATE_CHARS", 30_000, minimum=1_000, maximum=500_000
)
BROWSERACT_ALLOWED_DOMAINS = os.environ.get("BROWSERACT_ALLOWED_DOMAINS", "")
BROWSERACT_REQUIRE_DOMAIN_ALLOWLIST = _env_bool("BROWSERACT_REQUIRE_DOMAIN_ALLOWLIST", False)
BROWSERACT_ALLOW_PRIVATE_NETWORKS = _env_bool("BROWSERACT_ALLOW_PRIVATE_NETWORKS", False)
BROWSERACT_ALLOW_ABOUT_BLANK = _env_bool("BROWSERACT_ALLOW_ABOUT_BLANK", True)
BROWSERACT_AUTO_SELECT_SINGLE = _env_bool("BROWSERACT_AUTO_SELECT_SINGLE", True)
BROWSERACT_ALLOW_STEALTH_EXTRACT = _env_bool("BROWSERACT_ALLOW_STEALTH_EXTRACT", False)
WEB_ALLOWED_DOMAINS = os.environ.get("UFO_WEB_ALLOWED_DOMAINS", "")

UFO_BRIDGE_URL = os.environ.get("UFO_BRIDGE_URL", "http://100.113.176.84:9301")
UFO_BRIDGE_TOKEN_FILE = os.environ.get("UFO_BRIDGE_TOKEN_FILE", "/data/ufo_bridge_token.txt")
BRIDGE_JOB_TIMEOUT = int(os.environ.get("UFO_BRIDGE_JOB_TIMEOUT", "900"))
ALLOW_WEB = _env_bool("ALLOW_WEB", False)

ALLOWLIST = {
    "nvidia-smi", "docker", "df", "nproc", "uptime", "free", "uname",
    "hostname", "date", "whoami",
}

HISTORY: dict[str, list] = {}


def _browseract_cli_present() -> bool:
    candidate = os.path.expandvars(os.path.expanduser(BROWSERACT_CLI))
    return bool(
        os.path.isfile(candidate)
        or shutil.which(candidate)
        or shutil.which("browser-act")
    )


BROWSERACT_TOOL_ENABLED = BROWSERACT_ENABLED and BrowserActNavigator is not None and _browseract_cli_present()


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
                    print(f"[send-error] {type(e).__name__}", flush=True)
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


def save_owner(chat_id: str) -> bool:
    try:
        with open(OWNER_FILE, "w", encoding="utf-8") as f:
            f.write(str(chat_id))
        return True
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------------- tools
def _safe_shell_parts(parts) -> list[str] | None:
    """Validate the tiny fixed command surface used by slash commands.

    The model-facing tool does not expose this function.  Keeping the slash
    command path fixed-argv and non-shell prevents an allowlisted executable
    such as ``cat`` or ``curl`` from becoming an arbitrary file/network tool.
    """
    if not parts:
        return None
    try:
        command = [str(part) for part in parts]
    except Exception:  # noqa: BLE001
        return None
    head = os.path.basename(command[0])
    args = command[1:]
    if head not in ALLOWLIST:
        return None

    if head == "docker":
        allowed = (["ps", "--format", "{{.Names}} {{.Status}}"],)
    elif head == "nvidia-smi":
        allowed = (
            [],
            ["--query-gpu", "name,memory.total", "--format", "csv,noheader"],
            ["--query-gpu", "name,memory.total,utilization.gpu,temperature.gpu", "--format", "csv,noheader"],
            ["--query-gpu=name,memory.total", "--format=csv,noheader"],
            ["--query-gpu=name,memory.total,utilization.gpu,temperature.gpu", "--format=csv,noheader"],
        )
    elif head in {"df", "free"}:
        allowed = ([], ["-h"], ["--human-readable"], ["-m"])
    elif head == "uname":
        allowed = ([], ["-a"], ["-s"])
    else:
        allowed = ([],)
    if args not in allowed:
        return None
    return [head, *args]


def run_shell(parts, timeout=45) -> str:
    safe_parts = _safe_shell_parts(parts)
    if safe_parts is None:
        return "Blocked: only fixed read-only host status commands are allowed."
    try:
        result = subprocess.run(
            safe_parts,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            close_fds=True,
        )
        out = (result.stdout or "").strip() or (result.stderr or "").strip()
        return out[:3500] or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s."
    except Exception as exc:  # noqa: BLE001
        return f"Error: {type(exc).__name__}"


def tool_host_status(args: dict) -> str:
    """Return fixed host health observations without accepting a command."""
    op = str(args.get("op", "summary")).lower()
    if op == "gpu":
        return run_shell(
            ["nvidia-smi", "--query-gpu", "name,memory.total,utilization.gpu,temperature.gpu", "--format", "csv,noheader"]
        )
    if op == "disk":
        return run_shell(["df", "-h"])
    if op == "containers":
        return run_shell(["docker", "ps", "--format", "{{.Names}} {{.Status}}"])
    if op != "summary":
        return "Unknown host status op; use summary, gpu, disk, or containers."
    return "\n".join(
        part
        for part in (
            run_shell(["hostname"]),
            run_shell(["uptime"]),
            run_shell(["nproc"]),
            run_shell(["nvidia-smi", "--query-gpu", "name,memory.total", "--format", "csv,noheader"]),
        )
        if part
    )


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


def tool_vision(args: dict) -> str:
    """Perceive the Windows desktop with the gx10 vision models.

    ops:
      locate - find a labelled/icon control; returns pixel coordinates in the
               Telegram window bitmap, optionally clicking it
      ask    - ask a question about the current screen (state verification)
      scan   - inventory every element + a description of the current view

    The vision stack on the bridge is UI-Venus-2-9B (grounding) fused with
    WinRT OCR: text labels resolve through OCR phrase boxes, icon-only
    controls are grounded by Venus (median ~2px), and clicks are refused if
    the point would land on window chrome.
    """
    op = (args.get("op") or "locate").lower()
    action = {"locate": "vision_locate",
              "ask": "vision_ask",
              "scan": "vision_scan"}.get(op)
    if not action:
        return (f"unknown vision op {op!r}; use locate | ask | scan")
    params = dict(args.get("params") or {})
    for k in ("label", "question", "prefer", "screenshot", "settle"):
        if k in args and k not in params:
            params[k] = args[k]
    if "click" in args:
        params["click"] = bool(args["click"])
    return tool_ufo_bridge({"action": action, "params": params})


def _web_domain_allowed(hostname: str) -> bool:
    domains = tuple(
        item.strip().lower().rstrip(".").removeprefix("*.")
        for item in WEB_ALLOWED_DOMAINS.split(",")
        if item.strip()
    )
    if not domains:
        return True
    host = hostname.lower().rstrip(".")
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def _validate_web_url(url: str) -> str:
    value = str(url or "").strip()
    try:
        parsed = urllib.parse.urlsplit(value)
        hostname = parsed.hostname
    except ValueError as exc:
        raise ValueError("invalid URL") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not hostname:
        raise ValueError("only public http/https URLs are allowed")
    if parsed.username or parsed.password:
        raise ValueError("URL credentials are not allowed")
    if not _web_domain_allowed(hostname):
        raise ValueError("URL domain is not in the configured allowlist")
    host = hostname.lower().rstrip(".")
    try:
        address = ipaddress.ip_address(host)
        addresses = [address]
    except ValueError:
        try:
            addresses = [
                ipaddress.ip_address(str(info[4][0]))
                for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
            ]
        except OSError as exc:
            raise ValueError("URL hostname could not be resolved") from exc
    if any(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
        for address in addresses
    ):
        raise ValueError("private/local URL targets are disabled")
    return value


class _PublicRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        _validate_web_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def tool_web(args: dict) -> str:
    if not ALLOW_WEB:
        return "Web access is disabled on this runner."
    try:
        url = _validate_web_url(args.get("url", ""))
        request = urllib.request.Request(
            url, headers={"User-Agent": "ufo-agent/1.0"}
        )
        opener = urllib.request.build_opener(
            _PublicRedirectHandler(), urllib.request.ProxyHandler({})
        )
        with opener.open(request, timeout=30) as response:
            data = response.read(20000).decode("utf-8", "replace")
        return data[:6000]
    except Exception as exc:  # noqa: BLE001
        return f"Fetch failed: {type(exc).__name__}: {exc}"


_BROWSERACT_NAVIGATOR = None


def tool_browseract(args: dict) -> str:
    """Run one constrained BrowserAct navigation action when enabled."""
    if not BROWSERACT_ENABLED or BrowserActNavigator is None:
        return json.dumps(
            {
                "ok": False,
                "error": "BrowserAct is disabled or unavailable in this runner",
                "error_type": "BrowserActUnavailable",
            }
        )
    global _BROWSERACT_NAVIGATOR
    try:
        if _BROWSERACT_NAVIGATOR is None:
            _BROWSERACT_NAVIGATOR = BrowserActNavigator(
                cli_path=BROWSERACT_CLI,
                browser_id=BROWSERACT_BROWSER_ID,
                timeout_seconds=BROWSERACT_TIMEOUT,
                allow_private_networks=BROWSERACT_ALLOW_PRIVATE_NETWORKS,
                allowed_domains=BROWSERACT_ALLOWED_DOMAINS,
                require_domain_allowlist=BROWSERACT_REQUIRE_DOMAIN_ALLOWLIST,
                allow_about_blank=BROWSERACT_ALLOW_ABOUT_BLANK,
                max_input_chars=BROWSERACT_MAX_INPUT_CHARS,
                max_output_chars=BROWSERACT_MAX_OUTPUT_CHARS,
                max_state_chars=BROWSERACT_MAX_STATE_CHARS,
                auto_select_single=BROWSERACT_AUTO_SELECT_SINGLE,
                allow_stealth_extract=BROWSERACT_ALLOW_STEALTH_EXTRACT,
            )
        return _BROWSERACT_NAVIGATOR.execute(args)
    except BrowserActError as exc:
        return json.dumps({"ok": False, "error": str(exc), "error_type": "BrowserActError"})
    except Exception as exc:  # noqa: BLE001
        return json.dumps(
            {
                "ok": False,
                "error": f"BrowserAct tool failed: {type(exc).__name__}",
                "error_type": type(exc).__name__,
            }
        )


def close_browseract_session() -> None:
    """Close the owned BrowserAct session during normal process shutdown."""
    global _BROWSERACT_NAVIGATOR
    navigator = _BROWSERACT_NAVIGATOR
    if navigator is None:
        return
    keep_navigator = False
    try:
        if getattr(navigator, "session", None):
            result = navigator.close()
            if isinstance(result, str):
                try:
                    keep_navigator = json.loads(result).get("ok") is False
                except (TypeError, ValueError):
                    keep_navigator = True
    except Exception as exc:  # noqa: BLE001
        keep_navigator = True
        print(f"[browseract-cleanup] {type(exc).__name__}", flush=True)
    if not keep_navigator:
        _BROWSERACT_NAVIGATOR = None


atexit.register(close_browseract_session)


def tool_telegram(args: dict) -> str:
    requested = args.get("chat_id") or args.get("chat")
    text = args.get("text", "")
    if not text:
        return "Nothing to send (empty text)."
    owner_target = load_owner() if OWNER_CHAT_ID == "auto" else OWNER_CHAT_ID
    if not owner_target:
        return "No owner chat id is configured."
    if requested not in (None, "", "auto") and str(requested) != str(owner_target):
        return "Blocked: telegram is restricted to the owner chat."
    send_message(owner_target, text)
    return f"Sent to owner chat {owner_target}."


TOOL_IMPLS = {
    "host_status": tool_host_status,
    "ufo_bridge": tool_ufo_bridge,
    "vision": tool_vision,
    "web": tool_web,
    "telegram": tool_telegram,
    "browser_action": tool_browseract,
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
            "name": "vision",
            "description": (
                "Perceive the Windows desktop with the gx10 vision models "
                "(UI-Venus-2-9B grounding fused with WinRT OCR).\n"
                "op='locate': find a control by its visible label OR by a "
                "plain description of an icon (e.g. 'the microphone voice "
                "message button'). Set click=true to click it. Clicks on "
                "window chrome are refused automatically.\n"
                "op='ask': ask a yes/no question about the current screen to "
                "verify a step actually worked (e.g. 'Is the zodiac sign "
                "selector grid open?').\n"
                "op='scan': list every element and describe the current view.\n"
                "Use this whenever you need to know WHAT or WHERE something is "
                "on screen - it is far more reliable than guessing coordinates."),
            "parameters": {
                "type": "object",
                "properties": {
                    "op": {"type": "string",
                           "enum": ["locate", "ask", "scan"],
                           "description": "What kind of perception to do."},
                    "label": {
                        "type": "string",
                        "description": "op=locate: the target's visible text or "
                                       "a description of the icon/control."},
                    "question": {
                        "type": "string",
                        "description": "op=ask: the question about the screen."},
                    "click": {
                        "type": "boolean",
                        "description": "op=locate: click the located control."},
                    "prefer": {
                        "type": "string",
                        "enum": ["auto", "venus", "ocr"],
                        "description": "auto (default) = OCR-primary with "
                                       "Venus disambiguation; venus = force the "
                                       "vision point; ocr = no model call."},
                    "screenshot": {
                        "type": "string",
                        "description": "Optional PNG path; omit to capture the "
                                       "Telegram window fresh."},
                },
                "required": ["op"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "host_status",
            "description": (
                "Read fixed DGX health information. This tool never accepts a "
                "command, path, URL, or shell string."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "op": {
                        "type": "string",
                        "enum": ["summary", "gpu", "disk", "containers"],
                    }
                },
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

if not ALLOW_WEB:
    TOOLS_SCHEMA[:] = [
        tool for tool in TOOLS_SCHEMA if tool.get("function", {}).get("name") != "web"
    ]

if BROWSERACT_TOOL_ENABLED:
    TOOLS_SCHEMA.append(
        {
            "type": "function",
            "function": {
                "name": "browser_action",
                "description": (
                    "Use a real BrowserAct browser. Follow open -> state -> one "
                    "mutation -> fresh state. The session and state_token are "
                    "returned by the tool; BrowserAct indexes are ephemeral. "
                    "Never reuse an old index or retry a timed-out mutation. "
                    "Actions: diagnostics, list_browsers, open, state, navigate, "
                    "click, input, select, keys, scroll, scrollintoview, wait, "
                    "get, screenshot, close, stealth_extract."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "diagnostics",
                                "list_browsers",
                                "open",
                                "state",
                                "navigate",
                                "click",
                                "input",
                                "select",
                                "keys",
                                "scroll",
                                "scrollintoview",
                                "wait",
                                "get",
                                "screenshot",
                                "close",
                                "stealth_extract",
                            ],
                            "description": "BrowserAct operation.",
                        },
                        "url": {"type": "string", "description": "HTTP(S) URL."},
                        "browser_id": {
                            "type": "string",
                            "description": "Configured BrowserAct browser ID.",
                        },
                        "session": {
                            "type": "string",
                            "description": "Session handle returned by open/state.",
                        },
                        "state_token": {
                            "type": "string",
                            "description": "Latest state token; required for mutations.",
                        },
                        "index": {"type": "integer", "description": "Current indexed element."},
                        "selector": {"type": "string", "description": "Optional CSS selector."},
                        "text": {"type": "string", "description": "Text to enter."},
                        "option": {"type": "string", "description": "Select option."},
                        "keys": {"type": "string", "description": "Key combination."},
                        "direction": {"type": "string", "enum": ["up", "down"]},
                        "amount": {"type": "integer", "description": "Scroll amount."},
                        "kind": {
                            "type": "string",
                            "enum": ["title", "markdown", "text", "value", "html"],
                        },
                        "mode": {"type": "string", "enum": ["fill", "append"]},
                        "timeout_ms": {"type": "integer", "description": "Wait timeout in milliseconds."},
                        "timeout_seconds": {
                            "type": "integer",
                            "description": "Stealth extraction timeout in seconds.",
                        },
                        "full": {"type": "boolean", "description": "Capture a full-page screenshot."},
                        "content_type": {
                            "type": "string",
                            "enum": ["markdown", "html"],
                            "description": "stealth_extract output type.",
                        },
                    },
                    "required": ["action"],
                },
            },
        }
    )


SYSTEM_PROMPT = (
    "You are @ufo_assistant_bot, an agentic assistant running on a private "
    "server with access to a Windows desktop automation bridge.\n"
    "You fulfil the user's request by CALLING TOOLS, then reply with the "
    "result in plain text.\n"
    "\n"
    "TOOLCHAIN\n"
    "  ufo_bridge -> collect_horoscope fetches general daily horoscopes for "
    "zodiac signs from a Telegram bot (e.g. AstrologyScienceBot) by driving "
    "its Mini App; it returns each sign's text plus Love/Health/Career/Lunar "
    "ratings.\n"
    "  vision -> look at the Windows screen: op='locate' finds a control (by "
    "label or by describing an icon) and can click it, op='ask' verifies what "
    "is on screen, op='scan' inventories everything.\n"
    "  host_status -> fixed read-only DGX health observations (GPU, disk, containers); never a shell command.\n"
    "  web    -> fetch an http/https URL.\n"
    "  browser_action -> BrowserAct real-browser navigation (when enabled): open -> state -> one mutation -> fresh state; indexes and tokens are ephemeral. Use selector instead of an index when appropriate.\n"
    "  telegram -> post a message to a chat.\n"
    "\n"
    "METHOD\n"
    "  * For any multi-step UI task, verify each step with vision op='ask' "
    "before assuming it worked; do not chain blind guesses.\n"
    "  * Prefer a specific visible label over a description of an icon when "
    "one exists - text labels are resolved exactly.\n"
    "  * The vision tool returns the strategy it used (e.g. 'ocr-sole-match', "
    "'venus-disambiguated', 'venus-only'). If a click reports "
    "refused=true, the point landed on window chrome; re-locate with a more "
    "specific label rather than retrying the same call.\n"
    "  * For BrowserAct, issue at most one page mutation in one model response; "
    "after a mutation, use the returned fresh state before planning the next one.\n"
    "  * Never invent data. If a tool fails, say so and try a different "
    "approach.\n"
    "  * Keep the final reply complete but concise; include every item asked "
    "for."
)


# --------------------------------------------------------------- agent loop
def _content_text(value) -> str:
    """Flatten OpenAI-compatible text/content arrays without losing data."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return str(value)


def _tool_call_arguments(function: dict) -> dict:
    raw = function.get("arguments") or "{}"
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise ValueError("tool arguments must be a JSON object")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("tool arguments must be a JSON object")
    return parsed


def _is_browseract_mutation(name: str, args: dict) -> bool:
    if name != "browser_action" and not str(name).startswith("browseract_"):
        return False
    checker = is_browseract_mutation
    if checker is not None:
        try:
            return bool(checker(str(args.get("action", ""))))
        except Exception:  # noqa: BLE001
            pass
    return str(args.get("action", "")).strip().lower().replace("-", "_") in {
        "open",
        "navigate",
        "click",
        "input",
        "select",
        "keys",
        "scroll",
        "scrollintoview",
        "scroll_into_view",
    }


def _tool_result_text(value) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(value)
    if len(text) > 12_000:
        return text[:12_000] + "\n[tool output truncated]"
    return text


def llm_chat(messages):
    base_url = LLM_BASE_URL.rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise ValueError("LLM_BASE_URL must be an http/https URL")
    if "featherless.ai" in base_url.lower() and LLM_API_KEY in {"", "EMPTY"}:
        raise RuntimeError("Featherless requires FEATHERLESS_API_KEY or LLM_API_KEY")
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "tools": TOOLS_SCHEMA,
        "tool_choice": "auto",
        "temperature": 0.2,
        "max_tokens": 2048,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LLM_API_KEY}",
    }
    if "featherless.ai" in base_url.lower():
        headers.setdefault("HTTP-Referer", "https://github.com/microsoft/UFO")
        headers.setdefault("X-Title", "UFO BrowserAct Agent")
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as response:
        return json.loads(response.read().decode())


def agent(chat_id: int, user_text: str) -> str:
    hist = HISTORY.setdefault(str(chat_id), [])
    hist.append({"role": "user", "content": user_text})
    # Keep the conversation bounded.
    if len(hist) > HISTORY_TURNS * 2:
        del hist[: len(hist) - HISTORY_TURNS * 2]

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + hist
    for _turn in range(MAX_TURNS):
        try:
            resp = llm_chat(messages)
        except Exception as exc:  # noqa: BLE001
            return f"The model is unreachable at {LLM_BASE_URL}: {type(exc).__name__}: {exc}"
        if not isinstance(resp, dict):
            return "The model returned an invalid response."
        choice = (resp.get("choices") or [{}])[0]
        msg = choice.get("message") if isinstance(choice, dict) else {}
        msg = msg if isinstance(msg, dict) else {}
        tool_calls = msg.get("tool_calls") or []
        if not isinstance(tool_calls, list):
            tool_calls = []

        if not tool_calls:
            answer = _content_text(msg.get("content")).strip()
            if not answer:
                answer = "(the model returned nothing)"
            hist.append({"role": "assistant", "content": answer})
            return answer

        messages.append(
            {
                "role": "assistant",
                "content": _content_text(msg.get("content")),
                "tool_calls": tool_calls,
            }
        )
        # A single model response may contain parallel calls.  Serialize the
        # BrowserAct state machine by executing at most one page mutation from
        # that response; read-only calls (state/get/diagnostics) remain useful.
        browseract_mutations = 0
        for raw_tc in tool_calls:
            tc = raw_tc if isinstance(raw_tc, dict) else {}
            fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
            name = str(fn.get("name", ""))
            try:
                call_args = _tool_call_arguments(fn)
            except Exception as exc:  # noqa: BLE001
                out = json.dumps({"ok": False, "error": f"Invalid tool arguments: {exc}"})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(tc.get("id", "")),
                        "name": name,
                        "content": _tool_result_text(out),
                    }
                )
                continue

            impl = TOOL_IMPLS.get(name)
            if _is_browseract_mutation(name, call_args):
                if browseract_mutations:
                    out = json.dumps(
                        {
                            "ok": False,
                            "skipped": True,
                            "error": "Only one BrowserAct mutation is allowed per model response; observe the fresh state and retry in a later turn.",
                            "action": call_args.get("action", ""),
                        }
                    )
                else:
                    browseract_mutations += 1
                    if impl is None:
                        out = f"Unknown tool {name!r}."
                    else:
                        try:
                            out = impl(call_args)
                        except Exception as exc:  # noqa: BLE001
                            out = f"Tool {name} raised {type(exc).__name__}: {exc}"
            elif impl is None:
                out = f"Unknown tool {name!r}."
            else:
                try:
                    out = impl(call_args)
                except Exception as exc:  # noqa: BLE001
                    out = f"Tool {name} raised {type(exc).__name__}: {exc}"

            if name in {"browser_action"} or name.startswith("browseract_"):
                print(
                    f"[tool] {name} action={call_args.get('action', '')}",
                    flush=True,
                )
                print(f"[tool-result] browser observation bytes={len(_tool_result_text(out))}", flush=True)
            else:
                print(f"[tool] {name}", flush=True)
                print(f"[tool-result] bytes={len(_tool_result_text(out))}", flush=True)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": str(tc.get("id", "")),
                    "name": name,
                    "content": _tool_result_text(out),
                }
            )
    return (
        "I reached the tool-call limit for this request "
        f"({MAX_TURNS} turns). Try asking for fewer things at once."
    )


# --------------------------------------------------------------- dispatch
def _handle_shutdown(signum, _frame) -> None:
    raise KeyboardInterrupt


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
    provider = "featherless" if "featherless.ai" in LLM_BASE_URL.lower() else "openai-compatible"
    lines.append(f"llm: {LLM_BASE_URL} model={LLM_MODEL} provider={provider}")
    if BROWSERACT_ENABLED:
        navigator_ready = BrowserActNavigator is not None
        cli_ready = _browseract_cli_present()
        availability = "available" if navigator_ready and cli_ready else "CLI unavailable"
        browser = BROWSERACT_BROWSER_ID or "auto-select"
        lines.append(f"browseract: enabled ({availability}, browser={browser})")
    else:
        lines.append("browseract: disabled")
    lines.append(f"bridge: {UFO_BRIDGE_URL or '(unset)'}")
    return "\n".join(lines)


HELP = (
    "I am an agentic assistant - just tell me what to do in plain language.\n\n"
    "Examples:\n"
    "  - get all of tomorrow's general daily horoscopes from "
    "@AstrologyScienceBot\n"
    "  - what is the host GPU doing?\n"
    "  - fetch https://example.com and summarize it\n"
    "  - when BrowserAct is enabled, navigate a public website with open/state/one action\n\n"
    "Commands: /status /help /ping /exec <allowlisted cmd>"
)


def handle(chat_id: int, text: str) -> None:
    text = text.strip()
    if not text:
        return
    if OWNER_CHAT_ID == "auto":
        owner = load_owner()
        if not owner:
            if not save_owner(chat_id):
                send_message(chat_id, "Unable to persist the owner claim; runner storage is not writable.")
                return
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
    finally:
        close_browseract_session()
    send_message(chat_id, answer)


def poll_forever() -> None:
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN env var is required.", flush=True)
        sys.exit(2)
    previous_signal_handlers = {}
    for signal_name in ("SIGINT", "SIGTERM"):
        signal_number = getattr(signal, signal_name, None)
        if signal_number is not None:
            try:
                previous_signal_handlers[signal_number] = signal.signal(
                    signal_number, _handle_shutdown
                )
            except (OSError, ValueError):
                pass
    try:
        me = api_call("getMe", {})
        print(
            f"agent runner up: @{me.get('result', {}).get('username', '?')} "
            f"llm={LLM_BASE_URL} bridge={UFO_BRIDGE_URL}",
            flush=True,
        )
        offset = 0
        while True:
            try:
                upd = api_call(
                    "getUpdates",
                    {"offset": offset, "timeout": 50, "allowed_updates": '["message"]'},
                )
                for update in upd.get("result", []):
                    offset = update["update_id"] + 1
                    msg = update.get("message") or {}
                    chat_id = msg.get("chat", {}).get("id")
                    text = msg.get("text") or msg.get("caption") or ""
                    if chat_id and text:
                        try:
                            handle(chat_id, text)
                        except Exception as exc:  # noqa: BLE001
                            send_message(chat_id, f"Runner error: {exc}")
            except KeyboardInterrupt:
                raise
            except Exception as exc:  # noqa: BLE001
                print(f"[poll-error] {type(exc).__name__}; retrying in 5s", flush=True)
                time.sleep(5)
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("agent runner stopping", flush=True)
    finally:
        for signal_number, handler in previous_signal_handlers.items():
            try:
                signal.signal(signal_number, handler)
            except (OSError, ValueError):
                pass
        close_browseract_session()


if __name__ == "__main__":
    poll_forever()
