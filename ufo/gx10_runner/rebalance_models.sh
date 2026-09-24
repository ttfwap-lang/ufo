#!/usr/bin/env bash
# Rebalance the GB10's unified memory across the three model pools.
#
# BEFORE:  Qwen 0.68 (82.7GB, ~65GB of it unused KV cache)
#          Venus 0.19 (23.1GB, too tight for 8 sequences)
#          OmniParser: could not allocate at all (CUDA OOM), only 1GB free
#
# AFTER:   Qwen 0.56 (68.2GB - still ~49GB KV cache for a 32k/8-seq model,
#                      far more than the agent loop can consume)
#          Venus 0.26 (31.6GB - ~13GB KV: 8 concurrent grounding requests)
#          ~22GB left for the OS, OmniParser (~3GB) and the node services
#
# Qwen also gains concurrency: --max-num-seqs 1 (launcher default) -> 8, which
# is what actually limits the agent today; its memory was never the binding
# constraint.
set -euo pipefail

GALAXY="$HOME/ufo-galaxy"
VENUS_MEM="${VENUS_GPU_MEM:-0.26}"
QWEN_MEM="${QWEN_GPU_MEM:-0.56}"
QWEN_SEQS="${QWEN_SEQS:-8}"
QWEN_MAXLEN="${QWEN_MAX_LEN:-32768}"

wait_http() {   # wait_http <url> <label> <tries>
  local url="$1" label="$2" tries="$3" i
  for i in $(seq 1 "$tries"); do
    if curl -sf --max-time 3 "$url" >/dev/null 2>&1; then
      echo "$label ready after $((i*5))s"; return 0
    fi
    sleep 5
  done
  echo "$label TIMED OUT"; return 1
}

echo "=== 1/4 stopping Venus (frees its pool) ==="
docker rm -f ui-venus >/dev/null 2>&1 || true
sleep 5
free -g | head -2

echo "=== 2/4 stopping Qwen ==="
docker rm -f qwen-abliterated >/dev/null 2>&1 || true
sleep 8
free -g | head -2

echo "=== 3/4 starting Qwen at ${QWEN_MEM} with ${QWEN_SEQS} concurrent seqs ==="
# The launcher hardcodes --max-num-seqs 1, which is what limits the agent
# today; Qwen's memory was never the binding constraint, so raise concurrency
# and take the memory back out of its (huge, unused) KV cache instead.
if grep -q -- '--max-num-seqs 1' "$GALAXY/qwen_run.sh"; then
  sed -i 's|--max-num-seqs 1|--max-num-seqs "${QWEN_SEQS:-8}"|' "$GALAXY/qwen_run.sh"
  echo "patched qwen_run.sh: max-num-seqs is now parameterised"
fi
grep -n 'max-num-seqs\|gpu-memory-utilization' "$GALAXY/qwen_run.sh" || true
( cd "$GALAXY" && QWEN_GPU_MEM="$QWEN_MEM" QWEN_SEQS="$QWEN_SEQS" \
    QWEN_MAX_LEN="$QWEN_MAXLEN" bash qwen_run.sh )
wait_http http://127.0.0.1:8000/v1/models "qwen" 240 \
  || { docker logs --tail 25 qwen-abliterated; exit 1; }
curl -s http://127.0.0.1:8000/v1/models | head -c 200; echo

echo "=== 4/4 starting Venus at ${VENUS_MEM} ==="
( cd "$GALAXY" && VENUS_GPU_MEM="$VENUS_MEM" VENUS_SEQS=8 \
    VENUS_MAX_LEN=16384 bash venus_run.sh )
wait_http http://127.0.0.1:8002/v1/models "venus" 240 \
  || { docker logs --tail 25 ui-venus; exit 1; }

echo
echo "=== OmniParser (now that memory is available) ==="
systemctl --user restart omniparser.service
wait_http http://127.0.0.1:7861/api/health "omniparser" 90 \
  || { tail -25 "$HOME/OmniParser/logs/omniparser.log" || true; }
curl -s http://127.0.0.1:7861/api/health; echo

echo
echo "=== final state ==="
free -g | head -2
docker ps --format '{{.Names}}\t{{.Status}}'
