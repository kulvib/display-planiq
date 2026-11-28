import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
const read = path => fs.readFileSync(new URL(path, import.meta.url), "utf8");

test("1252 has a separate explicit one-client review and no ordinary catalog order", () => {
  const panel = read("../src/pages/adminpages/ClientFlowCandidate1252Panel.jsx");
  assert.match(panel, /candidate-1252/);
  assert.match(panel, /expected_source_version:"1\.4\.1"/);
  assert.match(panel, /confirmed_prepared:true,password/);
  assert.match(panel, /status\.revision === 3/);
  assert.match(panel, /status\.client_inventory_complete === true/);
  assert.match(panel, /!priorOrder/);
  assert.doesNotMatch(panel, /setInterval\(/);
  const admin = read("../src/pages/adminpages/ClientFlowReleaseAdministration.jsx");
  assert.match(admin, /<ClientFlowCandidate1252Panel status=\{status\} onAuthorized=\{refresh\}/);
  const control = read("../src/pages/clientdetailspage/ClientDetailsInfoSection.jsx");
  assert.match(control, /1\.4\.2-engangspiloten bestilles kun under Administration/);
  assert.match(control, /deployment\?\.target_release_id === "clientflow-1\.4\.2-seq-1252"/);
});

test("restoration requires local confirmation and reauthentication", () => {
  const panel = read("../src/pages/adminpages/ClientFlow1252RestorationPanel.jsx");
  assert.match(panel, /confirmed_local_recovery:true,password/);
  assert.match(panel, /verify-restoration/);
  assert.match(panel, /NeedDaemonReload=no/);
  assert.match(panel, /operator_attestation !== true/);
  assert.doesNotMatch(panel, /recovery_failed/);
});
