#!/usr/bin/env bash
# Deploy the gx10 Telegram runner: sync -> build -> up (detached, restart always).
set -euo pipefail

DGX="${DGX:-flak3dd@gx10.local}"
KEY="${KEY:-$HOME/.ssh/id_ed25519_ufo_agent}"
APP_DIR="ufo-tg-runner"

echo "==> syncing to $DGX:~/$APP_DIR"
ssh -i "$KEY" "$DGX" "mkdir -p ~/$APP_DIR"
scp -i "$KEY" -r \
  telegram_runner.py Dockerfile docker-compose.yml .env.example \
  "$DGX:~/$APP_DIR/"

echo "==> building & starting (detached, restart: always)"
ssh -i "$KEY" "$DGX" "cd ~/$APP_DIR && docker compose build && docker compose up -d"

echo "==> status"
ssh -i "$KEY" "$DGX" "cd ~/$APP_DIR && docker compose ps"
echo "Done. If .env is missing: ssh $DGX 'cd ~/$APP_DIR && cp .env.example .env && nano .env'"
