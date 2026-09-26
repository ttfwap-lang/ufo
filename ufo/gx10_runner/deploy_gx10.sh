#!/usr/bin/env bash
# Deploy the gx10 Telegram/agent runner: sync -> build -> up (detached, restart always).
# docker-compose.yml intentionally builds Dockerfile.agent; keep both legacy
# and native agent sources available during the transition.
set -euo pipefail

DGX="${DGX:-flak3dd@gx10.local}"
KEY="${KEY:-$HOME/.ssh/id_ed25519_ufo_agent}"
APP_DIR="${APP_DIR:-ufo-tg-runner}"

echo "==> syncing to $DGX:~/$APP_DIR"
ssh -i "$KEY" "$DGX" "mkdir -p ~/$APP_DIR"
scp -i "$KEY" -r \
  telegram_runner.py Dockerfile Dockerfile.agent agent_runner.py \
  browseract_navigation.py docker-compose.yml .env.example \
  "$DGX:~/$APP_DIR/"

echo "==> building & starting (detached, restart: always)"
ssh -i "$KEY" "$DGX" "cd ~/$APP_DIR && docker compose build && docker compose up -d"

echo "==> status"
ssh -i "$KEY" "$DGX" "cd ~/$APP_DIR && docker compose ps"
echo "Done. If .env is missing: ssh $DGX 'cd ~/$APP_DIR && cp .env.example .env && nano .env'"
