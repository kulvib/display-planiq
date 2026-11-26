import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import {
  MAX_PLAN_CLIENTS, planVersionGroups, preparePlan, validateReleasePlanningResponse, validatePlanningPreview, validateReleaseReadiness, summarizeReleaseFleet, fleetVersionStatus,
} from "../src/pages/adminpages/clientflowReleasePlan.mjs";

const body = {
  phase: "additive_draft_only", authorization_active: false, planning_review_available: true,
  fresh_install_open: false, fleet_open: false, cutover_enabled: false, physical_pilot_accepted: false,
  client_inventory_complete: true, revision: 1, stable_release_id: "clientflow-1.3.44-seq-1245",
  release_readiness: {
    schema_version: 1, release_id: "clientflow-1.3.44-seq-1245", policy_revision: 1,
    deployment_authorized: false, automatic_rollout_authorized: false,
    ready_for_fleet: false, ready_for_fresh_install: false,
    checks: ["stable_catalog_binding", "physical_pilot", "database_cutover", "fleet",
      "fresh_install", "reproducible_candidate", "physical_recovery"].map(
      (id, index) => index === 0
        ? ({id, ready: true, reason: null})
        : ({id, ready: false, reason: "Kræver særskilt verificering"})),
  },
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


test("62A preview fails closed on mismatched clients or imaginary rollout permissions", () => {
  const clean = {
    planning_eligible: true, deployment_authorized: false,
    release_approved_for_deployment: false, client_ids: [3, 4],
    source_version: "1.3.43", target_release_id: body.stable_release_id,
    policy_revision: body.revision, kind: "controlled",
  };
  assert.deepEqual(validatePlanningPreview(clean, [4, 3], "1.3.43", body.stable_release_id, 1), clean);
  for (const changes of [
    {deployment_authorized: true}, {release_approved_for_deployment: true},
    {planning_eligible: false}, {client_ids: [3, 5]},
    {policy_revision: 2}, {kind: "pilot"},
    {target_release_id: "clientflow-1.3.45-seq-1246"},
  ]) assert.throws(() => validatePlanningPreview({...clean, ...changes}, [3,4], "1.3.43", body.stable_release_id, 1));
  const source = fs.readFileSync(new URL("../src/pages/adminpages/ClientFlowReleaseAdministration.jsx", import.meta.url), "utf8");
  assert.match(source, /client\.post\(`\$\{RELEASE_PATH\}\/preview`/);
  assert.match(source, /ml: "auto", flexShrink: 0/);
  assert.match(source, /AdminRefreshButton/);
});


test("63D readiness gate cannot be converted into implicit deployment permission", () => {
  const known = clone();
  assert.equal(validateReleaseReadiness(known.release_readiness, known.stable_release_id, 1).deployment_authorized, false);
  for (const mutation of [
    {deployment_authorized: true}, {automatic_rollout_authorized: true},
    {ready_for_fleet: true}, {ready_for_fresh_install: true},
    {policy_revision: 2}, {checks: []},
    {checks: known.release_readiness.checks.map((row, index) => index === 0 ? {...row, ready: false} : row)},
    {checks: known.release_readiness.checks.map((row, index) => index === 1 ? {...row, reason: ""} : row)},
  ]) {
    const value = {...known.release_readiness, ...mutation};
    assert.throws(() => validateReleaseReadiness(value, known.stable_release_id, 1));
    assert.throws(() => validateReleasePlanningResponse(clone({release_readiness: value})));
  }
  assert.match(fs.readFileSync(new URL("../src/pages/adminpages/ClientFlowReleaseAdministration.jsx", import.meta.url), "utf8"),
    /Release readiness – obligatoriske gates/);
});


test("release administration automatically reconciles actual events without interval polling", () => {
  const ui = fs.readFileSync(new URL("../src/pages/adminpages/ClientFlowReleaseAdministration.jsx", import.meta.url), "utf8");
  assert.match(ui, /createReleaseAdministrationRealtimeCapability\(signal\)/);
  assert.match(ui, /waitForControlRoomRealtime\(capability, generation, 25, signal\)/);
  assert.match(ui, /createRealtimeRequestScope\(getAuthSessionSignal\(\)\)/);
  assert.match(ui, /if \(submitting \|\| intent\)/);
  assert.match(ui, /document\.visibilityState === "hidden"/);
  assert.match(ui, /Automatisk status aktiv/);
  assert.doesNotMatch(ui, /setInterval\(|Brug Opdater øverst/);
});


test("1248 exact source-only pilot summary can be displayed but cannot authorize installation", () => {
  const candidate = {
    schema_version: 1, phase: "approved_github_archive_source_staged_only",
    release_id: "clientflow-1.3.47-seq-1248", version: "1.3.47", sequence: 1248,
    source_commit: "c0d5a092efe0c4e8638866ad98621481d6f5d0e8",
    approved_bundle_sha256: "9ca8852ba29153f2ec40b58d18007c738a03f9569f14762486fc1953c59eb6ff",
    approved_bundle_size: 223692800, approval_reference: "CF-1.3.47-1248-20261121-c0d5a092-f8240014",
    active_release_id: body.stable_release_id, pilot_client_id: 3,
    github_artifact_approval_pinned: true, active_catalog_promoted: true,
    render_store_publication_verified: false, physical_pilot_accepted: false,
    deployment_authorized: false, fleet_authorized: false, fresh_install_authorized: false,
    database_cutover_authorized: false,
  };
  assert.equal(validateReleasePlanningResponse(clone({staged_pilot_candidate: candidate})).staged_pilot_candidate.release_id, candidate.release_id);
  for (const mutation of [{deployment_authorized: true}, {approved_bundle_sha256: "0".repeat(64)}, {pilot_client_id: 4}]) {
    assert.throws(() => validateReleasePlanningResponse(clone({staged_pilot_candidate: {...candidate, ...mutation}})));
  }
});

test("active deployments are validated independently of historical rows", () => {
  const row = {id:"07aba6a1-9454-4563-8ae3-4dd05c3d6bd4", client_id:3,
    target_version:"1.3.47", target_release_id:"clientflow-1.3.47-seq-1248",
    state:"downloading", requested_at:"2026-11-18T21:10:19Z", state_updated_at:"2026-11-18T21:10:19Z", completed_at:null};
  assert.equal(validateReleasePlanningResponse(clone({active_deployments:[row], active_deployments_complete:true})).active_deployments.length, 1);
  assert.throws(() => validateReleasePlanningResponse(clone({active_deployments:[row]})));
  assert.throws(() => validateReleasePlanningResponse(clone({active_deployments:[row,{...row,id:"17aba6a1-9454-4563-8ae3-4dd05c3d6bd4"}],active_deployments_complete:true})));
  assert.throws(() => validateReleasePlanningResponse(clone({active_deployments:[{...row,state:"cancelled",completed_at:row.requested_at}],active_deployments_complete:true})));
  const ui = fs.readFileSync(new URL("../src/pages/adminpages/ClientFlowReleaseAdministration.jsx", import.meta.url), "utf8");
  assert.match(ui, /cancelClientflowDeployment\(row\.id/);
  assert.doesNotMatch(ui, /requestClientflowDeployment\(/);
  assert.match(ui, /Tekniske releasedetaljer og historiske pilotplaner/);
  assert.match(ui, /active_deployments_complete === true/);
});


test("fleet distinguishes standard, older, newer and unknown without inferring approval", () => {
  const clients = [...body.available_clients, {id: 7, name:"Newer", reported_version:"1.3.47"}];
  assert.deepEqual(summarizeReleaseFleet(clients, "1.3.44"), {total:5,standard:1,older:2,newer:1,unknown:1});
  assert.equal(fleetVersionStatus(clients[4], "1.3.44"), "newer");
  assert.equal(fleetVersionStatus(clients[0], ""), "unknown");
});


test("1250 pilot uses explicit review and reauthentication, not the legacy plan", () => {
  const ui = fs.readFileSync(new URL("../src/pages/adminpages/ClientFlowReleaseAdministration.jsx", import.meta.url), "utf8");
  const panel = fs.readFileSync(new URL("../src/pages/adminpages/ClientFlowBaselinePilotPanel.jsx", import.meta.url), "utf8");
  assert.match(ui, /<ClientFlowBaselinePilotPanel status=\{status\} onAuthorized=\{refresh\}/);
  assert.match(panel, /client\.get\(PATH \+ "\/availability"/);
  assert.match(panel, /client\.post\(PATH \+ "\/authorize", body/);
  assert.match(panel, /confirmed_prepared:true,password/);
  assert.match(panel, /expected_bundle_sha256:authority\.bundle_sha256/);
  assert.match(panel, /status\.fleet_open === false/);
  assert.match(panel, /authority\.revision !== status\.revision/);
  assert.doesNotMatch(panel, /setInterval\(/);
});


test("daily release view keeps live status, compact recent history and the explicit pre-cutover distinction", () => {
  const ui = fs.readFileSync(new URL("../src/pages/adminpages/ClientFlowReleaseAdministration.jsx", import.meta.url), "utf8");
  const history = fs.readFileSync(new URL("../src/pages/adminpages/ClientFlowDeploymentHistory.jsx", import.meta.url), "utf8");
  assert.match(ui, /baselineInstalled && <Alert/);
  assert.match(ui, /status\.stable_version\}, indtil den særskilte releasegodkendelse/);
  assert.match(ui, /recentRows\.slice\(0, historyVisibleCount\)\} compact/);
  assert.match(ui, /recentProblems > 0/);
  assert.match(history, /compact && state\.terminal/);
  assert.match(history, /state\.color === "error"/);
  assert.match(history, /component="details"/);
  assert.match(history, /CANCELLABLE_STATES\.has\(item\.state\)/);
});
