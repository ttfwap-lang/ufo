#!/usr/bin/env bash
# (Re)creates the qwen-abliterated vLLM container (Qwen3.6-35B-A3B NVFP4, :8000, 127.0.0.1 only).
# Every size comes from gx10_budget.env - do not hard-code numbers here. The guard refuses a
# launch that would oversubscribe the GB10's unified memory (see gx10_guard.sh) and runs before
# the running container is removed, so a refused launch never takes down a working model.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
. "$here/gx10_guard.sh"

MEM="${QWEN_GPU_MEM:-0.35}"
MAXLEN="${QWEN_MAX_LEN:-65536}"
SEQS="${QWEN_SEQS:-4}"
# vLLM answers to every name given to --served-model-name. :8000 has been served by two stacks
# (this vLLM as `qwen-abliterated`, SparkDeck llama.cpp as `qwen38-27b-turbo`) and client configs
# (agents_dgx.yaml, litellm_config.yaml) name the latter, so accept both. QWEN_ALIASES="" disables.

guard_acquire qwen-abliterated "$MEM"
docker rm -f qwen-abliterated >/dev/null 2>&1 || true

docker run -d --name qwen-abliterated --restart unless-stopped \
  --network host --ipc host --shm-size 16g --gpus all \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 -e VLLM_MARLIN_USE_ATOMIC_ADD=1 \
  -e TORCH_MATMUL_PRECISION=high -e VLLM_USE_FLASHINFER_SAMPLER=1 -e CUTE_DSL_ARCH=sm_121a \
  -v /srv/models/Qwen3.6-35B-A3B-abliterated-NVFP4-MTP:/models/Qwen3.6-35B-A3B-abliterated-NVFP4-MTP:ro \
  vllm/vllm-openai:cu130-nightly \
  /models/Qwen3.6-35B-A3B-abliterated-NVFP4-MTP --host "${QWEN_HOST:-127.0.0.1}" --port 8000 --served-model-name qwen-abliterated ${QWEN_ALIASES-qwen38-27b-turbo} \
  --max-model-len "$MAXLEN" --max-num-batched-tokens 32768 --max-num-seqs "$SEQS" --trust-remote-code \
  --gpu-memory-utilization "$MEM" --reasoning-parser qwen3 --kv-cache-dtype fp8 --attention-backend flashinfer \
  --enable-prefix-caching --enable-auto-tool-choice --tool-call-parser qwen3_coder \
  --speculative-config "{\"method\":\"mtp\",\"num_speculative_tokens\":3}" -tp 1
