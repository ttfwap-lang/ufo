# DGX Spark — Quick Reference Card

## 🚀 One-Liners

```bash
# Daily driver stack (27B + Vision + fast)
ssh gx10-lan "mm stack on balanced"

# Training mode (all memory for Unsloth)
ssh gx10-lan "mm stack on training"

# Stop everything
ssh gx10-lan "mm stack off"

# Status
ssh gx10-lan "mm status"
```

## 📡 Live Endpoints (after `balanced`)

| Model | Port | URL | Engine |
|-------|------|-----|--------|
| Qwen3.8-27B Turbo Q8 | 8000 | `http://gx10:8000/v1` | llama.cpp |
| UI-Venus-2-9B | 8002 | `http://gx10:8002/v1` | vLLM |
| Qwen3-0.6B | 8005 | `http://gx10:8005/v1` | vLLM |

**Caddy proxy:** `http://abliterated.local/v1/*` → 8000

## 🐍 Unsloth

```bash
# Interactive
ssh gx10-lan "~/unsloth-build/run-unsloth.sh"

# Run script
ssh gx10-lan "~/unsloth-build/run-unsloth.sh python train.py"

# Verified: 60-step QLoRA on Llama-3.1-8B ✅
```

## 💾 Model Store

```
/srv/models/
├── gguf/           # Qwen3.8-27B-Turbo-Q8 + mmproj
├── base/UI-Venus-2-9B/
├── base/Qwen3.6-35B-A3B-NVFP4-MTP/
└── comfyui/        # Qwen3-VL-32B NVFP4
```

## 🔧 Key Files

| File | Purpose |
|------|---------|
| `/usr/local/bin/mm` | Model manager (lightswitch) |
| `/srv/models/profiles/*.env` | Model profiles |
| `/srv/models/stacks/*.env` | Stack presets |
| `~/unsloth-build/run-unsloth.sh` | Unsloth launcher |
| `~/unsloth-build/Dockerfile_DGX_Spark` | Unsloth build |

## 🔑 SSH

```powershell
# From Windows
ssh gx10-lan              # alias in ~/.ssh/config
ssh -i ~/.ssh/nvsync.key nick@192.168.4.103
```

## 📊 Memory

```bash
free -g              # 121 GB unified
docker stats         # Per-container
mm status            # Stack overview
```

---

**Last verified:** 2025-09-25 — All green ✅