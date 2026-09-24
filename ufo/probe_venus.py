"""Probe UI-Venus grounding from Windows over the tailnet.

Sends a real Telegram screenshot and asks for the coordinates of a UI element.
Verifies (a) the Windows->gx10 vision path, (b) the model's grounding format.
"""
import base64
import json
import os
import sys
import time
import urllib.request

VENUS = os.environ.get("VENUS_URL", "http://100.67.13.78:8002/v1")
MODEL = "ui-venus"

CANDIDATES = [
    r"C:\Users\lnxzf\Desktop\projects\ufo\ufo\astro_horoscope_aries.png",
    r"C:\Users\lnxzf\Desktop\projects\ufo\ufo\astro_v_pre_aries.png",
    r"C:\Users\lnxzf\Desktop\projects\ufo\ufo\astro_v_menu_aries.png",
]
img_path = next((p for p in CANDIDATES if os.path.exists(p)), None)
if not img_path:
    print("no screenshot found")
    sys.exit(1)

with open(img_path, "rb") as f:
    b64 = base64.b64encode(f.read()).decode()

from PIL import Image
with Image.open(img_path) as im:
    W, H = im.size
print(f"image: {img_path} ({W}x{H})")


def ask(prompt, temperature=0.0, reasoning=False, max_tokens=256):
    payload = {
        "model": MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": prompt},
            ],
        }],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if not reasoning:
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    req = urllib.request.Request(
        VENUS + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer EMPTY"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read().decode())
    msg = d["choices"][0]["message"]
    return (msg.get("content") or ""), time.time() - t0, d.get("usage")


TESTS = [
    ("grounding-point",
     "Locate the text button 'General Horoscopes' in this screenshot. "
     "Reply with only the click point as (x, y) in image pixel coordinates."),
    ("grounding-bbox",
     "Find the bounding box of the UI element labelled 'Change Sign'. "
     "Reply as JSON: {\"bbox\": [x1, y1, x2, y2]}"),
    ("describe",
     "In one short paragraph, describe what UI is currently shown."),
]

for name, prompt in TESTS:
    try:
        text, dt, usage = ask(prompt)
        print(f"\n=== {name} ({dt:.1f}s, tokens={usage}) ===")
        print(text.strip()[:600] or "(empty)")
    except Exception as e:
        print(f"\n=== {name} FAILED: {type(e).__name__}: {e} ===")
