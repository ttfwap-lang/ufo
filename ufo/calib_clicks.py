"""Click calibration: exact UIA rect centers -> screenshot after each."""
import sys, asyncio
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, "C:\\Users\\lnxzf\\Desktop\\projects\\ufo")
from ufo.automator.app_apis.telegram import TelegramGUIController
from ufo.automation.factory import get_desktop_automation
from ufo.automation.desktop import Rect


async def uia_rect(c, ctype, text):
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


async def snap(c, name):
    shot = await c.take_screenshot()
    with open(name, "wb") as f:
        f.write(shot)
    print("saved", name, len(shot))


async def main():
    desktop = get_desktop_automation("Telegram.exe")
    c = TelegramGUIController(desktop)
    await c.connect()

    r = await uia_rect(c, "Button", "Cancel search")
    print("Cancel search rect:", r)
    if r:
        cx, cy = (r[0] + r[2]) // 2, (r[1] + r[3]) // 2
        print("clicking Cancel search at", cx, cy)
        await c._click_at_rect(Rect(left=cx - 10, top=cy - 10, right=cx + 10, bottom=cy + 10))
        await asyncio.sleep(1.0)
        await snap(c, "calib_1_cancel.png")

    r2 = await uia_rect(c, "Edit", "Write a message...")
    print("input rect:", r2)
    if r2:
        cx2, cy2 = (r2[0] + r2[2]) // 2, (r2[1] + r2[3]) // 2
        print("clicking input at", cx2, cy2)
        await c._click_at_rect(Rect(left=cx2 - 15, top=cy2 - 15, right=cx2 + 15, bottom=cy2 + 15))
        await asyncio.sleep(1.0)
        await snap(c, "calib_2_input.png")


asyncio.run(main())
