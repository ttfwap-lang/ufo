#!/usr/bin/env bash
# One-time hardening so the gx10 stays REACHABLE when memory gets tight.
#
#   sudo bash protect_ssh.sh --dry-run    show what would change
#   sudo bash protect_ssh.sh              apply (idempotent; safe to re-run)
#   bash protect_ssh.sh --status          what is currently in effect
#
# The failure this addresses: unified memory fully committed -> the kernel reclaims/swaps
# aggressively -> sshd, tailscaled and dockerd stall. The box still answers ping and accepts
# TCP on :22 but never sends an SSH banner, tailscale drops offline, and nothing can fix it
# remotely. Three independent layers:
#   1. OOM shield: the OOM killer never picks sshd/tailscaled/dockerd/containerd.
#   2. Reclaim headroom: keep a free-memory floor and prefer dropping page cache over swapping
#      anonymous memory, so allocations do not fall into slow direct reclaim.
#   3. earlyoom (if installed): kills the biggest *non-protected* process at ~4% free instead of
#      letting the whole box thrash - vLLM restarts itself (--restart unless-stopped), a wedged
#      box does not.
set -euo pipefail
MODE="apply"
case "${1:-}" in --dry-run) MODE="dry" ;; --status) MODE="status" ;; "") ;; *) echo "usage: $0 [--dry-run|--status]"; exit 64 ;; esac

PROTECT_UNITS=(ssh sshd tailscaled docker containerd)
SYSCTL=/etc/sysctl.d/99-ufo-gx10.conf
EARLYOOM=/etc/default/earlyoom

if [ "$MODE" = status ]; then
  for u in "${PROTECT_UNITS[@]}"; do
    systemctl cat "$u.service" >/dev/null 2>&1 || continue
    printf '%-14s OOMScoreAdjust=%s\n' "$u" "$(systemctl show -p OOMScoreAdjust --value "$u.service")"
  done
  echo "vm.swappiness=$(sysctl -n vm.swappiness)  vm.min_free_kbytes=$(sysctl -n vm.min_free_kbytes)"
  command -v earlyoom >/dev/null && echo "earlyoom: $(systemctl is-active earlyoom 2>/dev/null)" || echo "earlyoom: not installed"
  exit 0
fi

[ "$MODE" = dry ] || [ "$(id -u)" = 0 ] || { echo "run as root (sudo), or use --dry-run"; exit 1; }
say() { echo "$*"; }
put() { # put <path> ; content on stdin
  local path="$1" new; new="$(cat)"
  if [ -f "$path" ] && [ "$(cat "$path")" = "$new" ]; then say "= unchanged  $path"; return; fi
  say "+ write      $path"
  [ "$MODE" = dry ] && { echo "$new" | sed 's/^/    | /'; return; }
  mkdir -p "$(dirname "$path")"; printf '%s\n' "$new" > "$path"
}

# 1. OOM shield
changed=0
for u in "${PROTECT_UNITS[@]}"; do
  systemctl cat "$u.service" >/dev/null 2>&1 || continue
  d="/etc/systemd/system/$u.service.d/10-ufo-protect.conf"
  before="$(cat "$d" 2>/dev/null || true)"
  put "$d" <<CONF
[Service]
OOMScoreAdjust=-900
CONF
  [ "$before" = "$(cat "$d" 2>/dev/null || true)" ] || changed=1
done
[ "$MODE" = dry ] || [ "$changed" = 0 ] || { say "+ systemctl daemon-reload"; systemctl daemon-reload; }
# (takes effect for each service at its next restart; do NOT restart sshd/docker remotely here)

# 2. reclaim headroom
put "$SYSCTL" <<'CONF'
# gx10: keep sshd/tailscaled responsive under memory pressure (see protect_ssh.sh)
vm.swappiness = 10
vm.min_free_kbytes = 2097152
CONF
[ "$MODE" = dry ] || sysctl -q -p "$SYSCTL"

# 3. earlyoom
if command -v earlyoom >/dev/null 2>&1; then
  put "$EARLYOOM" <<'CONF'
# SIGTERM at 4% MemAvailable, SIGKILL at 2%. Never kill the things that keep the box reachable.
EARLYOOM_ARGS="-m 4,2 -s 100 -r 60 --avoid '(^|/)(sshd|systemd|tailscaled|dockerd|containerd|containerd-shim.*)$'"
CONF
  [ "$MODE" = dry ] || systemctl enable --now earlyoom >/dev/null 2>&1 || true
else
  say "! earlyoom is not installed: layer 3 skipped (sudo apt-get install -y earlyoom, then re-run)"
fi
say "done ($MODE)"
