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
    # The controller re-applies its own "sane" geometry inside every click
    # (force_telegram_top), which silently invalidates the bitmap map.
    # Re-pin the window immediately before each click.
    fit_window(c)
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
    """WinRT OCR via the shared implementation (resident service, PowerShell
    fallback) - see venus_client.ocr_words.

    Returns (set_of_lowercase_words, full_text, boxes) where boxes is a list of
    (x, y, w, h, text). The boxes let us click a label by its real position
    instead of a stale hard-coded pixel.
    """
    import venus_client
    try:
        boxes = venus_client.ocr_words(png_path)
    except Exception as e:
        print(f"  ocr failed: {e}", flush=True)
        return set(), "", []
    words = {t.lower() for _x, _y, _w, _h, t in boxes}
    return words, " ".join(t.lower() for _x, _y, _w, _h, t in boxes), boxes


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
        found = {}
        for el in c.window.handle.descendants(control_type="Button"):
            try:
                t = (el.window_text() or "").strip()
            except Exception:
                continue
            if t in ("Info", "Close panel") and t not in found:
                r = el.element_info.rectangle
                if r.right - r.left > 1:
                    found[t] = (r.left, r.top, r.right, r.bottom)
        return found

    found = await asyncio.to_thread(_find)
    # "Close panel" present => the panel is ALREADY open. Clicking "Info"
    # then would CLOSE it and the command links would disappear.
    if "Close panel" in found:
        print("  info panel already open", flush=True)
        return False
    if "Info" in found:
        r = found["Info"]
        cx, cy = (r[0] + r[2]) // 2, (r[1] + r[3]) // 2
        print(f"  opening info panel at ({cx},{cy})", flush=True)
        await c._click_at_rect(Rect(left=cx - 15, top=cy - 15,
                                     right=cx + 15, bottom=cy + 15))
        await asyncio.sleep(2.0)
        return True
    print("  info panel button not found", flush=True)
    return False


def find_link(boxes, capture_h=1000):
    """Find the info-panel "General Horoscopes" command link.

    Must be a 'Horoscopes' with a 'General' immediately to its left on the
    same line AND in the info-panel region: right of the chat pane and near
    the bottom of the window. The chat itself also contains a "General
    Horoscopes" message header, and picking that one clicks a message instead
    of launching the Mini App (which silently does nothing).
    """
    panel_min_y = int(capture_h * 0.80)
    cands = [b for b in boxes
             if b[4].lower() == "horoscopes" and b[1] >= panel_min_y]
    for x, y, w, h, t in sorted(cands, key=lambda b: -b[1]):
        left = [b for b in boxes
                if b[4].lower() == "general" and abs(b[1] - y) <= 6
                and 0 < x - (b[0] + b[2]) < 40]
        if left:
            gx = min(b[0] for b in left)
            return (gx, y, (x + w) - gx, h, "General Horoscopes")
    return None


# --------------------------------------------------------------- vision aid
# UI-Venus-2-9B on gx10. Used ONLY when OCR cannot find the target: text
# labels are resolved by OCR (pixel-exact, 100% in bench_venus_final.py),
# while icons and unfamiliar layouts are what the vision model is for
# (icon-button median error ~1.7px, measured against UIA rects).
# This replaces the stale fixed-pixel fallbacks that used to mis-click.
VENUS_ENABLED = os.environ.get("UFO_VISION", "1") not in ("0", "false", "no")


async def vision_box(c, description, tag="vision"):
    """Locate a control semantically with Venus; return an OCR-style box.

    Returns (x, y, w, h, label) or None. The window is re-pinned first so the
    bitmap-to-physical mapping stays valid (clicks resize the window).
    """
    if not VENUS_ENABLED:
        return None
    try:
        import venus_client
    except Exception as e:
        print(f"  vision unavailable: {e}", flush=True)
        return None
    try:
        fit_window(c)
        path = await snap(c, f"vshot_{tag}")
        if not path:
            return None
        res = venus_client.locate(path, description, prefer="venus")
        if not res.found:
            print(f"  vision could not locate {description!r}", flush=True)
            return None
        x, y = res.x, res.y
        return (int(x) - 8, int(y) - 8, 16, 16, description[:40])
    except Exception as e:
        print(f"  vision error ({type(e).__name__}: {e})", flush=True)
        return None


async def verify(c, name, must_have, label):
    """Re-pin the window, screenshot + OCR, assert expected text is present."""
    fit_window(c)          # clicks resize the window; normalise before capture
    path = await snap(c, name)
    if not path:
        return None, set(), ""
    words, text, boxes = ocr_words(path)
    ok = all(m.lower() in words or m.lower() in text for m in must_have)
    print(f"  verify {label}: {'OK' if ok else 'MISSING ' + str(must_have)}",
          flush=True)
    return ok, words, boxes


