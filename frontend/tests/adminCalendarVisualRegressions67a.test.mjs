import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (relative) => readFileSync(new URL(`../src/${relative}`, import.meta.url), 'utf8');
const calendar = read('pages/calendarpage/CalendarPage.jsx');
const incidents = read('pages/adminpages/OperationalIncidents.jsx');
const maintenance = read('pages/adminpages/MaintenanceAdministration.jsx');
const access = read('pages/adminpages/UserAdministration.jsx');
const admin = read('pages/adminpages/AdminPage.jsx');
const boundary = read('pages/adminpages/AccessErrorBoundary.jsx');
const button = read('components/AdminRefreshButton.jsx');

// Source-contract assertions complement, not replace, executable MUI/browser tests in CI.
test('calendar selector keeps native checkbox in selected rounded row (no negative edge margin)', () => {
  const clientBlock = calendar.slice(calendar.indexOf('const ClientSelectorInline ='), calendar.indexOf('function markedDaysReducer'));
  assert.match(clientBlock, /component="label"/);
  assert.match(clientBlock, /htmlFor=\{`calendar-client-\$\{client\.id\}`\}/);
  assert.match(clientBlock, /<Checkbox[\s\S]*?id=\{`calendar-client-\$\{client\.id\}`\}/);
  assert.doesNotMatch(clientBlock, /edge="start"/);
  assert.match(clientBlock, /sx=\{\{ p: 0, mr: 1, ml: 0, flex: "0 0 auto" \}\}/);
  assert.match(clientBlock, /"&:focus-within"/);
  assert.match(clientBlock, /event\.target\.checked/);
  assert.match(clientBlock, /selected\.filter\(\(sid\) => sid !== client\.id\)/);
  assert.doesNotMatch(clientBlock, /tabIndex=\{-1\}/);
});

test('calendar selector avoids ultra-narrow five-column cards and text overflow', () => {
  assert.match(calendar, /md: "repeat\(3, minmax\(0, 1fr\)\)"/);
  assert.match(calendar, /xl: "repeat\(5, minmax\(0, 1fr\)\)"/);
  assert.match(calendar, /component="label"[\s\S]*?width: "100%"[\s\S]*?minWidth: 0,[\s\S]*?overflow: "hidden"/);
  assert.match(calendar, /<Box sx=\{\{ minWidth: 0, flex: "1 1 auto" \}\}>/);
  assert.match(calendar, /const handleToggleAll = \(\) =>/);
  assert.match(calendar, /if \(allMarked\)[\s\S]*?onChange\(selected\.filter/);
});

test('operations and maintenance refresh share Audit-log aligned header treatment', () => {
  assert.match(button, /variant="contained"/);
  for (const page of [incidents, maintenance]) {
    assert.match(page, /display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 2, flexWrap: "wrap"/);
    assert.equal((page.match(/<AdminRefreshButton\b/g) || []).length, 1);
    assert.match(page, /<AdminRefreshButton/);
  }
  assert.match(incidents, /onClick=\{reload\}/);
  assert.match(incidents, /loading=\{loading\}/);
  assert.match(maintenance, /onClick=\{\(\) => void load\(\)\}/);
  assert.match(maintenance, /disabled=\{saving\}/);
  assert.match(maintenance, /<Paper elevation=\{0\} sx=\{\{ p: \{ xs: 1\.5, md: 2 \}/);
});

test('Brugeradministration remains reachable for superadmin and API errors remain actionable', () => {
  assert.match(admin, /key: "access",\s*label: "Brugeradministration"/);
  assert.match(admin, /activeSection === "access"[\s\S]*?<AccessErrorBoundary>[\s\S]*?<UserAdministration/);
  assert.match(access, /const isSuperadmin = Boolean\(auth\?\.isSuperadmin/);
  assert.match(access, /if \(!isAdmin && !isSuperadmin\)/);
  assert.match(access, /\{userError && \([\s\S]*?role="alert"[\s\S]*?Brugerlisten kunne ikke hentes:/);
  assert.match(access, /onClick=\{\(\) => void loadData\(\)\}/);
  assert.match(boundary, /getDerivedStateFromError/);
  assert.match(boundary, /Prøv igen/);
  // No client-side backdoor or bypass of authenticated backend CRUD.
  assert.doesNotMatch(access, /localStorage\.setItem\([^)]*role/);
  assert.doesNotMatch(boundary, /fetch\(|api\/users|Authorization/);
});
