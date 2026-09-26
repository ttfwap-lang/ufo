# Where should OmniParser run? (measured 2026-09-26)

**Verdict: the Lenovo, not gx10. Installed there (2026-09-26); optional for the Telegram runner.**

## Evidence

| Host / device | Latency | Memory | Source |
|---|---|---|---|
| Lenovo GPU, **icons only** (detector + captions) | **0.9 s** median, 82 elements | **899 MB** peak VRAM of 8 GB | measured, 5 runs, standalone |
| Lenovo GPU, **full service** (icons + WinRT OCR + merge) | **0.91 s** at imgsz 640, 1.02 s at 1024 (140-143 elements) | ~1.3 GB VRAM total | measured through the HTTP service |
| same, with EasyOCR instead of WinRT (earlier build) | 1.73-1.96 s | | superseded, see docs/lenovo_performance.md |
| Lenovo, Core Ultra 9 386H CPU (fp32) | **3.0 s** (3.16, 2.88), 82 elements | ~1.3 GB RAM | measured, 2 runs |
| gx10, CPU | ~34 s | contends with the LLM pools | `gx10_recover.py`, `system.yaml` |
| gx10, GPU | ~7 s for 150 elements, **when it fit** | CUDA OOM once Qwen+Venus reserved the unified memory | `AGENT_PLAN.md` |

Same input for the Lenovo runs: a real 1438x1000 Telegram capture, YOLO
`icon_detect` at conf 0.05 / iou 0.1 / imgsz 640, then Florence-2 captions for
every crop (64x64, batch 64, greedy, 20 tokens), i.e. the upstream pipeline.
OCR is excluded: WinRT OCR already runs natively on Windows. All 82 captions
were non-empty. The weights are the same `microsoft/OmniParser-v2.0` the gx10
service loads, so detections do not depend on the host; only speed and memory do.

## Why not gx10

- It is the most contended machine in the setup. The 121 GB unified memory is
  reserved by the LLM pools; OmniParser either OOMs on CUDA or falls to CPU,
  where it takes ~34 s and starves Qwen/Venus of host CPU (the thrash that made
  gx10 unresponsive, see `gx10_recover.py`).
- The screenshot lives on the Lenovo. Sending it to gx10 adds a network hop and
  makes every parse depend on a tunnel and a box that is, as of this writing,
  **offline in Tailscale** (last seen 11+ min, SSH and :7861 unreachable).
- A loaded-but-idle OmniParser there costs memory that Qwen/Venus need.

## Why the Lenovo works

- The model is tiny (~1.3 GB weights, 0.9 GB VRAM) against an idle 8 GB GPU.
- No network, no tunnel, no dependency on gx10 being up.
- Even with the GPU busy, the 16-core CPU path (3 s) beats gx10's CPU path 10x.
- Needs CUDA 12.8+ PyTorch (Blackwell, compute capability 12.0). The project
  venv and the system Python 3.12 both have **CPU-only torch 2.14**, so a GPU
  build has to be installed deliberately (`--index-url .../whl/cu128`).

## Does the Telegram runner even need it?

Not for scripted flows. Its grounding is UIA + WinRT OCR + UI-Venus fusion
(`venus_client.py`), verified 6/6 including OCR-invisible icons. `telegram_gui.py`
never calls OmniParser; it is reached only through the vision-fallback rank 1,
the `mcp_fallback_omniparser` tool, and the bridge's `multi` cross-check.
Its real value is **enumerating every clickable region on an unfamiliar screen**
(Mini App webviews, hostile canvases) without knowing what to ask Venus for.

## Footprint

Dedicated venv `.venv_omniparser` (~5 GB: CUDA torch + ultralytics + EasyOCR),
the 1.3 GB OmniParser weights and Florence-2 code in the HuggingFace cache, and
~1.3 GB of VRAM while the service is up. The project venv and the system Python
(both CPU-only torch) are untouched. To remove it:
`powershell -File local_omniparser\install_task.ps1 -Remove`, then delete
`.venv_omniparser`.

## What was installed, and what the install taught

`local_omniparser/service.py` on `127.0.0.1:7871` (NOT 7861: that local port is
the tunnel to gx10), dedicated venv `.venv_omniparser` (CUDA 12.8 torch),
scheduled task `UFO-OmniParser-Local` (`install_task.ps1`), log
`local_omniparser/omniparser_local.log`. Same `POST /api/parse` contract as the
gx10 service; verified through the repo's own `OmniParser._rest_parse` client.

The first cut of the service took **4-7 s per call, not ~1 s**. Profiling (the
service reports per-stage `timings`) found three separate causes:

1. **Captioning 3-5 s instead of 0.8 s.** First use of CUDA in a *new thread*
   costs ~5 s (fresh worker thread 5.85 s, second call 0.80 s), and any new
   caption batch shape costs seconds again. FastAPI's threadpool hands requests
   to arbitrary threads and icon counts differ per screenshot. Fix: one
   dedicated worker thread that also runs the warm-up, and caption batches padded
   to a constant size.
2. **EasyOCR 3.98 s -> 1.28 s** with `batch_size=64` (identical 104 boxes; its
   default recognises one box at a time). Shrinking the canvas did not help.
3. A suspected cuDNN-flag side effect of EasyOCR was tested and **disproved**
   (flags unchanged), so it was not "fixed".

Task Scheduler "restart on failure" does **not** restart a killed process here
(task returns to Ready, result 0xFFFFFFFF), so the task instead re-fires every
2 minutes with `IgnoreNew`: ignored while the service lives, started if dead.

Not done: gx10's own `omniparser.service` is still enabled there. gx10 was
offline when this was installed; `gx10_recover.py` stops it on the next contact.
