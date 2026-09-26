# DGX Spark (GB10) — Complete Setup Reference

> **Generated:** 2025-09-25  
> **Host:** `gx10` (192.168.4.103) | User: `nick` | SSH alias: `gx10-lan`  
> **GPU:** NVIDIA GB10 (121 GB unified memory, SM 12.1 / `sm_121`)  
> **Driver:** 580.178.04 | CUDA 13.0 | Docker 29.6.2

---

## 1. Central Model Store

All models live in **`/srv/models`** (root:models, 2775 dirs / 664 files).  
Both `nick` and `flak3dd` are in the `models` group.

```
/srv/models/
├── gguf/                           # GGUF quantized models (llama.cpp)
│   ├── Qwen3.8-27B-TurboFCFusion-735-882-Here-Uncen-NEO-CODER-MAX-MTP-Q8_0.gguf  (28.2 GiB)
│   └── mmproj-F16.gguf             # Vision projector (884 MiB)
├── comfyui/                        # ComfyUI checkpoints
│   └── qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors  (14.6 GiB)
├── base/                           # vLLM / HF format models
│   ├── UI-Venus-2-9B/              # Vision grounding model (17.5 GiB)
│   ├── Qwen3.6-35B-A3B-abliterated-NVFP4-MTP/  (21.9 GiB)
│   └── Qwen3.8-27B-OBLITERATED/    (empty dir, HF cache used instead)
├── diffusion/                      # Symlinks to diffusion models
├── loras/                          # LoRA adapters
├── cache/                          # Staging / temp
├── incoming/                       # Rsync staging for new transfers
├── profiles/                       # mm model profiles (*.env)
├── stacks/                         # mm stack presets (*.env)
└── .active-stack                   # Current mm stack (managed by mm)
```

**Symlinks for backward compatibility:**
- `/home/nick/models` → `/srv/models`
- `/home/flak3dd/gx10/models` → `/srv/models`
- `/home/flak3dd/models` → `/srv/models`

---

## 2. Model Manager (`mm`) — Light-Switch System

```bash
mm list                    # Show all profiles + status
mm stack on balanced       # 27B Heretic + Venus + 0.6B (recommended)
mm stack on full           # All 4 serving models simultaneously
mm stack on vision         # Venus + 9B Heretic
mm stack on training       # Stop ALL serving, reserve memory for Unsloth
mm stack off               # Stop everything
mm on qwen38-27b-turbo-q8  # Start single profile
mm off qwen38-27b-turbo-q8 # Stop single profile
mm logs qwen38-27b-turbo-q8
mm unsloth unsloth/Qwen3-0.6B  # Launch Unsloth training container
```

**Stack presets** (`/srv/models/stacks/*.env`):
| Stack | Profiles | Use Case |
|-------|----------|----------|
| `balanced` | `qwen38-27b-turbo-q8`, `ui-venus`, `qwen3-0.6b` | Daily driver — 27B primary + vision + fast small |
| `full` | + `qwen35-9b-defiant-q6` | Maximum concurrent capacity |
| `vision` | `ui-venus`, `qwen35-9b-defiant-q6` | Vision-heavy workloads |
| `training` | *(none)* | All memory for Unsloth |

**Running endpoints after `mm stack on balanced`:**
| Port | Model | Engine | Notes |
|------|-------|--------|-------|
| 8000 | `qwen38-27b-turbo` | llama.cpp | GGUF Q8, vision via mmproj |
| 8002 | `ui-venus` | vLLM | Vision grounding, 9B |
| 8005 | `qwen3-0.6b` | vLLM | Fast small model (may need GPU_MEM tuning) |

**Caddy proxy** (`/home/nick/abliterated-proxy/Caddyfile`) exposes:
- `http://abliterated.local` → 8000 (Qwen)
- `http://venus.local` → 8002 (Venus)
- `http://qwen.local` → 8000 (legacy)

