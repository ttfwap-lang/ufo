"""Benchmark UI-Venus grounding accuracy against WinRT OCR ground truth.

For each capture we take real OCR word boxes (known positions) and ask Venus to
return the click point for that same label. We then measure:

  * hit rate within a tolerance (default 40 px)
  * median / mean distance from the OCR box centre

This decides whether Venus should be the PRIMARY locator, a fusion partner, or
only a fallback / verifier in the UFO bridge.
"""
import base64
import json
import os
import re
import statistics
import subprocess
import sys
import time
import urllib.request

BASE = r"C:\Users\lnxzf\Desktop\projects\ufo\ufo"
OCR = os.path.join(BASE, "ocr_shot.ps1")
VENUS = os.environ.get("VENUS_URL", "http://100.67.13.78:8002/v1")
MODEL = "ui-venus"
TOL = 40

# Targets chosen to be text labels (Venus's strength) on known captures.
TARGETS = [
    ("astro_v_pre_aries.png", "Horoscopes"),
    ("astro_v_menu_aries.png", "Select"),
    ("astro_v_grid_aries.png", "Taurus"),
    ("astro_v_pick_aries.png", "Tomorrow"),
    ("astro_horoscope_aries.png", "Click"),
    ("astro_v_grid_taurus.png", "Pisces"),
    ("astro_horoscope_taurus.png", "Love"),
    ("astro_v_pre_cancer.png", "Horoscopes"),
    ("astro_v_grid_cancer.png", "Gemini"),
    ("astro_horoscope_cancer.png", "Career"),
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


def venus_point(img_b64, label):
    prompt = (f"Locate the UI element labelled '{label}' in this screenshot. "
              "Reply with only its click point as (x, y) in image pixel "
              "coordinates.")
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "image_url",
             "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
            {"type": "text", "text": prompt},
        ]}],
        "temperature": 0.0,
        "max_tokens": 32,
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
        return None, txt.strip()[:80]
    return (float(m.group(1)), float(m.group(2))), None


def centre(box):
    x, y, w, h, _t = box
    return x + w / 2.0, y + h / 2.0


def main():
    rows = []
    for fname, label in TARGETS:
        path = os.path.join(BASE, fname)
        if not os.path.exists(path):
            print(f"[skip] {fname} missing")
            continue
        boxes = ocr_boxes(path)
        hits = [b for b in boxes if b[4].lower() == label.lower()]
        if not hits:
            print(f"[skip] {fname}: OCR did not find '{label}'")
            continue
        gt = max(hits, key=lambda b: b[2] * b[3])  # biggest instance
        gx, gy = centre(gt)
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        t0 = time.time()
        try:
            pt, err = venus_point(b64, label)
        except Exception as e:
            print(f"[err ] {fname}/{label}: {type(e).__name__}: {e}")
            continue
        dt = time.time() - t0
        if pt is None:
            print(f"[bad ] {fname}/{label}: unparseable {err!r}")
            continue
        dist = ((pt[0] - gx) ** 2 + (pt[1] - gy) ** 2) ** 0.5
        rows.append((fname, label, gx, gy, pt[0], pt[1], dist, dt))
        ok = "HIT " if dist <= TOL else "MISS"
        print(f"[{ok}] {fname:30} '{label:11} "
              f"ocr=({gx:6.0f},{gy:6.0f}) venus=({pt[0]:6.0f},{pt[1]:6.0f}) "
              f"d={dist:6.1f}px  {dt:4.1f}s")

    if not rows:
        print("no measurements")
        return
    dists = [r[6] for r in rows]
    hits = sum(1 for d in dists if d <= TOL)
    print(f"\n=== Venus grounding vs OCR ground truth (tol={TOL}px) ===")
    print(f"n={len(rows)}  hit-rate={hits}/{len(rows)} "
          f"({100.0*hits/len(rows):.0f}%)")
    print(f"median={statistics.median(dists):.1f}px  "
          f"mean={statistics.mean(dists):.1f}px  "
          f"max={max(dists):.1f}px")
    print(f"mean latency={statistics.mean(r[7] for r in rows):.1f}s")
    with open(os.path.join(BASE, "venus_grounding_bench.json"), "w",
              encoding="utf-8") as f:
        json.dump([{"file": r[0], "label": r[1], "ocr": [r[2], r[3]],
                    "venus": [r[4], r[5]], "dist": r[6], "secs": r[7]}
                   for r in rows], f, indent=2)


if __name__ == "__main__":
    main()
