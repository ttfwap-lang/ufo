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
JOBS: Dict[str, Dict[str, Any]] = {}
JOB_QUEUE: "queue.Queue[str]" = queue.Queue()
_worker_started = False
_worker_lock = threading.Lock()


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
    JOBS[job_id] = job
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
        subprocess.Popen(["explorer.exe", TELELEGRAM_EXE])
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


async def _click_bm(c, origin, bm, label=""):
    from ufo.automation.desktop import Rect
    px, py = origin[0] + bm[0], origin[1] + bm[1]
    print(f"  [bridge] click {label or bm} -> ({px},{py})", flush=True)
    await c._click_at_rect(Rect(left=px - 15, top=py - 15,
                                 right=px + 15, bottom=py + 15))
    await asyncio.sleep(2.5)


def _ocr_words(png_path: str):
    """OCR a PNG and return [(x, y, text)] in bitmap coordinates.

    The WinRT OCR helper occasionally returns nothing (busy shell, timeout),
    so we retry a couple of times before giving up on this frame.
    """
    import re
    import subprocess
    base = os.path.dirname(os.path.abspath(__file__))
    ocr_ps1 = os.path.join(base, "ocr_shot.ps1")
    for attempt in range(3):
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", ocr_ps1, png_path],
                capture_output=True, timeout=240)
            # PowerShell output is NOT guaranteed to be UTF-8 (the OCR text can
            # contain stray bytes); decode defensively.
            out = (r.stdout or b"").decode("utf-8", "replace")
        except Exception as e:
            print(f"[bridge] OCR attempt {attempt+1} failed: {e}", flush=True)
            time.sleep(2)
            continue
        words = []
        for line in out.splitlines():
            m = re.match(r"WORD\s+\[\s*(\d+),\s*(\d+)\s+(\d+)x\s*(\d+)\]\s+(.*)", line)
            if m:
                # (x, y, w, h, text) - the click target is the word CENTRE,
                # not its top-left corner (a corner click can land outside a
                # tight link/button and silently do nothing).
                words.append((int(m.group(1)), int(m.group(2)),
                              int(m.group(3)), int(m.group(4)),
                              m.group(5).strip()))
        if words:
            return words
        print(f"[bridge] OCR attempt {attempt+1} returned no words", flush=True)
        time.sleep(2)
    return []


async def _snap_and_ocr(c, tag: str):
    """Screenshot the Telegram window, OCR it, return (path, words, W, H)."""
    import tempfile
    from PIL import Image
    shot = await c.take_screenshot()
    path = os.path.join(tempfile.gettempdir(), f"ufo_ocr_{tag}.png")
    with open(path, "wb") as f:
        f.write(shot)
    words = _ocr_words(path)
    try:
        with Image.open(path) as im:
            W, H = im.size
    except Exception:
        W = H = 0
    return path, words, W, H


def _pick(words, W, H, needle, exact=False, xr=(0.0, 1.0), yr=(0.0, 1.0),
          prefer="last"):
    """Find OCR words inside a RELATIVE band of the capture.

    words are (x, y, w, h, text). Returns the match tuple so the caller can
    click the word centre. `prefer` selects the first or last match in reading
    order.
    """
    hits = []
    for x, y, w, h, t in words:
        if not (xr[0] * W <= x <= xr[1] * W):
            continue
        if not (yr[0] * H <= y <= yr[1] * H):
            continue
        tt = t.strip().strip("'\"")
        if (tt.lower() == needle.lower()) if exact else (needle.lower() in tt.lower()):
            hits.append((x, y, w, h, tt))
    if not hits:
        return None
    return hits[-1] if prefer == "last" else hits[0]


async def _click_at(c, origin, pos, label):
    """Click the CENTRE of an OCR word tuple (x, y, w, h, text)."""
    from ufo.automation.desktop import Rect
    x, y, w, h = pos[0], pos[1], pos[2], pos[3]
    px, py = origin[0] + x + w // 2, origin[1] + y + h // 2
    print(f"[bridge] click {label} '{pos[4]}' bitmap=({x},{y},{w}x{h}) "
          f"-> ({px},{py})", flush=True)
    await c._click_at_rect(Rect(left=px - 12, top=py - 12,
                                 right=px + 12, bottom=py + 12))
    await asyncio.sleep(2.5)


