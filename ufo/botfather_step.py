"""BotFather flow step helper (gated automation).

Per AGENTS.md global rules:
  Rule 1: 5s on-top countdown before ANY input (gate enforced by controller)
  Rule 2: force Telegram on top (elevated path if needed)
  Rule 3: screenshot after each action
  Rule 5: BotFather found via sidebar search/deeplink; tokens NEVER stored

Usage:
  python botfather_step.py open                  -> open BotFather (real click)
  python botfather_step.py deeplink              -> open via tg:// resolve
  python botfather_step.py seek <query>          -> sidebar global search
  python botfather_step.py send <text>           -> type into chat input + Enter
  python botfather_step.py shot                  -> screenshot current state
"""
import sys, asyncio
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, "C:\\Users\\lnxzf\\Desktop\\projects\\ufo")
from ufo.automator.app_apis.telegram import TelegramGUIController
from ufo.automation.factory import get_desktop_automation
from ufo.automation.desktop import Rect
import ctypes


def get_scale() -> float:
    """System DPI scale (GetDpiForSystem/96). Physical = logical * scale."""
    try:
        dpi = ctypes.windll.user32.GetDpiForSystem()
        return dpi / 96.0
    except Exception:
        return 1.0


def phys_rect(w) -> "Rect":
    """Convert the window's LOGICAL rect to PHYSICAL pixel rect for clicks."""
    s = get_scale()
    return Rect(
        left=int(w.left * s), top=int(w.top * s),
        right=int(w.right * s), bottom=int(w.bottom * s),
    )


def phys_offset(w, ox, oy, ow=50, oh=50) -> "Rect":
    """A Rect around a PHYSICAL px offset (offsets match the captured PNG)."""
    r = phys_rect(w)
    return Rect(left=r.left + ox, top=r.top + oy,
                right=r.left + ox + ow, bottom=r.top + oy + oh)


async def snap(c, name="botfather_state.png"):
    shot = await c.take_screenshot()
    with open(name, "wb") as f:
        f.write(shot)
    print(f"saved {name}", len(shot))


async def uia_click_by_text(c, ctype, text, exact=True):
    """Find a descendant by control_type + window_text and UIA-click it."""
    def _do():
        handle = c.window.handle
        for el in handle.descendants(control_type=ctype):
            try:
                t = (el.window_text() or "").strip()
            except Exception:
                continue
            if (t == text) if exact else (text in t):
                el.click_input()
                return True
        return False
    return await asyncio.to_thread(_do)


async def uia_find_rect(c, ctype, text):
    """Return the PHYSICAL rect of a descendant by control_type + text."""
    def _do():
        handle = c.window.handle
        for el in handle.descendants(control_type=ctype):
            try:
                t = (el.window_text() or "").strip()
            except Exception:
                continue
            if t == text:
                r = el.element_info.rectangle
                return (r.left, r.top, r.right, r.bottom)
        return None
    return await asyncio.to_thread(_do)


async def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "shot"
    desktop = get_desktop_automation("Telegram.exe")
    c = TelegramGUIController(desktop)
    connected = await c.connect()
    print("connected:", connected)
    if not connected:
        return

    w = c.window.rect if c.window else None

    if cmd == "open":
        ok = await c.open_chat("BotFather")
        print("open BotFather:", ok)
        await asyncio.sleep(1.0)
        await snap(c)

    elif cmd == "deeplink":
        import os
        os.startfile("tg://resolve?domain=BotFather")
        await asyncio.sleep(3.0)
        await snap(c)

    elif cmd == "seek":
        await c._type_keys_safe(c.SHORTCUTS["escape"])
        await asyncio.sleep(0.5)
        await c._type_keys_safe(c.SHORTCUTS["search"])
        await asyncio.sleep(0.4)
        await c._type_keys_safe(c.SHORTCUTS["select_all"])
        await asyncio.sleep(0.2)
        await c._type_keys_safe(sys.argv[2] if len(sys.argv) > 2 else "BotFather")
        await asyncio.sleep(1.2)
        await snap(c)

    elif cmd == "focus":
        # PHYSICAL-pixel clicks (PNG pixels == physical coords):
        # 1) search-panel X at PNG ~(360, 66)
        if w:
            await c._type_keys_safe(c.SHORTCUTS["escape"])
            await asyncio.sleep(0.4)
            await c._type_keys_safe(c.SHORTCUTS["escape"])
            await asyncio.sleep(0.5)
            await c._click_at_rect(phys_offset(w, 330, 40, 70, 60))   # search panel X
            await asyncio.sleep(0.6)
            await c._click_at_rect(phys_offset(w, 560, 400, 300, 100))  # chat area center
            await asyncio.sleep(0.5)
            await c._click_at_rect(phys_offset(w, 550, 740, 400, 50))   # message input
            await asyncio.sleep(0.5)
        await snap(c)

    elif cmd == "type":
        text = sys.argv[2]
        ok = await c._type_keys_safe(text)
        await asyncio.sleep(0.4)
        await c._type_keys_safe(c.SHORTCUTS["send"])
        print("typed:", ok, repr(text)[:40])
        await asyncio.sleep(2.5)
        await snap(c)

    elif cmd == "send":
        text = sys.argv[2]
        try:
            ok1 = await uia_click_by_text(c, "Button", "Cancel search")
            print("closed search panel:", ok1)
            await asyncio.sleep(0.4)
        except Exception as e:
            print("uia close err:", e)
        # Click the chat message area (physical centre) to dismiss sidebar search
        w = c.window.rect
        s = get_scale()
        phys_left = int(w.left * s); phys_top = int(w.top * s)
        try:
            await c._click_at_rect(Rect(left=phys_left + 480, top=phys_top + 380,
                                        right=phys_left + 780, bottom=phys_top + 480))
            print("clicked chat area")
        except Exception as e:
            print("chat click err:", e)
        await asyncio.sleep(0.6)
        # Tab to focus message input, type, send
        await c._type_keys_safe(c.SHORTCUTS["focus_input"])
        await asyncio.sleep(0.4)
        ok = await c._type_keys_safe(text)
        await asyncio.sleep(0.3)
        await c._type_keys_safe(c.SHORTCUTS["send"])
        print("typed:", ok, repr(text)[:40])
        await asyncio.sleep(2.4)
        await snap(c)

    elif cmd == "shot":
        await asyncio.sleep(1.0)
        await snap(c)


asyncio.run(main())
