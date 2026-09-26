#!/usr/bin/env bash
# UI-Venus-2-9B grounding/vision model for UFO (vLLM).
#
# Tuned for maximum UI-grounding capability on the GB10 (unified memory):
#   * --host 0.0.0.0   so the Windows UFO bridge and the agent runner can
#                       reach it over the tailnet (was localhost-only)
#   * GPU pool        Qwen holds 0.68 of the unified 121.7 GB, so only
#                     ~24 GB is actually free. VENUS_GPU_MEM must stay at or
#                     below the real free amount or vLLM aborts with
#                     "Free memory ... is less than desired GPU memory
#                     utilization". Raise it only together with a Qwen
#                     rebalance (see venus_rebalance.sh).
#   * 8 concurrent seq the collector/agent can fan out UI questions
set -euo pipefail

docker rm -f ui-venus >/dev/null 2>&1 || true

docker run -d --name ui-venus --restart unless-stopped \
  --network host --ipc host --shm-size 8g --gpus all \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 -e VLLM_MARLIN_USE_ATOMIC_ADD=1 \
  -e TORCH_MATMUL_PRECISION=high -e CUTE_DSL_ARCH=sm_121a \
  -v /srv/models/base/UI-Venus-2-9B:/models/UI-Venus-2-9B:ro \
  "${VENUS_IMAGE:-vllm/vllm-openai:latest}" \
  /models/UI-Venus-2-9B \
  --host 0.0.0.0 --port 8002 --served-model-name ui-venus \
  --gpu-memory-utilization "${VENUS_GPU_MEM:-0.19}" \
  --max-model-len "${VENUS_MAX_LEN:-16384}" \
  --max-num-seqs "${VENUS_SEQS:-8}" \
  --limit-mm-per-prompt '{"image":1}' \
  --reasoning-parser qwen3 --trust-remote-code

echo "ui-venus started (waiting for /v1/models)"
for i in $(seq 1 120); do
  sleep 5
  if curl -sf --max-time 3 http://127.0.0.1:8002/v1/models >/dev/null 2>&1; then
    echo "ui-venus ready after $((i*5))s"
    exit 0
  fi
done
echo "ui-venus did not become ready in time" >&2
docker logs --tail 20 ui-venus >&2 || true
exit 1
