"""Local OmniParser V2 screen parser - same REST contract as the gx10 one.

Runs on the Windows host itself (RTX GPU, ~0.9 s per 1438x1000 capture, ~0.9 GB
VRAM; CPU fallback ~3 s). See docs/omniparser_placement.md for why it lives here
and not on gx10: gx10's memory is contested and it is a network hop away from
the screenshot.

    POST /api/parse  {"image_b64", "box_threshold", "iou_threshold", "imgsz",
                      "use_ocr"}      (use_paddleocr accepted and ignored)
      -> {"width","height","count","seconds",
          "elements":[{"id","type","bbox_xywh","bbox_xyxy","cx","cy","content"}]}
    GET  /api/health

Coordinates are ABSOLUTE PIXELS of the submitted image. Binds 127.0.0.1 only:
the endpoint accepts arbitrary images and has no authentication.

Pipeline (upstream OmniParser): YOLO icon_detect -> EasyOCR text boxes -> merge
-> Florence-2 caption for each remaining icon crop (64x64, greedy, 20 tokens).
"""
from __future__ import annotations

import base64
import io
import os
import sys
import asyncio
from concurrent.futures import ThreadPoolExecutor
import time
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("OMNIPARSER_PORT", "7871"))
BIND = os.environ.get("OMNIPARSER_BIND", "127.0.0.1")
LOG = os.path.join(HERE, "omniparser_local.log")

# pythonw has no stdout/stderr; without this every print (and any crash) is lost.
if sys.stdout is None or sys.stderr is None:
    _fh = open(LOG, "a", buffering=1, encoding="utf-8")
    sys.stdout = sys.stderr = _fh


# Start fully offline once the weights are cached. At logon the network may not
# be up yet, and HuggingFace otherwise makes a network call per model load even
# when everything is on disk. First-ever run (no cache) stays online to download.
_HF_HOME = os.environ.get("HF_HOME") or os.path.join(
    os.path.expanduser("~"), ".cache", "huggingface")
if os.path.isdir(os.path.join(_HF_HOME, "hub", "models--microsoft--OmniParser-v2.0")) \
        and os.path.isdir(os.path.join(_HF_HOME, "hub", "models--microsoft--Florence-2-base")):
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


def log(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [omniparser] {msg}", flush=True)


sys.path.insert(0, HERE)
from omni_merge import area, clamp, merge  # noqa: E402

import numpy as np  # noqa: E402
import torch  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from PIL import Image  # noqa: E402

DEVICE = os.environ.get("OMNIPARSER_DEVICE", "").strip().lower() or (
    "cuda" if torch.cuda.is_available() else "cpu")
DTYPE = torch.float16 if DEVICE == "cuda" else torch.float32
CAPTION_BATCH = 64 if DEVICE == "cuda" else 16
OCR_MIN_CONF = float(os.environ.get("OMNIPARSER_OCR_MIN_CONF", "0.4"))

# ONE dedicated worker thread runs every inference and the warm-up. First use of
# CUDA/cuDNN/cuBLAS in a thread costs seconds (measured: 5.9 s on a fresh worker
# thread vs 0.8 s once warm), and FastAPI's default threadpool hands requests to
# arbitrary threads. A single thread is warm after start-up and also serialises
# GPU jobs, so requests queue instead of overlapping.
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="omniparser")
_t0 = time.time()
log(f"loading models on {DEVICE} ...")

from huggingface_hub import snapshot_download  # noqa: E402
from transformers import AutoModelForCausalLM, AutoProcessor  # noqa: E402
from ultralytics import YOLO  # noqa: E402

_root = snapshot_download("microsoft/OmniParser-v2.0")
yolo = YOLO(os.path.join(_root, "icon_detect", "model.pt")).to(DEVICE)
processor = AutoProcessor.from_pretrained(
    "microsoft/Florence-2-base", trust_remote_code=True)
captioner = AutoModelForCausalLM.from_pretrained(
    os.path.join(_root, "icon_caption"), torch_dtype=DTYPE,
    trust_remote_code=True).to(DEVICE).eval()