---

## 3. Unsloth Training Environment

**Image:** `unsloth-dgx-spark:latest` (37.7 GiB)  
**Base:** `nvcr.io/nvidia/pytorch:25.11-py3` (CUDA 13.0, PyTorch 2.10, Triton 3.4)

```bash
# Interactive shell
~/unsloth-build/run-unsloth.sh

# Run training script
~/unsloth-build/run-unsloth.sh python train.py

# Quick verification
~/unsloth-build/run-unsloth.sh python /workspace/verify-unsloth.py
```

**Mounts (read-only where possible):**
- `/srv/models` → `/srv/models:ro` (all models)
- `/srv/unsloth/cache/huggingface` → `/cache/huggingface` (HF cache)
- `/srv/unsloth/work` → `/workspace` (your code / outputs)
- `/srv/unsloth/build` → `/opt/unsloth:ro` (build scripts, entrypoint)

**Verified working (2025-09-25):**
- ✅ PyTorch 2.10 + CUDA 13.0 + `sm_121` (GB10)
- ✅ Unsloth 2026.9.11 + Unsloth-Zoo 2026.9.7
- ✅ Triton 3.4.0, bitsandbytes 0.50.2, transformers 4.56.2, trl 0.22.2
- ✅ bf16 matmul, 2-step LoRA training (Qwen3-0.6B, r=8)
- ✅ **NVIDIA official validation:** 60-step QLoRA on Llama-3.1-8B (loss 2.34 → 1.51)

**Entrypoint:** `/opt/unsloth/container-entrypoint.sh` (handles user mapping, cache dirs)

---

## 4. Serving Profiles (Key Ones)

### `qwen38-27b-turbo-q8` (llama.cpp, port 8000)
- **Model:** DavidAU Qwen3.8-27B TURBO Fusion Heretic Q8_0
- **Vision:** mmproj-F16.gguf (multimodal)
- **Context:** 16K | GPU layers: 99 | FlashAttn on
- **Memory:** ~30 GB model + KV cache (~25% of 121 GB)

### `ui-venus` (vLLM, port 8002)
- **Model:** Microsoft UI-Venus-2-9B (vision grounding)
- **Image:** `vllm/vllm-openai:cu130-nightly` (CUDA 13.0 required)
- **GPU_MEM:** 0.19 (~23 GB) — keep ≤0.32 or KV cache OOMs
- **Context:** 16K | Seq: 8 | `--limit-mm-per-prompt '{"image":1}'`

### `qwen36-35b-a3b` (vLLM, port 8006)
- **Model:** Qwen3.6-35B-A3B Abliterated NVFP4 MTP
- **Quant:** NVFP4 + MTP speculative decoding
- **GPU_MEM:** 0.35 | Context: 65K | Seq: 8
- **Image:** `vllm/vllm-openai:cu130-nightly`

### `qwen3-0.6b` (vLLM, port 8005)
- **Model:** Qwen3-0.6B (fast classifier / router)
- **GPU_MEM:** 0.05 | Context: 8K

### `qwen35-9b-defiant-q6` (llama.cpp, port 8004)
- **Model:** Qwen3.5-9B Defiant Heretic Q6
- **Context:** 32K

---

## 5. Key Commands Cheatsheet

```bash
# === Model switching ===
mm stack on balanced       # Recommended daily stack
mm stack on training       # Free all memory for Unsloth
mm stack off               # Stop everything

# === Unsloth ===
~/unsloth-build/run-unsloth.sh              # Shell
~/unsloth-build/run-unsloth.sh python foo.py # Script
mm unsloth unsloth/Qwen3-0.6B                # Quick Unsloth session

# === Monitoring ===
mm status                  # One-line summary
mm logs <profile>          # Tail container logs
docker stats               # Live GPU/mem (nvidia-smi limited on GB10)
free -g                    # Unified memory view

# === Model transfers (from Windows) ===
wsl rsync -avz --progress -e "ssh -i ~/.ssh/nvsync.key" \
  /mnt/c/Users/lnxzf/Desktop/*.gguf gx10-lan:/srv/models/incoming/
# Then on Spark: mm profile add <name> --from /srv/models/incoming/...

# === Caddy proxy (Windows/macOS access) ===
# Edit /home/nick/abliterated-proxy/Caddyfile, then:
docker restart abliterated-proxy
```

