"""ufo_bridge - Windows-side job server that exposes the UFO/Venus Telegram
automator as a tool service for the DGX agent runner.

Contract (see AGENT_PLAN.md):
    POST /jobs   {"job_id": "...", "action": "<action>", "params": {...}}
    GET  /result/<job_id>   -> {"status": "queued|running|done|error", ...}
    GET  /health            -> {"ok": true, ...}

Design rules that matter:
  * SINGLE WORKER. All input injection is serialised through one queue
    (AGENTS.md: one automation session at a time, countdown gate per input).
  * AUTH. Bearer token from UFO_BRIDGE_TOKEN (or ufo_bridge_token.txt).
  * Every action is a thin wrapper over the SAME proven code paths used
    interactively (astro_collect / astro_step), so behaviour cannot drift.
  * The bridge must run in the same user session + integrity level as
    Telegram (medium). An elevated Telegram would UIPI-block the captures.
"""
from __future__ import annotations

import asyncio
import json
import os
import queue
import re
import secrets
import subprocess
import sys
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict
from urllib.parse import urlparse

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), chr(46) + chr(46)))

# DPI: make THIS process per-monitor aware so GetWindowRect / MoveWindow and
# the controller's captures all speak the same (physical) pixel space.
# Without this the bitmap->physical conversion is off by the 125% scale.
try:
    import ctypes as _ct
    _ct.windll.user32.SetProcessDpiAwarenessContext(_ct.c_void_p(-4))
except Exception:  # older Windows
    try:
        import ctypes as _ct
        _ct.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

HOST = os.environ.get("UFO_BRIDGE_HOST", "0.0.0.0")
PORT = int(os.environ.get("UFO_BRIDGE_PORT", "9301"))
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "ufo_bridge_token.txt")


def load_token() -> str:
    tok = os.environ.get("UFO_BRIDGE_TOKEN")
    if tok:
        return tok.strip()
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            tok = f.read().strip()
            if tok:
                return tok
    tok = secrets.token_urlsafe(32)
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(tok)
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except Exception:
        pass
    print(f"[bridge] generated new token -> {TOKEN_FILE}", flush=True)
    return tok


TOKEN = load_token()

# ---------------------------------------------------------------- job store
# BOUNDED on purpose. This is a 24/7 service and a job result can be large
# (collect_horoscope embeds a full 12-sign OCR report, ~100 KB of text), so an
# append-only dict leaks until the process is restarted. We keep the newest
# MAX_JOBS entries and never evict a job that is still queued or running.
MAX_JOBS = int(os.environ.get("UFO_BRIDGE_MAX_JOBS", "200"))
JOBS: Dict[str, Dict[str, Any]] = {}
JOB_QUEUE: "queue.Queue[str]" = queue.Queue()
_worker_started = False
_worker_lock = threading.Lock()
_jobs_lock = threading.Lock()


def _evict_old_jobs() -> None:
    """Drop the oldest FINISHED jobs once the store exceeds MAX_JOBS."""
    with _jobs_lock:
        if len(JOBS) <= MAX_JOBS:
            return
        finished = sorted(
            (j for j in JOBS.values()
             if j.get("status") in ("done", "error")),
            key=lambda j: j.get("created", 0.0))
        for job in finished:
            if len(JOBS) <= MAX_JOBS:
                break
            JOBS.pop(job["job_id"], None)


