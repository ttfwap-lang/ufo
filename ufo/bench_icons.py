"""Does Venus' REASONING mode ground small icons better than direct mode?

Ground truth = the UIA rect of the control (exact, from Telegram's own
accessibility tree), converted into the pinned capture's bitmap space.

Run after pinning the window; prints the error for both modes.
"""
import asyncio
import base64
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, r"C:\Users\lnxzf\Desktop\projects\ufo")
from ufo.automator.app_apis.telegram import TelegramGUIController
from ufo.automation.desktop import Rect

import venus_client as vc

TARGETS = [
    ("Info", "the info panel toggle icon in the top bar"),
    ("Record Voice Message", "the microphone voice message button"),
    ("Add attachment", "the paperclip attachment button"),
    ("Chat menu", "the chat menu kebab button"),
]


def ask(img_b64, label, reasoning, temperature=0.0, max_tokens=96):
    prompt = (f"Locate the UI element described as: {label}. "
              "Reply with only its click point as (x, y).")
    payload = {
        "model": "ui-venus",
        "messages": [{"role": "user", "content": [
            {"type": "image_url",
             "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
            {"type": "text", "text": prompt}]}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if not reasoning:
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    req = urllib.request.Request(
        "http://100.67.13.78:8002/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer EMPTY"})
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read().decode())
    txt = d["choices"][0]["message"].get("content") or ""
    m = re.search(r"\(?\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)?", txt)
    if not m:
        return None, txt.strip()[:100], d.get("usage")
    return (float(m.group(1)) / 1000.0 * 1438, float(m.group(2))), txt, d.get("usage")


async def main():
    c = TelegramGUIController()
    if not await c.connect():
        print("connect failed")
        return
    import win32gui
    h = c.get_concrete_hwnd()
    win32gui.MoveWindow(h, 63, 50, 1438, 1000, True)
    await asyncio.sleep(1.0)

    # UIA ground truth
    truth = {}

    def _find():
        for el in c.window.handle.descendants(control_type="Button"):
            try:
                t = (el.window_text() or "").strip()
            except Exception:
                continue
            r = el.element_info.rectangle
            if r.right - r.left > 1:
                truth.setdefault(t, (r.left, r.top, r.right, r.bottom))
    await asyncio.to_thread(_find)

    shot = await c.take_screenshot()
    png = r"C:\Users\lnxzf\AppData\Local\Temp\icon_bench.png"
    open(png, "wb").write(shot)
    from PIL import Image
    with Image.open(png) as im:
        W, H = im.size
    print(f"capture {W}x{H}; window physical origin (63,50)\n")
    b64 = base64.b64encode(shot).decode()

    print(f"{'control':22} {'uia bitmap centre':22} {'direct':18} {'reasoning':18}")
    for name, desc in TARGETS:
        if name not in truth:
            print(f"{name:22} (not in UIA tree)")
            continue
        l, t, r, b = truth[name]
        gx = (l + r) / 2 - 63.0
        gy = (t + b) / 2 - 50.0
        out = []
        for reasoning in (False, True):
            try:
                pt, txt, usage = ask(b64, desc, reasoning,
                                     temperature=0.0 if not reasoning else 1.0)
                if pt is None:
                    out.append(f"unparsed({txt[:10]})")
                else:
                    d = ((pt[0] - gx) ** 2 + (pt[1] - gy) ** 2) ** 0.5
                    out.append(f"({pt[0]:.0f},{pt[1]:.0f}) d={d:.0f}px")
            except Exception as e:
                out.append(f"ERR {type(e).__name__}")
        print(f"{name:22} ({gx:6.0f},{gy:6.0f})        {out[0]:18} {out[1]:18}")
    await c.close()


if __name__ == "__main__":
    asyncio.run(main())
