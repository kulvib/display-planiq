import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createLivestreamBrowserTiming } from "../src/pages/clientdetailspage/livestreamBrowserTiming.mjs";

test("63D-33 HLS live-edge samples are bounded, local and independently labeled", () => {
  const timing = createLivestreamBrowserTiming(3);
  for (const seconds of [1, 3, 5, 7]) assert.equal(timing.observe(seconds), true);
  assert.deepEqual(timing.snapshot(), {
    samples: 3, ignored: 0, p50Seconds: 5, p95Seconds: 7,
  });
  timing.reset();
  assert.deepEqual(timing.snapshot(), {
    samples: 0, ignored: 0, p50Seconds: null, p95Seconds: null,
  });
});

test("63D-33 HLS invalid or extreme latency never contaminates the series", () => {
  const timing = createLivestreamBrowserTiming(3);
  for (const seconds of [NaN, Infinity, -1, 120.01, null]) {
    // null is not accepted as a measurement: callers must explicitly supply hls.latency.
    if (seconds !== null) assert.equal(timing.observe(seconds), false);
  }
  assert.equal(timing.snapshot().ignored, 4);
  assert.equal(timing.observe(0), true);
  assert.equal(timing.observe(8.13), true);
  assert.equal(timing.snapshot().p95Seconds, 8.1);
  for (const limit of [0, -1, 129, 1.5]) {
    assert.throws(() => createLivestreamBrowserTiming(limit), RangeError);
  }
});

test("63D-33 HLS UI separates live-edge player estimate from actual uploader age", () => {
  const source = readFileSync(new URL("../src/pages/clientdetailspage/ClientDetailsLivestreamSection.jsx", import.meta.url), "utf8");
  assert.match(source, /label: "HLS livekant"/);
  assert.match(source, /hlsBrowserTiming\.observe\(measuredLatency\)/);
  assert.match(source, /hlsBrowserTiming\.reset\(\)/);
  assert.match(source, /Browser p50/);
  assert.doesNotMatch(source, /label: "Uploadalder", value: formatLagValue\(lastSegmentLag\)/);
  assert.match(source, /lowLatencyMode: false/); // no LL-HLS claim or transport switch
});
