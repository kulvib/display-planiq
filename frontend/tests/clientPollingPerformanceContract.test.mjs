import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const read = (path) => fs.readFileSync(new URL(path, import.meta.url), "utf8");
const details = read("../src/pages/clientdetailspage/ClientDetailsPage.jsx");
const actions = read("../src/pages/clientdetailspage/ClientDetailsActionsSection.jsx");
const info = read("../src/pages/clientdetailspage/ClientDetailsInfoSection.jsx");

test("detail hot poll transports canonical presence without a second presence interval", () => {
  assert.match(details, /data\?\.presence/);
  assert.doesNotMatch(details, /getClientPresence\(/);
  assert.doesNotMatch(details, /setInterval\(refreshPresence/);
  assert.match(details, /presenceFetchFailed/);
});

test("ClientFlow deployment state has one parent-owned database poll", () => {
  assert.equal((details.match(/getClientflowDeployments\(client\.id, \{ limit: 1, signal: request.signal \}\)/g) || []).length, 1);
  assert.match(details, /request.signal.aborted \|\| deploymentRefreshInFlightRef.current !== request/);
  assert.match(details, /deploymentRefreshInFlightRef.current\?\.abort\(\)/);
  assert.match(details, /deploymentRefreshInFlightRef\.current/);
  assert.equal((details.match(/clientflowDeploymentActive \? CLIENTFLOW_DEPLOYMENT_POLL_MS : 60_000/g) || []).length, 1);
  assert.match(details, /window\.setInterval\(\(\) => \{\s*if \(isPageVisible\(\)\) void refreshClientflowDeployment\(\);\s*\}, clientflowDeploymentActive \? CLIENTFLOW_DEPLOYMENT_POLL_MS : 60_000\)/);
  assert.match(details, /CLIENTFLOW_DEPLOYMENT_POLL_MS = 2500/);
  assert.match(details, /createReleaseAdministrationRealtimeCapability\(signal\)/);
  assert.match(details, /CLIENTFLOW_DEPLOYMENT_ACTIVE_STATES\.has\(clientflowDeploymentState\)/);
  assert.doesNotMatch(actions, /getActiveClientflowDeployment|refreshDeployment|setInterval\([^)]*Deployment/);
  assert.doesNotMatch(info, /getClientflowDeployments|pollDeployment/);
  assert.match(info, /deployment=\{clientflowDeployment\}/);
});

test("Ubuntu and local-management lifecycle reuse the shared chrome-status hot read", () => {
  assert.doesNotMatch(info, /UBUNTU_POLL_MS|pollUbuntuUpdate|pollLocalManagement/);
  assert.match(info, /parent \/chrome-status hot poll already carries every Ubuntu field/);
  assert.match(info, /Local-management lifecycle now arrives on the shared \/chrome-status hot/);
  assert.match(details, /"local_management_status"/);
  assert.match(details, /"local_management_finished_at"/);
  assert.match(info, /onStarted\?\.\(\{ optimistic: true \}\)/);
});
