"""Extract clean per-sign horoscope text from the collected evidence PNGs.

The captures include the sidebar, so we keep only words inside the chat pane
(x >= CHAT_X_MIN in bitmap pixels) and rebuild lines by y-clustering.
"""
import os, re, subprocess, json

BASE = r"C:\Users\lnxzf\Desktop\projects\ufo\ufo"
OCR = os.path.join(BASE, "ocr_shot.ps1")
CHAT_X_MIN = 700          # chat pane starts here in the 1438-wide capture
SIGNS = ["aries", "taurus", "gemini", "cancer", "leo", "virgo",
         "libra", "scorpio", "sagittarius", "capricorn", "aquarius", "pisces"]
PRETTY = {s: s.capitalize() for s in SIGNS}


def ocr(path):
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", OCR, path],
        capture_output=True, text=True, timeout=120)
    return r.stdout


def words_of(path):
    out = []
    for line in ocr(path).splitlines():
        m = re.match(r"WORD\s+\[\s*(\d+),\s*(\d+)\s+(\d+)x\s*(\d+)\]\s+(.*)", line)
        if m:
            x, y, w, h, t = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), m.group(5).strip()
            if x >= CHAT_X_MIN:
                out.append((y, x, t))
    return out


def to_lines(words, tol=7):
    words.sort(key=lambda w: (w[0], w[1]))
    lines, cur, cur_y = [], [], None
    for y, x, t in words:
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
    r"Dexdepth|MonsterCat|Tension Republic|20260923|\(9\+9\)|OpenCode)",
    re.I)


def main():
    out = {}
    for sign in SIGNS:
        p = os.path.join(BASE, f"astro_horoscope_{sign}.png")
        if not os.path.exists(p):
            out[sign] = None
            continue
        lines = to_lines(words_of(p))
        body = [l for l in lines if l.strip() and not NOISE.match(l.strip())]
        text = "\n".join(body)
        ratings = dict(re.findall(r"(Love|Health|Career|Lunar)\s*\((\d)/5\)", text))
        dm = re.search(r"(\d{2}\.\d{2}\.\d{4})", text)
        out[sign] = {"date": dm.group(1) if dm else None,
                     "ratings": ratings, "text": text}
        print(f"[{sign:11}] {out[sign]['date']} {ratings} lines={len(body)}")

    with open(os.path.join(BASE, "horoscope_clean.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print("\nwrote horoscope_clean.json")


if __name__ == "__main__":
    main()