#!/usr/bin/env bash
# Ensure containers on the gx10 can reach the box's own model tunnel through ufw.
#
#   sudo bash fw_model_tunnel.sh --dry-run    show what would change
#   sudo bash fw_model_tunnel.sh              apply (idempotent; safe to re-run)
#   sudo bash fw_model_tunnel.sh --status     what is in effect, incl. LAN exposure
#                                             (sudo is needed to READ the rules, not
#                                             just to change them)
#
# The failure this addresses: ufw runs with INPUT DROP and had no rule for the
# docker bridge, so from INSIDE a container every 0.0.0.0-bound host port was
# firewalled off - only :22 answered. That silently broke anything a container
# runs against the box's models, because ufo-tunnel.service deliberately exposes
# vLLM on 0.0.0.0:18000 (vLLM itself binds 127.0.0.1 and is unreachable any
# other way), and ufo-tg-runner calls it via VLLM_URL=http://host.docker.internal:
# 18000/v1. Symptom was a timeout, not a refusal, which reads like a slow model
# rather than a firewall - so it was misdiagnosed as a config problem first.
#
# Why the source is 172.16.0.0/12 and not one subnet: docker hands out a
# DIFFERENT bridge per compose project (bridge=172.17, the runner is on
# 172.22.0.0/16, others on 172.18-172.21). Hardcoding the default bridge is
# exactly the bug this replaces - a rule that works in testing and then stops
# matching the moment a network is recreated with a new subnet. RFC1918
# 172.16/12 is docker's private range, so it covers every bridge without
# opening the ports to the LAN.
#
# Ports are limited to the three ufo-tunnel.service forwards (8000/8002/7861
# on loopback) and nothing else. This does NOT touch the existing LAN rules.
set -euo pipefail
MODE="apply"
case "${1:-}" in
  --dry-run) MODE="dry" ;;
  --status)  MODE="status" ;;
  "") ;;
  *) echo "usage: $0 [--dry-run|--status]"; exit 64 ;;
esac

SRC="172.16.0.0/12"
PORTS=(18000 18002 18061)
say() { echo "$*"; }

# `ufw status` refuses to print its rule set to a non-root caller (it errors out
# rather than showing a truncated view), so reading needs the same privilege as
# writing. Without this, every check silently returns "not found" and --status
# reports MISSING for rules that are in fact present - a false negative that
# would send someone "fixing" a firewall that was already correct.
ufw_status() {
  if [ "$(id -u)" = 0 ]; then ufw status 2>/dev/null
  elif sudo -n ufw status >/dev/null 2>&1; then sudo -n ufw status 2>/dev/null
  elif ufw status >/dev/null 2>&1; then ufw status 2>/dev/null
  else echo "ERROR: cannot read ufw rules - run with sudo" >&2; return 1
  fi
}

have() { # have <port> - is there a rule already opening this port from $SRC?
  ufw_status | awk -v p="$1" -v s="$SRC" \
    '$0 ~ p"/tcp" && $0 ~ s && $0 ~ /ALLOW/ {found=1} END {exit !found}'
}

if [ "$MODE" = status ]; then
  say "=== container -> box model tunnel (the rule this script owns) ==="
  for p in "${PORTS[@]}"; do
    if have "$p"; then printf '  :%-6s OK   %s\n' "$p" "$(ufw_status | grep -E "(^| )$p/tcp" | grep "$SRC" | head -1 | xargs)"
    else printf '  :%-6s MISSING - containers cannot reach it\n' "$p"; fi
  done

  say ""
  say "=== LAN exposure (informational; these rules are NOT managed here) ==="
  # Answering "what is actually exposed" is the whole reason this report exists.
  # A port bound to 0.0.0.0 is not the same as a port the LAN can reach: ufw's
  # INPUT DROP keeps 80 (Caddy) and 11434 (Ollama) closed even though both bind
  # 0.0.0.0, and testing from the box to its own LAN IP cannot tell you the
  # difference because that path never traverses INPUT. Only ufw's own table can.
  # Strip trailing "#" comments before parsing: ufw quotes comments as free text,
  # so a rule commented "...(any docker net)" would otherwise be reported as
  # coming from the source "net)".
  ufw_status | grep ALLOW \
    | grep -Ev 'Anywhere|OpenSSH' \
    | sed 's/[[:space:]]*#.*//' \
    | awk 'NF>=3 {printf "  %-16s <- %s\n", $1, $NF}'
  say "  (anything not listed above is blocked from the LAN by INPUT DROP)"

  say ""
  say "=== docker bridges in use (why 172.16.0.0/12) ==="
  docker network ls --format '{{.Name}}' 2>/dev/null | while read -r n; do
    cid=$(docker network inspect -f '{{.Id}}' "$n" 2>/dev/null || true)
    [ -z "$cid" ] && continue
    sub=$(docker network inspect -f '{{range .IPAM.Config}}{{.Subnet}} {{end}}' "$cid" 2>/dev/null || true)
    [ -n "$sub" ] && printf '  %-32s %s\n' "$n" "$sub"
  done
  exit 0
fi

[ "$MODE" = dry ] || [ "$(id -u)" = 0 ] || { echo "run as root (sudo), or use --dry-run"; exit 1; }

for p in "${PORTS[@]}"; do
  if have "$p"; then
    say "= unchanged  :$p from $SRC"
    continue
  fi
  say "+ allow      $SRC -> host:$p/tcp"
  [ "$MODE" = dry ] && continue
  # comment tags the rule so it is identifiable in `ufw status numbered` output
  ufw allow from "$SRC" to any port "$p" proto tcp \
    comment 'ufo: container -> box model tunnel' >/dev/null
done

say "done ($MODE)"
[ "$MODE" = dry ] && { say "(dry run: nothing was changed)"; exit 0; }
say ""
say "verify with: sudo bash $0 --status"
