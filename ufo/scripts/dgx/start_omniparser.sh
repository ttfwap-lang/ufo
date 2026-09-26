#!/usr/bin/env bash
# (Re)starts OmniParser V2 (Gradio API on 127.0.0.1:7861) under systemd --user.
cd "$(dirname "$0")"
mkdir -p logs
systemctl --user restart omniparser.service
for i in $(seq 1 60); do
  sleep 5
  if ss -ltn | grep -q "127.0.0.1:7861 "; then echo "omniparser up (pid $(systemctl --user show -p MainPID --value omniparser.service))"; exit 0; fi
  if ! systemctl --user is-active --quiet omniparser.service; then echo "omniparser not running"; tail -20 logs/omniparser.log; exit 1; fi
done
echo "timed out waiting for 7861"; tail -20 logs/omniparser.log; exit 1
