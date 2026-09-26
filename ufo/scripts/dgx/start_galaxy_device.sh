#!/usr/bin/env bash
# (Re)starts the gx10 UFO Galaxy device services under systemd --user
# (Linux MCP :8010, server :5001, device client dgx_gx10; all 127.0.0.1).
# The units restart on failure and start at boot (linger is enabled).
set -euo pipefail
cd "$(dirname "$0")"
umask 077
[ -f .secrets ] || { printf "UFO_MCP_API_KEY=%s\nUFO_WS_TOKEN=%s\n" "$(openssl rand -hex 24)" "$(openssl rand -hex 24)" > .secrets; }
mkdir -p logs
systemctl --user restart ufo-linux-mcp.service ufo-galaxy-server.service ufo-galaxy-client.service
sleep 8
for u in ufo-linux-mcp ufo-galaxy-server ufo-galaxy-client; do
  echo "$u: $(systemctl --user is-active $u.service) (pid $(systemctl --user show -p MainPID --value $u.service))"
done
