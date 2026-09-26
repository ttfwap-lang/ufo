#!/usr/bin/env bash
# One-time switch from the nohup-launched processes to systemd user units.
set -euo pipefail
UNITDIR="$HOME/.config/systemd/user"
mkdir -p "$UNITDIR" "$HOME/ufo-galaxy/logs" "$HOME/OmniParser/logs"
SRC="$(dirname "$0")"
install -m 644 "$SRC"/ufo-linux-mcp.service "$SRC"/ufo-galaxy-server.service "$SRC"/ufo-galaxy-client.service \
  "$SRC"/omniparser.service "$SRC"/ufo-galaxy.target "$UNITDIR"/
install -m 755 "$SRC"/start_galaxy_device.sh "$HOME/ufo-galaxy/start_galaxy_device.sh"
install -m 755 "$SRC"/start_omniparser.sh "$HOME/OmniParser/start_omniparser.sh"
# Model launchers + the shared memory budget/guard (one launcher, one budget; see gx10_budget.env).
install -m 755 "$SRC"/qwen_run.sh "$SRC"/venus_run.sh "$SRC"/gx10_guard.sh "$SRC"/gx10_memguard.sh "$HOME/ufo-galaxy/"
install -m 644 "$SRC"/gx10-memguard.service "$SRC"/gx10-memguard.timer "$UNITDIR"/
# Keep an operator-edited budget: only install the default when there is none.
[ -f "$HOME/ufo-galaxy/gx10_budget.env" ] || install -m 644 "$SRC"/gx10_budget.env "$HOME/ufo-galaxy/gx10_budget.env"
loginctl enable-linger "$USER" 2>/dev/null || true
systemctl --user daemon-reload
# Stop the old nohup processes (bracket patterns so this script does not match itself).
pkill -f "ufo[.]client[.]mcp[.]http_servers[.]linux_mcp_server" || true
pkill -f "ufo[.]server[.]app" || true
pkill -f "ufo[.]client[.]client" || true
pkill -f "python gradio_dem[o]" || true
sleep 2
# OmniParser now runs locally on the Windows GPU; make sure the CPU-bound copy here is off.
systemctl --user disable --now omniparser.service 2>/dev/null || true
systemctl --user enable ufo-linux-mcp.service ufo-galaxy-server.service ufo-galaxy-client.service ufo-galaxy.target
systemctl --user enable --now gx10-memguard.timer   # keeps >= 5% free, encourages 10%
systemctl --user start ufo-galaxy.target
echo installed
