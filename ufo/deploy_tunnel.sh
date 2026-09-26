#!/usr/bin/env bash
# Deploy ufo-tunnel: republish the loopback-bound model servers on the tailnet
# WITHOUT relaunching them (another agent owns those launches).
set -uo pipefail
H=/home/flak3dd
D=$H/ufo-watchdog

echo "########## 1. SYNTAX GATE ##########"
python3 -c "import ast,io;ast.parse(io.open('/tmp/ufo_tunnel.py',encoding='utf-8').read());print('  ufo_tunnel.py OK')" || exit 1
bash -n /tmp/ufo_watchdog.sh && echo "  ufo_watchdog.sh OK" || exit 1
bash /tmp/ufo_watchdog.sh --selftest || exit 1

echo
echo "########## 2. INSTALL ##########"
install -m 0755 /tmp/ufo_tunnel.py    "$D/ufo_tunnel.py"
install -m 0755 /tmp/ufo_watchdog.sh  "$D/ufo_watchdog.sh"
install -m 0644 /tmp/ufo-tunnel.service "$H/.config/systemd/user/ufo-tunnel.service"
ls -la "$D" | sed 's/^/  /'

echo
echo "########## 3. FREE THE PORTS AND START THE TUNNEL ##########"
# clear any earlier rebuild lock so the tunnel is not confused by it
rm -f "$D/.venus_rebuild_running"
systemctl --user daemon-reload
systemctl --user enable --now ufo-tunnel.service 2>&1 | sed 's/^/  /'
sleep 4
systemctl --user is-active ufo-tunnel.service | sed 's/^/  active: /'
echo "  --- listening ---"
ss -ltn 2>/dev/null | grep -E ':(18000|18002|18061)' | sed 's/^/    /'
echo "  --- tunnel log ---"
tail -8 "$D/tunnel.log" 2>/dev/null | sed 's/^/    /'

echo
echo "########## 4. VERIFY: local upstreams still loopback, tunnel republishes them ##########"
printf '  brain  127.0.0.1:8000  HTTP %s\n' "$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8000/v1/models)"
printf '  venus  127.0.0.1:8002  HTTP %s\n' "$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8002/v1/models)"
printf '  TUNNEL 100.67.13.78:18000 HTTP %s\n' "$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://100.67.13.78:18000/v1/models)"
printf '  TUNNEL 100.67.13.78:18002 HTTP %s\n' "$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://100.67.13.78:18002/v1/models)"
echo "  --- model ids through the tunnel ---"
curl -s --max-time 10 http://100.67.13.78:18002/v1/models 2>/dev/null | head -c 200; echo

echo
echo "########## 5. ALLOW THE TUNNEL PORTS THROUGH THE FIREWALL ##########"
for p in 18000 18002 18061; do
  for n in 100.64.0.0/10 192.168.0.0/16 10.0.0.0/8; do
    sudo -n ufw allow from "$n" to any port "$p" proto tcp >/dev/null 2>&1
  done
  echo "  allowed $p"
done

echo
echo "########## 6. WATCHDOG PASS ##########"
systemctl --user start ufo-watchdog.service 2>/dev/null
sleep 12
cat "$D/state.json" | sed 's/^/  /'
echo "  --- log ---"
tail -10 "$D/watchdog.log" | sed 's/^/    /'

echo
echo "########## 7. VENUS: no more relaunch fights ##########"
echo "  venus container bind (left exactly as the other agent launched it):"
ss -ltn 2>/dev/null | grep ':8002' | sed 's/^/    /'
echo "  rebuild-in-flight marker: $([ -f "$D/.venus_rebuild_running" ] && echo PRESENT || echo clear)"
echo
echo "########## done ##########"
