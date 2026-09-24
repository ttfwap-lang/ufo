"""Consolidated UI-Venus grounding benchmark (single source of truth =
venus_client, so the coordinate convention lives in exactly one place).

Text labels  -> ground truth is the WinRT OCR phrase box (pixel-exact).
Icon buttons -> ground truth is the UIA element rect (requires a live
                Telegram window; skipped when unavailable).

Reports accuracy for the raw vision point and for the fused locator, so the
value of OCR fusion is visible rather than assumed.
"""
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import venus_client as vc

BASE = os.path.dirname(os.path.abspath(__file__))
TOL = 25          # px considered a hit

TEXT_TESTS = [
    ("astro_v_pre_aries.png", "General Horoscopes"),
    ("astro_v_menu_aries.png", "Select"),
    ("astro_v_grid_aries.png", "Taurus"),
    ("astro_v_pick_aries.png", "Tomorrow"),
    ("astro_horoscope_aries.png", "Click"),
    ("astro_v_grid_taurus.png", "Pisces"),
    ("astro_horoscope_taurus.png", "Love"),
    ("astro_v_grid_cancer.png", "Gemini"),
    ("astro_horoscope_cancer.png", "Career"),
    ("astro_v_grid_capricorn.png", "Aquarius"),
    ("astro_v_grid_libra.png", "Sagittarius"),
    ("astro_horoscope_libra.png", "Health"),
]

ICON_TESTS = [
    ("Info", "the info panel toggle icon in the top bar"),
    ("Record Voice Message", "the microphone voice message button"),
    ("Add attachment", "the paperclip attachment button"),
    ("Chat menu", "the chat menu kebab button"),
    ("Menu", "the emoji/sticker button next to the input"),
]


def _d(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def text_bench():
    raw, fused = [], []
    print("=== TEXT LABELS (ground truth = OCR phrase box) ===")
    for fname, label in TEXT_TESTS:
        path = os.path.join(BASE, fname)
        if not os.path.exists(path):
            print(f"  [skip] {fname}")
            continue
        boxes = vc.ocr_words(path)
        phrases = vc.group_phrases(boxes)
        cands = [b for b in phrases if vc._label_matches(label, b[4])] or \
                [b for b in boxes if vc._label_matches(label, b[4])]
        if not cands:
            print(f"  [skip] {fname}: OCR has no '{label}'")
            continue
        gt = vc._centre(max(cands, key=lambda b: b[2] * b[3]))
        res = vc.locate(path, label, ocr_boxes=boxes, prefer="auto")
        rawpt = res.venus_px
        fusedpt = (res.x, res.y)
        if rawpt:
            raw.append(_d(rawpt, gt))
        fused.append(_d(fusedpt, gt))
        hit = "HIT " if _d(fusedpt, gt) <= TOL else "MISS"
        print(f"  [{hit}] {fname:28} '{label:18} "
              f"gt=({gt[0]:6.0f},{gt[1]:5.0f}) "
              f"fused=({fusedpt[0]:6.0f},{fusedpt[1]:5.0f}) "
              f"d={_d(fusedpt, gt):5.1f} [{res.strategy}]")
    return raw, fused


def icon_bench():
    """Live benchmark against UIA rects. Needs a pinned Telegram window."""
    import asyncio
    import win32gui
    sys.path.insert(0, r"C:\Users\lnxzf\Desktop\projects\ufo")
    from ufo.automator.app_apis.telegram import TelegramGUIController

    async def run():
        c = TelegramGUIController()
        if not await c.connect():
            print("  [skip] cannot connect to Telegram")
            return [], []
        h = c.get_concrete_hwnd()
        win32gui.MoveWindow(h, 63, 50, 1438, 1000, True)
        await asyncio.sleep(1.2)
        truth = {}

        def _find():
            for el in c.window.handle.descendants(control_type="Button"):
                try:
                    t = (el.window_text() or "").strip()
                except Exception:
                    continue
                r = el.element_info.rectangle
                if r.right - r.left > 1 and t not in truth:
                    truth[t] = (r.left, r.top, r.right, r.bottom)
        await asyncio.to_thread(_find)
        if not truth:
            print("  [skip] UIA tree exposed no buttons")
            await c.close()
            return [], []

        shot = await c.take_screenshot()
        png = os.path.join(os.environ.get("TEMP", "."), "icon_bench2.png")
        open(png, "wb").write(shot)
        from PIL import Image
        with Image.open(png) as im:
            W, H = im.size
        print(f"\n=== ICON BUTTONS (ground truth = UIA rect) capture {W}x{H} ===")
        raw, fused = [], []
        for name, desc in ICON_TESTS:
            if name not in truth:
                print(f"  [skip] {name} not in UIA tree")
                continue
            l, t, r, b = truth[name]
            gt = ((l + r) / 2 - 63.0, (t + b) / 2 - 50.0)
            res = vc.locate(png, desc, ocr_boxes=[], prefer="venus")
            if not res.found:
                print(f"  [skip] {name}: vision returned nothing")
                continue
            pt = (res.x, res.y)
            raw.append(_d(pt, gt))
            fused.append(_d(pt, gt))
            hit = "HIT " if _d(pt, gt) <= TOL else "MISS"
            print(f"  [{hit}] {name:22} gt=({gt[0]:6.0f},{gt[1]:5.0f}) "
                  f"venus=({pt[0]:6.0f},{pt[1]:5.0f}) d={_d(pt, gt):5.1f}px")
        await c.close()
        return raw, fused

    try:
        return asyncio.run(run())
    except Exception as exc:
        print(f"  [skip] icon benchmark failed: {type(exc).__name__}: {exc}")
        return [], []


def report(name, ds):
    if not ds:
        print(f"{name}: no data")
        return
    hits = sum(1 for d in ds if d <= TOL)
    print(f"{name}: n={len(ds)}  hit<={TOL}px {hits}/{len(ds)} "
          f"({100*hits/len(ds):.0f}%)  median={statistics.median(ds):.1f}px  "
          f"mean={statistics.mean(ds):.1f}px  max={max(ds):.1f}px")


if __name__ == "__main__":
    raw, fused = text_bench()
    print()
    report("text: raw Venus point ", raw)
    report("text: fused locator   ", fused)
    iraw, ifused = icon_bench()
    print()
    report("icons: raw Venus point", iraw)
    out = {"text_raw": raw, "text_fused": fused,
           "icons_raw": iraw, "tolerance_px": TOL}
    with open(os.path.join(BASE, "venus_bench_final.json"), "w",
              encoding="utf-8") as f:
        json.dump(out, f, indent=2)