async def _ocr_click(c, origin, words, needle: str, exact=False, nth=0,
                     y_min=None, y_max=None):
    """Click the nth OCR word matching needle. Returns True if clicked.

    y_min/y_max restrict the search to a horizontal band of the window, which
    disambiguates repeated labels (e.g. "Change in 'Settings' menu" vs the
    "Change Sign" button).
    """
    from ufo.automation.desktop import Rect
    hits = []
    for x, y, t in words:
        if y_min is not None and y < y_min:
            continue
        if y_max is not None and y > y_max:
            continue
        tt = t.strip().strip("'\"")
        if (tt.lower() == needle.lower()) if exact else (needle.lower() in tt.lower()):
            hits.append((x, y, tt))
    if not hits or (nth >= 0 and len(hits) <= nth):
        return False
    x, y, t = hits[nth]
    px, py = origin[0] + x, origin[1] + y
    print(f"[bridge] ocr-click '{t}' bitmap=({x},{y}) -> ({px},{py})", flush=True)
    await c._click_at_rect(Rect(left=px - 12, top=py - 12, right=px + 12, bottom=py + 12))
    await asyncio.sleep(2.5)
    return True


async def _ensure_info_panel(c):
    """Open the chat info panel if it is closed.

    The bot's command links ("General Horoscopes" etc.) live in the info panel,
    which is NOT open by default in a fresh window. The panel toggle is a real
    UIA Button, so this is an exact-rect click rather than pixel guessing.
    """
    from ufo.automation.desktop import Rect
    import asyncio as _a

    def _find():
        for el in c.window.handle.descendants(control_type="Button"):
            try:
                t = (el.window_text() or "").strip()
            except Exception:
                continue
            if t in ("Info", "Close panel"):
                r = el.element_info.rectangle
                if r.right - r.left > 1:
                    return t, (r.left, r.top, r.right, r.bottom)
        return None, None

    name, rect = await _a.to_thread(_find)
    if name == "Info":
        cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
        print(f"[bridge] opening info panel at ({cx},{cy})", flush=True)
        await c._click_at_rect(Rect(left=cx - 15, top=cy - 15,
                                     right=cx + 15, bottom=cy + 15))
        await _a.sleep(2.0)
        return True
    return False


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


