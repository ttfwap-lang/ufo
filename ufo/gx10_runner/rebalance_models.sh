#!/usr/bin/env bash
# Restart both model pools from the ONE budget file (scripts/dgx/gx10_budget.env).
#
# This script used to carry its own numbers (Qwen 0.56 + Venus 0.26 = 99 GB of a 121 GB box,
# "~22 GB left for everything else") and patched qwen_run.sh in place with sed. Those numbers
# disagreed with every other launcher, left no headroom for the OS and page cache, and are the
# combination that starves sshd. Sizing now lives only in gx10_budget.env; the launchers refuse
# to exceed it (gx10_guard.sh).
#
# OmniParser is intentionally NOT restarted here: it runs locally on the Windows GPU
# (docs/omniparser_placement.md); on the gx10 it was CPU-bound (34 s/parse) and the heaviest
# thing on the box.
set -euo pipefail
GALAXY="${GALAXY:-$HOME/ufo-galaxy}"

wait_http() {   # wait_http <url> <label> <tries>
  local url="$1" label="$2" tries="$3" i
  for i in $(seq 1 "$tries"); do
    curl -sf --max-time 3 "$url" >/dev/null 2>&1 && { echo "$label ready after $((i*5))s"; return 0; }
    sleep 5
  done
  echo "$label TIMED OUT"; return 1
}

echo "=== audit before ==="; bash "$GALAXY/gx10_guard.sh" --audit || true
echo "=== 1/2 Qwen (guard runs before the old container is removed) ==="
bash "$GALAXY/qwen_run.sh"
wait_http http://127.0.0.1:8000/v1/models qwen 240 || { docker logs --tail 25 qwen-abliterated; exit 1; }
echo "=== 2/2 Venus ==="
bash "$GALAXY/venus_run.sh"
wait_http http://127.0.0.1:8002/v1/models venus 240 || { docker logs --tail 25 ui-venus; exit 1; }
echo "=== audit after ==="; bash "$GALAXY/gx10_guard.sh" --audit || true