async def click_box(c, box, label):
    """Click the centre of an OCR word box (window re-pinned first)."""
    from ufo.automation.desktop import Rect
    x, y, w, h = box[0], box[1], box[2], box[3]
    fit_window(c)
    px, py = WIN_X + x + w // 2, WIN_Y + y + h // 2
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


async def ensure_chat_state(c, bot, expect=("astrology", "horoscope"),
                           tries=3):
    """Put Telegram into a known state before clicking anything.

    Two drift modes were observed in the field and both silently poisoned
    every later step:

      * the wrong chat is active (the window title is the only truth), and
      * the chat is in message-SELECTION mode, which replaces the whole
        layout with a FORWARD/DELETE/CANCEL bar - the info panel link then
        does not exist and every coordinate target is wrong.

    Returns True when the window title matches the expected bot. Recovery is
    a plain ESC (selection mode) plus a deeplink re-open; nothing here is
    destructive.
    """
    import win32gui

    for attempt in range(tries):
        title = ""
        try:
            title = win32gui.GetWindowText(c.get_concrete_hwnd()) or ""
        except Exception:
            pass
        low = title.lower()
        if any(e in low for e in expect):
            # selection mode overlays the chat even in the right chat
            fit_window(c)
            path = await snap(c, f"vstate_{attempt}")
            if path:
                _w, text, _b = ocr_words(path)
                stuck = any(k in text for k in
                            ("forward", "delete", "cancel"))
                if stuck:
                    print("  selection mode detected - pressing ESC",
                          flush=True)
                    await escape_press(c)
                    await asyncio.sleep(1.2)
            return True

        print(f"  wrong/unknown chat (title={title!r}) - re-opening {bot}",
              flush=True)
        try:
            os.startfile(f"tg://resolve?domain={bot}")
        except Exception as e:
            print(f"  deeplink failed: {e}", flush=True)
        await asyncio.sleep(4.0)
        await c.force_telegram_top()
        await asyncio.sleep(1.0)
    return False


async def escape_press(c):
    """Send ESC through the gated controller (Rule-1 countdown still applies).

    _type_keys_safe takes a pywinauto key string, e.g. "{ESC}".
    """
    try:
        ok = await c._type_keys_safe("{ESC}")
        if not ok:
            print("  ESC injection refused (countdown cancelled?)", flush=True)
    except Exception as e:
        print(f"  ESC failed: {type(e).__name__}: {e}", flush=True)


async def detect_miniapp_consent(c, name="consent"):
    """Detect Telegram's Mini App consent sheet.

    Telegram shows "By launching this mini app, you agree to the Terms of
    Service for Mini Apps." before the first launch of a Mini App. It is a
    MODAL that replaces the layout, so every later coordinate target is wrong
    while it is up - which is exactly how a run that "clicks the link" and
    nothing happens.

    Accepting it is a Terms-of-Service decision, so this function only
    DETECTS. `accept_miniapp_consent` is opt-in via --accept-miniapp-tos.
    """
    fit_window(c)
    path = await snap(c, name)
    if not path:
        return None
    _w, text, boxes = ocr_words(path)
    flat = text.lower()
    if "terms of service" in flat and "mini app" in flat:
        return {"detected": True, "screenshot": path,
                "words": len(boxes)}
    return {"detected": False, "screenshot": path}


async def accept_miniapp_consent(c, words=None):
    """Click the consent sheet's confirm button (opt-in; see module docstring).

    The button is located by OCR: the sheet's primary action is the bottom-
    right control, and its label is one of the known accept strings.
    """
    from ufo.automation.desktop import Rect

    for label in ("Open", "Continue", "Accept", "Agree", "OK"):
        box = find_box(words, label, exact=True, y_min=600)
        if box:
            await click_box(c, box, f"consent '{label}'")
            return True
    return False


