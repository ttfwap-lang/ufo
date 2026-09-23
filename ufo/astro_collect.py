"""Collect the bot's general horoscope for all 12 zodiac signs via the Mini App.

Flow per sign (all clicks are gated 8s by the controller, per AGENTS.md):
  1. open the Mini App via the info-panel command link "General Horoscopes"
  2. "Change Sign" -> sign grid -> pick the target sign
  3. "For Tomorrow" -> the bot posts that sign's horoscope into the chat
  4. screenshot evidence per sign

Coordinate model: OCR bitmap pixels -> physical = bitmap + (WIN_X, WIN_Y),
where the window origin in PHYSICAL pixels is measured before the run
(125% DPI: physical = logical * 1.25).
"""
import sys, asyncio, time, json, os
import re
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, "C:\\Users\\lnxzf\\Desktop\\projects\\ufo")
from ufo.automator.app_apis.telegram import TelegramGUIController
from ufo.automation.factory import get_desktop_automation
from ufo.automation.desktop import Rect
import ctypes

# ---- geometry (physical px) -------------------------------------------------
WIN_X, WIN_Y = 63, 50   # measured: logical (50,40) * 1.25

# bitmap centres measured from OCR (see AGENT_PLAN / recon)
OPEN_APP_BM   = (1085, 955)   # info-panel command link "General Horoscopes"
CHANGE_SIGN_BM= (940, 607)    # main-menu "Change Sign"
TOMORROW_BM   = (954, 371)    # main-menu "For Tomorrow"

SIGN_BM = {                    # sign-selector grid (4 rows x 3 cols)
    "aries":       (803, 464), "taurus":     (948, 464), "gemini":    (1092, 464),
    "cancer":      (806, 512), "leo":        (949, 512), "virgo":     (1092, 513),
    "libra":       (805, 558), "scorpio":    (949, 560), "sagittarius": (1091, 560),
    "capricorn":   (805, 607), "aquarius":   (948, 607), "pisces":    (1092, 605),
}

SIGNS = list(SIGN_BM.keys())


def bm2phys(bm):
    return WIN_X + bm[0], WIN_Y + bm[1]


async def click(c, bm, label=""):
    px, py = bm2phys(bm)
    print(f"  click {label or bm} bitmap={bm} -> physical=({px},{py})", flush=True)
    await c._click_at_rect(Rect(left=px - 15, top=py - 15, right=px + 15, bottom=py + 15))
    await asyncio.sleep(2.5)


async def snap(c, name):
    try:
        shot = await c.take_screenshot()
        path = f"C:\\Users\\lnxzf\\Desktop\\projects\\ufo\\ufo\\astro_{name}.png"
        with open(path, "wb") as f:
            f.write(shot)
        print(f"  saved {path} ({len(shot)} bytes)", flush=True)
        return path
    except Exception as e:
        print(f"  snap failed: {e}", flush=True)
        return None


# ---------------------------------------------------------------- verification
OCR_PS1 = r"C:\Users\lnxzf\Desktop\projects\ufo\ufo\ocr_shot.ps1"


def ocr_words(png_path):
    """Run the WinRT OCR helper.

    Returns (set_of_lowercase_words, full_text, boxes) where boxes is a list of
    (x, y, w, h, text). The boxes let us click a label by its real position
    instead of a stale hard-coded pixel.
    """
    import subprocess
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", OCR_PS1, png_path],
            capture_output=True, timeout=240)
        out = (r.stdout or b"").decode("utf-8", "replace")
    except Exception as e:
        print(f"  ocr failed: {e}", flush=True)
        return set(), "", []
    words, boxes, lines = set(), [], []
    for line in out.splitlines():
        m = re.match(r"WORD\s+\[\s*(\d+),\s*(\d+)\s+(\d+)x\s*(\d+)\]\s+(.*)", line)
        if m:
            x, y, w, h = (int(m.group(i)) for i in (1, 2, 3, 4))
            t = m.group(5).strip().strip("'\"")
            words.add(t.lower())
            boxes.append((x, y, w, h, t))
            lines.append(t.lower())
    return words, " ".join(lines), boxes


def find_box(boxes, needle, exact=True, rightmost=False, y_min=None, y_max=None):
    """Locate a word by text. Returns (x, y, w, h, text) or None."""
    hits = []
    for x, y, w, h, t in boxes:
        if y_min is not None and y < y_min:
            continue
        if y_max is not None and y > y_max:
            continue
        tl = t.lower()
        if (tl == needle.lower()) if exact else (needle.lower() in tl):
            hits.append((x, y, w, h, t))
    if not hits:
        return None
    if rightmost:
        return max(hits, key=lambda b: b[0])
    return hits[0]


def fit_window(c):
    """Pin the window to the geometry the click map was measured on."""
    try:
        import win32gui, win32con
        h = c.get_concrete_hwnd()
        if h:
            win32gui.ShowWindow(h, win32con.SW_RESTORE)
            win32gui.MoveWindow(h, 63, 50, 1438, 1000, True)
            time.sleep(0.6)
            print(f"  window -> {win32gui.GetWindowRect(h)}", flush=True)
            return True
    except Exception as e:
        print(f"  fit_window failed: {e}", flush=True)
    return False


