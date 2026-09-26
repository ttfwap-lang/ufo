"""Probe the OmniParser REST API from Windows over the tailnet.

Sends a real Telegram capture and reports the parsed elements. This verifies
(a) Windows -> gx10:7861 reachability, (b) the parse pipeline, (c) that the
returned boxes are absolute pixels we can click.
"""
import base64
import json
import os
import sys
import time
import urllib.request

OMNI = os.environ.get("OMNIPARSER_URL", "http://127.0.0.1:7871").rstrip("/")

CANDIDATES = [
    r"C:\Users\lnxzf\Desktop\projects\ufo\ufo\astro_v_grid_aries.png",
    r"C:\Users\lnxzf\Desktop\projects\ufo\ufo\astro_horoscope_aries.png",
    r"C:\Users\lnxzf\Desktop\projects\ufo\ufo\astro_state.png",
]


def get(path):
    with urllib.request.urlopen(OMNI + path, timeout=20) as r:
        return json.loads(r.read().decode())


def parse(path, use_paddleocr=True, imgsz=1024):
    b64 = base64.b64encode(open(path, "rb").read()).decode()
    payload = {"image_b64": b64, "use_paddleocr": use_paddleocr,
               "imgsz": imgsz, "box_threshold": 0.05}
    req = urllib.request.Request(
        OMNI + "/api/parse", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read().decode()), time.time() - t0


def main():
    print("health:", json.dumps(get("/api/health")))
    path = next((p for p in CANDIDATES if os.path.exists(p)), None)
    if not path:
        print("no capture available")
        return
    from PIL import Image
    with Image.open(path) as im:
        W, H = im.size
    print(f"\nparsing {os.path.basename(path)} ({W}x{H}) ...")
    try:
        res, dt = parse(path)
    except Exception as exc:
        print(f"  parse failed: {type(exc).__name__}: {exc}")
        return
    if "error" in res:
        print("  api error:", res["error"][:300])
        return
    print(f"  {res['count']} elements in {res.get('seconds', dt):.1f}s")
    for e in res["elements"][:24]:
        print(f"    {str(e['id']):>3}  xywh={e['bbox_xywh']} "
              f"centre=({e['cx']},{e['cy']})  {e['content'][:52]!r}")


if __name__ == "__main__":
    main()
