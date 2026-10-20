import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import {
  WIFI_DIAGNOSTICS_COMMAND,
  WIFI_STAGE_PROFILE_COMMAND,
} from '../src/pages/clientdetailspage/terminal/wifiSupportCommands.mjs';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const dialog = readFileSync(path.join(ROOT, '../src/pages/clientdetailspage/terminal/ClientTerminalDialog.jsx'), 'utf8');

function assertBashSyntax(command) {
  const check = spawnSync('bash', ['-n'], { input: command, encoding: 'utf8' });
  assert.equal(check.status, 0, check.stderr);
  // Heredoc contents are data to the wrapper parser; validate the inner script as Bash too.
  const lines = command.trim().split('\n');
  assert.match(lines[0], /^cat <<'CLIENTFLOW_WIFI_[A-Z]+' \| sudo bash$/);
  const inner = spawnSync('bash', ['-n'], { input: lines.slice(1, -1).join('\n'), encoding: 'utf8' });
  assert.equal(inner.status, 0, inner.stderr);
}

test('both helpers are syntactically valid Bash and restricted to Admin-terminal', () => {
  assertBashSyntax(WIFI_DIAGNOSTICS_COMMAND);
  assertBashSyntax(WIFI_STAGE_PROFILE_COMMAND);
  assert.match(dialog, /label: "WiFi \/ NetworkManager diagnose", command: WIFI_DIAGNOSTICS_COMMAND, adminOnly: true/);
  assert.match(dialog, /label: "Tilføj WiFi-profil \(uden aktivering\)", command: WIFI_STAGE_PROFILE_COMMAND, adminOnly: true/);
});

test('diagnostic helper does not modify NetworkManager state or dump credentials', () => {
  assert.match(WIFI_DIAGNOSTICS_COMMAND, /nmcli .*device status/);
  assert.match(WIFI_DIAGNOSTICS_COMMAND, /nmcli .*wifi list --rescan no/);
  assert.doesNotMatch(WIFI_DIAGNOSTICS_COMMAND, /nmcli\s+(?:device\s+disconnect|connection\s+(?:up|down|modify|add|delete)|radio\s+wifi\s+on)/);
  assert.doesNotMatch(WIFI_DIAGNOSTICS_COMMAND, /connection\.show.*--show-secrets|journalctl/);
});

test('setup stages an inactive WiFi profile without switching the remote terminal uplink', () => {
  assert.match(WIFI_STAGE_PROFILE_COMMAND, /connection\.autoconnect no/);
  assert.match(WIFI_STAGE_PROFILE_COMMAND, /nmcli connection add type wifi/);
  assert.match(WIFI_STAGE_PROFILE_COMMAND, /nmcli connection modify uuid/);
  assert.match(WIFI_STAGE_PROFILE_COMMAND, /read -r -s .* psk <\/dev\/tty/);
  assert.match(WIFI_STAGE_PROFILE_COMMAND, /approval.*OPRET/);
  assert.match(WIFI_STAGE_PROFILE_COMMAND, /trap cleanup EXIT/);
  assert.match(WIFI_STAGE_PROFILE_COMMAND, /WIFI_PROFILE_STAGED=PASS/);
  assert.doesNotMatch(WIFI_STAGE_PROFILE_COMMAND, /nmcli\s+connection\s+(?:up|down)|nmcli\s+device\s+(?:connect|disconnect)|nmcli\s+radio\s+wifi\s+on/);
  assert.doesNotMatch(WIFI_STAGE_PROFILE_COMMAND, /connection\.autoconnect yes/);
  assert.doesNotMatch(WIFI_STAGE_PROFILE_COMMAND, /echo.*\$psk|printf.*\$psk/);
});

test('original 15 specialized support commands remain and raw previews can be summarized', () => {
  const labels = [
    'ClientFlow samlet status', 'Display / kiosk browser', 'Aktiv release / updater',
    'Livestream v2 status', 'Terminal status', 'Remote Desktop status',
    'Aktive ClientFlow units', 'Ubuntu / APT health', 'Disk, RAM og oppetid',
    'Netværk, DNS, tid og backend', 'Display/browser logs', 'Status/System logs',
    'Livestream logs', 'Terminal logs', 'Remote Desktop logs',
  ];
  for (const label of labels) assert.ok(dialog.includes(`label: "${label}"`), `missing: ${label}`);
  assert.match(dialog, /item\.description \|\| item\.command/);
  assert.match(dialog, /const itemDisabled = terminalDisabled \|\| \(item\.adminOnly && !isAdminMode\)/);
});