def _new_job(job_id: str, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
    job = {
        "job_id": job_id,
        "action": action,
        "params": params,
        "status": "queued",
        "created": time.time(),
        "started": None,
        "finished": None,
        "result": None,
        "error": None,
    }
    with _jobs_lock:
        JOBS[job_id] = job
    _evict_old_jobs()
    return job


# ------------------------------------------------------------------- actions
TELEGRAM_EXE = os.path.join(
    os.environ.get("APPDATA", r"C:\Users\lnxzf\AppData\Roaming"),
    "Telegram Desktop", "Telegram.exe")


def telegram_running() -> bool:
    try:
        import win32gui, win32process
        try:
            import psutil
        except Exception:
            psutil = None
        found = []

        def cb(hwnd, _):
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                name = psutil.Process(pid).name().lower() if psutil else ""
            except Exception:
                return
            if name == "telegram.exe" and "QWindowIcon" in win32gui.GetClassName(hwnd):
                found.append(hwnd)
        win32gui.EnumWindows(cb, None)
        return bool(found)
    except Exception:
        return False


def launch_telegram() -> bool:
    """Relaunch Telegram through the user's Explorer shell.

    Explorer hands the launch to the interactive shell so Telegram runs at
    NORMAL integrity with a full token. Do NOT use `runas /trustlevel`
    (Basic User): that trust level disables the Qt accessibility bridge and
    the automator goes blind. An ELEVATED Telegram is also wrong - it
    UIPI-blocks the screen captures the controller needs.
    """
    if not os.path.exists(TELEGRAM_EXE):
        print(f"[bridge] Telegram exe missing: {TELEGRAM_EXE}", flush=True)
        return False
    import subprocess
    # Launch THROUGH explorer.exe: the shell resolves the request and starts
    # the app with the SHELL's (medium) token. os.startfile here would inherit
    # this process's token, and an elevated Telegram breaks every UIA read and
    # screen capture for the medium-integrity controller.
    try:
        subprocess.Popen(["explorer.exe", TELEGRAM_EXE])
    except Exception as e:
        print(f"[bridge] explorer launch failed ({e}); trying startfile", flush=True)
        try:
            os.startfile(TELEGRAM_EXE)
        except Exception:
            return False
    for _ in range(30):
        time.sleep(1.0)
        if telegram_running():
            print("[bridge] Telegram relaunched", flush=True)
            return True
    print("[bridge] Telegram did not come back", flush=True)
    return False


async def ensure_telegram(retries: int = 3) -> bool:
    """Make sure a usable Telegram window exists (RULE 2 prerequisite)."""
    for attempt in range(retries):
        if telegram_running():
            return True
        print(f"[bridge] Telegram not running (attempt {attempt+1}) - launching",
              flush=True)
        launch_telegram()
    return telegram_running()


async def _connect_controller():
    from ufo.automator.app_apis.telegram import TelegramGUIController
    c = TelegramGUIController()
    for attempt in range(3):
        if await c.connect():
            return c
        print(f"[bridge] connect failed (attempt {attempt+1})", flush=True)
        if not await ensure_telegram():
            await asyncio.sleep(3.0)
    raise RuntimeError("cannot connect to Telegram Desktop")


def _fit_window(c, x=63, y=50, w=1438, h=1000):
    """Pin the Telegram window to the geometry the click map was measured on.

    astro_collect.py was validated with a 1438x1000 capture (window at
    physical (63,50) on this 125% DPI display). Reproducing that geometry
    EXACTLY keeps the fixed bitmap click map valid - the controller otherwise
    resizes the window and every target shifts.
    """
    try:
        import win32gui, win32con
        hwnd = c.get_concrete_hwnd()
        if not hwnd:
            return False
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.MoveWindow(hwnd, x, y, w, h, True)
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        time.sleep(0.6)
        print(f"[bridge] window fitted to logical ({x},{y},{w},{h})", flush=True)
        return True
    except Exception as e:
        print(f"[bridge] fit_window failed: {e}", flush=True)
        return False


def _window_origin(c) -> tuple[int, int]:
    """Physical origin of the Telegram window.

    This process is per-monitor DPI aware, so GetWindowRect is already in
    physical pixels - the same space as the controller's captures. The bitmap
    returned by take_screenshot() therefore maps with a plain offset.
    """
    import win32gui
    l, _t, _r, _b = win32gui.GetWindowRect(c.get_concrete_hwnd())
    return int(l), int(_t)


def _ocr_words(png_path: str):
    """OCR a PNG and return [(x, y, w, h, text)] in bitmap coordinates.

    Delegates to venus_client.ocr_words (resident OCR service, PowerShell helper
    as fallback). OCR occasionally returns nothing (busy shell, timeout), so we
    retry a couple of times before giving up on this frame; empty results are
    not cached there, so a retry really re-runs OCR. The click target is the word
    CENTRE, not its top-left corner (a corner click can land outside a tight
    link/button and silently do nothing).
    """
    import venus_client
    for attempt in range(3):
        words = venus_client.ocr_words(png_path)
        if words:
            return words
        print(f"[bridge] OCR attempt {attempt+1} returned no words", flush=True)
        time.sleep(2)
    return []


async def action_collect_horoscope(params: Dict[str, Any]) -> Dict[str, Any]:
    """Collect general daily horoscopes for zodiac signs from a Telegram bot.

    The desktop work is delegated to the PROVEN interactive path
    (`astro_collect.py` driven through `uac_run.py`, i.e. the same daemon +
    controller + 8s gate chain that collected all 12 signs successfully).
    Doing the clicks in-process here proved unreliable (the bridge process
    and the Telegram window can end up on different integrity/foreground
    states), so the bridge stays the API/queue layer and the daemon does the
    automation.

    params:
      bot     - bot username (default AstrologyScienceBot)
      signs   - list of signs (default: all 12)
      period  - tomorrow | week | month | year (default tomorrow)
    """
    from astro_collect import SIGNS

    bot = params.get("bot", "AstrologyScienceBot")
    signs = [s.lower() for s in (params.get("signs") or SIGNS)]
    period = params.get("period", "tomorrow")
    base = os.path.dirname(os.path.abspath(__file__))
    py = os.path.join(os.path.dirname(base), ".venv", "Scripts", "python.exe")
    if not os.path.exists(py):
        py = sys.executable

    cmd = [py, "-X", "utf8", os.path.join(base, "uac_run.py"),
           os.path.join(base, "astro_collect.py")] + signs
    if bot != "AstrologyScienceBot":
        cmd += ["--bot", bot]
    if period != "tomorrow":
        cmd += ["--period", period]

    print(f"[bridge] running: {' '.join(cmd)}", flush=True)
    proc = await asyncio.to_thread(
        lambda: subprocess.run(cmd, capture_output=True, timeout=3600,
                               cwd=base))
    out = (proc.stdout or b"").decode("utf-8", "replace")
    err = (proc.stderr or b"").decode("utf-8", "replace")
    print(f"[bridge] collector rc={proc.returncode}", flush=True)
    if out.strip():
        print(out[-3000:], flush=True)
    if proc.returncode != 0 and err.strip():
        print(f"[bridge] stderr: {err[-1500:]}", flush=True)

    shots = {}
    for s in signs:
        p = os.path.join(base, f"astro_horoscope_{s}.png")
        if os.path.exists(p):
            shots[s] = p
    if not shots:
        raise RuntimeError(
            f"collector produced no captures (rc={proc.returncode}). "
            f"stderr: {err[-500:]}")
    report = _ocr_reports(shots)
    rep_path = os.path.join(base, "bridge_horoscope_report.json")
    with open(rep_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return {"bot": bot, "period": period, "signs": signs, "shots": shots,
            "report_path": rep_path, "report": report,
            "collector_rc": proc.returncode}


def _ocr_reports(shots: Dict[str, str]) -> Dict[str, Any]:
    """Turn the evidence captures into per-sign text + ratings.

    OCR words are filtered to the chat pane and re-clustered into lines; the
    Love/Health/Career/Lunar scores are then read straight out of the card.
    """
    import re
    out: Dict[str, Any] = {}
    for sign, path in shots.items():
        try:
            words = [w for w in _ocr_words(path) if w[0] >= 700]  # chat pane
            words.sort(key=lambda w: (w[1], w[0]))
            lines, cur, cur_y = [], [], None
            for x, y, _w, _h, t in words:
                if cur_y is None or abs(y - cur_y) <= 7:
                    cur.append((x, t))
                    cur_y = y if cur_y is None else cur_y
                else:
                    lines.append(" ".join(t for _, t in sorted(cur)))
                    cur, cur_y = [(x, t)], y
            if cur:
                lines.append(" ".join(t for _, t in sorted(cur)))
            text = "\n".join(lines)
            ratings = dict(re.findall(
                r"(Love|Health|Career|Lunar)\s*\((\d)/5\)", text))
            out[sign] = {"ratings": ratings, "text": text}
        except Exception as e:  # noqa: BLE001
            out[sign] = {"error": str(e)}
    return out


async def action_list_actions(_params) -> Dict[str, Any]:
    return {"actions": sorted(ACTIONS.keys())}


# =====================================================================
# VISION (UI-Venus-2-9B on gx10, fused with WinRT OCR)
# =====================================================================
async def _vision_snap(c, tag: str) -> str:
    """Screenshot the Telegram window to a temp PNG and return its path."""
    import tempfile
    _fit_window(c)
    shot = await c.take_screenshot()
    path = os.path.join(tempfile.gettempdir(), f"ufo_vision_{tag}.png")
    with open(path, "wb") as f:
        f.write(shot)
    return path


# Window chrome is inside the capture (the capture is the full window, title
# bar included). A mis-grounded vision point in that band hits minimise /
# maximise / CLOSE, which previously closed Telegram outright. Vision clicks
# are therefore refused unless the point lands in the client area.
_CHROME_TOP_PX = 42
_CHROME_EDGE_PX = 24


def _point_is_safe(png: str, x: float, y: float) -> tuple[bool, str]:
    """Reject vision points that land on window chrome or outside the client."""
    from PIL import Image
    try:
        with Image.open(png) as im:
            W, H = im.size
    except Exception as exc:
        return False, f"cannot measure capture: {exc}"
    if not (0 <= x < W and 0 <= y < H):
        return False, f"point ({x:.0f},{y:.0f}) outside capture {W}x{H}"
    if y < _CHROME_TOP_PX:
        return False, (f"point y={y:.0f} is in the title-bar/chrome band "
                       f"(y<{_CHROME_TOP_PX}) - would hit window buttons")
    if x < _CHROME_EDGE_PX or x > W - _CHROME_EDGE_PX:
        return False, f"point x={x:.0f} is in the window edge band"
    if y > H - 8:
        return False, f"point y={y:.0f} is on the bottom window border"
    return True, "ok"


async def action_vision_locate(params: Dict[str, Any]) -> Dict[str, Any]:
    """Locate a labelled UI element with Venus+OCR fusion.

    params:
      screenshot - path to a PNG (optional; if omitted a fresh Telegram
                   screenshot is taken)
      label      - text/icon description of the target, e.g. "Change Sign"
      prefer     - fusion (default) | venus | ocr
      click      - if true, click the located point through the gated
                   controller (8s countdown applies, per AGENTS.md)
    """
    import re as _re
    import venus_client

    label = params.get("label", "")
    if not label:
        raise ValueError("vision_locate requires 'label'")
    prefer = params.get("prefer", "auto")
    engine = params.get("engine", "venus")     # venus | multi
    c = None
    try:
        if params.get("screenshot") and os.path.exists(params["screenshot"]):
            png = params["screenshot"]
        else:
            c = await _connect_controller()
            png = await _vision_snap(c, _re.sub(r"\W+", "_", label)[:24])

        boxes = venus_client.ocr_words(png)
        if engine == "multi":
            out = venus_client.locate_multi(png, label, ocr_boxes=boxes)
            out["screenshot"] = png
            out["engine"] = "multi"
            if params.get("click"):
                cands = out.get("primary") or {}
                if not cands.get("found"):
                    raise RuntimeError(
                        f"vision could not locate {label!r}: "
                        f"{cands.get('note', 'no estimate')}")
                px, py = cands["x"], cands["y"]
                safe, why = _point_is_safe(png, px, py)
                out["safe_to_click"] = safe
                out["safety"] = why
                if not safe:
                    out["refused"] = True
                    print(f"[bridge] REFUSED multi-click on {label!r}: {why}",
                          flush=True)
                    return out
                from ufo.automation.desktop import Rect
                ox, oy = _window_origin(c)
                await c._click_at_rect(Rect(left=ox + px - 15, top=oy + py - 15,
                                            right=ox + px + 15, bottom=oy + py + 15))
                await asyncio.sleep(float(params.get("settle", 2.5)))
                out["clicked_physical"] = [int(ox + px), int(oy + py)]
            return out

        res = venus_client.locate(png, label, ocr_boxes=boxes, prefer=prefer)
        out = res.as_dict()
        out["screenshot"] = png
        out["engine"] = engine
        out["ocr_candidates"] = len([b for b in boxes
                                     if venus_client._label_matches(label, b[4])])
        if params.get("click"):
            if not res.found:
                raise RuntimeError(f"vision could not locate {label!r}: {res.note}")
            safe, why = _point_is_safe(png, res.x, res.y)
            out["safe_to_click"] = safe
            out["safety"] = why
            if not safe:
                out["refused"] = True
                print(f"[bridge] REFUSED vision-click on {label!r}: {why}", flush=True)
                return out
            from ufo.automation.desktop import Rect
            ox, oy = _window_origin(c)
            px, py = ox + res.x, oy + res.y
            print(f"[bridge] vision-click '{label}' -> ({px},{py}) "
                  f"via {res.strategy}", flush=True)
            await c._click_at_rect(Rect(left=px - 15, top=py - 15,
                                        right=px + 15, bottom=py + 15))
            await asyncio.sleep(float(params.get("settle", 2.5)))
            out["clicked_physical"] = [int(px), int(py)]
        return out
    finally:
        if c is not None:
            await c.close()


def _strip_reasoning(text: str) -> str:
    """Remove reasoning traces from a vision answer.

    Venus is launched with `--reasoning-parser qwen3`, so even with
    `enable_thinking: false` the template can emit a stray `</think>` (and
    occasionally the reasoning text itself) into `content`. Observed verbatim
    in a live run: the answer came back as

        "Element AI\\n</think>\\n\\nElement AI"

    which the agent would then read as part of the model's conclusion - a state
    check that reports the app name plus template debris invites the agent to
    reason about the debris. Everything up to the LAST closing tag is reasoning;
    if the model put its thinking first and the answer after, we keep the tail.
    """
    if not text:
        return ""
    out = text
    # If there is a closing tag, anything before it is the reasoning trace.
    idx = out.rfind("</think>")
    if idx != -1:
        out = out[idx + len("</think>"):]
    # Drop an unterminated opening tag plus whatever followed it.
    out = re.sub(r"<think>.*", "", out, flags=re.S)
    # Some builds emit the tags with no angle brackets, e.g. "think>" or a
    # bare "</think>" split across chunks; handle the common leftovers.
    out = out.replace("<think>", "").replace("</think>", "")
    return out.strip()


async def action_vision_ask(params: Dict[str, Any]) -> Dict[str, Any]:
    """Ask Venus a free-form question about the current screen (state check).

    params:
      question   - e.g. "Is the zodiac sign selector grid open?"
      screenshot - optional PNG (default: fresh Telegram screenshot)
      reasoning  - enable Venus' reasoning mode (default false)
    """
    import base64
    import json as _json
    import urllib.request

    question = params.get("question", "")
    if not question:
        raise ValueError("vision_ask requires 'question'")

    c = None
    try:
        if params.get("screenshot") and os.path.exists(params["screenshot"]):
            png = params["screenshot"]
        else:
            c = await _connect_controller()
            png = await _vision_snap(c, "ask")

        b64 = base64.b64encode(open(png, "rb").read()).decode()
        payload = {
            "model": os.environ.get("VENUS_MODEL", "ui-venus"),
            "messages": [{"role": "user", "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": question}]}],
            "temperature": 0.2,
            "max_tokens": int(params.get("max_tokens", 512)),
        }
        if not params.get("reasoning"):
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        req = urllib.request.Request(
            # The tunnel port, not 8002. The model itself is bound to
            # 127.0.0.1 on gx10, so the direct port is unreachable from
            # Windows and this fallback silently broke every vision call.
            os.environ.get("VENUS_URL", "http://100.67.13.78:18002/v1")
            .rstrip("/") + "/chat/completions",
            data=_json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer EMPTY"})
        with urllib.request.urlopen(req, timeout=300) as r:
            d = _json.loads(r.read().decode())
        msg = d["choices"][0]["message"]
        return {"question": question, "screenshot": png,
                "answer": _strip_reasoning(msg.get("content") or ""),
                "raw_content_len": len(msg.get("content") or ""),
                "usage": d.get("usage")}
    finally:
        if c is not None:
            await c.close()


async def action_vision_elements(params: Dict[str, Any]) -> Dict[str, Any]:
    """OmniParser screen parse: every element with a box and an icon caption.

    Complements vision_locate: instead of answering one grounding question,
    this enumerates the whole screen (icon detection + Florence-2 captions),
    which is how the agent discovers controls it was never told the name of.
    """
    import venus_client
    c = None
    try:
        if params.get("screenshot") and os.path.exists(params["screenshot"]):
            png = params["screenshot"]
        else:
            c = await _connect_controller()
            png = await _vision_snap(c, "elements")
        elements = venus_client.omniparser_elements(
            png, imgsz=int(params.get("imgsz", 1024)))
        limit = int(params.get("limit", 60))
        return {"screenshot": png, "count": len(elements),
                "elements": elements[:limit]}
    finally:
        if c is not None:
            await c.close()


async def action_vision_scan(params: Dict[str, Any]) -> Dict[str, Any]:
    """Inventory every UI element the vision+OCR stack can see right now.

    Returns OCR words plus Venus' free-form description of the screen, which
    is what the agent uses to decide its next step.
    """
    import venus_client
    c = None
    try:
        c = await _connect_controller()
        png = await _vision_snap(c, "scan")
        boxes = venus_client.ocr_words(png)
        words = [{"text": b[4], "box": [b[0], b[1], b[2], b[3]]} for b in boxes]
        desc = ""
        try:
            asked = await action_vision_ask(
                {"screenshot": png, "question": params.get(
                    "question",
                    "Describe the current screen: which app, which view, and "
                    "which interactive controls are visible. Be concise.")})
            desc = asked.get("answer", "")
        except Exception as e:
            desc = f"(vision description unavailable: {e})"
        return {"screenshot": png, "word_count": len(words), "words": words,
                "description": desc}
    finally:
        if c is not None:
            await c.close()



async def action_health(_params) -> Dict[str, Any]:
    import win32gui
    title = ""
    try:
        c = await _connect_controller()
        title = win32gui.GetWindowText(c.get_concrete_hwnd())
        await c.close()
    except Exception as e:
        title = f"error: {e}"

    # report vision-model reachability too (it is part of the toolchain)
    vision = {}
    for label, url in (("venus", os.environ.get(
            "VENUS_URL", "http://100.67.13.78:18002/v1").rstrip("/")),
            ("omniparser", os.environ.get(
            "OMNIPARSER_URL", "http://127.0.0.1:7871").rstrip("/"))):
        try:
            import urllib.request
            with urllib.request.urlopen(url + "/api/health" if "omni" in label
                                        else url + "/models", timeout=8) as r:
                body = r.read().decode()
            vision[label] = "ok" if body else "empty response"
        except Exception as e:
            vision[label] = f"unavailable: {type(e).__name__}"

    return {"telegram_title": title, "queued": JOB_QUEUE.qsize(),
            "workers": 1, "vision": vision}


ACTIONS = {
    "collect_horoscope": action_collect_horoscope,
    "vision_locate": action_vision_locate,
    "vision_ask": action_vision_ask,
    "vision_elements": action_vision_elements,
    "vision_scan": action_vision_scan,
    "list_actions": action_list_actions,
    "health": action_health,
}


# -------------------------------------------------------------------- worker
def _worker_loop():
    asyncio.set_event_loop(asyncio.new_event_loop())
    loop = asyncio.get_event_loop()
    while True:
        job_id = JOB_QUEUE.get()
        with _jobs_lock:
            job = JOBS.get(job_id)
        if not job:
            JOB_QUEUE.task_done()
            continue
        # NOTE: the job dict is mutated in place while HTTP handlers may be
        # serialising it, so readers get a snapshot copy (see _job_snapshot).
        job["status"] = "running"
        job["started"] = time.time()
        try:
            fn = ACTIONS.get(job["action"])
            if not fn:
                raise KeyError(f"unknown action {job['action']!r}; "
                               f"known: {sorted(ACTIONS)}")
            result = loop.run_until_complete(fn(job["params"] or {}))
            job["result"] = result
            job["status"] = "done"
        except Exception as e:
            job["status"] = "error"
            job["error"] = f"{type(e).__name__}: {e}"
            job["traceback"] = traceback.format_exc()[-4000:]
            print(f"[bridge] job {job_id} ERROR: {job['error']}", flush=True)
        finally:
            job["finished"] = time.time()
            JOB_QUEUE.task_done()
            _evict_old_jobs()


def _job_snapshot(job_id: str) -> Optional[Dict[str, Any]]:
    """Return a shallow copy so a response can never observe a half-written
    job (the worker thread mutates the same dict while we serialise it)."""
    with _jobs_lock:
        job = JOBS.get(job_id)
        return dict(job) if job else None


def ensure_worker():
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True
    threading.Thread(target=_worker_loop, name="ufo-bridge-worker",
                     daemon=True).start()
    print("[bridge] worker started (single worker)", flush=True)


# -------------------------------------------------------------------- server
class Handler(BaseHTTPRequestHandler):
    server_version = "ufo_bridge/1.0"

    def log_message(self, fmt, *args):
        print(f"[bridge] {self.address_string()} {fmt % args}", flush=True)

    def _auth(self) -> bool:
        hdr = self.headers.get("Authorization", "")
        if hdr.startswith("Bearer "):
            return secrets.compare_digest(hdr[7:].strip(), TOKEN)
        return False

    def _send(self, code: int, payload: Dict[str, Any]):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self._send(200, {"ok": True, "token_required": True})
            return
        if not self._auth():
            self._send(401, {"error": "unauthorized"})
            return
        if path.startswith("/result/"):
            job_id = path[len("/result/"):]
            job = _job_snapshot(job_id)
            if not job:
                self._send(404, {"error": "unknown job_id"})
                return
            self._send(200, job)
            return
        self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if not self._auth():
            self._send(401, {"error": "unauthorized"})
            return
        if path != "/jobs":
            self._send(404, {"error": "not found"})
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            self._send(400, {"error": f"bad json: {e}"})
            return
        action = payload.get("action")
        if not action:
            self._send(400, {"error": "missing 'action'"})
            return
        job_id = payload.get("job_id") or str(uuid.uuid4())
        with _jobs_lock:
            duplicate = job_id in JOBS
        if duplicate:
            self._send(409, {"error": "job_id already exists", "job_id": job_id})
            return
        job = _new_job(job_id, action, payload.get("params") or {})
        ensure_worker()
        JOB_QUEUE.put(job_id)
        print(f"[bridge] queued job {job_id} action={action}", flush=True)
        self._send(202, {"job_id": job_id, "status": job["status"]})


def main():
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[bridge] listening on http://{HOST}:{PORT}  "
          f"(POST /jobs, GET /result/<id>, GET /health)", flush=True)
    print(f"[bridge] token in {TOKEN_FILE}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[bridge] shutting down", flush=True)


if __name__ == "__main__":
    main()