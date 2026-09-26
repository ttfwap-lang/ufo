#!/usr/bin/env bash
# gx10_memguard.sh - one enforcement pass: keep free memory >= FREE_FLOOR_PCT (5%) and push it
# back toward FREE_TARGET_PCT (10%). Run every 30 s by gx10-memguard.timer, so it applies no
# matter which controller (SparkDeck, the watchdog, our launchers, a training run) used the
# memory. Numbers come from gx10_budget.env (see gx10_guard.sh).
#
#   tier ok     free >= TARGET          nothing to do
#   tier low    FLOOR <= free < TARGET  release what is cheap and reclaimable, disrupt nobody:
#                                         - unload idle Ollama models (keep_alive 0)
#                                         - drop CLEAN page cache (loading weights fills it)
#                                         - stop the CPU OmniParser if it is running
#   tier floor  free < FLOOR            all of the above, then stop ONE container from
#                                       SHED_CONTAINERS per pass (2 min apart); the default
#                                       list is only the small auxiliary Qwens, never the primary
#                                       Qwen or Venus. earlyoom
#                                       (protect_ssh.sh) is the last line at the same floor.
#
#   gx10_memguard.sh [--dry-run]     exit 0 ok / 1 low / 2 floor. Every action is logged with why.
set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$here/gx10_guard.sh"
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1
LOG="${GX10_MEMGUARD_LOG:-$HOME/ufo-galaxy/logs/memguard.log}"
STATE="${GX10_MEMGUARD_STATE:-${XDG_RUNTIME_DIR:-/tmp}/gx10-memguard.shed}"
mkdir -p "$(dirname "$LOG")" 2>/dev/null || true

say() { local m; m="$(date -u +%FT%TZ) $*"; echo "$m"; echo "$m" >>"$LOG" 2>/dev/null || true; }
do_() { if [ "$DRY" = 1 ]; then say "would: $*"; else "$@"; fi; }

avail=$(avail_gb); fpct=$(pct "$avail")
tier=ok; rc=0
if _gt "$FREE_TARGET_PCT" "$fpct"; then tier=low; rc=1; fi
if _gt "$FREE_FLOOR_PCT" "$fpct"; then tier=floor; rc=2; fi
[ "$tier" = ok ] && { [ "$DRY" = 1 ] && echo "ok: ${fpct}% free (${avail} GB)"; exit 0; }
say "$tier: ${fpct}% free (${avail} GB); floor ${FREE_FLOOR_PCT}% target ${FREE_TARGET_PCT}%"

# 1. Ollama: unload every loaded model (a stray request pins several GB for minutes).
ps_json=$(curl -s --max-time 3 http://127.0.0.1:11434/api/ps 2>/dev/null || true)
for m in $(printf '%s' "$ps_json" | grep -o '"name":"[^"]*"' | cut -d'"' -f4); do
  say "release: unload Ollama model $m"
  do_ curl -s --max-time 5 -X POST http://127.0.0.1:11434/api/generate -d "{\"model\":\"$m\",\"keep_alive\":0}" >/dev/null
done

# 2. Clean page cache. Safe (only clean pages), needs root: directly or via passwordless sudo.
dc="${GX10_PROC:-/proc}/sys/vm/drop_caches"
if [ -w "$dc" ] || sudo -n true 2>/dev/null; then
  say "release: drop clean page cache"
  if [ "$DRY" = 1 ]; then :; elif [ -w "$dc" ]; then sync; echo 1 >"$dc"; else sudo -n sh -c "sync; echo 1 >$dc"; fi
fi

# 3. OmniParser on the gx10 is CPU-bound and redundant (it runs on the Windows GPU now).
if systemctl --user is-active --quiet omniparser 2>/dev/null; then
  say "release: stop CPU OmniParser"
  do_ systemctl --user stop omniparser
fi

# 4. Floor only: shed one named container per pass, at most every 2 minutes.
if [ "$tier" = floor ] && [ -n "${SHED_CONTAINERS:-}" ]; then
  now=$(date +%s); last=$(cat "$STATE" 2>/dev/null || echo 0)
  if [ $((now - last)) -ge 120 ]; then
    for c in $SHED_CONTAINERS; do
      if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$c"; then
        say "SHED: stopping container $c (free ${fpct}% is under the ${FREE_FLOOR_PCT}% floor)"
        do_ docker stop "$c"; [ "$DRY" = 1 ] || echo "$now" >"$STATE"
        break
      fi
    done
  fi
fi
exit "$rc"
