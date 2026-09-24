"""Verify the UI-Venus coordinate convention and re-score grounding accuracy.

Observation from the first benchmark: Venus' y matched OCR within ~3px on
every sample while x was scaled by a constant factor ~= 1000/W. Hypothesis:

    x_pixels = x_venus / 1000 * image_width
    y_pixels = y_venus

This script (a) re-scores the same benchmark with the correction applied and
(b) probes the convention on an image of a DIFFERENT width to confirm it is
width-normalised to 1000 rather than a fixed pixel offset.
"""
import base64
import json
import os
import re
import statistics
import subprocess
import time
import urllib.request

from PIL import Image

BASE = r"C:\Users\lnxzf\Desktop\projects\ufo\ufo"
OCR = os.path.join(BASE, "ocr_shot.ps1")
VENUS = os.environ.get("VENUS_URL", "http://100.67.13.78:8002/v1")
MODEL = "ui-venus"

TARGETS = [
    ("astro_v_pre_aries.png", "Horoscopes"),
    ("astro_v_menu_aries.png", "Select"),
    ("astro_v_grid_aries.png", "Taurus"),
    ("astro_v_pick_aries.png", "Tomorrow"),
    ("astro_horoscope_aries.png", "Click"),
    ("astro_v_grid_taurus.png", "Pisces"),
    ("astro_horoscope_taurus.png", "Love"),
    ("astro_v_grid_cancer.png", "Gemini"),
    ("astro_horoscope_cancer.png", "Career"),
    ("astro_v_grid_capricorn.png", "Aquarius"),
]


def ocr_boxes(path):
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", OCR, path],
        capture_output=True, timeout=240)
    out = (r.stdout or b"").decode("utf-8", "replace")
    boxes = []
    for line in out.splitlines():
        m = re.match(r"WORD\s+\[\s*(\d+),\s*(\d+)\s+(\d+)x\s+(\d+)\]\s+(.*)", line)
        if m:
            boxes.append((int(m.group(1)), int(m.group(2)),
                          int(m.group(3)), int(m.group(4)),
                          m.group(5).strip().strip("'\"")))
    return boxes


def venus_point(b64, label):
    prompt = (f"Locate the UI element labelled '{label}' in this screenshot. "
              "Reply with only its click point as (x, y).")
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "image_url",
             "image_url": {"url": f"data:image/png;base64,{b64}"}},
            {"type": "text", "text": prompt}]}],
        "temperature": 0.0, "max_tokens": 32,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    req = urllib.request.Request(
        VENUS + "/chat/completions", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer EMPTY"})
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read().decode())
    txt = d["choices"][0]["message"].get("content") or ""
    m = re.search(r"\(?\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)?", txt)
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))


def main():
    raw, fixed = [], []
    for fname, label in TARGETS:
        path = os.path.join(BASE, fname)
        if not os.path.exists(path):
            continue
        boxes = ocr_boxes(path)
        hits = [b for b in boxes if b[4].lower() == label.lower()]
        if not hits:
            continue
        with Image.open(path) as im:
            W, H = im.size
        b64 = base64.b64encode(open(path, "rb").read()).decode()
        pt = venus_point(b64, label)
        if pt is None:
            print(f"[bad] {fname}/{label}")
            continue
        for b in hits:
            gx, gy = b[0] + b[2] / 2.0, b[1] + b[3] / 2.0
            d_raw = ((pt[0] - gx) ** 2 + (pt[1] - gy) ** 2) ** 0.5
            fx = pt[0] / 1000.0 * W
            d_fix = ((fx - gx) ** 2 + (pt[1] - gy) ** 2) ** 0.5
            raw.append(d_raw)
            fixed.append(d_fix)
            best = min(raw[-1], fixed[-1])
            flag = "HIT " if fixed[-1] <= 25 else ("near" if fixed[-1] <= 60 else "MISS")
            print(f"[{flag}] {fname:28} '{label:10} W={W} "
                  f"ocr=({gx:6.0f},{gy:5.0f}) venus=({pt[0]:6.0f},{pt[1]:5.0f}) "
                  f"fixed_x={fx:6.0f} | d_raw={d_raw:6.1f} d_fix={d_fix:6.1f}")

    def stats(name, ds):
        if not ds:
            return
        hit25 = sum(1 for d in ds if d <= 25)
        hit60 = sum(1 for d in ds if d <= 60)
        print(f"{name}: n={len(ds)} <=25px {hit25}/{len(ds)} "
              f"({100*hit25/len(ds):.0f}%)  <=60px {hit60}/{len(ds)} "
              f"({100*hit60/len(ds):.0f}%)  median={statistics.median(ds):.1f}px "
              f"mean={statistics.mean(ds):.1f}px")

    print()
    stats("raw       ", raw)
    stats("x-corrected", fixed)

    # ---- convention probe on a different width -------------------------
    print("\n=== convention probe: same content rendered at two widths ===")
    src = os.path.join(BASE, "astro_v_grid_aries.png")
    if os.path.exists(src):
        im = Image.open(src)
        W0, H0 = im.size
        for new_w in (1000, 1438, 900):
            sc = new_w / W0
            out = f"{BASE}/_probe_w{new_w}.png"
            im.resize((new_w, int(H0 * sc))).save(out)
            b64 = base64.b64encode(open(out, "rb").read()).decode()
            pt = venus_point(b64, "Taurus")
            if pt:
                print(f"  width={new_w:5} -> venus=({pt[0]:7.1f},{pt[1]:6.1f}) "
                      f"| x_norm1000->{pt[0]/1000*new_w:7.1f}px "
                      f"| y_as_is->{pt[1]:6.1f}px")
            os.remove(out)


if __name__ == "__main__":
    main()
