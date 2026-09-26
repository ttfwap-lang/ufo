#!/usr/bin/env bash
# gx10_apply.sh - bring the gx10 to the intended state, in order, restarting only what differs.
# "Differs" = concurrency (seqs), quantization, the legacy name alias. NOT the memory pool size: a
# healthy model running a pool within policy (SparkDeck runs Venus at 0.24, the budget says 0.20) is
# not restarted to save a few GB - that interrupts users for nothing. The free-memory policy governs.
#   1. retire the llama.cpp Qwen 27B (gx10_retire_qwen27b.sh)          -> one Qwen on :8000
#   2. install scripts/units + budget, enable gx10-memguard.timer      -> 5% floor / 10% target
#   3. vLLM Qwen: recreate ONLY if its running flags differ from the budget (seqs, memory, aliases)
#   4. Venus: same
#   5. protect_ssh.sh if passwordless sudo exists (otherwise prints the one command to run)
# Safe to re-run. Progress goes to stdout; the last line is APPLY_DONE or APPLY_FAILED <step>.
#   gx10_apply.sh [--dry-run]
set -u
here="$(cd "$(dirname "$0")" && pwd)"
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1
HOME_DIR="$HOME/ufo-galaxy"
step() { echo; echo "=== $(date -u +%T) $* ==="; }
fail() { echo "APPLY_FAILED $1"; exit 1; }

# does running container $1 already have `--flag value` (or --flag=value) in its command?
cmd_has() {
  docker inspect -f '{{range .Config.Cmd}}{{println .}}{{end}}' "$1" 2>/dev/null \
    | awk -v f="$2" -v v="$3" 'prev==f && $0==v {ok=1} $0==f"="v {ok=1} {prev=$0} END{exit !ok}'
}
# the vLLM Qwen must also answer to the legacy name clients use (unless aliases are disabled)
alias_ok() {
  local want="${QWEN_ALIASES-qwen38-27b-turbo}"; [ -z "$want" ] && return 0
  docker inspect -f '{{range .Config.Cmd}}{{println .}}{{end}}' qwen-abliterated 2>/dev/null | grep -qx "$want"
}
wait_http() { local i; for i in $(seq 1 "$3"); do curl -sf --max-time 3 "$1" >/dev/null 2>&1 && { echo "$2 ready after $((i*5))s"; return 0; }; sleep 5; done; echo "$2 NOT ready"; return 1; }

if [ "$DRY" = 1 ]; then echo "(dry run: showing decisions only)"; fi
. "$here/gx10_guard.sh"   # loads gx10_budget.env (QWEN_*, VENUS_*)

step "1/5 retire llama.cpp Qwen 27B"
bash "$here/gx10_retire_qwen27b.sh" $([ "$DRY" = 1 ] && echo --dry-run) || fail retire

step "2/5 install scripts, units, budget, memguard timer"
if [ "$DRY" = 1 ]; then echo "would run install.sh"; else bash "$here/install.sh" || fail install; fi
GUARD="${HOME_DIR}/gx10_guard.sh"; [ -f "$GUARD" ] || GUARD="$here/gx10_guard.sh"
bash "$GUARD" --audit || true

step "3/5 vLLM Qwen (seqs=$QWEN_SEQS, mem=$QWEN_GPU_MEM)"
if docker ps --format '{{.Names}}' | grep -qx qwen-abliterated \
   && cmd_has qwen-abliterated --max-num-seqs "$QWEN_SEQS" \
   && alias_ok; then
  echo "already running with the intended settings - not restarting"
elif [ "$DRY" = 1 ]; then echo "would recreate qwen-abliterated"
else
  bash "${HOME_DIR}/qwen_run.sh" || fail qwen
  wait_http http://127.0.0.1:8000/v1/models qwen 240 || { docker logs --tail 30 qwen-abliterated; fail qwen-ready; }
fi

step "4/5 Venus (seqs=$VENUS_SEQS, mem=$VENUS_GPU_MEM${VENUS_QUANT:+, quant=$VENUS_QUANT})"
if docker ps --format '{{.Names}}' | grep -qx ui-venus \
   && cmd_has ui-venus --max-num-seqs "$VENUS_SEQS" \
   && { [ -z "${VENUS_QUANT:-}" ] || cmd_has ui-venus --quantization "$VENUS_QUANT"; }; then
  echo "already running with the intended settings - not restarting"
elif [ "$DRY" = 1 ]; then echo "would recreate ui-venus"
else
  bash "${HOME_DIR}/venus_run.sh" || fail venus
  wait_http http://127.0.0.1:8002/v1/models venus 240 || { docker logs --tail 30 ui-venus; fail venus-ready; }
fi

step "5/5 ssh/OOM protection"
if [ "$DRY" = 1 ]; then echo "would run protect_ssh.sh"
elif sudo -n true 2>/dev/null; then sudo -n bash "$here/protect_ssh.sh" || echo "protect_ssh.sh reported a problem (non-fatal)"
else echo "no passwordless sudo: run once by hand ->  sudo bash $here/protect_ssh.sh"; fi

step "result"; bash "$GUARD" --audit || true
echo APPLY_DONE
