"""Assemble the collected per-sign horoscope cards into one report.

Reads astro_horoscope_<sign>.png (evidence captured by astro_collect.py),
runs the WinRT OCR helper on each, and writes a consolidated text report.
"""
import os, re, subprocess, json, sys

BASE = r"C:\Users\lnxzf\Desktop\projects\ufo\ufo"
OCR = os.path.join(BASE, "ocr_shot.ps1")
SIGNS = ["aries", "taurus", "gemini", "cancer", "leo", "virgo",
         "libra", "scorpio", "sagittarius", "capricorn", "aquarius", "pisces"]


def ocr(path):
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", OCR, path],
            capture_output=True, text=True, timeout=120)
        return r.stdout
    except Exception as e:
        return f"OCR_FAILED {e}"


def parse_words(out):
    """Return list of (x, y, text) from the WORD lines."""
    items = []
    for line in out.splitlines():
        m = re.match(r"WORD\s+\[\s*(\d+),\s*(\d+)\s+\d+x\s*\d+\]\s+(.*)", line)
        if m:
            items.append((int(m.group(1)), int(m.group(2)), m.group(3).strip()))
    return items


def main():
    report = {}
    for sign in SIGNS:
        path = os.path.join(BASE, f"astro_horoscope_{sign}.png")
        if not os.path.exists(path):
            report[sign] = {"status": "missing"}
            print(f"[{sign}] MISSING")
            continue
        words = parse_words(ocr(path))
        if not words:
            report[sign] = {"status": "no_ocr"}
            print(f"[{sign}] no OCR words")
            continue

        # Rebuild lines by grouping words on similar y (within 6px)
        words.sort(key=lambda w: (w[1], w[0]))
        lines, cur, cur_y = [], [], None
        for x, y, t in words:
            if cur_y is None or abs(y - cur_y) <= 6:
                cur.append((x, t))
                cur_y = y if cur_y is None else cur_y
            else:
                lines.append((cur_y, sorted(cur)))
                cur, cur_y = [(x, t)], y
        if cur:
            lines.append((cur_y, sorted(cur)))

        text_lines = [" ".join(t for _, t in ln) for _, ln in lines]
        full = "\n".join(text_lines)

        # Ratings
        ratings = dict(re.findall(r"(Love|Health|Career|Lunar)\s*\((\d)/5\)", full))
        # Date
        dm = re.search(r"(\d{2}\.\d{2}\.\d{4})", full)
        report[sign] = {
            "status": "ok",
            "date": dm.group(1) if dm else None,
            "ratings": ratings,
            "text": full,
        }
        print(f"[{sign}] date={report[sign]['date']} ratings={ratings} "
              f"lines={len(text_lines)}")

    out = os.path.join(BASE, "horoscope_report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()