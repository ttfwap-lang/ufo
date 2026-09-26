"""OmniParser V2 screen parser - REST API + Gradio UI in ONE process.

Why this exists
---------------
OmniParser (YOLO icon detector + Florence-2 captioner) was only reachable as a
localhost-only Gradio demo. The UFO agent runs on a different host, so the
models were unusable from the automation loop. This wrapper keeps the human
UI at "/" and adds a JSON API:

    POST /api/parse   {"image_b64": "...", "box_threshold": 0.05,
                       "iou_threshold": 0.1, "use_paddleocr": true,
                       "imgsz": 640}
      -> {"width": W, "height": H, "count": N, "seconds": S,
          "elements": [{"id": "0", "bbox_xywh": [x,y,w,h],
                        "bbox_xyxy": [x1,y1,x2,y2],
                        "cx": x, "cy": y, "content": "..."}]}

    GET  /api/health  -> {"ok": true, "model": "...", "device": "cpu"}

Coordinates are returned in ABSOLUTE PIXELS of the submitted image (the
library emits ratios; they are scaled here) so the caller can click directly.

Both the API and the UI share the single loaded pair of models, so binding on
0.0.0.0 costs no extra GPU memory.
"""
import base64
import io
import os
import sys
import time
from typing import Any, Dict, List, Optional

import gradio as gr
import numpy as np
import torch
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from util.utils import (check_ocr_box, get_som_labeled_img,  # noqa: E402
                        get_yolo_model, get_caption_model_processor)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
BOX_TRESHOLD = 0.05
IOU_THRESHOLD = 0.1

# The GB10's unified memory is largely reserved by the two vLLM pools, so the
# detector/captioner may fail to allocate on CUDA. They are small (~1.3 GB), so
# fall back to CPU rather than crash-looping the service.
_load_device = os.environ.get("OMNIPARSER_DEVICE", "").strip().lower()


def _load_models(device_arg: str):
    yolo = get_yolo_model(device=device_arg) if device_arg else get_yolo_model()
    cap = get_caption_model_processor(
        model_name="florence2",
        model_name_or_path="weights/icon_caption_florence",
        device=device_arg or None)
    return yolo, cap


print("[omniparser] loading models ...", flush=True)
t0 = time.time()
attempts = [_load_device] if _load_device else ["cuda", "cpu"]
yolo_model = caption_model_processor = None
for dev in attempts:
    if dev == "cuda" and not torch.cuda.is_available():
        continue
    try:
        yolo_model, caption_model_processor = _load_models(dev)
        DEVICE = torch.device(dev)
        print(f"[omniparser] models on {dev}", flush=True)
        break
    except Exception as exc:                          # noqa: BLE001
        print(f"[omniparser] {dev} load failed ({type(exc).__name__}: "
              f"{str(exc)[:160]})", flush=True)
        yolo_model = caption_model_processor = None
if yolo_model is None:
    raise SystemExit("[omniparser] could not load models on any device")
print(f"[omniparser] models ready in {time.time()-t0:.1f}s on {DEVICE}", flush=True)


def parse_image(image: Image.Image, box_threshold: float = BOX_TRESHOLD,
                iou_threshold: float = IOU_THRESHOLD,
                use_paddleocr: bool = True, imgsz: int = 640
                ) -> Dict[str, Any]:
    """Run the full OmniParser pipeline and return ABSOLUTE pixel elements."""
    if image.mode == "RGBA":
        image = image.convert("RGB")
    w, h = image.size

    ocr_result, _ = check_ocr_box(
        image, display_img=False, output_bb_format="xyxy",
        goal_filtering=None,
        easyocr_args={"paragraph": False, "text_threshold": 0.9},
        use_paddleocr=use_paddleocr)
    ocr_text, ocr_bbox = ocr_result

    # output_coord_in_ratio=False -> label_coordinates are absolute pixels
    _img_b64, label_coords, parsed_elems = get_som_labeled_img(
        image, yolo_model, BOX_TRESHOLD=box_threshold,
        output_coord_in_ratio=False, ocr_bbox=ocr_bbox,
        draw_bbox_config=None, caption_model_processor=caption_model_processor,
        ocr_text=ocr_text, iou_threshold=iou_threshold, imgsz=imgsz)

    elements: List[Dict[str, Any]] = []
    for key, coords in (label_coords or {}).items():
        try:
            a, b, c, d = [float(v) for v in coords]
        except Exception:
            continue
        # NOTE: annotate() emits label_coordinates as [x, y, w, h] (xywh).
        # Returning them as xyxy without converting silently moves every point,
        # so convert explicitly and expose BOTH forms with unambiguous names.
        x, y, bw, bh = a, b, c, d
        x2, y2 = x + bw, y + bh
        content = None
        try:
            idx = int(key)
            if idx < len(parsed_elems) and isinstance(parsed_elems[idx], dict):
                content = parsed_elems[idx].get("content")
        except Exception:
            content = None
        elements.append({
            "id": key,
            "bbox_xywh": [int(x), int(y), int(bw), int(bh)],
            "bbox_xyxy": [int(x), int(y), int(x2), int(y2)],
            "cx": int((x + x2) / 2),
            "cy": int((y + y2) / 2),
            "content": (str(content) if content is not None else ""),
        })
    elements.sort(key=lambda e: (e["bbox_xywh"][1], e["bbox_xywh"][0]))
    return {"width": w, "height": h, "count": len(elements),
            "elements": elements}


