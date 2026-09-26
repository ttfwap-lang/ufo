"""Generic Telegram-bot step helper (gated automation) - same engine as
botfather_step.py but parameterized for ANY bot (recon, menu driving,
message depth-first): deeplink, reply, buttons-dump, click-by-text, grep.

Per AGENTS.md: 8s on-top countdown gate before any input (controller-enforced),
Telegram forced on top, UIA-exact text reads (no OCR/vision needed).

Usage:
  python astro_step.py deeplink <domain>     open tg://resolve?domain=<domain>
  python astro_step.py reply <text>          paste+enter in the current chat
  python astro_step.py buttons               dump every UIA Button (menu/inline kb)
  python astro_step.py clickbtn <text>        UIA-click a Button by text (fuzzy)
  python astro_step.py grep <needle>          print all UIA text containing needle
  python astro_step.py keys <seq>             send a raw key sequence
  python astro_step.py clickpx <x> <y>        physical click at PNG offset
  python astro_step.py paste                  Ctrl+V + Enter (clipboard preset)
  python astro_step.py shot                   screenshot evidence
"""
import sys, asyncio
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, "C:\\Users\\lnxzf\\Desktop\\projects\\ufo")
from ufo.automator.app_apis.telegram import TelegramGUIController
from ufo.automation.factory import get_desktop_automation
from ufo.automation.desktop import Rect
import ctypes


def get_scale() -> float:
    try:
        dpi = ctypes.windll.user32.GetDpiForSystem()
        return dpi / 96.0
    except Exception:
        return 1.0


def phys_rect(w) -> "Rect":
    s = get_scale()
    return Rect(left=int(w.left * s), top=int(w.top * s),
                right=int(w.right * s), bottom=int(w.bottom * s))


def phys_offset(w, ox, oy, ow=50, oh=50) -> "Rect":
    r = phys_rect(w)
    return Rect(left=r.left + ox, top=r.top + oy,
                right=r.left + ox + ow, bottom=r.top + oy + oh)


async def snap(c, name=r"C:\Users\lnxzf\Desktop\projects\ufo\ufo\astro_state.png"):
    shot = await c.take_screenshot()
    with open(name, "wb") as f:
        f.write(shot)
    print(f"saved {name}", len(shot))