---

## 6. Network & Access

| Name | Address | Purpose |
|------|---------|---------|
| LAN | `192.168.4.103` | Direct SSH, Docker API |
| Tailscale | `gx10.tail930ca4.ts.net` | Remote access |
| mDNS | `abliterated.local`, `venus.local`, `qwen.local`, `gx10.local` | LAN hostname |
| Caddy HTTP | Port 80 | Reverse proxy with model endpoints |

**SSH from Windows (PowerShell):**
```powershell
ssh -i ~/.ssh/nvsync.key nick@gx10-lan
# or use the alias (configured in ~/.ssh/config):
ssh gx10-lan
```

---

## 7. Disk Layout

```
Filesystem      Size  Used Avail Use% Mounted on
/dev/nvme0n1p2  3.7T  1.1T  2.5T  31% /                (root, models, Docker)
/dev/nvme0n1p1  511M  6.1M  505M   2% /boot/efi
```

- **Models:** ~60 GB in `/srv/models`
- **Docker images:** ~100 GB (`docker system df`)
- **HF cache:** ~80 GB in `/srv/unsloth/cache/huggingface`
- **Plenty of headroom** — 2.5 TB free

---

## 8. Troubleshooting Quick Reference

| Symptom | Fix |
|---------|-----|
| `ui-venus` OOM on startup | Increase `GPU_MEM` in profile (try 0.32) |
| `qwen3-0.6b` container disappears | Lower `GPU_MEM` or reduce `SEQS` |
| mm stack fails mid-activation | `mm stack off` then `mm stack on <name>` |
| Unsloth OOM | `mm stack on training` first (stops all serving) |
| Curl `/v1/models` fails | Wait 60-120s for model load (17 GB takes ~2 min) |
| Permission denied on `/srv/models` | `sudo chown -R root:models /srv/models && sudo chmod -R g+rwX /srv/models` |

---

## 9. Version Lock (Pinned)

| Component | Version | Source |
|-----------|---------|--------|
| Ubuntu | 24.04 LTS | Base OS |
| NVIDIA Driver | 580.178.04 | `.run` installer |
| CUDA Toolkit | 13.0 | Driver bundle |
| Docker | 29.6.2 | Docker APT |
| PyTorch | 2.10.0a0+b558c98 (25.11) | `nvcr.io/nvidia/pytorch:25.11-py3` |
| Unsloth | 2026.9.11 | Built from `Dockerfile_DGX_Spark` |
| Unsloth-Zoo | 2026.9.7 | Same build |
| Triton | 3.4.0 | Built from source (c5d671f) |
| vLLM (serving) | 0.19.2rc1.dev (cu130-nightly) | `vllm/vllm-openai:cu130-nightly` |
| llama.cpp | server-cuda (latest) | `ghcr.io/ggml-org/llama.cpp:server-cuda` |

---

## 10. Next Steps / Known Gaps

- [ ] `qwen3-0.6b` profile needs GPU_MEM tuning (container restarts under load)
- [ ] Add `qwena3b` (Qwen3.6-35B NVFP4) as a vLLM profile alongside llama.cpp 27B
- [ ] Wire OmniParser profile (`omniparser.env` exists but untested)
- [ ] Document `rebalance_models.sh` logic for dynamic GPU_MEM adjustment
- [ ] Add systemd user units for `mm stack on balanced` at boot

---

*This document reflects the live state as of 2025-09-25. Run `mm status` for current reality.*