OCR_NAME = "none"
_ocr = None            # EasyOCR reader (fallback engine)
_winrt = None          # winrt_ocr module (preferred engine)
_want = os.environ.get("OMNIPARSER_OCR", "auto").strip().lower()   # auto|winrt|easyocr|none
if _want in ("auto", "winrt"):
    try:
        import winrt_ocr as _winrt  # noqa: E402

        _winrt._get_engine()          # fail now, not on the first request
        OCR_NAME = "winrt"
    except Exception as exc:  # noqa: BLE001 - fall back, and say so
        _winrt = None
        log(f"WinRT OCR unavailable ({type(exc).__name__}: {exc}); falling back")
if _winrt is None and _want in ("auto", "easyocr"):
    try:
        import easyocr  # noqa: E402

        _ocr = easyocr.Reader(["en"], gpu=(DEVICE == "cuda"), verbose=False)
        OCR_NAME = "easyocr"
    except Exception as exc:  # noqa: BLE001 - degrade to icons-only, say so
        log(f"OCR unavailable, icons only: {type(exc).__name__}: {exc}")

# batch_size=64: EasyOCR's default recognises boxes one at a time; on a Telegram
# capture that is 3.98 s vs 1.28 s batched, with identical output (104 boxes).
def _ocr_boxes(image: Image.Image, raw: Optional[bytes] = None
               ) -> List[Tuple[Tuple[int, int, int, int], str]]:
    w, h = image.size
    if _winrt is not None:
        if raw is None:                       # only re-encode if we were not given bytes
            buf = io.BytesIO()
            image.save(buf, "PNG")
            raw = buf.getvalue()
        return [(clamp(b, w, h), t) for b, t in _winrt.ocr_phrases(raw)]
    if _ocr is None:
        return []
    out = []
    for pts, text, conf in _ocr.readtext(np.asarray(image), paragraph=False, batch_size=64):
        text = (text or "").strip()
        if not text or conf < OCR_MIN_CONF:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        b = clamp((int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))), w, h)
        if area(b) > 0:
            out.append((b, text))
    return out


def _caption(crops: List[Image.Image]) -> List[str]:
    caps: List[str] = []
    for i in range(0, len(crops), CAPTION_BATCH):
        real = crops[i:i + CAPTION_BATCH]
        # Always run a FULL batch (repeat the last crop, discard its captions).
        # A new batch shape costs seconds on first use, and the count of icons
        # changes with every screenshot; a constant shape is paid once, at warm-up.
        batch = real + [real[-1]] * (CAPTION_BATCH - len(real))
        inp = processor(images=batch, text=["<CAPTION>"] * len(batch),
                        return_tensors="pt", do_resize=False).to(DEVICE, DTYPE)
        with torch.inference_mode():
            gen = captioner.generate(
                input_ids=inp["input_ids"], pixel_values=inp["pixel_values"],
                max_new_tokens=20, num_beams=1, do_sample=False)
        caps += [s.strip() for s in
                 processor.batch_decode(gen, skip_special_tokens=True)][:len(real)]
    return caps


def parse_image(image: Image.Image, box_threshold: float = 0.05,
                iou_threshold: float = 0.1, imgsz: int = 640,
                use_ocr: bool = True, raw: Optional[bytes] = None) -> Dict[str, Any]:
    image = image.convert("RGB")
    w, h = image.size
    tm: Dict[str, float] = {}
    _t = time.time()
    det = yolo.predict(image, conf=box_threshold, iou=iou_threshold, imgsz=imgsz,
                       verbose=False, device=DEVICE)[0]
    icons = [clamp(tuple(int(v) for v in b), w, h)
             for b in det.boxes.xyxy.cpu().numpy().tolist()]
    icons = [b for b in icons if b[2] - b[0] >= 4 and b[3] - b[1] >= 4]
    tm["detect"] = time.time() - _t
    _t = time.time()
    texts = _ocr_boxes(image, raw) if use_ocr else []
    tm["ocr"] = time.time() - _t

    elements, to_caption = merge(icons, texts, w, h)

    _t = time.time()
    if to_caption:
        caps = _caption([image.crop(elements[i]["box"]).resize((64, 64))
                         for i in to_caption])
        for i, c in zip(to_caption, caps):
            elements[i]["content"] = c
    tm["caption"] = time.time() - _t

    elements.sort(key=lambda e: (e["box"][1], e["box"][0]))
    out = []
    for n, e in enumerate(elements):
        x1, y1, x2, y2 = e["box"]
        out.append({"id": str(n), "type": e["type"],
                    "bbox_xywh": [x1, y1, x2 - x1, y2 - y1],
                    "bbox_xyxy": [x1, y1, x2, y2],
                    "cx": (x1 + x2) // 2, "cy": (y1 + y2) // 2,
                    "content": e["content"]})
    return {"width": w, "height": h, "count": len(out), "elements": out,
            "timings": {k: round(v, 2) for k, v in tm.items()}}