# ------------------------------------------------------------------ REST API
app = FastAPI(title="OmniParser screen parser", version="1.0")


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "device": str(DEVICE), "model": "omniparser-v2",
            "detector": "yolo icon_detect_v3", "captioner": "florence2",
            "cuda_available": bool(torch.cuda.is_available())}


@app.post("/api/parse")
async def api_parse(payload: Dict[str, Any]) -> Any:
    b64 = payload.get("image_b64") or ""
    if not b64:
        return JSONResponse({"error": "image_b64 is required"}, status_code=400)
    if "," in b64[:64] and b64.strip().startswith("data:"):
        b64 = b64.split(",", 1)[1]
    try:
        raw = base64.b64decode(b64)
        image = Image.open(io.BytesIO(raw))
    except Exception as exc:
        return JSONResponse({"error": f"bad image: {exc}"}, status_code=400)
    try:
        t0 = time.time()
        out = parse_image(
            image,
            box_threshold=float(payload.get("box_threshold", BOX_TRESHOLD)),
            iou_threshold=float(payload.get("iou_threshold", IOU_THRESHOLD)),
            use_paddleocr=bool(payload.get("use_paddleocr", True)),
            imgsz=int(payload.get("imgsz", 640)))
        out["seconds"] = round(time.time() - t0, 2)
        return out
    except Exception as exc:                      # noqa: BLE001
        return JSONResponse({"error": f"{type(exc).__name__}: {exc}"},
                            status_code=500)


# ----------------------------------------------------------------- Gradio UI
MARKDOWN = """
# OmniParser for UFO - screen parsing (REST + UI)
`POST /api/parse` with `{"image_b64": "..."}` returns every detected element
with an absolute-pixel bounding box and a caption/OCR string.
"""

with gr.Blocks() as demo:
    gr.Markdown(MARKDOWN)
    with gr.Row():
        with gr.Column():
            img_in = gr.Image(type="pil", label="Screenshot")
            box_th = gr.Slider(0.01, 1.0, value=BOX_TRESHOLD, step=0.01,
                               label="Box Threshold")
            iou_th = gr.Slider(0.01, 1.0, value=IOU_THRESHOLD, step=0.01,
                               label="IOU Threshold")
            use_pp = gr.Checkbox(value=True, label="Use PaddleOCR")
            imgsz = gr.Slider(640, 1920, value=640, step=32,
                              label="Detect image size")
            go = gr.Button("Parse", variant="primary")
        with gr.Column():
            out_txt = gr.Textbox(label="Elements (id: bbox content)")

    def _ui(image, bt, it, pp, sz):
        if image is None:
            return ""
        res = parse_image(image, bt, it, pp, int(sz))
        lines = [f"image {res['width']}x{res['height']} "
                 f"({res['count']} elements)"]
        for e in res["elements"][:80]:
            lines.append(f"{e['id']}: {e['bbox_xywh']} {e['content']}")
        return "\n".join(lines)

    go.click(_ui, [img_in, box_th, iou_th, use_pp, imgsz], [out_txt])

# Mount the UI onto the FastAPI app so ONE process serves both.
app = gr.mount_gradio_app(app, demo, path="/")

if __name__ == "__main__":
    port = int(os.environ.get("OMNIPARSER_PORT", "7861"))
    bind = os.environ.get("OMNIPARSER_BIND", "0.0.0.0")
    print(f"[omniparser] serving API+UI on {bind}:{port} "
          f"(device={DEVICE})", flush=True)
    # gr.mount_gradio_app returns a FastAPI application, so it must be served
    # by uvicorn (FastAPI has no .run()).
    import uvicorn
    uvicorn.run(app, host=bind, port=port, log_level="warning")