async def ensure_info_panel(c):
    """Open the chat info panel (it holds the bot's command links).

    A freshly started Telegram has the panel CLOSED, and the fixed click map
    for "General Horoscopes" assumes it is open. The panel toggle is a real
    UIA Button, so we click it by its exact rect.
    """
    from ufo.automation.desktop import Rect

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

    name, rect = await asyncio.to_thread(_find)
    if name == "Info":
        cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
        print(f"  opening info panel at ({cx},{cy})", flush=True)
        await c._click_at_rect(Rect(left=cx - 15, top=cy - 15,
                                     right=cx + 15, bottom=cy + 15))
        await asyncio.sleep(2.0)
        return True
    print(f"  info panel already open ({name})", flush=True)
    return False


async def verify(c, name, must_have, label):
    """Screenshot + OCR; assert the expected text is present."""
    path = await snap(c, name)
    if not path:
        return None, set(), ""
    words, text, boxes = ocr_words(path)
    ok = all(m.lower() in words or m.lower() in text for m in must_have)
    print(f"  verify {label}: {'OK' if ok else 'MISSING ' + str(must_have)}",
          flush=True)
    return ok, words, boxes


async def click_box(c, box, label):
    """Click the centre of an OCR word box."""
    from ufo.automation.desktop import Rect
    x, y, w, h = box[0], box[1], box[2], box[3]
    ox, oy = WIN_X, WIN_Y
    px, py = ox + x + w // 2, oy + y + h // 2
    print(f"  click {label} '{box[4]}' bitmap=({x},{y}) -> physical ({px},{py})",
          flush=True)
    await c._click_at_rect(Rect(left=px - 12, top=py - 12,
                                 right=px + 12, bottom=py + 12))
    await asyncio.sleep(2.5)


def _restore_telegram_window():
    """Show + reposition any Telegram main window (Qt QWindowIcon)."""
    import win32gui, win32con, win32process
    try:
        import psutil
    except Exception:
        psutil = None
    def cb(hwnd, _):
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            name = psutil.Process(pid).name().lower() if psutil else ""
        except Exception:
            return
        if name == "telegram.exe" and "QWindowIcon" in win32gui.GetClassName(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOP, 63, 50, 1438, 1000,
                                  win32con.SWP_SHOWWINDOW)
    win32gui.EnumWindows(cb, None)


TELEGRAM_EXE = os.path.join(
    os.environ.get("APPDATA", r"C:\Users\lnxzf\AppData\Roaming"),
    "Telegram Desktop", "Telegram.exe")


def _telegram_running() -> bool:
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


def _launch_telegram() -> bool:
    """Launch through Explorer so Telegram gets a MEDIUM-integrity token.

    A Basic-User trust-level launch kills the Qt accessibility bridge, and an
    elevated Telegram UIPI-blocks the screen captures - Explorer is the one
    launcher that yields a normal-integrity process in the user session.
    """
    import subprocess
    if not os.path.exists(TELEGRAM_EXE):
        print(f"  Telegram exe missing: {TELEGRAM_EXE}", flush=True)
        return False
    subprocess.Popen(["explorer.exe", TELEGRAM_EXE])
    for _ in range(30):
        time.sleep(1.0)
        if _telegram_running():
            print("  Telegram launched", flush=True)
            return True
    return False


async def ensure_connected(retries=4):
    """Connect, restoring a hidden window or relaunching a dead Telegram."""
    for attempt in range(retries):
        c = TelegramGUIController()
        if await c.connect():
            print(f"connected (attempt {attempt + 1})", flush=True)
            return c
        print(f"connect failed (attempt {attempt + 1})", flush=True)
        if _telegram_running():
            _restore_telegram_window()
        else:
            _launch_telegram()
        await asyncio.sleep(3.0)
    return None


