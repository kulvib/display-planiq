import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { normalizeClientflowReleaseCatalog, selectableClientflowUpdateReleases } from "../src/pages/clientdetailspage/clientflowCatalogOptions.mjs";

const infoSource = fs.readFileSync(
  new URL("../src/pages/clientdetailspage/ClientDetailsInfoSection.jsx", import.meta.url),
  "utf8",
);
const apiSource = fs.readFileSync(new URL("../src/api/api.js", import.meta.url), "utf8");
const auditSource = fs.readFileSync(
  new URL("../src/pages/adminpages/AuditLog.jsx", import.meta.url),
  "utf8",
);

test("Control Room only selects stable or supported ClientFlow releases", () => {
  const optionSource = fs.readFileSync(new URL("../src/pages/clientdetailspage/clientflowCatalogOptions.mjs", import.meta.url), "utf8");
  assert.match(optionSource, /\["stable", "supported"\]/);
  assert.match(optionSource, /release\.update_allowed === true/);
  assert.match(infoSource, /Seneste stabile/);
  assert.match(infoSource, /Bekræft ClientFlow-nedgradering/);
  assert.match(infoSource, /Begrundelse/);
  assert.match(infoSource, /selectedRelease\?\.requires_reboot === true/);
  assert.match(infoSource, /kræver én kontrolleret genstart efter grøn ClientFlow-activation/);
  assert.match(infoSource, /Verificér reconnect efter reboot/);
});

test("ClientFlow update request creates a canonical deployment", () => {
  assert.match(
    apiSource,
    /requestClientflowDeployment[\s\S]*\/api\/clients\/\$\{encodeURIComponent\(clientId\)\}\/clientflow-deployments[\s\S]*headers: authHeaders\(\{ "Content-Type": "application\/json" \}\)/,
  );
  assert.match(apiSource, /target_version: targetVersion/);
  assert.match(apiSource, /targetVersion\.toLowerCase\(\) === "latest"/);
  assert.match(infoSource, /targetVersion: resolvedSelectedVersion/);
  assert.match(apiSource, /confirm_downgrade: options\.confirmDowngrade === true/);
  assert.match(apiSource, /reason: options\.reason \|\| null/);
  assert.match(apiSource, /pre_first_activation_repair: options\.preFirstActivationRepair === true/);
  assert.match(apiSource, /getClientflowDeployments/);
  assert.match(apiSource, /getActiveClientflowDeployment/);
  assert.match(apiSource, /cancelClientflowDeployment/);
  assert.match(apiSource, /\/api\/clientflow\/releases/);
  assert.doesNotMatch(apiSource, /\/api\/clients\/\$\{clientId\}\/clientflow-update/);
});

test("canonical deployment events have Danish audit labels", () => {
  assert.match(auditSource, /clientflow_deployment_authorized/);
  assert.match(auditSource, /ClientFlow-deployment autoriseret/);
  assert.match(auditSource, /clientflow_deployment_cancelled/);
  assert.match(auditSource, /ClientFlow-deployment annulleret/);
  assert.match(auditSource, /ClientFlow-version bestilt \(historisk\)/);
});

test("Control Room always requires an explicit reason before any ClientFlow deployment", () => {
  assert.match(infoSource, /setUpdateReasonDialogOpen\(true\)/);
  assert.match(infoSource, /buildClientflowUpdateRequest\(\{/);
  assert.match(infoSource, /await executeClientFlowUpdate\(\{ confirmDowngrade: isDowngrade, reason \}\)/);
  assert.match(infoSource, /disabled=\{!updateReason\.trim\(\) \|\| starting \|\| inProgress\}/);
  assert.match(infoSource, /Bekræft ClientFlow-opdatering/);
  assert.doesNotMatch(infoSource, /executeClientFlowUpdate\(\);/);
});


test("Control Room actually fetches the protected release catalog and fails closed on errors", () => {
  assert.match(infoSource, /const fetchCatalog = async \(\) => \{/);
  assert.match(infoSource, /normalizeClientflowReleaseCatalog\(await getClientflowReleases\(\)\)/);
  assert.match(infoSource, /if \(!cancelled\) setReleaseCatalog\(catalog\)/);
  assert.match(infoSource, /setReleaseCatalog\(null\)/);
  assert.match(infoSource, /setCatalogError\(err\?\.message/);
  assert.match(infoSource, /return \(\) => \{ cancelled = true; \}/);
  assert.match(infoSource, /\[clientId, catalogRetryKey\]/);
  assert.match(infoSource, /setCatalogRetryKey\(\(previous\) => previous \+ 1\)/);
  assert.match(infoSource, /!releaseCatalog \|\| !selectedRelease/);
});

test("supported 1.3.39 update pilot is selectable while fresh-install-only and blocked versions are not", () => {
  const valid = normalizeClientflowReleaseCatalog({
    latest_stable: "1.3.38",
    releases: [
      { version: "1.3.38", status: "stable", update_allowed: false, install_modes: ["fresh_install"] },
      { version: "1.3.39", status: "supported", update_allowed: true, install_modes: ["in_place_update"], installable: false },
      { version: "1.3.40", status: "blocked", update_allowed: true, install_modes: ["in_place_update"] },
      { version: "1.3.41", status: "supported", update_allowed: true, install_modes: ["fresh_install"] },
      { version: "1.3.42", status: "supported", update_allowed: false, install_modes: ["in_place_update"] },
    ],
  });
  assert.deepEqual(selectableClientflowUpdateReleases(valid).map((release) => release.version), ["1.3.39"]);
  assert.deepEqual(selectableClientflowUpdateReleases(null), []);
  assert.deepEqual(selectableClientflowUpdateReleases({ releases: null }), []);
});

test("malformed or missing release catalog must be rejected, not interpreted as an empty success", () => {
  for (const invalid of [undefined, null, [], {}, { latest_stable: "1.3.38", releases: null },
    { latest_stable: "", releases: [] }]) {
    assert.throws(() => normalizeClientflowReleaseCatalog(invalid), /ugyldigt format/);
  }
});
