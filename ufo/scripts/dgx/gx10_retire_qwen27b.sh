#!/usr/bin/env bash
# gx10_retire_qwen27b.sh - turn OFF the llama.cpp Qwen3.8-27B (served as `qwen38-27b-turbo`) so the
# vLLM Qwen3.6-35B-A3B is the one Qwen serving :8000.
#
# Why this one: it is dense (every token reads all ~27 GB of Q8 weights: ~10 tok/s on the GB10's
# ~273 GB/s), holds ~30 GB + KV, and llama.cpp slots split one context. The 35B-A3B activates ~3B
# parameters per token, uses NVFP4 + speculative decoding and batches requests continuously.
# The vLLM container also answers to the old name (QWEN_ALIASES), so clients do not change.
#
#   gx10_retire_qwen27b.sh [--dry-run]
# Idempotent. Never touches the vLLM `qwen-abliterated` container. Stops matching containers and
# sets --restart=no so Docker does not bring them back, then removes the profile from every
# SparkDeck stack file (backed up once as <file>.bak-retire) so `mm stack on` does not restart it.
set -u
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1
STACK_DIR="${GX10_STACK_DIR:-/srv/models/stacks}"
PROFILE="${GX10_QWEN27B_PROFILE:-qwen38-27b-turbo-q8}"
KEEP="qwen-abliterated"          # the vLLM Qwen: never matched, never stopped
say() { echo "retire: $*"; }
act() { if [ "$DRY" = 1 ]; then say "would: $*"; else "$@"; fi; }

# 1. containers: by name or image, llama.cpp 27B only
found=0
for c in $(docker ps -a --format '{{.Names}}' 2>/dev/null); do
  [ "$c" = "$KEEP" ] && continue
  img=$(docker inspect -f '{{.Config.Image}}' "$c" 2>/dev/null || true)
  if printf '%s %s' "$c" "$img" | grep -Eqi 'qwen3?8?-?27b|27b-turbo'; then
    found=1
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$c"; then say "stopping $c ($img)"; act docker stop "$c"; else say "$c already stopped"; fi
    act docker update --restart=no "$c"
  fi
done
[ "$found" = 0 ] && say "no llama.cpp qwen27b container found"

# 2. stack files: drop the profile so SparkDeck does not restart it
for f in "$STACK_DIR"/*.env; do
  [ -f "$f" ] || continue
  grep -Eq "^STACK_PROFILES=.*(^|[= \"'])$PROFILE([ \"']|$)" "$f" || continue
  say "removing $PROFILE from $f"
  if [ "$DRY" = 1 ]; then continue; fi
  [ -f "$f.bak-retire" ] || cp -p "$f" "$f.bak-retire"
  awk -v prof="$PROFILE" '
    /^STACK_PROFILES=/ {
      split($0, kv, "="); val=substr($0, length(kv[1])+2); q=""; 
      if (val ~ /^"/) { q="\""; gsub(/"/, "", val) } else if (val ~ /^'"'"'/) { q="'"'"'"; gsub(/'"'"'/, "", val) }
      n=split(val, t, " "); out="";
      for (i=1;i<=n;i++) if (t[i]!=prof && t[i]!="") out = out (out==""?"":" ") t[i];
      print kv[1] "=" q out q; next }
    { print }' "$f.bak-retire" > "$f.tmp" && mv "$f.tmp" "$f"
done

# 3. verify: nothing 27b running, and (if vLLM is up) :8000 is the vLLM Qwen
left=$(docker ps --format '{{.Names}} {{.Image}}' 2>/dev/null | grep -Ei 'qwen3?8?-?27b|27b-turbo' | grep -vw "$KEEP" || true)
if [ -n "$left" ] && [ "$DRY" = 0 ]; then say "STILL RUNNING: $left"; exit 1; fi
say "done ($([ "$DRY" = 1 ] && echo dry-run || echo applied))"
