#!/usr/bin/env bash
# gx10_model_swap.sh - on-demand slot for the big optional models (llama.cpp, Q8_0 GGUF).
#
#   gx10_model_swap.sh 42b      stop the 27B (and tongyi), serve the Qwen3-42B-A3B TOTAL-RECALL coder on :8006
#   gx10_model_swap.sh tongyi   stop the 27B (and 42b),    serve Tongyi-DeepResearch-30B-A3B on :8007
#   gx10_model_swap.sh 27b      stop 42b/tongyi, start the always-on Qwen3.8 27B again (:8004)
#   gx10_model_swap.sh status   what is up, and free memory
#
# Why a swap and not "run everything": the box has 121 GB of unified memory. The 35B brain
# (~30 GB) and the 27B (~42 GB) already leave ~32 GB free; the 42B needs ~57 GB and Tongyi
# ~41 GB. So exactly one of {27B, 42B, Tongyi} runs at a time. The 35B and qwen3-0.6b are
# never touched here.
#
# Safety: the memory check runs BEFORE anything is stopped, using the gx10_budget.env floor and
# target (gx10_guard.sh), counting the memory the stopped containers will give back. A refused
# swap leaves the running model alone. Tailnet exposure is ufo-tunnel.service (:18006/:18007).
set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$here/gx10_guard.sh"

IMG=ghcr.io/ggml-org/llama.cpp:server-cuda
GGUF=/srv/models/gguf
ALWAYS_ON=qwen38-27b-turbo
ONDEMAND="qwen3-42b-coder tongyi-30b"

# name port gguf need_gb ctx sampler...
spec() {
  case "$1" in
    42b) echo "qwen3-42b-coder 8006 Qwen3-42B-A3B-2507-Thinking-Abliterated-uncensored-TOTAL-RECALL-v2-Medium-MASTER-CODER.Q8_0.gguf 57 131072 --temp 0.5 --top-p 0.95 --top-k 20 --min-p 0.05 --repeat-penalty 1.0" ;;
    tongyi) echo "tongyi-30b 8007 Alibaba-NLP_Tongyi-DeepResearch-30B-A3B-Q8_0.gguf 41 131072 --temp 0.6 --top-p 0.95 --top-k 20 --min-p 0.0 --repeat-penalty 1.0" ;;
    *) return 1 ;;
  esac
}

