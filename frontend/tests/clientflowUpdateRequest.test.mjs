import assert from "node:assert/strict";
import test from "node:test";
import { buildClientflowUpdateRequest } from "../src/pages/clientdetailspage/clientflowUpdateRequest.mjs";

test("pilot forward update sends exact version, a non-empty audit reason, and no downgrade", () => {
  assert.deepEqual(buildClientflowUpdateRequest({
    targetVersion: " 1.3.39 ", reason: " Viborg1 udviklingstest 1.3.38 → 1.3.39 ",
  }), {
    targetVersion: "1.3.39", confirmDowngrade: false,
    reason: "Viborg1 udviklingstest 1.3.38 → 1.3.39",
  });
});

test("no API request may be constructed without a valid reason and concrete version", () => {
  for (const reason of [undefined, null, "", " ", "  \n ", "x".repeat(501)]) {
    assert.throws(() => buildClientflowUpdateRequest({ targetVersion: "1.3.39", reason }), /begrundelse/);
  }
  for (const targetVersion of [undefined, "", " ", "latest", "LATEST"]) {
    assert.throws(() => buildClientflowUpdateRequest({ targetVersion, reason: "Pilot" }), /målversion/);
  }
  assert.equal(buildClientflowUpdateRequest({
    targetVersion: "1.3.39", reason: "x".repeat(500),
  }).reason.length, 500);
});

test("only explicit boolean true permits downgrade confirmation", () => {
  assert.equal(buildClientflowUpdateRequest({
    targetVersion: "1.3.38", reason: "Godkendt rollback", confirmDowngrade: true,
  }).confirmDowngrade, true);
  for (const confirmDowngrade of [undefined, null, "true", 1, false]) {
    assert.equal(buildClientflowUpdateRequest({
      targetVersion: "1.3.39", reason: "Pilot", confirmDowngrade,
    }).confirmDowngrade, false);
  }
});