async def _legacy_collect_horoscope(params: Dict[str, Any]) -> Dict[str, Any]:
    """In-process variant kept for reference (NOT used).

    It drove the UI directly from the bridge process; that proved unreliable
    because the bridge and Telegram can sit on different integrity/foreground
    states, so the action now delegates to the daemon-proven collector.
    """
    from astro_collect import SIGNS, SIGN_BM, TOMORROW_BM, CHANGE_SIGN_BM, \
        OPEN_APP_BM

    bot = params.get("bot", "AstrologyScienceBot")
    signs = params.get("signs") or SIGNS
    period = params.get("period", "tomorrow")
    out_dir = params.get("out_dir") or r"C:\Users\lnxzf\Desktop\projects\ufo\ufo"
    period_bm = {"week": (940, 418), "month": (940, 464),
                 "year": (940, 512)}.get(period, TOMORROW_BM)

    c = await _connect_controller()
    import os
    _fit_window(c)
    os.startfile(f"tg://resolve?domain={bot}")
    await asyncio.sleep(5.0)
    await c.force_telegram_top()
    await asyncio.sleep(1.0)
    _fit_window(c)

    import win32gui
    title = win32gui.GetWindowText(c.get_concrete_hwnd())
    print(f"[bridge] active chat: {title!r}", flush=True)

    shots = {}
    for sign in signs:
        print(f"[bridge] === {sign} ===", flush=True)

        # 1) open the Mini App from the info-panel command link.
        #    Coordinates come from the validated astro_collect map; OCR only
        #    VERIFIES the outcome (and relocates the link if it moved).
        await _ensure_info_panel(c)
        _, words, W, H = await _snap_and_ocr(c, f"pre_{sign}")
        origin = _window_origin(c)

        def _menu_open(ws, w, h):
            return (_pick(ws, w, h, "Select", exact=True) is not None
                    and _pick(ws, w, h, "Tomorrow", exact=True) is not None)

        if not _menu_open(words, W, H):
            cands = [w for w in words
                     if w[4].strip().strip("'\"").lower() == "horoscopes"]
            link = max(cands, key=lambda w: w[0]) if cands else None
            if link:
                await _click_at(c, origin, link, "open app")
            else:
                await _click_bm(c, origin, OPEN_APP_BM, "open app (fixed)")
            await asyncio.sleep(3.0)
            _, words, W, H = await _snap_and_ocr(c, f"menu_{sign}")
            if not _menu_open(words, W, H) and link is None:
                # fixed map missed -> retry with the located link
                cands = [w for w in words
                         if w[4].strip().strip("'\"").lower() == "horoscopes"]
                link = max(cands, key=lambda w: w[0]) if cands else None
                if link:
                    await _click_at(c, _window_origin(c), link,
                                    "open app (retry)")
                    await asyncio.sleep(3.0)
                    _, words, W, H = await _snap_and_ocr(c, f"menu2_{sign}")
        print(f"[bridge]   menu visible: {_menu_open(words, W, H)}", flush=True)
        if not _menu_open(words, W, H):
            raise RuntimeError(f"Mini App menu did not open for {sign}")

        # 2) "Change Sign" (the lower "Change" label)
        origin = _window_origin(c)
        btn = _pick(words, W, H, "Change", xr=(0.45, 1.0), yr=(0.45, 0.80),
                    prefer="last")
        if btn:
            await _click_at(c, origin, btn, "change sign")
        else:
            await _click_bm(c, origin, CHANGE_SIGN_BM, "change sign (fixed)")
        await asyncio.sleep(2.0)

        _, words, W, H = await _snap_and_ocr(c, f"grid_{sign}")
        grid_ok = any(_pick(words, W, H, s, exact=True) is not None
                      for s in ("aries", "taurus", "gemini", "cancer"))
        print(f"[bridge]   sign grid visible: {grid_ok}", flush=True)
        if not grid_ok:
            raise RuntimeError(f"sign selector did not open for {sign}")

        # 3) pick the sign (grid area, right half)
        cell = _pick(words, W, H, sign.capitalize(), exact=True,
                     xr=(0.45, 1.0), yr=(0.30, 0.75))
        if cell:
            await _click_at(c, _window_origin(c), cell, f"select {sign}")
        else:
            await _click_bm(c, _window_origin(c), SIGN_BM[sign],
                            f"select {sign} (fixed)")
        await asyncio.sleep(2.0)

        _, words, W, H = await _snap_and_ocr(c, f"picked_{sign}")
        applied = _pick(words, W, H, sign.lower(), exact=False) is not None
        print(f"[bridge]   sign {sign} applied: {applied}", flush=True)
        if not applied:
            raise RuntimeError(f"sign {sign} was not applied")

        # 4) request the period's horoscope
        label = {"tomorrow": "Tomorrow", "week": "Week",
                 "month": "Month", "year": "Year"}.get(period, "Tomorrow")
        opt = _pick(words, W, H, label, exact=True, xr=(0.45, 1.0),
                    yr=(0.20, 0.50))
        if opt:
            await _click_at(c, _window_origin(c), opt, f"for {period}")
        else:
            await _click_bm(c, _window_origin(c), period_bm,
                            f"for {period} (fixed)")
        await asyncio.sleep(7.0)
        shot = await c.take_screenshot()
        path = os.path.join(out_dir, f"bridge_horoscope_{sign}.png")
        with open(path, "wb") as f:
            f.write(shot)
        shots[sign] = path
        print(f"[bridge] saved {path}", flush=True)

    # OCR the captures into a structured report
    report = _ocr_reports(shots)
    rep_path = os.path.join(out_dir, "bridge_horoscope_report.json")
    with open(rep_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    await c.close()
    return {"bot": bot, "period": period, "signs": signs,
            "shots": shots, "report_path": rep_path, "report": report}


def _ocr_reports(shots: Dict[str, str]) -> Dict[str, Any]:
    """Turn the evidence captures into per-sign text + ratings."""
    import re
    out = {}
    for sign, path in shots.items():
        try:
            words = [w for w in _ocr_words(path) if w[0] >= 700]  # chat pane
            words.sort(key=lambda w: (w[1], w[0]))
            lines, cur, cur_y = [], [], None
            for x, y, _w, _h, t in words:
                if cur_y is None or abs(y - cur_y) <= 7:
                    cur.append((x, t)); cur_y = y if cur_y is None else cur_y
                else:
                    lines.append(" ".join(t for _, t in sorted(cur)))
                    cur, cur_y = [(x, t)], y
            if cur:
                lines.append(" ".join(t for _, t in sorted(cur)))
            text = "\n".join(lines)
            ratings = dict(re.findall(
                r"(Love|Health|Career|Lunar)\s*\((\d)/5\)", text))
            out[sign] = {"ratings": ratings, "text": text}
        except Exception as e:
            out[sign] = {"error": str(e)}
    return out


async def action_list_actions(_params) -> Dict[str, Any]:
    return {"actions": sorted(ACTIONS.keys())}


async def action_health(_params) -> Dict[str, Any]:
    import win32gui
    title = ""
    try:
        c = await _connect_controller()
        title = win32gui.GetWindowText(c.get_concrete_hwnd())
        await c.close()
    except Exception as e:
        title = f"error: {e}"
    return {"telegram_title": title, "queued": JOB_QUEUE.qsize(),
            "workers": 1}


ACTIONS = {
    "collect_horoscope": action_collect_horoscope,
    "list_actions": action_list_actions,
    "health": action_health,
}


# -------------------------------------------------------------------- worker
def _worker_loop():
    asyncio.set_event_loop(asyncio.new_event_loop())
    loop = asyncio.get_event_loop()
    while True:
        job_id = JOB_QUEUE.get()
        job = JOBS.get(job_id)
        if not job:
            continue
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
            job = JOBS.get(job_id)
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
        if job_id in JOBS:
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