async def main():
    argv = sys.argv[1:]
    bot = "AstrologyScienceBot"
    period = "tomorrow"
    period_bm = TOMORROW_BM
    PERIOD_BM = {"tomorrow": TOMORROW_BM, "week": (954, 418),
                 "month": (954, 464), "year": (954, 512)}
    only = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--bot" and i + 1 < len(argv):
            bot = argv[i + 1]; i += 2; continue
        if a == "--period" and i + 1 < len(argv):
            period = argv[i + 1]
            period_bm = PERIOD_BM.get(period, TOMORROW_BM)
            i += 2; continue
        only.append(a.lower())
        i += 1
    if not only:
        only = SIGNS

    c = await ensure_connected()
    if not c:
        print("connect failed")
        return

    # Make sure the astrology bot chat is the active one
    import os
    os.startfile(f"tg://resolve?domain={bot}")
    await asyncio.sleep(5.0)
    await c.force_telegram_top()
    await asyncio.sleep(1.5)
    title = ""
    try:
        import win32gui
        title = win32gui.GetWindowText(c.get_concrete_hwnd())
    except Exception:
        pass
    print(f"active window title: {title!r}", flush=True)
    if "Astrology" not in title and "Horoscope" not in title:
        print("WARNING: bot chat not active - clicks may hit the wrong chat", flush=True)

    results = {}
    for sign in only:
        print(f"\n=== {sign.upper()} ===", flush=True)
        try:
            # 0) known geometry + info panel open (the command links live there)
            fit_window(c)
            await ensure_info_panel(c)

            # 1) open the Mini App. The command link's pixel position drifts
            #    with the panel layout, so locate it by OCR and fall back to
            #    the measured map only if OCR cannot see it.
            ok, _w, boxes = await verify(c, f"v_pre_{sign}", [], "pre-state")
            link = find_box(boxes, "Horoscopes", exact=True, rightmost=True,
                            y_min=700) or find_box(boxes, "Horoscopes")
            if link:
                await click_box(c, link, "open app")
            else:
                await click(c, OPEN_APP_BM, "open app (fixed)")
            await asyncio.sleep(3.0)
            ok, _w, _b = await verify(c, f"v_menu_{sign}", ["Select", "Tomorrow"],
                                      "app menu")
            if not ok:
                await ensure_info_panel(c)
                ok2, _w2, boxes2 = await verify(c, f"v_pre2_{sign}", [],
                                               "pre-state 2")
                link = find_box(boxes2, "Horoscopes", exact=True,
                                rightmost=True, y_min=700) or \
                    find_box(boxes2, "Horoscopes")
                if link:
                    await click_box(c, link, "open app (retry)")
                else:
                    await click(c, OPEN_APP_BM, "open app (retry fixed)")
                await asyncio.sleep(3.5)
                ok, _w, _b = await verify(c, f"v_menu2_{sign}",
                                          ["Select", "Tomorrow"],
                                          "app menu retry")
            if not ok:
                raise RuntimeError("Mini App menu did not open")

            # 2) "Change Sign" - locate the lower "Change" label
            _ok, _w, boxes = await verify(c, f"v_state_{sign}", [], "state")
            btn = find_box(boxes, "Change", exact=True, y_min=500)
            if btn:
                await click_box(c, btn, "change sign")
            else:
                await click(c, CHANGE_SIGN_BM, "change sign (fixed)")
            await asyncio.sleep(2.0)
            ok, _w, boxes = await verify(c, f"v_grid_{sign}",
                                         ["Aries", "Taurus", "Gemini"],
                                         "sign grid")
            if not ok:
                _ok, _w, boxes = await verify(c, f"v_grid_try_{sign}", [],
                                              "state")
                btn = find_box(boxes, "Change", exact=True, y_min=500)
                if btn:
                    await click_box(c, btn, "change sign (retry)")
                else:
                    await click(c, CHANGE_SIGN_BM, "change sign (retry fixed)")
                await asyncio.sleep(2.0)
                ok, _w, boxes = await verify(c, f"v_grid2_{sign}",
                                             ["Aries", "Taurus", "Gemini"],
                                             "sign grid retry")
            if not ok:
                raise RuntimeError("sign selector did not open")

            # 3) pick the sign from the grid
            cell = find_box(boxes, sign.capitalize(), exact=True)
            if cell:
                await click_box(c, cell, f"select {sign}")
            else:
                await click(c, SIGN_BM[sign], f"select {sign} (fixed)")
            await asyncio.sleep(2.0)
            ok, _w, _b = await verify(c, f"v_pick_{sign}", [sign],
                                      f"sign {sign}")
            if not ok:
                _ok, _w, boxes = await verify(c, f"v_pick_try_{sign}", [],
                                              "state")
                cell = find_box(boxes, sign.capitalize(), exact=True)
                if cell:
                    await click_box(c, cell, f"select {sign} (retry)")
                else:
                    await click(c, SIGN_BM[sign], f"select {sign} (retry fixed)")
                await asyncio.sleep(2.0)
                ok, _w, _b = await verify(c, f"v_pick2_{sign}", [sign],
                                          f"sign {sign} retry")
            if not ok:
                raise RuntimeError(f"sign {sign} was not applied")

            # 4) request the period's general horoscope
            _ok, _w, boxes = await verify(c, f"v_final_{sign}", [], "state")
            label = {"tomorrow": "Tomorrow", "week": "Week",
                     "month": "Month", "year": "Year"}.get(period, "Tomorrow")
            opt = find_box(boxes, label, exact=True, y_min=250, y_max=520)
            if opt:
                await click_box(c, opt, f"for {period}")
            else:
                await click(c, period_bm, f"for {period} (fixed)")
            await asyncio.sleep(7.0)
            p = await snap(c, f"horoscope_{sign}")
            results[sign] = p
        except Exception as e:
            print(f"  ERROR on {sign}: {e}", flush=True)
            results[sign] = None
            try:
                await c.force_telegram_top()
                fit_window(c)
            except Exception:
                pass
            await asyncio.sleep(2.0)

    with open(r"C:\Users\lnxzf\Desktop\projects\ufo\ufo\astro_collect_results.json",
              "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print("\nDONE", json.dumps(results, indent=2), flush=True)
    await c.close()


if __name__ == "__main__":
    asyncio.run(main())