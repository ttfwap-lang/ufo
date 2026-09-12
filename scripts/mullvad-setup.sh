#!/bin/zsh
set -euo pipefail

# --- FILL IN YOUR KEYS BELOW ---
MULLVAD_ACCOUNT="5901587210529138"
WG_PRIVATE_KEY="paste-PrivateKey-here"
WG_PUBLIC_KEY="paste-PublicKey-here"
DNS_SERVER="10.64.0.1, fc00:bbbb:bbbb:bb01::1"
# -------------------------------

OUTDIR="$HOME/Desktop/mullvad-tunnels"

if [[ "$WG_PRIVATE_KEY" == *"paste-"* ]]; then
    echo "Error: Please open this script and insert your WireGuard keys."
    exit 1
fi

echo "==> Creating output folder on your Desktop..."
mkdir -p "$OUTDIR"
cd "$OUTDIR"

echo "==> Registering public key with Mullvad..."
curl -sS -X POST https://api.mullvad.net/app/v1/wireguard-keys \
  -H "Content-Type: application/json" \
  -H "Authorization: Token $MULLVAD_ACCOUNT" \
  -d "{\"pubkey\":\"$WG_PUBLIC_KEY\"}" -o register.json

IPV4=$(osascript -l JavaScript -e "
  var app = Application.currentApplication(); app.includeStandardAdditions = true;
  JSON.parse(app.read(Path('$OUTDIR/register.json'))).ipv4_address;")
IPV6=$(osascript -l JavaScript -e "
  var app = Application.currentApplication(); app.includeStandardAdditions = true;
  JSON.parse(app.read(Path('$OUTDIR/register.json'))).ipv6_address;")

echo "==> Assigned address: $IPV4, $IPV6"

echo "==> Fetching active relay list..."
curl -sS https://api.mullvad.net/public/relays/wireguard/v1/ -o relays.json

echo "==> Finding all active Australian servers..."
AU_HOSTS_STR=$(osascript -l JavaScript -e "
  var app = Application.currentApplication(); app.includeStandardAdditions = true;
  var data = JSON.parse(app.read(Path('$OUTDIR/relays.json')));
  var hosts = [];
  data.countries.forEach(function(c) {
    if (c.name === 'Australia') {
      c.cities.forEach(function(ci) {
        ci.relays.forEach(function(r) {
          if (r.active) hosts.push(r.hostname);
        });
      });
    }
  });
  hosts.join(' ');")

SELECTED_HOSTS=(${=AU_HOSTS_STR})
echo "==> Found ${#SELECTED_HOSTS[@]} Australian servers. Generating configs..."

for HOST in "${SELECTED_HOSTS[@]}"; do
  LINE=$(osascript -l JavaScript -e "
    var app = Application.currentApplication(); app.includeStandardAdditions = true;
    var data = JSON.parse(app.read(Path('$OUTDIR/relays.json')));
    var found = null;
    data.countries.forEach(function(c){ c.cities.forEach(function(ci){ ci.relays.forEach(function(r){
      if (r.hostname === '$HOST') found = r.public_key + '|' + r.ipv4_addr_in;
    })})});
    found;")
  
  if [[ -z "$LINE" || "$LINE" == "null" ]]; then
    continue
  fi
  
  PUBKEY="${LINE%%|*}"
  IP="${LINE##*|}"
  
  cat > "$HOST.conf" <<EOF
[Interface]
PrivateKey = $WG_PRIVATE_KEY
Address = $IPV4, $IPV6
DNS = $DNS_SERVER

[Peer]
PublicKey = $PUBKEY
Endpoint = $IP:51820
AllowedIPs = 0.0.0.0/0, ::/0
EOF
done

echo "==> Zipping configurations for easy import..."
zip -q -j mullvad-relays.zip *.conf
rm *.conf register.json relays.json

echo "====================================================="
echo " SUCCESS! "
echo " You will find 'mullvad-relays.zip' on your Desktop."
echo "====================================================="
