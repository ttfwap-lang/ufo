# Where should OmniParser run? (measured 2026-09-26)

**Verdict: the Lenovo, not gx10. And it is optional for the Telegram runner.**

## Evidence

| Host / device | Latency | Memory | Source |
|---|---|---|---|
| Lenovo, RTX PRO 1000 Blackwell (CUDA 12.8) | **0.92 s** median (0.78-1.03), 82 elements | **899 MB** peak VRAM of 8 GB (0 used before) | measured, 5 runs after warm-up |
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

## If enabling it

1. Local service on `127.0.0.1` only, same `POST /api/parse` contract as
   `gx10_runner/omniparser_api.py`, so no client changes.
2. `OMNIPARSER.ENDPOINT: http://127.0.0.1:<port>`, `ENABLED: true` in
   `config/ufo/system.yaml` (the old "unusable, 34 s" comments there describe
   gx10-CPU and no longer apply to a Lenovo endpoint).
3. Stop the gx10 `omniparser.service` so it stops competing for memory.
4. Footprint of the trial: 4.8 GB scratch venv (torch + ultralytics) and the
   1.3 GB weights in the HF cache. A permanent install needs the same.
