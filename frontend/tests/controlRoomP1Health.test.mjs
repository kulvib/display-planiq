import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { sameClientHealthIssues } from "../src/utils/clientHealthIssues.mjs";
import { summarizeServiceLevels } from "../src/utils/serviceHealthSummary.mjs";
import { hasActiveLivestreamError } from "../src/utils/livestreamHealth.mjs";

const listSource = readFileSync(new URL("../src/pages/ClientInfoPage.jsx", import.meta.url), "utf8");
const diagnosticsSource = readFileSync(new URL("../src/pages/clientdetailspage/ClientDetailsInfoSection.jsx", import.meta.url), "utf8");

const issue = { code: "kiosk_error", severity: "error", title: "Fejl", message: "Service nede", required_role: "admin", suggested_resolution: "Kontroller service" };

test("Control Room list invalidates when an issue appears, clears or its text/role changes", () => {
  assert.equal(sameClientHealthIssues([], [issue]), false);
  assert.equal(sameClientHealthIssues([issue], []), false);
  assert.equal(sameClientHealthIssues([issue], [{ ...issue, message: "Rettet tekst" }]), false);
  assert.equal(sameClientHealthIssues([issue], [{ ...issue, suggested_resolution: "Ny handling" }]), false);
  assert.equal(sameClientHealthIssues([issue], [{ ...issue, required_role: "superadmin" }]), false);
  assert.equal(sameClientHealthIssues([issue], [{ ...issue }]), true);
  assert.equal(sameClientHealthIssues(undefined, []), true);
  assert.match(listSource, /!sameClientHealthIssues\(ca\.health_issues, cb\.health_issues\)/);
  // Execute the production snapshot comparator, not just the standalone helper.
  const match = listSource.match(/function isClientListEqual\([\s\S]*?\n}\n\n\/\/ -+/);
  assert.ok(match, "Actual Control Room list comparator must remain testable");
  const comparator = runInNewContext(
    `${match[0].replace(/\n\n\/\/ -+[\s\S]*$/, "")}\nisClientListEqual`,
    {
      sameClientHealthIssues,
      getClientOnline: (client) => client?.presence?.is_online,
      getClientOrganizationId: (client) => client?.organization_id,
    },
  );
  const base = { id: 1, health_issues: [issue] };
  assert.equal(comparator([base], [{ ...base }]), true);
  assert.equal(comparator([base], [{ ...base, health_issues: [] }]), false);
  assert.equal(comparator([base], [{ ...base, health_issues: [{ ...issue, message: "Ny fejltekst" }] }]), false);
});

test("Service summary never reports unknown, missing or working statuses as OK", () => {
  assert.deepEqual(summarizeServiceLevels(["ok", "neutral", "info", "warn", "error"]), {
    ok: 1, issues: 2, unverified: 2, total: 5,
  });
  assert.deepEqual(summarizeServiceLevels(["ok", "neutral"]), {
    ok: 1, issues: 0, unverified: 1, total: 2,
  });
  assert.match(diagnosticsSource, /const serviceLevels = serviceRows\.map\(getRowLevel\)/);
  assert.match(diagnosticsSource, /level: serviceSummary\.issues \? "error" : serviceSummary\.unverified \? "neutral" : "ok"/);
  assert.doesNotMatch(diagnosticsSource, /serviceRows\.length - serviceIssues\.length/);
});

test("Historical livestream failure is not an active alarm after verified recovery", () => {
  const error = { livestream_last_error: "old_failure" };
  assert.equal(hasActiveLivestreamError({ ...error, livestream_status: "failed", livestream_process_status: "stopped" }), true);
  assert.equal(hasActiveLivestreamError({ ...error, livestream_status: "starting", livestream_process_status: "running" }), true);
  assert.equal(hasActiveLivestreamError({ ...error, livestream_status: "running", livestream_process_status: "stopped" }), true);
  assert.equal(hasActiveLivestreamError({ ...error, livestream_status: "running", livestream_process_status: "running" }), false);
  assert.equal(hasActiveLivestreamError({ livestream_last_error: null, livestream_status: "failed" }), false);
  assert.match(diagnosticsSource, /hasActiveLivestreamError\(client\)/);
  assert.match(diagnosticsSource, /Seneste livestream-fejl \(historik\)/);
});
