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
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOP, 50, 40, 1150, 800,
                                  win32con.SWP_SHOWWINDOW)
    win32gui.EnumWindows(cb, None)


async def ensure_connected(retries=4):
    """Connect, restoring the window if Telegram hid/minimized itself."""
    for attempt in range(retries):
        c = TelegramGUIController()
        if await c.connect():
            print(f"connected (attempt {attempt + 1})", flush=True)
            return c
        print(f"connect failed (attempt {attempt + 1}) - restoring window", flush=True)
        _restore_telegram_window()
        await asyncio.sleep(3.0)
    return None


async def main():
    only = sys.argv[1:] or SIGNS
    c = await ensure_connected()
    if not c:
        print("connect failed")
        return

    # Make sure the astrology bot chat is the active one
    import os
    os.startfile("tg://resolve?domain=AstrologyScienceBot")
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
            # 1) open the Mini App
            await click(c, OPEN_APP_BM, "open app")
            await asyncio.sleep(2.0)
            # 2) open the sign selector
            await click(c, CHANGE_SIGN_BM, "change sign")
            await asyncio.sleep(1.5)
            # 3) pick the sign
            await click(c, SIGN_BM[sign], f"select {sign}")
            await asyncio.sleep(1.5)
            # 4) request tomorrow's general horoscope
            await click(c, TOMORROW_BM, "for tomorrow")
            await asyncio.sleep(6.0)
            # 5) evidence
            p = await snap(c, f"horoscope_{sign}")
            results[sign] = p
        except Exception as e:
            print(f"  ERROR on {sign}: {e}", flush=True)
            # re-raise Telegram and continue with the next sign
            try:
                await c.force_telegram_top()
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