import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import {
  createRealtimeRequestScope,
  realtimeRetryDelayMs,
  REALTIME_RETRY_MAX_MS,
  waitForRealtimeRetry,
} from "../src/utils/controlRoomRealtimeLifecycle.mjs";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (file) => fs.readFileSync(path.join(frontendRoot, file), "utf8");

test("retries back off, honor Retry-After, and never exceed the cap", () => {
  assert.equal(realtimeRetryDelayMs(1), 2000);
  assert.equal(realtimeRetryDelayMs(2), 4000);
  assert.equal(realtimeRetryDelayMs(3), 8000);
  assert.equal(realtimeRetryDelayMs(50), REALTIME_RETRY_MAX_MS);
  assert.equal(realtimeRetryDelayMs(1, { status: 429, retryAfterSeconds: 25 }), 25000);
  assert.equal(realtimeRetryDelayMs(5, { retryAfterSeconds: 3600 }), REALTIME_RETRY_MAX_MS);
});

test("a queued retry resolves immediately when the route or session is aborted", async () => {
  const authController = new AbortController();
  const scope = createRealtimeRequestScope(authController.signal);
  const sleeper = waitForRealtimeRetry(REALTIME_RETRY_MAX_MS, scope.signal);
  authController.abort();
  assert.equal(await sleeper, false);
  assert.equal(scope.signal.aborted, true);
  scope.cancel();
});

test("both pages preserve the 25s capability contract and bind all transport calls to one abortable session scope", () => {
  for (const page of ["src/pages/ClientInfoPage.jsx", "src/pages/clientdetailspage/ClientDetailsPage.jsx"]) {
    const source = read(page);
    assert.match(source, /createRealtimeRequestScope\(getAuthSessionSignal\(\)\)/);
    assert.match(source, /while \(!signal\.aborted && getAuthToken\(\)\)/);
    assert.match(source, /waitForControlRoomRealtime\(capability, generation, 25\)/);
    assert.match(source, /requestControlRoomRealtimeWait\(capability, generation, timeoutSeconds, scope\.signal\)/);
    assert.match(source, /error\?\.status === 403/);
    assert.match(source, /return \(\) => scope\.cancel\(\)/);
    assert.doesNotMatch(source, /window\.setTimeout\(resolve, 2000\)/);
  }
});
