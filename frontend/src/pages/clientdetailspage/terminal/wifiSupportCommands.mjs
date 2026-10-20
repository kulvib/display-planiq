// ClientFlow remote-support helpers. The setup helper deliberately stages a profile;
// changing the active uplink would risk cutting off the remote terminal.
export const WIFI_DIAGNOSTICS_COMMAND = `cat <<'CLIENTFLOW_WIFI_DIAGNOSTICS' | sudo bash
set -uo pipefail

echo "=== ClientFlow WiFi / netværk (kun læsning) ==="
if ! command -v nmcli >/dev/null 2>&1; then
  echo "NetworkManager / nmcli findes ikke."
  exit 1
fi

echo
 echo "== NetworkManager =="
nmcli -f RUNNING,STATE,CONNECTIVITY general status 2>&1 || true
 echo "== Radio =="
nmcli radio wifi 2>&1 || true
 echo "== Enheder =="
nmcli -f DEVICE,TYPE,STATE,CONNECTION device status 2>&1 || true
 echo "== Aktive forbindelser (ingen secrets) =="
nmcli -f NAME,UUID,TYPE,DEVICE connection show --active 2>&1 || true
 echo "== Gemte WiFi-profiler (ingen secrets) =="
nmcli -f NAME,UUID,TYPE,AUTOCONNECT connection show 2>&1 | grep -E '^(NAME|.*wifi.*|.*802-11-wireless.*)' || true
 echo "== Kendte WiFi-netværk (ingen tvungen rescan) =="
nmcli -f IN-USE,SSID,SIGNAL,SECURITY device wifi list --rescan no 2>&1 || true
 echo "== IP og routing =="
ip -br address show 2>&1 || true
ip route show default 2>&1 || true
ip -6 route show default 2>&1 || true
 echo "== DNS =="
resolvectl dns 2>&1 || true
 echo "== NetworkManager status =="
systemctl is-active NetworkManager.service 2>&1 || true
 echo "WIFI_DIAGNOSTICS=COMPLETE"
CLIENTFLOW_WIFI_DIAGNOSTICS`;

export const WIFI_STAGE_PROFILE_COMMAND = `cat <<'CLIENTFLOW_WIFI_STAGE' | sudo bash
set -euo pipefail
umask 077
export LC_ALL=C

echo "=== ClientFlow: opret WiFi-profil uden forbindelsesskift ==="
echo "ADVARSEL: Dette script opretter kun en gemt profil og aktiverer den IKKE."
echo "Det ændrer ikke eksisterende netværk, routing eller autoconnect."
echo "Remote WiFi-omkobling kræver særskilt plan med fysisk fallback."

if [[ "$(id -u)" -ne 0 ]]; then
  echo "FEJL: Kræver Admin-terminal/root."
  exit 1
fi
if ! command -v nmcli >/dev/null 2>&1; then
  echo "FEJL: nmcli mangler."
  exit 1
fi
if [[ "$(nmcli -g RUNNING general status 2>/dev/null | head -1)" != "running" ]]; then
  echo "FEJL: NetworkManager er ikke aktiv."
  exit 1
fi

nmcli -f DEVICE,TYPE,STATE,CONNECTION device status
printf '\\n'
read -r -p "WiFi interface (fx wlp2s0): " iface </dev/tty
if [[ -z "$iface" ]] || ! nmcli -t -f DEVICE,TYPE device status | grep -Fxq "$iface:wifi"; then
  echo "FEJL: Vælg et eksisterende WiFi-interface fra listen."
  exit 1
fi
read -r -p "WiFi SSID (netværksnavn): " ssid </dev/tty
if [[ -z "$ssid" ]] || (( \${#ssid} > 32 )); then
  echo "FEJL: SSID skal være 1–32 bytes."
  exit 1
fi
read -r -p "Skjult SSID? [j/N]: " hidden </dev/tty
if [[ "$hidden" != "" && "$hidden" != "j" && "$hidden" != "J" && "$hidden" != "n" && "$hidden" != "N" ]]; then
  echo "FEJL: Vælg j eller n."
  exit 1
fi
read -r -p "Sikkerhed (1=WPA2/WPA3-overgang, 2=WPA3-only SAE) [1]: " security </dev/tty
case "$security" in
  ""|1) key_mgmt="wpa-psk" ;;
  2) key_mgmt="sae" ;;
  *) echo "FEJL: Vælg 1 eller 2."; exit 1 ;;
esac
read -r -s -p "WiFi WPA2/WPA3-personlig adgangskode (vises ikke): " psk </dev/tty
printf '\\n'
if [[ "$key_mgmt" == "wpa-psk" ]]; then
  if (( \${#psk} < 8 || \${#psk} > 63 )) && ! { (( \${#psk} == 64 )) && [[ "$psk" =~ ^[0-9a-fA-F]{64}$ ]]; }; then
    unset psk
    echo "FEJL: WPA2/overgang kræver 8–63 tegn eller 64 hex-tegn."
    exit 1
  fi
elif [[ -z "$psk" ]]; then
  echo "FEJL: WPA3 SAE kræver en ikke-tom adgangskode."
  exit 1
fi
read -r -p "Skriv OPRET for kun at gemme profilen: " approval </dev/tty
if [[ "$approval" != "OPRET" ]]; then
  unset psk
  echo "AFBRUDT: Ingen ændringer."
  exit 0
fi

profile="ClientFlow WiFi - $(date -u +%Y%m%dT%H%M%S) - $$"
created_uuid=""
created=0
cleanup() {
  if [[ "$created" == 1 ]]; then
    nmcli connection delete id "$profile" >/dev/null 2>&1 || true
    echo "Ufuldstændig ny WiFi-profil: rydning forsøgt."
  fi
}
trap cleanup EXIT

nmcli connection add type wifi ifname "$iface" ssid "$ssid" con-name "$profile" \
  connection.autoconnect no ipv4.method auto ipv6.method auto \
  ipv4.route-metric 600 ipv6.route-metric 600 >/dev/null
created=1
created_uuid="$(nmcli -g connection.uuid connection show "$profile" | head -1)"
if [[ -z "$created_uuid" ]]; then
  echo "FEJL: Ny profils UUID kunne ikke verificeres. Kontrollér nmcli."
  exit 1
fi
nmcli connection modify uuid "$created_uuid" wifi-sec.key-mgmt "$key_mgmt" wifi-sec.psk "$psk"
unset psk
if [[ "$hidden" == "j" || "$hidden" == "J" ]]; then
  nmcli connection modify uuid "$created_uuid" wifi.hidden yes
fi
[[ "$(nmcli -g connection.autoconnect connection show uuid "$created_uuid")" == "no" ]]
[[ -z "$(nmcli -g GENERAL.DEVICES connection show uuid "$created_uuid" | grep -v '^--$' || true)" ]]
trap - EXIT
 echo "WIFI_PROFILE_STAGED=PASS"
 echo "PROFILE_UUID=$created_uuid"
 echo "AUTOCONNECT=no"
 echo "ACTIVE_CONNECTION_UNCHANGED=yes"
 echo "WiFi er IKKE aktiveret. Aftal sikker omkobling med fallback først."
CLIENTFLOW_WIFI_STAGE`;
