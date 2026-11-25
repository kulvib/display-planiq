import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createLivestreamBrowserTiming, createHlsReserveController, contiguousVideoBuffer, latestManifestSegment, hlsHttpTransportLabel } from "../src/pages/clientdetailspage/livestreamBrowserTiming.mjs";

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

function fakeVideo() {
  const listeners = new Map();
  const video = {
    currentTime: 0, ranges: [], readyState: 2, paused: true, seeking: false, autoplay: true,
    plays: 0, pauses: 0, failPlay: false,
    get buffered() { return { length: this.ranges.length, start: (i) => this.ranges[i][0], end: (i) => this.ranges[i][1] }; },
    addEventListener(event, handler) { listeners.set(event, handler); },
    removeEventListener(event, handler) { if (listeners.get(event) === handler) listeners.delete(event); },
    emit(event) { listeners.get(event)?.(); },
    play() {
      this.plays++;
      if (this.failPlay) return Promise.reject(Object.assign(new Error("blocked"), { name: "NotAllowedError" }));
      this.paused = false;
      return Promise.resolve();
    },
    pause() { this.paused = true; this.pauses++; },
  };
  return video;
}

test("63D-73A requires two contiguous segment durations, not manifest entries or disjoint ranges", async () => {
  const video = fakeVideo();
  let ready = 0;
  const gate = createHlsReserveController(video, { onReady: () => ready++ });
  assert.equal(video.autoplay, false);
  video.ranges = [[0, 2], [3, 8]];
  assert.equal(contiguousVideoBuffer(video).ahead, 2);
  assert.equal(gate.pump(), false);
  assert.equal(video.plays, 0);
  video.ranges = [[0, 4]];
  assert.equal(gate.pump(), true);
  assert.equal(gate.pump(), false);
  await Promise.resolve();
  assert.equal(ready, 1);
  assert.equal(video.plays, 1);
  assert.equal(gate.snapshot().phase, "playing");
  gate.dispose();
});

test("63D-73A refills after real underrun, adapts and never seeks away the reserve", async () => {
  const video = fakeVideo();
  let clock = 0;
  const gate = createHlsReserveController(video, { now: () => clock });
  video.ranges = [[0, 6]];
  gate.pump();
  await Promise.resolve();
  video.currentTime = 5.8;
  video.emit("waiting");
  assert.equal(video.paused, true);
  assert.equal(gate.snapshot().requiredSeconds, 5);
  assert.equal(gate.snapshot().refills, 1);
  assert.equal(gate.pump(), false);
  video.ranges = [[0, 11]];
  video.emit("progress");
  await Promise.resolve();
  assert.equal(video.paused, false);
  assert.equal(gate.catchUp(20), false);
  video.ranges = [[0, 20]];
  assert.equal(gate.catchUp(17), true);
  assert.equal(video.currentTime, 15);
  clock = 31_000;
  video.emit("timeupdate");
  assert.equal(gate.snapshot().requiredSeconds, 4);
  gate.dispose();
  video.emit("waiting");
  assert.equal(gate.snapshot().refills, 1);
});

test("63D-73A preserves user activation and ignores late promises after disposal", async () => {
  const video = fakeVideo();
  const taps = [];
  const gate = createHlsReserveController(video, { onTapRequired: (v) => taps.push(v) });
  gate.setTargetDuration(1);
  video.ranges = [[0, 2]];
  video.failPlay = true;
  gate.pump();
  await Promise.resolve();
  assert.deepEqual(taps, [true]);
  assert.equal(gate.pump(), false);
  video.failPlay = false;
  assert.equal(gate.playFromGesture(), true);
  gate.dispose();
  await Promise.resolve();
  assert.deepEqual(taps, [true]);
});

test("63D-73A both HLS.js views use the reserve and keep native Safari fallback", () => {
  for (const path of ["../src/pages/clientdetailspage/ClientDetailsLivestreamSection.jsx", "../src/pages/adminpages/LivestreamOverview.jsx"]) {
    const source = readFileSync(new URL(path, import.meta.url), "utf8");
    assert.match(source, /createHlsReserveController\(video/);
    assert.match(source, /Hls\.Events\.BUFFER_APPENDED/);
    assert.match(source, /initialLiveManifestSize:/);
    assert.match(source, /maxLiveSyncPlaybackRate: 1,/);
    assert.match(source, /playFromGesture\(\)/);
    assert.match(source, /video\.canPlayType\("application\/vnd\.apple\.mpegurl"\)/);
    assert.doesNotMatch(source, /video\.currentTime = Math\.max\(0, livePos/);
  }
});

test("63D-73C manifest edge and transport are independent of playhead", () => {
  assert.equal(latestManifestSegment({ fragments: [{ sn: 57 }, { sn: 58 }, { sn: 59 }] }), 59);
  assert.equal(latestManifestSegment({ fragments: [] }), null);
  assert.equal(latestManifestSegment({ fragments: [{ sn: "59" }] }), null);
  assert.equal(hlsHttpTransportLabel("https://api.example.test/hls/3/index.m3u8"), "HTTPS");
  assert.equal(hlsHttpTransportLabel("/hls/3/index.m3u8", "http://localhost:8080"), "HTTP");
  assert.equal(hlsHttpTransportLabel("wss://api.example.test/video"), null);
  const source = readFileSync(new URL("../src/pages/clientdetailspage/ClientDetailsLivestreamSection.jsx", import.meta.url), "utf8");
  assert.doesNotMatch(source, /setLastSegNum\(data\.frag\.sn\)/);
  assert.match(source, /setLastSegNum\(published\)/);
  assert.doesNotMatch(source, /segsBehind/);
  assert.match(source, /bufferStats\.aheadSeconds/);
  assert.match(source, /HLS · \$\{mediaTransport\}/);
});

test("63D-73C slows before depletion, counts one waiting episode and measures duration", async () => {
  const video = fakeVideo();
  let clock = 0;
  const observations = [];
  const gate = createHlsReserveController(video, { now: () => clock, onSnapshot: (s) => observations.push(s) });
  video.ranges = [[0, 6]];
  gate.pump();
  await Promise.resolve();
  assert.equal(video.playbackRate, 1);
  video.currentTime = 4;
  clock = 1000;
  video.emit("timeupdate");
  assert.equal(video.playbackRate, 0.95);
  assert.equal(gate.snapshot().stalls, 0);
  video.ranges = [[0, 9]];
  clock = 2000;
  video.emit("timeupdate");
  assert.equal(video.playbackRate, 1);
  video.currentTime = 6;
  clock = 3000;
  video.emit("waiting");
  video.emit("waiting");
  assert.equal(gate.snapshot().stalls, 1);
  clock = 3500;
  video.emit("playing");
  assert.equal(gate.snapshot().stalledSeconds, 0.5);
  video.currentTime = 8.5;
  clock = 4000;
  video.emit("waiting");
  assert.equal(gate.snapshot().stalls, 2);
  assert.equal(gate.snapshot().refills, 1);
  video.ranges = [[0, 14]];
  clock = 5000;
  video.emit("progress");
  await Promise.resolve();
  assert.equal(gate.snapshot().stalledSeconds, 1.5);
  assert.ok(observations.length > 0);
  gate.dispose();
  assert.equal(video.playbackRate, 1);
});
