import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path) => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');
const admin = read('pages/adminpages/AdminPage.jsx');
const users = read('pages/adminpages/UserAdministration.jsx');
const audit = read('pages/adminpages/AuditLog.jsx');
const boundary = read('pages/adminpages/AccessErrorBoundary.jsx');
const refresh = read('components/AdminRefreshButton.jsx');

test('navigation label is Brugeradministration without changing URL routing or roles', () => {
  assert.match(admin, /key: "access",\s*label: "Brugeradministration"/);
  assert.match(admin, /activeSection === "access"[\s\S]*?<AccessErrorBoundary>[\s\S]*?<UserAdministration/);
  assert.doesNotMatch(admin, /label: "Adgang"/);
  assert.match(boundary, /Brugeradministration kunne ikke vises/);
  assert.match(users, /if \(!isAdmin && !isSuperadmin\)/);
});

test('user refresh matches Audit-log header placement, typography and shared action', () => {
  const auditHeader = audit.slice(audit.indexOf('justifyContent: "space-between", gap: 2, mb: 2'), audit.indexOf('<Alert severity="info"'));
  const header = users.slice(users.indexOf('justifyContent: "space-between", gap: 2, mb: 2'), users.indexOf('<Divider sx={{ my: 2'));
  assert.match(auditHeader, /<AdminRefreshButton/);
  assert.match(header, /flexWrap: "wrap"/);
  assert.match(header, /<PeopleAltIcon color="primary"\s*\/>/);
  assert.match(header, /<Typography variant="h5"/);
  assert.match(header, /<Stack direction="row" spacing=\{1\} useFlexGap/);
  assert.match(header, /flexShrink: 0/);
  assert.match(header, /<AdminRefreshButton onClick=\{\(\) => void loadData\(\)\} loading=\{userLoading\}/);
  assert.match(refresh, /variant="contained"/);
  assert.equal((users.match(/<AdminRefreshButton\b/g) ?? []).length, 1);
});
