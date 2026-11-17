import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import {
  MAX_PLAN_CLIENTS, planVersionGroups, preparePlan, validateReleasePlanningResponse,
} from "../src/pages/adminpages/clientflowReleasePlan.mjs";

const body = {
  phase: "additive_draft_only", authorization_active: false, planning_review_available: true,
  fresh_install_open: false, fleet_open: false, cutover_enabled: false, physical_pilot_accepted: false,
  client_inventory_complete: true, revision: 1, stable_release_id: "clientflow-1.3.44-seq-1245",
  stable_version: "1.3.44", bundle_sha256: "a".repeat(64), waves: [],
  available_releases: [{release_id: "clientflow-1.3.44-seq-1245", version: "1.3.44", status: "stable", bundle_sha256: "a".repeat(64), deployment_authorized: false}],
  available_clients: [
    {id: 3, name: "Viborg1", reported_version: "1.3.43"},
    {id: 4, name: "Viborg2", reported_version: "1.3.43"},
    {id: 5, name: "Ny", reported_version: null},
    {id: 6, name: "Stabil", reported_version: "1.3.44"},
  ],
};
const clone = (changes = {}) => structuredClone({...body, ...changes});

test("only a locked, stable, single-catalog response can enable planning", () => {
  assert.equal(validateReleasePlanningResponse(clone()).stable_version, "1.3.44");
  for (const key of ["authorization_active", "fresh_install_open", "fleet_open", "cutover_enabled", "physical_pilot_accepted"]) {
    const unsafe = clone(); unsafe[key] = true;
    assert.throws(() => validateReleasePlanningResponse(unsafe));
  }
  for (const changed of [
    {client_inventory_complete: false}, {available_clients: null}, {available_releases: []},
    {available_releases: [{...body.available_releases[0], deployment_authorized: true}]},
    {available_releases: [{...body.available_releases[0], version: "1.3.45"}]},
    {waves: [{state: "approved", deployment_authorized: false}]},
    {waves: [{state: "draft", deployment_authorized: true}]},
    {available_clients: [{id: 3, name: "Viborg1", reported_version: "1.3.43"}, {id: 3, name: "Duplicate", reported_version: "1.3.43"}]},
  ]) assert.throws(() => validateReleasePlanningResponse(clone(changed)));
});

test("client versions are sourced from known approved inventory, never typed", () => {
  assert.deepEqual(planVersionGroups([...body.available_clients, {id:7,name:"Newer",reported_version:"1.3.45"}], body.stable_version), [{version: "1.3.43", count: 2}]);
  const pilot = preparePlan(body.available_clients, [3], "1.3.43", "1.3.44", 24);
  assert.equal(pilot.kind, "pilot");
  assert.equal(pilot.source_version, "1.3.43");
  assert.match(pilot.reason, /Ingen installation autoriseret/);
  const wave = preparePlan(body.available_clients, [4,3], "1.3.43", "1.3.44", 72);
  assert.deepEqual(wave.client_ids, [3,4]);
  assert.equal(wave.kind, "controlled");
  assert.throws(() => preparePlan(body.available_clients, [3], "1.3.45", "1.3.44", 24));
  for (const ids of [[], [3,3], [3,5], [3,6], [999], Array.from({length: 26}, (_, i) => i + 100)]) {
    assert.throws(() => preparePlan(body.available_clients, ids, "1.3.43", "1.3.44", 24));
  }
});

test("UX never directly authorizes client deployments; reauth retained; audit reason automatic", () => {
  const ui = fs.readFileSync(new URL("../src/pages/adminpages/ClientFlowReleaseAdministration.jsx", import.meta.url), "utf8");
  assert.match(ui, /Genbekræft din adgangskode/);
  assert.match(ui, /client\.post\(`\$\{RELEASE_PATH\}\/drafts`/);
  assert.match(ui, /expected_revision: status\.revision, password/);
  assert.match(ui, /expected_revision: intent\.wave\.revision, password/);
  assert.doesNotMatch(ui, /clientflow-deployments|\/api\/clientflow\/releases\/.+post/);
  assert.doesNotMatch(ui, /label="Begrundelse"|label="Type"|label="Klient-ID'er/);
  assert.match(ui, /Gennemgå og gem inaktiv plan/);
});
