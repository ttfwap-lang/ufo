#!/usr/bin/env bash
# (Re)creates the ui-venus container (UI-Venus-2-9B grounding model, vLLM, 127.0.0.1:8002 ONLY).
# Sizes come from gx10_budget.env. This is the only Venus launcher: an older copy under
# gx10_runner/ bound 0.0.0.0 (LAN-exposed, no auth) and ignored VENUS_SEQS here.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
. "$here/gx10_guard.sh"

MEM="${VENUS_GPU_MEM:-0.20}"

guard_acquire ui-venus "$MEM"
docker rm -f ui-venus >/dev/null 2>&1 || true

docker run -d --name ui-venus --restart unless-stopped \
  --network host --ipc host --shm-size 8g --gpus all \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 -e VLLM_MARLIN_USE_ATOMIC_ADD=1 \
  -e TORCH_MATMUL_PRECISION=high -e CUTE_DSL_ARCH=sm_121a \
  -v /srv/models/base/UI-Venus-2-9B:/models/UI-Venus-2-9B:ro \
  "${VENUS_IMAGE:-vllm/vllm-openai:latest}" \
  /models/UI-Venus-2-9B --host 127.0.0.1 --port 8002 --served-model-name ui-venus \
  --gpu-memory-utilization "$MEM" --max-model-len "${VENUS_MAX_LEN:-16384}" \
  --max-num-seqs "${VENUS_SEQS:-8}" --limit-mm-per-prompt "{\"image\":1}" --reasoning-parser qwen3 --trust-remote-code ${VENUS_QUANT:+--quantization "$VENUS_QUANT"} ${VENUS_EXTRA_ARGS:-}