async def uia_click_by_text(c, ctype, text, exact=False):
    """Find a descendant by control_type + window_text and click its PHYSICAL
    rect center via the gated controller (HumanMouse + Rule-1 gate)."""
    def _do():
        handle = c.window.handle
        for el in handle.descendants(control_type=ctype):
            try:
                t = (el.window_text() or "").strip()
            except Exception:
                continue
            if (t == text) if exact else (text in t):
                r = el.element_info.rectangle
                if r.right - r.left <= 1 or r.bottom - r.top <= 1:
                    continue  # hidden/zero-size element
                return (r.left, r.top, r.right, r.bottom)
        return None
    rect = await asyncio.to_thread(_do)
    if not rect:
        return False
    cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
    await c._click_at_rect(Rect(left=cx - 20, top=cy - 20, right=cx + 20, bottom=cy + 20))
    return True


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

    if cmd == "deeplink":
        domain = sys.argv[2] if len(sys.argv) > 2 else "AstrologyScienceBot"
        import os
        os.startfile(f"tg://resolve?domain={domain}")
        await asyncio.sleep(3.0)
        await snap(c)

    elif cmd == "tree":
        # Full UIA descendant inventory: type, rect, text (bonus: button-role)
        def _t():
            out = []
            for el in c.window.handle.descendants():
                try:
                    t = (el.window_text() or "").strip()
                except Exception:
                    continue
                r = el.element_info.rectangle
                if t or r.right - r.left > 1:
                    out.append((el.element_info.control_type,
                                (r.left, r.top, r.right, r.bottom), t[:120]))
            return out
        items = await asyncio.to_thread(_t)
        print("elements:", len(items))
        for it in items:
            print(it)

    elif cmd == "chats":
        # UIA-verified chat list with rects (controller.get_chats)
        chats = await c.get_chats(max_chats=80)
        for ch in chats:
            print(ch.name[:60], "|", tuple(int(x) for x in ch.rect))
        print("chats:", len(chats))

    elif cmd == "searchchat":
        # Rule-5 path: sidebar GLOBAL search field -> type username -> Enter.
        name = sys.argv[2]
        await c._dismiss_overlays()
        rect = await uia_find_rect(c, "Edit", "Search")
        print("search rect:", rect)
        if not rect:
            # try the Ui::InputField via generic Edit search
            hit = None
            def _sf():
                for el in c.window.handle.descendants(control_type="Edit"):
                    try:
                        nm = el.element_info.name or ""
                    except Exception:
                        continue
                    if "search" in nm.lower():
                        r = el.element_info.rectangle
                        return (r.left, r.top, r.right, r.bottom)
                return None
            rect = await asyncio.to_thread(_sf)
            print("alt search rect:", rect)
        if rect:
            cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
            await c._click_at_rect(Rect(left=cx - 15, top=cy - 15, right=cx + 15, bottom=cy + 15))
            await asyncio.sleep(0.8)
            await c._type_text_safe(name)
            await asyncio.sleep(2.0)
            await c._type_keys_safe("{ENTER}")
            await asyncio.sleep(2.0)
        await snap(c)

    elif cmd == "topwin":
        # Native EnumWindows: pid, class, title, rect for all top-level windows
        import ctypes as _c
        from ctypes import wintypes as _wt

        def _enum():
            results = []
            user32 = _c.windll.user32
            _WNDENUMPROC = _c.WINFUNCTYPE(_wt.BOOL, _wt.HWND, _wt.LPARAM)
            _cdata = []
            @_c.WINFUNCTYPE(_wt.BOOL, _wt.HWND, _wt.LPARAM)
            def cb(hwnd, lparam):
                if not user32.IsWindowVisible(hwnd):
                    return True
                pid = _wt.DWORD()
                user32.GetWindowThreadProcessId(hwnd, _c.byref(pid))
                length = user32.GetWindowTextLengthW(hwnd)
                buf = _c.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                cls = _c.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cls, 256)
                r = _wt.RECT()
                user32.GetWindowRect(hwnd, _c.byref(r))
                _cdata.append((int(pid.value), cls.value, buf.value[:80],
                               (r.left, r.top, r.right, r.bottom)))
                return True
            user32.EnumWindows(cb, 0)
            return _cdata
        for it in await asyncio.to_thread(_enum):
            print(it)
        print("done")

    elif cmd == "clickocr":
        # Click at OCR word center (bitmap coords -> physical)
        # Usage: clickocr <word_text>  -- finds first matching word, clicks its center
        target = sys.argv[2].lower()
        import subprocess, json
        result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", 
                                 r"C:\Users\lnxzf\Desktop\projects\ufo\ufo\ocr_shot.ps1"], 
                                capture_output=True, text=True, timeout=60)
        for line in result.stdout.splitlines():
            if line.startswith("WORD "):
                # Parse: WORD [ x,  y   w x h] text
                import re
                m = re.match(r'WORD\s+\[\s*(\d+),\s*(\d+)\s+(\d+)x\s*(\d+)\]\s+(.+)', line)
                if m:
                    x, y, w, h, text = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), m.group(5)
                    if target in text.lower():
                        # Bitmap center -> physical using the LIVE window origin
                        wr = phys_rect(c.window.rect)
                        px, py = wr.left + x + w // 2, wr.top + y + h // 2
                        print(f"Clicking '{text}' at bitmap ({x},{y}) -> physical ({px},{py})")
                        await c._click_at_rect(Rect(left=px-15, top=py-15, right=px+15, bottom=py+15))
                        await asyncio.sleep(1.5)
                        await snap(c)
                        return
        print(f"No word matching '{target}' found")

    elif cmd == "clickphys":
        # Direct physical click (bypassing PNG coordinate mapping)
        px, py = int(sys.argv[2]), int(sys.argv[3])
        await c._click_at_rect(Rect(left=px-15, top=py-15, right=px+15, bottom=py+15))
        await asyncio.sleep(1.0)
        await snap(c)

    elif cmd == "webapp":
        domain = sys.argv[2] if len(sys.argv) > 2 else "AstrologyScienceBot"
        import os
        os.startfile(f"https://t.me/{domain}/app")
        await asyncio.sleep(5.0)
        await snap(c)

    elif cmd == "windows":
        # List all visible top-level windows with pid, class, title, rect
        def _w():
            out = []
            from pywinauto import Desktop as PyDesktop
            for w in PyDesktop(backend="uia").windows(visible_only=True)[:60]:
                try:
                    out.append((w.process_id(), w.class_name(), w.window_text()[:60],
                                tuple(int(x) for x in w.rectangle())))
                except Exception:
                    continue
            return out
        for it in await asyncio.to_thread(_w):
            print(it)
        print("done")

    elif cmd == "openapp":
        domain = sys.argv[2] if len(sys.argv) > 2 else "AstrologyScienceBot"
        import os
        os.startfile(f"tg://resolve?domain={domain}&app")
        await asyncio.sleep(5.0)
        await snap(c)

    elif cmd == "buttons":
        # Dump every Button with its text + physical rect (inline keyboards,
        # menus, panels) - recon without vision.
        def _b():
            out = []
            for el in c.window.handle.descendants(control_type="Button"):
                try:
                    t = (el.window_text() or "").strip()
                except Exception:
                    continue
                if t:
                    r = el.element_info.rectangle
                    out.append((t[:120], (r.left, r.top, r.right, r.bottom)))
            return out
        bs = await asyncio.to_thread(_b)
        print("buttons:", len(bs))
        for b in bs:
            print(b)

    elif cmd == "clickbtn":
        text = sys.argv[2]
        ok = await uia_click_by_text(c, "Button", text)
        print("clickbtn:", ok, repr(text)[:60])
        await asyncio.sleep(1.8)
        await snap(c)

    elif cmd == "reply":
        text = sys.argv[2]
        # 1) dismiss any search overlay with ESC (keyboard, no cursor needed)
        await c._type_keys_safe(c.SHORTCUTS["escape"])
        await asyncio.sleep(0.5)
        await c._type_keys_safe(c.SHORTCUTS["escape"])
        await asyncio.sleep(0.6)
        # 2) focus the message input via its physical rect center
        rect = await uia_find_rect(c, "Edit", "Write a message...")
        print("input rect:", rect)
        if rect:
            cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
            await c._click_at_rect(Rect(left=cx - 15, top=cy - 15, right=cx + 15, bottom=cy + 15))
            await asyncio.sleep(0.6)
        # 3) paste + enter (clipboard must be pre-set locally)
        await c._type_keys_safe(c.SHORTCUTS["paste"])
        await asyncio.sleep(0.5)
        await c._type_keys_safe(c.SHORTCUTS["send"])
        await asyncio.sleep(2.2)
        await snap(c)

    elif cmd == "openchat":
        name = sys.argv[2]
        ok = await c.open_chat(name)
        print("open_chat:", ok, repr(name)[:60])
        await asyncio.sleep(1.5)
        await snap(c)

    elif cmd == "focusinput":
        # Pure input focus: click the message input's UIA rect, NO ESC keys.
        rect = await uia_find_rect(c, "Edit", "Write a message...")
        print("input rect:", rect)
        if rect:
            cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
            print("clicking:", cx, cy)
            await c._click_at_rect(Rect(left=cx - 15, top=cy - 15, right=cx + 15, bottom=cy + 15))
            await asyncio.sleep(1.2)
        await snap(c)

    elif cmd == "typecmd":
        # Type a command into the chat input and hit Enter (no clipboard):
        # ESC x2 to dismiss overlays, focus the Edit via UIA rect, type+Enter.
        text = sys.argv[2]
        await c._type_keys_safe(c.SHORTCUTS["escape"])
        await asyncio.sleep(0.4)
        await c._type_keys_safe(c.SHORTCUTS["escape"])
        await asyncio.sleep(0.4)
        rect = await uia_find_rect(c, "Edit", "Write a message...")
        print("input rect:", rect)
        if rect:
            cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
            await c._click_at_rect(Rect(left=cx - 15, top=cy - 15, right=cx + 15, bottom=cy + 15))
            await asyncio.sleep(0.6)
        await c._type_text_safe(text)
        await asyncio.sleep(0.8)
        await c._type_keys_safe(c.SHORTCUTS["send"])
        await asyncio.sleep(2.4)
        await snap(c)

    elif cmd == "grep":
        needle = sys.argv[2]
        def _g():
            out = []
            for el in c.window.handle.descendants():
                try:
                    t = (el.window_text() or "").strip()
                except Exception:
                    continue
                if needle in t:
                    r = el.element_info.rectangle
                    out.append((el.element_info.control_type,
                                (r.left, r.top, r.right, r.bottom), t[:400]))
            return out
        hits = await asyncio.to_thread(_g)
        print("hits:", len(hits))
        for h in hits:
            print(h)

    elif cmd == "keys":
        seq = sys.argv[2]
        ok = await c._type_keys_safe(seq)
        print("keys sent:", ok, repr(seq)[:40])
        await asyncio.sleep(1.5)
        await snap(c)

    elif cmd == "clickpx":
        ox, oy = int(sys.argv[2]), int(sys.argv[3])
        if w:
            await c._click_at_rect(phys_offset(w, ox - 20, oy - 20, 40, 40))
            await asyncio.sleep(1.0)
        await snap(c)

    elif cmd == "paste":
        await c._type_keys_safe(c.SHORTCUTS["paste"])
        await asyncio.sleep(0.5)
        await c._type_keys_safe(c.SHORTCUTS["send"])
        print("pasted")
        await asyncio.sleep(2.4)
        await snap(c)

    elif cmd == "shot":
        await asyncio.sleep(1.0)
        await snap(c)


asyncio.run(main())