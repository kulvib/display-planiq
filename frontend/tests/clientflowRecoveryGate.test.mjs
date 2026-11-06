import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';
import { test } from 'node:test';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const api = readFileSync(resolve(root, 'src/api/api.js'), 'utf8');
const ui = readFileSync(resolve(root, 'src/pages/clientdetailspage/ClientDetailsInfoSection.jsx'), 'utf8');

test('recovery acknowledgement is a separate authenticated superadmin API action', () => {
  assert.match(api, /export async function getClientflowRecoveryGate\(/);
  assert.match(api, /export async function acknowledgeClientflowRecovery\(/);
  assert.match(api, /confirmed_local_recovery:\s*true/);
  assert.match(api, /acknowledge-recovery/);
  assert.match(api, /headers: authHeaders\(\{ "Content-Type": "application\/json" \}\)/);
});

test('ClientFlow UI fails closed while recovery state is unknown or unresolved', () => {
  assert.match(ui, /recoveryGateLoading \|\| !!recoveryGateError \|\| recoveryGate\?\.blocked !== false/);
  assert.match(ui, /recoveryGate\?\.blocked/);
  assert.match(ui, /recoveryConfirmed/);
  assert.match(ui, /recoveryReason\.trim\(\)\.length < 12/);
  assert.match(ui, /activation_intent=None/);
  assert.match(ui, /NeedDaemonReload=no/);
  assert.match(ui, /Kvittér verificeret recovery/);
});
