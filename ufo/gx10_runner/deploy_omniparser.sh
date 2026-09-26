# Switch the OmniParser user service to the REST+UI wrapper (one process,
# one copy of the models) and bind it to 0.0.0.0 so the Windows UFO bridge can
# reach it over the tailnet. Assumes omniparser_api.py was already scp'd into
# ~/OmniParser/.
set -euo pipefail

DEST_DIR="$HOME/OmniParser"
SVC_DIR="$HOME/.config/systemd/user"

test -f "$DEST_DIR/omniparser_api.py" || { echo "omniparser_api.py not in $DEST_DIR"; exit 1; }
test -f "$DEST_DIR/util/utils.py"        || { echo "OmniParser checkout missing"; exit 1; }

mkdir -p "$SVC_DIR" "$DEST_DIR/logs"
cat > "$SVC_DIR/omniparser.service" <<'UNIT'
[Unit]
Description=OmniParser V2 screen parser for UFO (REST API + Gradio UI on 0.0.0.0:7861)
PartOf=ufo-galaxy.target

[Service]
Type=simple
WorkingDirectory=%h/OmniParser
Environment=PYTHONUNBUFFERED=1
Environment=OMNIPARSER_BIND=0.0.0.0
# The GB10's unified memory is fully reserved by the two LLM pools, so the
# detector/captioner cannot allocate on CUDA and the service crash-loops with
# CUDA out of memory. They are small (~1.3 GB) so run them on CPU instead.
Environment=OMNIPARSER_DEVICE=cpu
Environment=OMNIPARSER_PORT=7861
ExecStart=%h/OmniParser/.venv/bin/python omniparser_api.py
Restart=always
RestartSec=10
StandardOutput=append:%h/OmniParser/logs/omniparser.log
StandardError=inherit

[Install]
WantedBy=ufo-galaxy.target
UNIT
echo "wrote omniparser.service"

systemctl --user daemon-reload
systemctl --user restart omniparser.service

for i in $(seq 1 90); do
  sleep 5
  if curl -sf --max-time 3 http://127.0.0.1:7861/api/health >/dev/null 2>&1; then
    echo "omniparser API up after $((i*5))s"
    curl -s http://127.0.0.1:7861/api/health; echo
    ss -ltn | grep 7861 || true
    exit 0
  fi
  if ! systemctl --user is-active --quiet omniparser.service; then
    echo "service failed to stay up"
    systemctl --user status omniparser.service --no-pager | tail -20 || true
    tail -40 "$DEST_DIR/logs/omniparser.log" || true
    exit 1
  fi
done
echo "timed out waiting for /api/health"
tail -40 "$DEST_DIR/logs/omniparser.log" || true
exit 1
