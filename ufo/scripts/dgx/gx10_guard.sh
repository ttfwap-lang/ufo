#!/usr/bin/env bash
# gx10_guard.sh - shared launch guard and memory-pressure audit for the gx10's models.
#
#   source it:  . gx10_guard.sh; guard_acquire <container> <gpu_fraction>
#                 - takes the model-launch lock (one launcher at a time), checks the new
#                   pool against the budget and against what is actually free, and exits 3
#                   with a reason if the launch would oversubscribe unified memory.
#                   Call it BEFORE removing the container being replaced: a refused launch
#                   must never kill a working model.
#   run it:     gx10_guard.sh --audit
#                 - read-only report: budget vs reserved pools, MemAvailable, swap, and the
#                   kernel's memory-pressure (PSI). Exit 0 ok / 1 warning / 2 critical.
#
# Bypass (you own the consequences): GX10_FORCE=1.
set -u

_guard_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for _f in "${GX10_BUDGET_FILE:-}" /srv/models/gx10_budget.env "$_guard_dir/gx10_budget.env"; do
  if [ -n "$_f" ] && [ -f "$_f" ]; then
    # per-box overrides live in gx10_budget.local.env next to it; sourced first so they win over the
    # shipped defaults. Write them in the budget's own form, VAR="${VAR:-value}", so a value set in
    # the environment for one call still beats both files.
    _l="${_f%.env}.local.env"; [ -f "$_l" ] && . "$_l"
    . "$_f"; GX10_BUDGET_SRC="$_f"; break
  fi
done
: "${TOTAL_GB:=121}" "${MODEL_POOL_MAX:=0.70}" "${FREE_FLOOR_PCT:=5}" "${FREE_TARGET_PCT:=10}"
GX10_BUDGET_SRC="${GX10_BUDGET_SRC:-built-in defaults}"

_mem_kb()  { awk -v k="$1:" '$1==k{print $2}' "${GX10_PROC:-/proc}"/meminfo; }
avail_gb() { echo $(( $(_mem_kb MemAvailable) / 1048576 )); }
swap_used_mb() { echo $(( ( $(_mem_kb SwapTotal) - $(_mem_kb SwapFree) ) / 1024 )); }
# psi <some|full> -> avg10 (percent of the last 10 s some/all tasks stalled on memory)
psi() { awk -v kind="$1" '$1==kind{for(i=2;i<=NF;i++){split($i,a,"=");if(a[1]=="avg10")print a[2]}}' "${GX10_PROC:-/proc}"/pressure/memory 2>/dev/null || echo 0; }
# pct <gb> -> that many GB as a percent of TOTAL_GB (one decimal)
pct() { awk -v g="$1" -v t="$TOTAL_GB" 'BEGIN{printf "%.1f", g*100/t}'; }
_le() { awk -v a="$1" -v b="$2" 'BEGIN{exit !(a<=b)}'; }
_gt() { awk -v a="$1" -v b="$2" 'BEGIN{exit !(a>b)}'; }

# "name fraction" for every RUNNING container that reserves a vLLM GPU pool.
running_pools() {
  local c f
  for c in $(docker ps --format '{{.Names}}' 2>/dev/null); do
    f=$(docker inspect -f '{{range .Config.Cmd}}{{println .}}{{end}}' "$c" 2>/dev/null \
        | awk '/^--gpu-memory-utilization$/{getline; print; exit} /^--gpu-memory-utilization=/{sub(/.*=/,""); print; exit}')
    [ -n "$f" ] && echo "$c $f"
  done
  return 0   # the loop's last test fails for a container without a pool; under the launchers'
             # `set -eo pipefail` that non-zero status killed them silently before any output
}

