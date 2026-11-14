import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { SUPPORT_COMMAND_GUIDES, SUPPORT_RISK_LABELS } from '../src/pages/clientdetailspage/terminal/terminalSupportGuides.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const component = readFileSync(path.join(here, '../src/pages/clientdetailspage/terminal/ClientTerminalDialog.jsx'), 'utf8');
const labels = [...component.matchAll(/\{ label: "([^"]+)", command:/g)].map((match) => match[1]);

test('every support command has a full and individually meaningful Danish operator guide', () => {
  assert.equal(labels.length, 20);
  assert.deepEqual(Object.keys(SUPPORT_COMMAND_GUIDES).sort(), labels.sort());
  for (const label of labels) {
    const guide = SUPPORT_COMMAND_GUIDES[label];
    for (const key of ['purpose', 'when', 'output', 'caution']) {
      assert.equal(typeof guide[key], 'string', `${label}: missing ${key}`);
      assert.ok(guide[key].trim().length >= 55, `${label}: ${key} must be genuinely explanatory`);
    }
    assert.ok(['read', 'stage', 'switch'].includes(guide.risk), `${label}: missing safety category`);
    assert.ok(SUPPORT_RISK_LABELS[guide.risk]);
  }
});

test('WiFi profile creation and network switching are clearly separate and visibly warned', () => {
  assert.equal(SUPPORT_COMMAND_GUIDES['WiFi / NetworkManager diagnose'].risk, 'read');
  assert.equal(SUPPORT_COMMAND_GUIDES['WiFi udfald og recovery'].risk, 'read');
  assert.equal(SUPPORT_COMMAND_GUIDES['Tilføj WiFi-profil (uden aktivering)'].risk, 'stage');
  assert.equal(SUPPORT_COMMAND_GUIDES['Test gemt WiFi (auto-rollback)'].risk, 'switch');
  assert.match(SUPPORT_COMMAND_GUIDES['Test gemt WiFi (auto-rollback)'].caution, /KAN AFBRYDE/);
  assert.match(SUPPORT_COMMAND_GUIDES['Tilføj WiFi-profil (uden aktivering)'].output, /AUTOCONNECT=no/);
  assert.match(SUPPORT_COMMAND_GUIDES['Test gemt WiFi (auto-rollback)'].output, /\bTEST\b.*\bYes\b/);
  assert.match(component, /Hvornår skal jeg bruge denne\?/);
  assert.match(component, /guide\?\.purpose \|\| item\.description/);
  assert.match(component, /VIGTIG ADVARSEL/);
});

test('browser refresh and its cookie-dialog diagnosis have contextual guidance', () => {
  assert.match(SUPPORT_COMMAND_GUIDES['Display / kiosk browser'].when, /cookie-dialog/);
  assert.match(SUPPORT_COMMAND_GUIDES['Display/browser logs'].when, /refresh-timeren/);
});
