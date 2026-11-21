import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import {validateStagedPilotCandidate} from "../src/pages/adminpages/clientflowReleasePlan.mjs";

const exact = Object.freeze({
  schema_version: 1, phase: "approved_github_archive_source_staged_only",
  release_id: "clientflow-1.3.47-seq-1248", version: "1.3.47", sequence: 1248,
  source_commit: "c0d5a092efe0c4e8638866ad98621481d6f5d0e8",
  approved_bundle_sha256: "9ca8852ba29153f2ec40b58d18007c738a03f9569f14762486fc1953c59eb6ff",
  approved_bundle_size: 223692800,
  approval_reference: "CF-1.3.47-1248-20261121-c0d5a092-f8240014",
  active_release_id: "clientflow-1.3.44-seq-1245", pilot_client_id: 3,
  github_artifact_approval_pinned: true,
  render_store_publication_verified: false, active_catalog_promoted: true,
  physical_pilot_accepted: false, deployment_authorized: false,
  fleet_authorized: false, fresh_install_authorized: false, database_cutover_authorized: false,
});

test("63D21: exact 1248 proof is accepted without inferring deployment permission", () => {
  assert.equal(validateStagedPilotCandidate(exact, exact.active_release_id), exact);
  for (const field of ["source_commit", "approved_bundle_sha256", "approved_bundle_size",
    "approval_reference", "version", "sequence", "pilot_client_id", "active_release_id", "release_id"]) {
    assert.throws(() => validateStagedPilotCandidate({
      ...exact, [field]: field === "approved_bundle_size" ? 1 : "wrong",
    }, exact.active_release_id), field);
  }
  for (const field of ["render_store_publication_verified", "physical_pilot_accepted",
    "deployment_authorized", "fleet_authorized", "fresh_install_authorized",
    "database_cutover_authorized"]) {
    assert.throws(() => validateStagedPilotCandidate({...exact, [field]: true}, exact.active_release_id), field);
  }
  assert.throws(() => validateStagedPilotCandidate({...exact, active_catalog_promoted: "true"}, exact.active_release_id));
  assert.throws(() => validateStagedPilotCandidate({...exact, github_artifact_approval_pinned: false}, exact.active_release_id));
});

test("63D21: 1248 UI is one-client, signed-source and backend authorization only", () => {
  const dir = new URL("../src/pages/adminpages/", import.meta.url);
  const panel = fs.readFileSync(new URL("ClientFlowPilot1248Panel.jsx", dir), "utf8");
  const page = fs.readFileSync(new URL("ClientFlowReleaseAdministration.jsx", dir), "utf8");
  const route = fs.readFileSync(new URL("../../backend/service1/routers/clientflow_release_pilot_63d17.py", import.meta.url), "utf8");
  assert.match(page, /ClientFlowPilot1248Panel status=/);
  assert.match(panel, /release-pilot-1248\/authorize/);
  assert.match(panel, /new Set\(\["1\.3\.46"\]\)/);
  assert.match(panel, /candidate\?\.release_id !== RELEASE_ID/);
  assert.match(panel, /candidate\.pilot_client_id === 3/);
  assert.match(panel, /device\?\.name === "Viborg1"/);
  assert.match(panel, /confirmed_single_pilot: true/);
  assert.match(panel, /expected_current_version: device\.reported_version/);
  assert.match(panel, /expected_policy_revision: status\.revision/);
  assert.match(panel, /Genbekræft superadministratorens adgangskode/);
  assert.match(panel, /starter IKKE updater-servicen/);
  assert.ok(panel.includes('setPassword("");'));
  assert.match(panel, /alreadyKnown/);
  assert.doesNotMatch(panel, /setInterval|setTimeout|useEffect\(|systemctl/);
  assert.match(route, /_reauth\(request, session, user, body\.password\)/);
  assert.match(route, /lock_system_client\(session, 3\)/);
  assert.match(route, /require_database_pilot_1248\(/);
  assert.match(route, /create_authorized_deployment\(/);
  assert.match(route, /allow_downgrade=False/);
  assert.match(route, /prior is not None/);
});
