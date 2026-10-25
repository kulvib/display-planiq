import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const button = read('src/components/AdminRefreshButton.jsx');

const pages = [
  ['Audit-log', 'adminpages/AuditLog.jsx', /onClick=\{\(\) => setRefreshTick/, /loading=\{loading\}/],
  ['Organisation', 'adminpages/OrganizationAdministration.jsx', /onClick=\{fetchOrganizations\}/, /loading=\{loading\}/],
  ['Adgang', 'adminpages/UserAdministration.jsx', /onClick=\{\(\) => void loadData\(\)\}/, /loading=\{userLoading\}/],
  ['Driftsfejl', 'adminpages/OperationalIncidents.jsx', /onClick=\{reload\}/, /loading=\{loading\}/],
  ['Installation', 'adminpages/EnrollmentTokensPage.jsx', /onClick=\{loadTokens\}/, /loading=\{loading\}/],
  ['Livestreams', 'adminpages/LivestreamOverview.jsx', /onClick=\{\(\) => void load\(\)\}/, /loading=\{loading\}/],
  ['Vedligeholdelse', 'adminpages/MaintenanceAdministration.jsx', /onClick=\{\(\) => void load\(\)\}/, /loading=\{loading\}/],
  ['Control Room / Client List', 'ClientInfoPage.jsx', /onClick=\{handleRefresh\}/, /loading=\{refreshing\}/],
  ['Kalender', 'calendarpage/CalendarPage.jsx', /onClick=\{\(\) => fetchClients\(true\)\}/, /loading=\{loadingClients\}/],
];

test('The Audit-log refresh appearance is centralized and preserves its contained loading-safe action', () => {
  assert.match(button, /variant="contained"/);
  assert.match(button, /startIcon=\{<RefreshIcon \/>\}/);
  assert.match(button, /loading=\{loading\}/);
  assert.match(button, /loadingPosition="start"/);
  assert.match(button, /onClick=\{onClick\}/);
  assert.match(button, /disabled=\{disabled \|\| loading\}/);
  assert.match(button, /aria-label=\{ariaLabel\}/);
  assert.match(button, />\s*Opdater\s*<\/Button>/);
});

for (const [label, relative, action, state] of pages) {
  test(`${label}: one manual refresh in its page heading, wired to the existing fetch and loading state`, () => {
    const source = read(`src/pages/${relative}`);
    assert.match(source, /import AdminRefreshButton from/);
    assert.equal((source.match(/<AdminRefreshButton\b/g) || []).length, 1);
    const refreshTag = source.match(/<AdminRefreshButton\b[\s\S]*?\/>/);
    assert.ok(refreshTag, 'refresh action must render');
    assert.match(refreshTag[0], action);
    assert.match(refreshTag[0], state);
    assert.match(refreshTag[0], /ariaLabel="Opdater/);
    assert.doesNotMatch(source, /<Chip\s+label="Opdater"/);
  });
}

test('Refresh controls sit to the right of their headings, not in content or destructive actions', () => {
  const audit = read('src/pages/adminpages/AuditLog.jsx');
  const clientList = read('src/pages/ClientInfoPage.jsx');
  const access = read('src/pages/adminpages/UserAdministration.jsx');
  const maintenance = read('src/pages/adminpages/MaintenanceAdministration.jsx');
  const organization = read('src/pages/adminpages/OrganizationAdministration.jsx');
  const incidents = read('src/pages/adminpages/OperationalIncidents.jsx');
  const installation = read('src/pages/adminpages/EnrollmentTokensPage.jsx');
  const overview = read('src/pages/adminpages/LivestreamOverview.jsx');
  const calendar = read('src/pages/calendarpage/CalendarPage.jsx');
  assert.ok(audit.indexOf('Audit-log\n') < audit.indexOf('<AdminRefreshButton'));
  assert.ok(organization.indexOf('Organisationsadministration') < organization.indexOf('<AdminRefreshButton'));
  assert.ok(incidents.indexOf('Driftsfejl og genopretning') < incidents.indexOf('<AdminRefreshButton'));
  assert.ok(installation.indexOf('Installationskoder</Typography>') < installation.indexOf('<AdminRefreshButton'));
  assert.ok(overview.indexOf('Livestream oversigt') < overview.indexOf('<AdminRefreshButton'));
  assert.ok(access.indexOf('Brugeradministration</Typography>') < access.indexOf('<AdminRefreshButton'));
  assert.ok(maintenance.indexOf('Vedligeholdelse</Typography>') < maintenance.indexOf('<AdminRefreshButton'));
  assert.ok(clientList.indexOf('Control Room\n') < clientList.indexOf('<AdminRefreshButton'));
  assert.ok(calendar.indexOf('Kalender\n') < calendar.indexOf('<AdminRefreshButton'));
  assert.match(calendar, /alignItems: \{ xs: "stretch", md: "flex-start" \}/);
  assert.match(maintenance, /disabled=\{saving\} ariaLabel="Opdater vedligeholdelsesstatus"/);
  assert.match(clientList, /disabled=\{savingSort\}/);
  assert.doesNotMatch(maintenance, /<Button[^>]*>Genindlæs status<\/Button>/);
});

test('The client list manual refresh continues loading all three existing data groups', () => {
  const source = read('src/pages/ClientInfoPage.jsx');
  assert.match(source, /const handleRefresh = useCallback\(async \(\) => \{/);
  assert.match(source, /fetchClients\(true, true, false\)/);
  assert.match(source, /fetchDeletedClients\(false, false\)/);
  assert.match(source, /fetchOrganizations\(\)/);
  assert.match(source, /showSnackbar\("Siden er opdateret\."/);
});


test('Calendar refresh keeps the original approved-client-only fetch, without reloading or saving marked dates', () => {
  const source = read('src/pages/calendarpage/CalendarPage.jsx');
  assert.match(source, /<Tooltip title="Opdater klienter">[\s\S]*?<AdminRefreshButton[\s\S]*?onClick=\{\(\) => fetchClients\(true\)\}[\s\S]*?loading=\{loadingClients\}[\s\S]*?ariaLabel="Opdater kalenderens klienter"/);
  assert.match(source, /const fetchClients = useCallback\(/);
  assert.match(source, /const data = await getClients\(token\)/);
  assert.match(source, /getMarkedDays\(selectedSeason, activeClient\)/);
  assert.doesNotMatch(source, /import RefreshIcon from/);
  assert.equal((source.match(/<AdminRefreshButton\b/g) || []).length, 1);
});

test('Panel and editable-field corners follow Client List, preserving intentional day circles', () => {
  const theme = read('src/theme.js');
  const clientList = read('src/pages/ClientInfoPage.jsx');
  const calendar = read('src/pages/calendarpage/CalendarPage.jsx');
  const livestream = read('src/pages/adminpages/LivestreamOverview.jsx');
  const users = read('src/pages/adminpages/UserAdministration.jsx');
  const layout = read('src/utils/layoutStyles.js');

  assert.match(theme, /MuiOutlinedInput:[\s\S]*?root: \{\s*borderRadius: 10,/);
  assert.match(clientList, /<Paper sx=\{\{ p: 1\.5, mb: 2, borderRadius: 2,/);
  assert.match(layout, /darkPagePanelSx = \{\s*borderRadius: 2,/);
  assert.match(calendar, /<Card\s+sx=\{\{\s*borderRadius: 2,/);
  assert.match(calendar, /borderRadius: "50%"/); // calendar date circles must stay circles
  assert.equal((livestream.match(/borderRadius: 2,/g) || []).length, 3);
  assert.doesNotMatch(livestream, /borderRadius: 2\.5/);
  assert.match(users, /const editableInlineFieldSx = \{[\s\S]*?borderRadius: 1,/);
  assert.match(users, /const userListPanelSx = \{[\s\S]*?borderRadius: 2,/);
});
