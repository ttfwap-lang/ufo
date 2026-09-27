#!/usr/bin/env bash
# gx10_model_swap.sh - resident UI-Venus plus ONE on-demand big model.
#
#   gx10_model_swap.sh 27b      serve the Qwen3.8 27B (llama.cpp, :8004, existing container)
#   gx10_model_swap.sh tongyi   serve Tongyi-DeepResearch-30B-A3B (llama.cpp, :8007)
#   gx10_model_swap.sh venus    stop the on-demand model, make sure UI-Venus (:8002) is up
#   gx10_model_swap.sh status   what is up, and free memory
#
# Layout since 2026-09-27 (user requests): the brain on :8000 is the Qwen3-42B-A3B
# TOTAL-RECALL coder (container qwen3-42b-coder, llama.cpp; the 35B qwen-abliterated is
# stopped, kept for rollback). UI-Venus is resident. At most one of {27B, Tongyi} runs on
# demand beside them. The brain and qwen3-0.6b are never touched here.
#
# Memory (121 GB unified): the check runs BEFORE anything is stopped, against the
# gx10_budget.env floor/target (gx10_guard.sh). To make room it stops, in order and only as
# far as needed: the other on-demand model, whatever SparkDeck put on :8004 (its "slice C"
# qwen35-9b-defiant refills :8004 whenever it is free; always stopped for the 27B, which
# needs that port), then UI-Venus. A refused swap stops nothing. A failed load brings Venus back.
set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$here/gx10_guard.sh"

IMG=ghcr.io/ggml-org/llama.cpp:server-cuda
GGUF=/srv/models/gguf
RESIDENT=ui-venus
RESIDENT_PORT=8002
ONDEMAND="qwen38-27b-turbo tongyi-30b"

# name port need_gb [gguf ctx sampler...]  (27b has no gguf: its container already exists)
spec() {
  case "$1" in
    27b) echo "qwen38-27b-turbo 8004 43" ;;
    tongyi) echo "tongyi-30b 8007 41 Alibaba-NLP_Tongyi-DeepResearch-30B-A3B-Q8_0.gguf 131072 --temp 0.6 --top-p 0.95 --top-k 20 --min-p 0.0 --repeat-penalty 1.0" ;;
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

# Running containers other than $1 whose command line serves --port $2.
port_squatters() {
  local c
  for c in $(docker ps --format '{{.Names}}'); do
    [ "$c" = "$1" ] && continue
    docker inspect -f '{{join .Args " "}}' "$c" 2>/dev/null | grep -qE -- "--port[ =]$2( |\$)" && echo "$c"
  done
  return 0
}

wait_ready() {  # port name
  local i
  for i in $(seq 1 240); do
    running "$2" || { echo "swap: $2 exited during load:" >&2; docker logs --tail 15 "$2" >&2; return 1; }
    # /health, not /v1/models: llama-server answers /v1/models while still loading weights
    curl -sf --max-time 3 "http://127.0.0.1:$1/health" >/dev/null && { echo "swap: $2 ready on :$1 after $((i * 5))s"; return 0; }
    sleep 5
  done
  echo "swap: $2 not ready after 1200s" >&2; return 1
}

lock() {
  exec 9>"${GX10_LOCK:-/tmp/ufo-gx10-models.lock}"
  flock -w 900 9 || { echo "swap: another model launch holds the lock" >&2; exit 3; }
}

status() {
  local c
  for c in qwen3-42b-coder $RESIDENT $ONDEMAND $(port_squatters qwen38-27b-turbo 8004); do
    if running "$c"; then echo "  up    $c ($(held_gb "$c") GB)"; else echo "  down  $c"; fi
  done
  echo "  free: $(avail_gb) GB ($(pct "$(avail_gb)")%)"
}

resident_up() {
  running "$RESIDENT" && return 0
  echo "swap: starting $RESIDENT"
  docker start "$RESIDENT" >/dev/null && wait_ready "$RESIDENT_PORT" "$RESIDENT"
}

up() {
  local s name port need file ctx sampler c free stop="" squat
  s=$(spec "$1") || { echo "usage: $0 27b|tongyi|venus|status (the 42B is the brain on :8000)" >&2; exit 2; }
  read -r name port need file ctx sampler <<<"$s"
  [ -n "${file:-}" ] && [ ! -f "$GGUF/$file" ] && { echo "swap: $GGUF/$file not downloaded yet" >&2; exit 1; }
  lock
  running "$name" && { echo "swap: $name already up"; status; return 0; }

  # Plan what to stop, cheapest first, until the launch leaves at least the TARGET free.
  free=$(avail_gb)
  for c in $ONDEMAND; do
    [ "$c" != "$name" ] && running "$c" && { stop="$stop $c"; free=$((free + $(held_gb "$c"))); }
  done
  squat=$(port_squatters qwen38-27b-turbo 8004)
  for c in $squat; do
    if [ "$name" = qwen38-27b-turbo ] || _gt "$FREE_TARGET_PCT" "$(pct $((free - need)))"; then
      stop="$stop $c"; free=$((free + $(held_gb "$c")))
    fi
  done
  if running "$RESIDENT" && _gt "$FREE_TARGET_PCT" "$(pct $((free - need)))"; then
    stop="$stop $RESIDENT"; free=$((free + $(held_gb "$RESIDENT")))
  fi
  if _gt "$FREE_FLOOR_PCT" "$(pct $((free - need)))"; then
    echo "swap: REFUSED $name - even after stopping [${stop# }] only $((free - need)) GB would be free, under the ${FREE_FLOOR_PCT}% floor. Nothing was stopped." >&2
    exit 3
  fi
  _gt "$FREE_TARGET_PCT" "$(pct $((free - need)))" && echo "swap: WARNING $name leaves $((free - need)) GB, under the ${FREE_TARGET_PCT}% target" >&2

  for c in $stop; do echo "swap: stopping $c"; docker stop "$c" >/dev/null; done
  if [ -z "${file:-}" ]; then
    docker start "$name" >/dev/null
  else
    docker rm -f "$name" >/dev/null 2>&1
    # shellcheck disable=SC2086  # $sampler is a flag list
    docker run -d --name "$name" --network host --ipc host --gpus all --restart unless-stopped \
      -v "$GGUF/$file:/model/model.gguf:ro" "$IMG" \
      --model /model/model.gguf --alias "$name" --host 127.0.0.1 --port "$port" \
      --ctx-size "$ctx" --parallel 2 --kv-unified --n-gpu-layers 99 --threads 8 \
      --batch-size 2048 --ubatch-size 512 --cache-type-k q8_0 --cache-type-v q8_0 --flash-attn on \
      --cont-batching --jinja --reasoning-format deepseek --metrics --no-webui --cache-reuse 256 \
      $sampler >/dev/null
  fi
  if ! wait_ready "$port" "$name"; then
    echo "swap: $name failed; restoring $RESIDENT" >&2
    docker stop "$name" >/dev/null 2>&1
    resident_up
    exit 1
  fi
  status
}

venus() {
  lock
  local c
  for c in $ONDEMAND; do running "$c" && { echo "swap: stopping $c"; docker stop "$c" >/dev/null; }; done
  resident_up && status
}

case "${1:-status}" in
  status) status ;;
  venus) venus ;;
  *) up "$1" ;;
esac