guard_acquire() {
  local name="$1" frac="$2" others sum avail own
  exec 9>"${GX10_LOCK:-/tmp/ufo-gx10-models.lock}"
  if ! flock -w "${GX10_LOCK_WAIT:-900}" 9; then
    echo "guard: another model launch held the lock for ${GX10_LOCK_WAIT:-900}s; refusing to pile on" >&2
    exit 3
  fi
  others=$(running_pools | awk -v n="$name" '$1!=n{s+=$2}END{printf "%.2f", s+0}')
  sum=$(awk -v a="$others" -v b="$frac" 'BEGIN{printf "%.2f", a+b}')
  if _gt "$sum" "$MODEL_POOL_MAX"; then
    echo "guard: REFUSED $name at $frac - other pools already hold $others, total $sum > MODEL_POOL_MAX $MODEL_POOL_MAX ($GX10_BUDGET_SRC)" >&2
    [ "${GX10_FORCE:-0}" = 1 ] || exit 3
    echo "guard: GX10_FORCE=1, continuing anyway" >&2
  fi
  # Free memory as the kernel sees it, plus what this container gives back when replaced.
  own=$(running_pools | awk -v n="$name" '$1==n{printf "%d", $2*'"$TOTAL_GB"'}')
  avail=$(( $(avail_gb) + ${own:-0} ))
  # Free memory after this launch, as a percent of the box. The FLOOR is never crossed; the
  # TARGET is encouraged (warning, or a refusal with GX10_STRICT=1).
  local proj projpct
  proj=$(awk -v a="$avail" -v f="$frac" -v t="$TOTAL_GB" 'BEGIN{printf "%.1f", a - f*t}')
  projpct=$(pct "$proj")
  if _gt "$FREE_FLOOR_PCT" "$projpct"; then
    echo "guard: REFUSED $name at $frac - would leave ${proj} GB free (${projpct}%), below the ${FREE_FLOOR_PCT}% floor (only ${avail} GB available now)" >&2
    echo "guard: something outside the vLLM pools (llama.cpp, Ollama, training) holds the memory; see: $0 --audit" >&2
    exit 3        # the floor is not bypassable, not even with GX10_FORCE=1
  fi
  if _gt "$FREE_TARGET_PCT" "$projpct"; then
    echo "guard: WARNING $name at $frac leaves ${proj} GB free (${projpct}%), under the ${FREE_TARGET_PCT}% target" >&2
    if [ "${GX10_STRICT:-0}" = 1 ]; then echo "guard: REFUSED (GX10_STRICT=1)" >&2; exit 3; fi
  fi
  echo "guard: ok $name $frac (pools $others+$frac=$sum <= $MODEL_POOL_MAX; ${proj} GB = ${projpct}% free after)"
}

guard_audit() {
  local pools sum avail some full swap rc=0 line
  pools=$(running_pools)
  sum=$(echo "$pools" | awk 'NF{s+=$2}END{printf "%.2f", s+0}')
  avail=$(avail_gb); swap=$(swap_used_mb); some=$(psi some); full=$(psi full)
  echo "budget file       : $GX10_BUDGET_SRC"
  echo "vLLM pools        : ${sum} of max ${MODEL_POOL_MAX} ($(awk -v s="$sum" -v t="$TOTAL_GB" 'BEGIN{printf "%d", s*t}') GB of ${TOTAL_GB})"
  echo "$pools" | awk 'NF{printf "    %-24s %s\n", $1, $2}'
  local fpct; fpct=$(pct "$avail")
  echo "MemAvailable      : ${avail} GB = ${fpct}% free (floor ${FREE_FLOOR_PCT}%, target ${FREE_TARGET_PCT}%)"
  echo "swap in use       : ${swap} MB"
  echo "memory pressure   : some avg10=${some}%  full avg10=${full}%   (full > 10% = the box is thrashing)"
  if _gt "$sum" "$MODEL_POOL_MAX"; then echo "WARN: pools exceed the budget"; rc=1; fi
  if _gt "$FREE_TARGET_PCT" "$fpct"; then echo "WARN: free memory ${fpct}% is under the ${FREE_TARGET_PCT}% target"; rc=1; fi
  if _gt "$FREE_FLOOR_PCT" "$fpct"; then echo "CRITICAL: free memory ${fpct}% is under the ${FREE_FLOOR_PCT}% floor"; rc=2; fi
  # WARN never lowers a CRITICAL already raised above (the floor check sets rc=2).
  if _gt "$some" 20; then echo "WARN: sustained memory stalls (some avg10 > 20%)"; [ "$rc" -ge 1 ] || rc=1; fi
  # Thrashing is memory PRESSURE (tasks stalled on memory), not swap occupancy: cold pages parked
  # in swap after an earlier episode stay there indefinitely and cost nothing until touched.
  if _gt "$full" 10; then echo "CRITICAL: thrashing (memory stalls full avg10 > 10%)"; rc=2; fi
  if [ "$swap" -gt 4096 ]; then echo "WARN: ${swap} MB in swap (cold pages; a latency risk when touched, not thrashing by itself)"; [ "$rc" -ge 1 ] || rc=1; fi
  [ "$rc" = 0 ] && echo "OK"
  return "$rc"
}

# Run directly (not sourced)
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  case "${1:-}" in
    --audit) guard_audit; exit $? ;;
    *) echo "usage: $0 --audit   (or source this file and call guard_acquire <container> <fraction>)" >&2; exit 64 ;;
  esac
fi
