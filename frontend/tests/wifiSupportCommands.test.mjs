import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { WIFI_DIAGNOSTICS_COMMAND, WIFI_STAGE_PROFILE_COMMAND } from '../src/pages/clientdetailspage/terminal/wifiSupportCommands.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const dialog = readFileSync(path.join(HERE, '../src/pages/clientdetailspage/terminal/ClientTerminalDialog.jsx'), 'utf8');

function requireValidScript(command, marker) {
  assert.match(command.split('\n')[0], new RegExp(`^cat <<'${marker}' \\| sudo bash$`));
  const wrapper = spawnSync('bash', ['-n'], { input: command, encoding: 'utf8' });
  assert.equal(wrapper.status, 0, wrapper.stderr);
  const lines = command.trim().split('\n');
  assert.equal(lines.at(-1), marker);
  const body = spawnSync('bash', ['-n'], { input: lines.slice(1, -1).join('\n'), encoding: 'utf8' });
  assert.equal(body.status, 0, body.stderr);
}

test('WiFi helpers are valid bash and available only as Admin support commands', () => {
  requireValidScript(WIFI_DIAGNOSTICS_COMMAND, 'CLIENTFLOW_WIFI_DIAGNOSTICS');
  requireValidScript(WIFI_STAGE_PROFILE_COMMAND, 'CLIENTFLOW_WIFI_STAGE');
  assert.match(dialog, /label: "WiFi \/ NetworkManager diagnose", command: WIFI_DIAGNOSTICS_COMMAND, adminOnly: true/);
  assert.match(dialog, /label: "Tilføj WiFi-profil \(uden aktivering\)", command: WIFI_STAGE_PROFILE_COMMAND, adminOnly: true/);
  assert.match(dialog, /const itemDisabled = terminalDisabled \|\| \(item\.adminOnly && !isAdminMode\)/);
});

test('diagnostics are read-only and omit secrets and active rescans', () => {
  assert.match(WIFI_DIAGNOSTICS_COMMAND, /nmcli .*wifi list --rescan no/);
  assert.match(WIFI_DIAGNOSTICS_COMMAND, /nmcli .*connection show --active/);
  assert.doesNotMatch(WIFI_DIAGNOSTICS_COMMAND, /nmcli\s+(?:device\s+disconnect|connection\s+(?:up|down|modify|add|delete|load)|radio\s+wifi\s+on)/);
  assert.doesNotMatch(WIFI_DIAGNOSTICS_COMMAND, /--show-secrets|journalctl/);
});

test('profile setup stages a protected NetworkManager keyfile and never changes active connection', () => {
  assert.match(WIFI_STAGE_PROFILE_COMMAND, /read -r -s -p .* psk <\/dev\/tty/);
  assert.match(WIFI_STAGE_PROFILE_COMMAND, /approval.*OPRET/);
  assert.match(WIFI_STAGE_PROFILE_COMMAND, /umask 077/);
  assert.match(WIFI_STAGE_PROFILE_COMMAND, /set \+x/);
  assert.match(WIFI_STAGE_PROFILE_COMMAND, /\/run\/clientflow-wifi-stage/);
  assert.match(WIFI_STAGE_PROFILE_COMMAND, /install -m 0600/);
  assert.match(WIFI_STAGE_PROFILE_COMMAND, /nmcli connection load "\$target"/);
  assert.match(WIFI_STAGE_PROFILE_COMMAND, /autoconnect=false/);
  assert.match(WIFI_STAGE_PROFILE_COMMAND, /active_before=/);
  assert.match(WIFI_STAGE_PROFILE_COMMAND, /ACTIVE_CONNECTION_UNCHANGED=yes/);
  assert.match(WIFI_STAGE_PROFILE_COMMAND, /trap cleanup EXIT/);
  assert.match(WIFI_STAGE_PROFILE_COMMAND, /WIFI_PROFILE_STAGED=PASS/);
  assert.doesNotMatch(WIFI_STAGE_PROFILE_COMMAND, /nmcli\s+connection\s+(?:up|down|modify)|nmcli\s+device\s+(?:connect|disconnect)|nmcli\s+radio\s+wifi\s+on/);
  assert.doesNotMatch(WIFI_STAGE_PROFILE_COMMAND, /connection\.autoconnect yes|autoconnect=true/);
});

test('PSK is not supplied in argv, environment, logging or the rendered support-command preview', () => {
  assert.match(WIFI_STAGE_PROFILE_COMMAND, /printf 'psk=%s\\n' "\$escaped_psk"/);
  assert.doesNotMatch(WIFI_STAGE_PROFILE_COMMAND, /nmcli[^\n]*\b(?:psk|password)\b/i);
  assert.doesNotMatch(WIFI_STAGE_PROFILE_COMMAND, /export\s+(?:psk|password)|echo[^\n]*\$psk|set -x/);
  assert.match(dialog, /item\.description \|\| item\.command/);
  assert.match(dialog, /WIFI_STAGE_PROFILE_COMMAND.*description: "Interaktiv/);
});

test('all 15 original specialized support commands remain available', () => {
  const labels = [
    'ClientFlow samlet status', 'Display / kiosk browser', 'Aktiv release / updater',
    'Livestream v2 status', 'Terminal status', 'Remote Desktop status',
    'Aktive ClientFlow units', 'Ubuntu / APT health', 'Disk, RAM og oppetid',
    'Netværk, DNS, tid og backend', 'Display/browser logs', 'Status/System logs',
    'Livestream logs', 'Terminal logs', 'Remote Desktop logs',
  ];
  for (const label of labels) assert.ok(dialog.includes(`label: "${label}"`), `Missing existing command: ${label}`);
});