app = FastAPI(title="OmniParser (local)", version="1.0")


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "device": DEVICE, "model": "omniparser-v2",
            "detector": "yolo icon_detect", "captioner": "florence2",
            "ocr": OCR_NAME, "cuda_available": bool(torch.cuda.is_available()),
            "host": "local"}


@app.post("/api/parse")
async def api_parse(payload: Dict[str, Any]) -> Any:
    b64 = payload.get("image_b64") or ""
    if not b64:
        return JSONResponse({"error": "image_b64 is required"}, status_code=400)
    if b64.startswith("data:") and "," in b64[:64]:
        b64 = b64.split(",", 1)[1]
    try:
        raw = base64.b64decode(b64)
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"bad image: {exc}"}, status_code=400)

    def _job() -> Dict[str, Any]:
        t = time.time()
        out = parse_image(
            image,
            box_threshold=float(payload.get("box_threshold", 0.05)),
            iou_threshold=float(payload.get("iou_threshold", 0.1)),
            imgsz=int(payload.get("imgsz", 640)),
            use_ocr=bool(payload.get("use_ocr", True)), raw=raw)
        out["seconds"] = round(time.time() - t, 2)
        return out

    try:
        return await asyncio.get_running_loop().run_in_executor(_pool, _job)
    except Exception as exc:  # noqa: BLE001 - report, never crash the service
        log(f"parse failed: {type(exc).__name__}: {exc}")
        return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=500)


# Plain OCR (word boxes) for callers that do not need icon detection: the bridge
# and venus_client used to spawn `powershell ocr_shot.ps1` per call (0.65-0.74 s).
# Own pool: WinRT OCR is CPU/NPU work and must not queue behind a GPU parse.
_ocr_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="omniparser-ocr")


@app.post("/api/ocr")
async def api_ocr(payload: Dict[str, Any]) -> Any:
    if _winrt is None:
        return JSONResponse({"error": "WinRT OCR not available on this host"}, status_code=503)
    b64 = payload.get("image_b64") or ""
    if b64.startswith("data:") and "," in b64[:64]:
        b64 = b64.split(",", 1)[1]
    try:
        raw = base64.b64decode(b64)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"bad image: {exc}"}, status_code=400)

    def _job() -> Dict[str, Any]:
        t = time.time()
        words = _winrt.ocr_words(raw)
        return {"words": [list(w) for w in words], "count": len(words),
                "seconds": round(time.time() - t, 3)}

    try:
        return await asyncio.get_running_loop().run_in_executor(_ocr_pool, _job)
    except Exception as exc:  # noqa: BLE001
        log(f"ocr failed: {type(exc).__name__}: {exc}")
        return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=500)


def _warm_up() -> None:
    """Runs on the worker thread: pay every first-use cost before a request."""
    t = time.time()
    _caption([Image.new("RGB", (64, 64), "white")])          # the fixed caption shape
    for size in (640, 1024):                                  # detector shapes in use
        yolo.predict(Image.new("RGB", (size, size), "white"), imgsz=size,
                     verbose=False, device=DEVICE)
    if _ocr is not None:
        _ocr.readtext(np.full((240, 640, 3), 255, dtype=np.uint8), paragraph=False,
                      batch_size=64)
    if _winrt is not None:
        buf = io.BytesIO()
        Image.new("RGB", (320, 120), "white").save(buf, "PNG")
        _winrt.ocr_words(buf.getvalue())
    log(f"warm-up done in {time.time() - t:.1f}s")


if __name__ == "__main__":
    log(f"models ready in {time.time() - _t0:.1f}s (ocr={OCR_NAME})")
    _pool.submit(_warm_up).result()
    import uvicorn

    log(f"serving on {BIND}:{PORT} device={DEVICE}")
    uvicorn.run(app, host=BIND, port=PORT, log_level="warning")
