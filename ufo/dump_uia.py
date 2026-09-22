"""Dump UIA controls of the current Telegram window to find clickable UI."""
import sys, asyncio
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, "C:\\Users\\lnxzf\\Desktop\\projects\\ufo")
from ufo.automator.app_apis.telegram import TelegramGUIController
from ufo.automation.factory import get_desktop_automation

async def main():
    desktop = get_desktop_automation("Telegram.exe")
    c = TelegramGUIController(desktop)
    await c.connect()
    print("connected, window:", repr(c.window.name) if c.window else None)

    def _dump():
        handle = c.window.handle
        out = []
        # Buttons & Edits & Text of interest
        try:
            for el in handle.descendants(control_type="Button"):
                name = el.window_text()
                r = el.element_info.rectangle
                out.append(("Button", name[:40], (r.left, r.top, r.right, r.bottom)))
        except Exception as e:
            out.append(("btn-err", str(e), ()))
        try:
            for el in handle.descendants(control_type="Edit"):
                name = el.window_text()
                r = el.element_info.rectangle
                out.append(("Edit", name[:40], (r.left, r.top, r.right, r.bottom)))
        except Exception as e:
            out.append(("edit-err", str(e), ()))
        return out

    rows = await asyncio.to_thread(_dump)
    for kind, name, r in rows:
        print(f"{kind:8s} name={name!r} rect={r}")

asyncio.run(main())
