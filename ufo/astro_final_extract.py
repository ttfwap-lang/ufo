"""Extract per-sign text + ratings from the collected evidence captures.

The chat pane position shifts with the info panel, so the left edge is derived
from the capture itself (the sidebar is ~28% of the window) instead of a
hard-coded pixel.
"""
import json
import os
import re
import subprocess

BASE = r"C:\Users\lnxzf\Desktop\projects\ufo\ufo"
OCR = os.path.join(BASE, "ocr_shot.ps1")
SIGNS = ["aries", "taurus", "gemini", "cancer", "leo", "virgo",
         "libra", "scorpio", "sagittarius", "capricorn", "aquarius", "pisces"]


def ocr_boxes(path):
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", OCR, path], capture_output=True, timeout=240)
        out = (r.stdout or b"").decode("utf-8", "replace")
    except Exception as e:
        print("ocr failed", path, e)
        return []
    boxes = []
    for line in out.splitlines():
        m = re.match(r"WORD\s+\[\s*(\d+),\s*(\d+)\s+(\d+)x\s*(\d+)\]\s+(.*)", line)
        if m:
            boxes.append((int(m.group(1)), int(m.group(2)),
                          int(m.group(3)), int(m.group(4)),
                          m.group(5).strip().strip("'\"")))
    return boxes


def capture_size(path):
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:
        return (0, 0)


def to_lines(words, tol=8):
    words.sort(key=lambda w: (w[1], w[0]))
    lines, cur, cur_y = [], [], None
    for x, y, _w, _h, t in words:
        if cur_y is None or abs(y - cur_y) <= tol:
            cur.append((x, t))
            cur_y = y if cur_y is None else cur_y
        else:
            lines.append((cur_y, sorted(cur)))
            cur, cur_y = [(x, t)], y
    if cur:
        lines.append((cur_y, sorted(cur)))
    return [" ".join(t for _, t in ln) for _, ln in lines]


NOISE = re.compile(
    r"^(Write a message|Astrology I Numerology|Search$|Archived chats|"
    r"Open$|Open App$|Gift a Star$|Ask Astrologer$|Personal Forecasts$|"
    r"General Horoscopes$|Click for details:?$|Nexus Intel|Joker|MikeBoy|"
    r"ANO Info|whale cc|Order Number|CCSHOP|KK_shop|boxed\.chat|Balrog|"
    r"Dexdepth|MonsterCat|Tension Republic|20260923|\(9\+9\)|OpenCode|"
    r"Message$|Mute$|Username$|Mobile$)",
    re.I)


def main():
    report = {}
    for sign in SIGNS:
        path = os.path.join(BASE, f"astro_horoscope_{sign}.png")
        if not os.path.exists(path):
            report[sign] = None
            print(f"[{sign}] missing")
            continue
        W, H = capture_size(path)
        boxes = ocr_boxes(path)
        # chat pane starts after the sidebar (~28% of the window width)
        xmin = int(W * 0.28)
        boxes = [b for b in boxes if b[0] >= xmin]
        lines = to_lines(boxes)
        body = [l for l in lines if l.strip() and not NOISE.match(l.strip())]
        text = "\n".join(body)
        ratings = dict(re.findall(
            r"(Love|Health|Career|Lunar)\s*\((\d)/5\)", text))
        dm = re.search(r"(\d{2}\.\d{2}\.\d{4})", text)
        sm = re.search(r"Daily Horoscope (?:for )?([A-Z][a-z]+)", text)
        report[sign] = {
            "date": dm.group(1) if dm else None,
            "sign_in_card": sm.group(1) if sm else None,
            "ratings": ratings,
            "text": text,
        }
        print(f"[{sign:11}] card={sm.group(1) if sm else '?':12} "
              f"{ratings} lines={len(body)}")

    out = os.path.join(BASE, "horoscope_final.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print("\nwrote", out)


if __name__ == "__main__":
    main()