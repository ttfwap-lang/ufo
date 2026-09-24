"""Validate the corrected locate() policy, including vision-only targets."""
import os

import venus_client as vc

BASE = os.path.dirname(os.path.abspath(__file__))

TEXT_TESTS = [
    ("astro_v_menu_aries.png", "Select"),            # multi-instance
    ("astro_v_grid_aries.png", "Taurus"),            # single match
    ("astro_v_pre_aries.png", "General Horoscopes"),  # info-panel link
    ("astro_v_grid_capricorn.png", "Aquarius"),
]

VISION_ONLY = [
    ("astro_v_grid_aries.png", "the back arrow navigation button"),
    ("astro_v_grid_aries.png", "the info panel toggle icon in the top bar"),
    ("astro_horoscope_aries.png", "the microphone voice message button"),
    ("astro_v_grid_aries.png", "the control that opens the zodiac sign grid"),
]


def run(fname, label, prefer="auto", show_cands=False):
    path = os.path.join(BASE, fname)
    if not os.path.exists(path):
        print(f"  [skip] {fname} missing")
        return
    boxes = vc.ocr_words(path)
    res = vc.locate(path, label, ocr_boxes=boxes, prefer=prefer)
    d = res.as_dict()
    agree = d.get("snap_distance")
    agree_s = f"{agree:6.1f}" if agree is not None else "   n/a"
    print(f"  ({d['x']:7.1f},{d['y']:6.1f})  {d['strategy']:22} "
          f"agree={agree_s}  cands={len(res.candidates):2}  {d['note'][:44]}")
    if show_cands and res.candidates:
        for c in res.candidates[:5]:
            print(f"        candidate {c['text']!r} at {c['box']} d={c['dist']}")


print("=== text labels (OCR-primary, Venus disambiguates) ===")
for f, l in TEXT_TESTS:
    print(f"{f}  '{l}'")
    run(f, l, show_cands=(l == "Select"))

print()
print("=== vision-only targets (OCR has no text to match) ===")
for f, d in VISION_ONLY:
    print(f"{f}  '{d}'")
    run(f, d)
