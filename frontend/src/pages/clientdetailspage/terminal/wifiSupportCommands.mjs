// Admin-only ClientFlow network helpers. The profile setup deliberately never activates WiFi.
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
set +x
umask 077
export LC_ALL=C

echo '=== ClientFlow: opret WiFi-profil uden forbindelsesskift ==='
echo 'Der oprettes en gemt WPA2/WPA3-profil; aktivt netværk, routing og autoconnect ændres ikke.'
echo 'WiFi-omkobling kræver en særskilt plan med sikker rollback eller fysisk adgang.'

if [[ "$(id -u)" -ne 0 ]]; then
  echo 'FEJL: Kræver autoriseret Admin-terminal/root.'
  exit 1
fi
if ! command -v nmcli >/dev/null 2>&1 || ! command -v install >/dev/null 2>&1; then
  echo 'FEJL: NetworkManager/nmcli eller install mangler.'
  exit 1
fi
if [[ "$(nmcli -g RUNNING general status 2>/dev/null | head -1)" != 'running' ]]; then
  echo 'FEJL: NetworkManager er ikke aktiv.'
  exit 1
fi
if [[ ! -d /etc/NetworkManager/system-connections ]]; then
  echo 'FEJL: NetworkManagers systemprofilmappe mangler.'
  exit 1
fi
if [[ ! -r /dev/tty ]]; then
  echo 'FEJL: Interaktiv TTY kræves. Adgangskoden må ikke indgå i en kommando.'
  exit 1
fi

nmcli -f DEVICE,TYPE,STATE,CONNECTION device status
printf '\\n'
read -r -p 'WiFi-interface (fx wlp2s0): ' iface </dev/tty
if [[ -z "$iface" ]] || ! nmcli -t -f DEVICE,TYPE device status | grep -Fxq "$iface:wifi"; then
  echo 'FEJL: Vælg et eksisterende WiFi-interface.'
  exit 1
fi
read -r -p 'WiFi-SSID (netværksnavn): ' ssid </dev/tty
if [[ -z "$ssid" || "$ssid" == *$'\\r'* || "$ssid" == *$'\\n'* ]] || (( \${#ssid} > 32 )); then
  echo 'FEJL: SSID skal være 1–32 bytes og uden linjeskift.'
  exit 1
fi
read -r -p 'Skjult SSID? [j/N]: ' hidden </dev/tty
case "$hidden" in ''|n|N|j|J) ;; *) echo 'FEJL: Svar j eller n.'; exit 1 ;; esac
read -r -p 'Sikkerhed (1=WPA2/WPA3-overgang, 2=WPA3 SAE) [1]: ' security </dev/tty
case "$security" in
  ''|1) key_mgmt='wpa-psk' ;;
  2) key_mgmt='sae' ;;
  *) echo 'FEJL: Vælg 1 eller 2.'; exit 1 ;;
esac
read -r -s -p 'WiFi-adgangskode (vises ikke): ' psk </dev/tty
printf '\\n'
if [[ "$psk" == *$'\\r'* || "$psk" == *$'\\n'* ]]; then
  unset psk
  echo 'FEJL: Adgangskoden må ikke indeholde linjeskift.'
  exit 1
fi
if [[ "$key_mgmt" == 'wpa-psk' ]]; then
  if (( \${#psk} < 8 || \${#psk} > 63 )) && ! { (( \${#psk} == 64 )) && [[ "$psk" =~ ^[0-9a-fA-F]{64}$ ]]; }; then
    unset psk
    echo 'FEJL: WPA2 kræver 8–63 bytes eller 64 hex-tegn.'
    exit 1
  fi
elif [[ -z "$psk" || \${#psk} -gt 63 ]]; then
  unset psk
  echo 'FEJL: WPA3-adgangskode skal være 1–63 bytes.'
  exit 1
fi
read -r -p 'Skriv OPRET for kun at gemme profilen: ' approval </dev/tty
if [[ "$approval" != 'OPRET' ]]; then
  unset psk
  echo 'AFBRUDT: Ingen ændringer.'
  exit 0
fi

# Use bash builtins and a root-only /run keyfile; NEVER pass the secret in process argv.
# The persistent NetworkManager profile must hold the PSK for later activation.
uuid="$(cat /proc/sys/kernel/random/uuid)"
profile="ClientFlow WiFi - $uuid"
stage_dir="$(mktemp -d /run/clientflow-wifi-stage.XXXXXXXX)"
stage_path="$stage_dir/profile.nmconnection"
target="/etc/NetworkManager/system-connections/clientflow-$uuid.nmconnection"
installed=0
cleanup() {
  if [[ "$installed" == 1 ]]; then
    nmcli connection delete uuid "$uuid" >/dev/null 2>&1 || true
    rm -f -- "$target"
    echo 'Ufuldstændig WiFi-profil: oprydning forsøgt.'
  fi
  rm -f -- "$stage_path" 2>/dev/null || true
  rmdir -- "$stage_dir" 2>/dev/null || true
  unset psk escaped_psk
}
trap cleanup EXIT
trap 'exit 1' INT TERM HUP
if [[ -e "$target" ]]; then
  echo 'FEJL: Den genererede profil findes allerede.'
  exit 1
fi

# GLib keyfile strings use backslash escapes. Never interpolate raw newlines.
escaped_ssid="\${ssid//\\\\/\\\\\\\\}"
escaped_psk="\${psk//\\\\/\\\\\\\\}"
{
  printf '%s\\n' '[connection]'
  printf 'id=%s\\n' "$profile"
  printf 'uuid=%s\\n' "$uuid"
  printf '%s\\n' 'type=wifi' "interface-name=$iface" 'autoconnect=false' ''
  printf '%s\\n' '[wifi]' 'mode=infrastructure'
  printf 'ssid=%s\\n' "$escaped_ssid"
  printf 'hidden=%s\\n' "$( [[ "$hidden" == 'j' || "$hidden" == 'J' ]] && echo true || echo false )"
  printf '%s\\n' 'security=802-11-wireless-security' '' '[wifi-security]'
  printf 'key-mgmt=%s\\n' "$key_mgmt"
  printf 'psk=%s\\n' "$escaped_psk"
  printf '%s\\n' '' '[ipv4]' 'method=auto' 'route-metric=600' '' '[ipv6]' 'method=auto' 'route-metric=600'
} > "$stage_path"
unset psk escaped_psk
chmod 0600 "$stage_path"
active_before="$(nmcli -t -f UUID,DEVICE connection show --active)"
install -m 0600 -- "$stage_path" "$target"
installed=1
nmcli connection load "$target" >/dev/null
if [[ "$(nmcli -g connection.autoconnect connection show uuid "$uuid")" != 'no' ]]; then
  echo 'FEJL: Ny profil er ikke markeret som inaktiv.'
  exit 1
fi
if [[ "$(nmcli -t -f UUID,DEVICE connection show --active)" != "$active_before" ]]; then
  echo 'FEJL: Aktiv forbindelse blev ændret; undersøges straks.'
  exit 1
fi
installed=0
printf '%s\\n' 'WIFI_PROFILE_STAGED=PASS' "PROFILE_UUID=$uuid" 'AUTOCONNECT=no' 'ACTIVE_CONNECTION_UNCHANGED=yes'
echo 'WiFi er IKKE aktiveret. Planlæg omkobling med rollback før netværksskift.'
CLIENTFLOW_WIFI_STAGE`;
