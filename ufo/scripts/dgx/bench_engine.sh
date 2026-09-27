#!/usr/bin/env bash
# bench_engine.sh - STAGED, run by hand when you accept ~15-20 min of brain downtime.
#
#   ~/ufo-galaxy/bench_engine.sh vllm     benchmark NVIDIA vLLM aarch64 (Blackwell-native, FP8)
#   ~/ufo-galaxy/bench_engine.sh sglang   benchmark SGLang arm64 (FP8) - more likely to hit
#                                         sm_121 kernel gaps; try vllm first
#
# WHAT IT DOES (and why the brain must go down): the 42B brain (llama.cpp GGUF,
# container qwen3-42b-coder, :8000) and a second 42B on a modern engine cannot
# both fit in 121 GB. So this stops the llama.cpp brain, brings the chosen engine
# up on the SAME :8000 (gateway/tunnel unchanged), benchmarks it against the known
# llama.cpp numbers, then ALWAYS restores the llama.cpp brain - on success, on
# failure, or on Ctrl-C (EXIT trap). The llama.cpp container is only stopped, never
# removed, so rollback is a docker start.
#
# Compared to the llama.cpp 42B baseline measured 2026-09-27:
#   ~33 tok/s single stream; appended-turn prefix reuse ~1 s warm; but a mid-history
#   edit forces a FULL re-prefill (hybrid qwen3.5 arch has no cache-reuse). The point
#   of this bench is whether vLLM/SGLang prefix caching survives a mid-history edit.
set -u
ENGINE="${1:-vllm}"
BRAIN=qwen3-42b-coder                       # the llama.cpp brain container to protect
BENCH="bench-${ENGINE}-42b"                  # throwaway benchmark container
MODEL_DIR=/srv/models/Qwen3-42B-A3B-TOTAL-RECALL-v2   # BF16 safetensors, quantized to FP8 on load
PORT=8000
LOG=/srv/models/_dl/bench_${ENGINE}.log
CLIENT=~/ufo-galaxy/bench_client.py
mkdir -p /srv/models/_dl

log(){ echo "[$(date +%H:%M:%S)] $*"; }

rollback(){
  log "ROLLBACK: removing $BENCH, restoring llama.cpp brain $BRAIN"
  docker rm -f "$BENCH" >/dev/null 2>&1 || true
  docker start "$BRAIN" >/dev/null 2>&1 || true
  for i in $(seq 1 60); do
    curl -sf --max-time 3 http://127.0.0.1:$PORT/health >/dev/null 2>&1 && { log "brain back on :$PORT"; return 0; }
    sleep 5
  done
  log "WARNING: brain did not report healthy within 300 s - check 'docker logs $BRAIN'"
}
trap rollback EXIT

command -v docker >/dev/null || { echo "docker missing"; exit 1; }
[ -f "$MODEL_DIR/config.json" ] || { echo "model dir $MODEL_DIR missing"; exit 1; }
[ -f "$CLIENT" ] || { echo "client $CLIENT missing (scp it first)"; exit 1; }

exec 9>/tmp/ufo-gx10-models.lock; flock -w 300 9 || { echo "model lock busy"; exit 3; }

log "stopping llama.cpp brain $BRAIN (kept for rollback)"
docker stop "$BRAIN" >/dev/null 2>&1 || true
docker rm -f "$BENCH" >/dev/null 2>&1 || true

case "$ENGINE" in
  vllm)
    IMG=nvcr.io/nvidia/vllm:26.08-py3
    # gpu-memory-utilization 0.42 ~= 51 GB; leaves room for venus(20)+0.6b(4)+defiant(10)
    # already resident. FP8 weights + fp8 KV. Modest 32k ctx for the bench.
    log "launching vLLM (FP8) on :$PORT - cold FP8 quant of 84 GB BF16 can take several minutes"
    docker run -d --name "$BENCH" --network host --ipc host --gpus all \
      -v "$MODEL_DIR:/model:ro" "$IMG" \
      vllm serve /model --served-model-name qwen3-42b-coder --host 127.0.0.1 --port $PORT \
      --quantization fp8 --kv-cache-dtype fp8 --max-model-len 32768 \
      --gpu-memory-utilization 0.42 --enable-prefix-caching --trust-remote-code >>"$LOG" 2>&1
    ;;
  sglang)
    IMG=lmsysorg/sglang:latest
    log "launching SGLang (FP8) on :$PORT - RadixAttention prefix cache; may hit sm_121 gaps"
    docker run -d --name "$BENCH" --network host --ipc host --gpus all \
      -v "$MODEL_DIR:/model:ro" "$IMG" \
      python3 -m sglang.launch_server --model-path /model --served-model-name qwen3-42b-coder \
      --host 127.0.0.1 --port $PORT --quantization fp8 --kv-cache-dtype fp8 \
      --context-length 32768 --mem-fraction-static 0.42 --trust-remote-code >>"$LOG" 2>&1
    ;;
  *) echo "usage: $0 vllm|sglang"; exit 2 ;;
esac

log "waiting for $ENGINE health on :$PORT (up to 20 min for cold FP8 load)"
ok=0
for i in $(seq 1 240); do
  st=$(docker inspect -f '{{.State.Status}}' "$BENCH" 2>/dev/null || echo gone)
  [ "$st" != running ] && { log "container $st; last log lines:"; docker logs --tail 25 "$BENCH" 2>&1 | sed 's/^/    /'; break; }
  curl -sf --max-time 3 http://127.0.0.1:$PORT/v1/models >/dev/null 2>&1 && { ok=1; log "$ENGINE ready after $((i*5)) s"; break; }
  sleep 5
done
[ "$ok" = 1 ] || { log "$ENGINE did NOT come up - see $LOG. Rolling back."; exit 1; }

log "=== BENCHMARK: $ENGINE (prefix cache + throughput) ==="
python3 "$CLIENT" "http://127.0.0.1:$PORT/v1" qwen3-42b-coder "$ENGINE" 2>&1 | tee -a "$LOG"

log "=== SPECULATIVE DECODING NOTE (#4) ==="
log "vLLM spec-decode for this MoE needs --speculative-config with a draft model (e.g. the"
log "0.6B) and is a SEPARATE run; llama.cpp already runs MTP spec-decode on the brain. Enable"
log "here only after the baseline above is trusted, so a bad draft model does not muddy it."

log "benchmark done; EXIT trap will restore the llama.cpp brain now."