# GPU memory (GB, rounded up) held by a running container, 0 if not running.
held_gb() {
  local cid mib=0 pid m
  cid=$(docker ps -q --no-trunc -f "name=^$1\$" 2>/dev/null)
  [ -z "$cid" ] && { echo 0; return; }
  while IFS=, read -r pid m; do
    grep -q "$cid" "/proc/${pid// /}/cgroup" 2>/dev/null && mib=$((mib + ${m//[^0-9]/}))
  done < <(nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits 2>/dev/null)
  echo $(( (mib + 1023) / 1024 ))
}

running() { docker ps --format '{{.Names}}' | grep -qx "$1"; }

wait_ready() {  # port name
  local i
  for i in $(seq 1 120); do
    running "$2" || { echo "swap: $2 exited during load:" >&2; docker logs --tail 15 "$2" >&2; return 1; }
    # /health, not /v1/models: llama-server answers /v1/models while still loading weights
    curl -sf --max-time 3 "http://127.0.0.1:$1/health" >/dev/null && { echo "swap: $2 ready on :$1 after $((i * 5))s"; return 0; }
    sleep 5
  done
  echo "swap: $2 not ready after 600s" >&2; return 1
}

status() {
  local c
  for c in $ALWAYS_ON $ONDEMAND; do
    if running "$c"; then echo "  up    $c ($(held_gb "$c") GB)"; else echo "  down  $c"; fi
  done
  echo "  free: $(avail_gb) GB ($(pct "$(avail_gb)")%)"
}

up() {
  local s name port file need ctx sampler giveback c proj projpct
  s=$(spec "$1") || { echo "usage: $0 42b|tongyi|27b|status" >&2; exit 2; }
  read -r name port file need ctx sampler <<<"$s"
  [ -f "$GGUF/$file" ] || { echo "swap: $GGUF/$file not downloaded yet" >&2; exit 1; }
  exec 9>"${GX10_LOCK:-/tmp/ufo-gx10-models.lock}"
  flock -w 900 9 || { echo "swap: another model launch holds the lock" >&2; exit 3; }
  running "$name" && { echo "swap: $name already up"; status; return 0; }

  giveback=0
  for c in $ALWAYS_ON $ONDEMAND; do [ "$c" != "$name" ] && giveback=$((giveback + $(held_gb "$c"))); done
  proj=$(( $(avail_gb) + giveback - need )); projpct=$(pct "$proj")
  if _gt "$FREE_FLOOR_PCT" "$projpct"; then
    echo "swap: REFUSED $name - would leave ${proj} GB (${projpct}%) free, under the ${FREE_FLOOR_PCT}% floor. Nothing was stopped." >&2
    exit 3
  fi
  _gt "$FREE_TARGET_PCT" "$projpct" && echo "swap: WARNING $name leaves ${proj} GB (${projpct}%), under the ${FREE_TARGET_PCT}% target" >&2

  running "$ALWAYS_ON" && { echo "swap: stopping $ALWAYS_ON"; docker stop "$ALWAYS_ON" >/dev/null; }
  for c in $ONDEMAND; do [ "$c" != "$name" ] && docker rm -f "$c" >/dev/null 2>&1; done
  docker rm -f "$name" >/dev/null 2>&1
  # shellcheck disable=SC2086  # $sampler is a flag list
  docker run -d --name "$name" --network host --ipc host --gpus all --restart unless-stopped \
    -v "$GGUF/$file:/model/model.gguf:ro" "$IMG" \
    --model /model/model.gguf --alias "$name" --host 127.0.0.1 --port "$port" \
    --ctx-size "$ctx" --parallel 2 --kv-unified --n-gpu-layers 99 --threads 8 \
    --batch-size 2048 --ubatch-size 512 --cache-type-k q8_0 --cache-type-v q8_0 --flash-attn on \
    --cont-batching --jinja --reasoning-format deepseek --metrics --no-webui --cache-reuse 256 \
    $sampler >/dev/null
  if ! wait_ready "$port" "$name"; then
    echo "swap: $name failed; bringing $ALWAYS_ON back" >&2
    docker rm -f "$name" >/dev/null 2>&1; docker start "$ALWAYS_ON" >/dev/null
    exit 1
  fi
  status
}

# Running containers other than $1 whose command line serves --port $2. While the 27B is
# swapped out, another controller has been seen filling :8004 (2026-09-27: SparkDeck's
# qwen35-9b-defiant-q6 profile, the model the 27B replaced), and the 27B then crash-loops on
# "couldn't bind HTTP server socket".
port_squatters() {
  local c
  for c in $(docker ps --format '{{.Names}}'); do
    [ "$c" = "$1" ] && continue
    docker inspect -f '{{join .Args " "}}' "$c" 2>/dev/null | grep -qE -- "--port[ =]$2( |\$)" && echo "$c"
  done
  return 0
}

back() {
  exec 9>"${GX10_LOCK:-/tmp/ufo-gx10-models.lock}"
  flock -w 900 9 || { echo "swap: another model launch holds the lock" >&2; exit 3; }
  local c
  for c in $ONDEMAND; do running "$c" && { echo "swap: stopping $c"; docker rm -f "$c" >/dev/null; }; done
  for c in $(port_squatters "$ALWAYS_ON" 8004); do
    echo "swap: $c is holding :8004 (started by another controller while the 27B was out); stopping it"
    docker stop "$c" >/dev/null
  done
  running "$ALWAYS_ON" || docker start "$ALWAYS_ON" >/dev/null
  wait_ready 8004 "$ALWAYS_ON" && status
}

case "${1:-status}" in
  status) status ;;
  27b) back ;;
  *) up "$1" ;;
esac
