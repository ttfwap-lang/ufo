#!/usr/bin/env bash
# DEPRECATED - forwards to the canonical launcher in scripts/dgx/venus_run.sh.
# The copy that lived here bound 0.0.0.0 (reachable from the whole LAN, no auth), ignored the
# memory budget and drifted from the real launcher. One launcher, one budget: scripts/dgx/.
here="$(cd "$(dirname "$0")" && pwd)"
for c in "$here/../scripts/dgx/venus_run.sh" "$here/scripts/dgx/venus_run.sh" "$HOME/ufo-galaxy/venus_run.sh"; do
  [ -f "$c" ] && [ "$(cd "$(dirname "$c")" && pwd)/$(basename "$c")" != "$(cd "$here" && pwd)/venus_run.sh" ] && exec bash "$c" "$@"
done
echo "canonical venus_run.sh not found (expected scripts/dgx/venus_run.sh)" >&2; exit 1
