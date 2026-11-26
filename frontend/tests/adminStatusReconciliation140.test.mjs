import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = path => readFileSync(new URL("../src/" + path, import.meta.url), "utf8");
const maintenance = read("pages/adminpages/MaintenanceAdministration.jsx");
const incidents = read("pages/adminpages/OperationalIncidents.jsx");
const wall = read("pages/adminpages/LivestreamOverview.jsx");
const detail = read("pages/clientdetailspage/ClientDetailsPage.jsx");

test("failed maintenance read invalidates old authorization state", () => {
  assert.match(maintenance, /setState\(null\);[\s\S]*?setPendingEnabled\(null\)/);
  assert.match(maintenance, /if \(state === null \|\| loading \|\| saving\) return/);
});

test("incident and wall status distinguish unavailable from empty and refresh on visibility", () => {
  assert.match(incidents, /!loading && resultVerified && !result.items/);
  assert.match(incidents, /operationsVerified && !visibleOperations\.length/);
  assert.match(incidents, /setOperationsVerified\(false\)/);
  assert.match(incidents, /setOperationsVerified\(true\)/);
  assert.match(incidents, /if \(!Array\.isArray\(data\?\.items\)\)/);
  assert.match(wall, /inventoryValid \? "Ingen godkendte klienter matcher søgningen\." : "Klientoversigten er ikke verificeret\."/);
  assert.match(wall, /inventoryRequest.current\?\.abort\(\)/);
  for (const source of [incidents, wall]) {
    assert.match(source, /document.addEventListener\("visibilitychange", refreshVisible\)/);
    assert.match(source, /document.removeEventListener\("visibilitychange", refreshVisible\)/);
  }
});

test("Control Room consumes release wakeups and reconciles externally ordered updates", () => {
  assert.match(detail, /createReleaseAdministrationRealtimeCapability\(signal\)/);
  assert.match(detail, /requestControlRoomRealtimeWait\(capability, generation, 25, signal\)/);
  assert.match(detail, /clientflowDeploymentActive \? CLIENTFLOW_DEPLOYMENT_POLL_MS : 60_000/);
  assert.match(detail, /request.signal.aborted \|\| deploymentRefreshInFlightRef.current !== request/);
  assert.match(detail, /deploymentRefreshInFlightRef.current\?\.abort\(\)/);
});


test("organization writes require verified organization-season data and a current deletion preview", () => {
  const org = read("pages/adminpages/OrganizationAdministration.jsx");
  assert.match(org, /verifiedSeasonTimes\(timesResult\.value, org\.id, season\)/);
  assert.match(org, /timesScope\.season === selectedSeason/);
  assert.match(org, /if \(!timesVerified \|\| timesLoading \|\| timesBusy/);
  assert.match(org, /verifiedDeleteId !== organizationToDelete\.id/);
  assert.match(org, /request !== deleteRead\.current/);
  assert.match(org, /Klientlisten er ikke verificeret\. Sletning er spærret/);
  assert.match(org, /også i papirkurven/);
});
test("failed administrative reads cannot be presented as empty verified lists", () => {
  const tokens = read("pages/adminpages/EnrollmentTokensPage.jsx");
  const audit = read("pages/adminpages/AuditLog.jsx");
  assert.match(tokens, /setTokensVerified\(false\)/);
  assert.match(tokens, /if \(!Array\.isArray\(data\)\) throw/);
  assert.match(tokens, /\{tokensVerified && <>/);
  assert.match(audit, /if \(controller\.signal\.aborted\) return/);
  assert.match(audit, /!loading && !error && visibleLogs\.length === 0/);
  assert.match(incidents, /!Number\.isSafeInteger\(data\.total\)/);
});