async def main():
    argv = sys.argv[1:]
    bot = "AstrologyScienceBot"
    period = "tomorrow"
    period_bm = TOMORROW_BM
    PERIOD_BM = {"tomorrow": TOMORROW_BM, "week": (954, 418),
                 "month": (954, 464), "year": (954, 512)}
    only = []
    accept_tos = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--bot" and i + 1 < len(argv):
            bot = argv[i + 1]; i += 2; continue
        if a == "--period" and i + 1 < len(argv):
            period = argv[i + 1]
            period_bm = PERIOD_BM.get(period, TOMORROW_BM)
            i += 2; continue
        if a == "--accept-miniapp-tos":
            # Explicit opt-in only: this clicks a button that accepts
            # Telegram's Terms of Service for Mini Apps on the user's
            # account. It is never done implicitly.
            accept_tos = True
            i += 1; continue
        only.append(a.lower())
        i += 1
    if not only:
        only = SIGNS

    c = await ensure_connected()
    if not c:
        print("connect failed")
        return

    # Make sure the astrology bot chat is the active one, and that we are not
    # sitting in a selection-mode overlay (see ensure_chat_state).
    import os
    os.startfile(f"tg://resolve?domain={bot}")
    await asyncio.sleep(5.0)
    await c.force_telegram_top()
    await asyncio.sleep(1.5)
    ready = await ensure_chat_state(c, bot)
    title = ""
    try:
        import win32gui
        title = win32gui.GetWindowText(c.get_concrete_hwnd())
    except Exception:
        pass
    print(f"active window title: {title!r} (state ok: {ready})", flush=True)
    if not ready:
        print("ABORT: could not reach the bot chat - refusing to click blindly",
              flush=True)
        try:
            await c.close()
        except Exception:
            pass
        return

    results = {}
    for sign in only:
        print(f"\n=== {sign.upper()} ===", flush=True)
        try:
            # 0) known state: right chat, no selection overlay, info panel open
            fit_window(c)
            if not await ensure_chat_state(c, bot, tries=2):
                raise RuntimeError("lost the bot chat mid-run")

            # 0b) Mini App consent sheet - a modal that blocks the whole flow.
            consent = await detect_miniapp_consent(c, f"consent_{sign}")
            if consent and consent.get("detected"):
                if not accept_tos:
                    raise RuntimeError(
                        "BLOCKED: Telegram is showing the Mini App consent "
                        "sheet ('you agree to the Terms of Service for Mini "
                        "Apps'). Accepting it is a Terms-of-Service decision, "
                        "so the collector will not click it unless you pass "
                        "--accept-miniapp-tos. Accept it once in the Telegram "
                        "UI, or re-run with that flag.")
                print("  consent sheet detected - accepting (opt-in flag set)",
                      flush=True)
                _w, _t, boxes = ocr_words(consent["screenshot"])
                if not await accept_miniapp_consent(c, boxes):
                    raise RuntimeError(
                        "consent sheet present but its confirm button was not "
                        "found - accept it once in the Telegram UI")

            await ensure_info_panel(c)

            # 1) open the Mini App. The command link's pixel position drifts
            #    with the panel layout, so locate it by OCR, fall back to the
            #    vision model, and only then to the measured map.
            _ok, _w, boxes = await verify(c, f"v_pre_{sign}", [], "pre-state")
            from PIL import Image as _PILImage
            try:
                with _PILImage.open(
                        r"C:\Users\lnxzf\Desktop\projects\ufo\ufo\\"
                        f"astro_v_pre_{sign}.png") as _im:
                    _cap_h = _im.size[1]
            except Exception:
                _cap_h = 1000
            link = find_link(boxes, _cap_h)
            if link:
                await click_box(c, link, "open app")
            else:
                link = await vision_box(
                    c, "the 'General Horoscopes' command link in the chat "
                       "info panel", f"link_{sign}")
                if link:
                    await click_box(c, link, "open app (vision)")
                else:
                    await click(c, OPEN_APP_BM, "open app (fixed)")
            await asyncio.sleep(3.0)
            ok, _w, _b = await verify(c, f"v_menu_{sign}", ["Select", "Tomorrow"],
                                      "app menu")
            if not ok:
                await ensure_info_panel(c)
                _ok, _w, boxes2 = await verify(c, f"v_pre2_{sign}", [],
                                               "pre-state 2")
                try:
                    with _PILImage.open(
                            r"C:\Users\lnxzf\Desktop\projects\ufo\ufo\\"
                            f"astro_v_pre2_{sign}.png") as _im:
                        _cap_h2 = _im.size[1]
                except Exception:
                    _cap_h2 = 1000
                link = find_link(boxes2, _cap_h2)
                if link is None:
                    # OCR could not see the panel link: let the vision model
                    # ground it instead of clicking stale measured pixels.
                    link = await vision_box(
                        c, "the 'General Horoscopes' command link in the "
                           "chat info panel", f"link_retry_{sign}")
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
            if cell is None:
                cell = await vision_box(
                    c, f"the '{sign.capitalize()}' option in the zodiac "
                       f"sign selector", f"sign_{sign}")
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
                if cell is None:
                    cell = await vision_box(
                        c, f"the '{sign.capitalize()}' option in the zodiac "
                           f"sign selector", f"sign_retry_{sign}")
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
            if opt is None:
                opt = await vision_box(
                    c, f"the 'For {label}' option in the general horoscope "
                       f"type list", f"period_{sign}")
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