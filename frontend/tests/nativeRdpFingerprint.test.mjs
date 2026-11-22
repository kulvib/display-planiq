import { test } from "node:test";
import assert from "node:assert/strict";
import { normalizeNativeRdpFingerprint } from "../src/pages/clientdetailspage/remotedesktop/nativeRdpFingerprint.js";

test("accepts sha256 hex fingerprints and normalizes to colon separated pairs", () => {
  const raw = "A1".repeat(32);
  assert.equal(normalizeNativeRdpFingerprint(raw), Array(32).fill("a1").join(":"));
  assert.equal(normalizeNativeRdpFingerprint("SHA256=" + raw), Array(32).fill("a1").join(":"));
  assert.equal(normalizeNativeRdpFingerprint(Array(32).fill("A1").join(":")), Array(32).fill("a1").join(":"));
});
test("rejects invalid, overlong or injected certificates", () => {
  for (const value of ["", "ABC", "ZZ".repeat(32), "A1".repeat(32) + "\n/p:steal", "A1".repeat(33), null]) {
    assert.equal(normalizeNativeRdpFingerprint(value), null);
  }
});
