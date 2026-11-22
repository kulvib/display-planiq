import assert from "node:assert/strict";
import test from "node:test";
import { createRemoteDesktopTiming } from "../src/pages/clientdetailspage/remotedesktop/remoteDesktopTiming.mjs";
import { createLatestRemoteFramePainter } from "../src/pages/clientdetailspage/remotedesktop/latestRemoteFramePainter.mjs";

test("63D-33 captures browser-only receive-to-img.load and RAF-to-img.load durations", () => {
  let t = 0;
  const meter = createRemoteDesktopTiming({ now: () => t, sampleLimit: 4 });
  const raf = [];
  const image = { src: "" };
  const painter = createLatestRemoteFramePainter({
    requestFrame: (cb) => { raf.push(cb); return raf.length; },
    cancelFrame: () => {},
    getImage: () => image,
    now: () => t,
    onFrameAssigned: (m) => meter.frameAssigned(m),
  });
  const receivedAt = meter.frameReceived();
  painter.push("a", { receivedAt });
  t = 6;
  assert.equal(meter.snapshot().assigned, 0);
  raf.shift()();
  assert.equal(image.src, "data:image/jpeg;base64,a");
  t = 10;
  assert.equal(meter.imageLoaded(), true);
  assert.equal(meter.imageLoaded(), false);
  assert.deepEqual(meter.snapshot(), {
    received: 1, assigned: 1, decoded: 1, replaced: 0,
    samples: 1, browserP50Ms: 10, browserP95Ms: 10, imageLoadP50Ms: 4,
  });
});

test("63D-33 replaces only pending image while preserving first and latest timing", () => {
  let t = 0;
  const meter = createRemoteDesktopTiming({ now: () => t });
  const raf = [];
  const painter = createLatestRemoteFramePainter({
    requestFrame: (cb) => { raf.push(cb); return raf.length; },
    cancelFrame: () => {},
    getImage: () => ({ set src(value) { assert.equal(value, "data:image/jpeg;base64,last"); } }),
    onFrameAssigned: (x) => meter.frameAssigned(x),
  });
  for (const word of ["first", "middle", "last"]) {
    painter.push(word, { receivedAt: meter.frameReceived() });
    t += 3;
  }
  raf.shift()();
  assert.equal(meter.snapshot().received, 3);
  assert.equal(meter.snapshot().assigned, 1);
  assert.equal(meter.snapshot().replaced, 2);
  t = 21;
  assert.equal(meter.imageLoaded(), true);
  assert.equal(meter.snapshot().browserP50Ms, 15);
});

test("63D-33 keeps a strict bounded rolling window, resets all metrics", () => {
  let t = 0;
  const m = createRemoteDesktopTiming({ now: () => t, sampleLimit: 2 });
  for (const age of [3, 6, 9]) {
    const receivedAt = m.frameReceived();
    m.frameAssigned({ receivedAt });
    t += age;
    assert.equal(m.imageLoaded(), true);
  }
  const snap = m.snapshot();
  assert.equal(snap.received, 3);
  assert.equal(snap.samples, 2);
  assert.equal(snap.browserP50Ms, 6);
  assert.equal(snap.browserP95Ms, 9);
  m.reset();
  assert.equal(m.snapshot().received, 0);
  assert.equal(m.snapshot().samples, 0);
  assert.equal(m.imageLoaded(), false);
  for (const limit of [-1, 0, 129, 1.1]) {
    assert.throws(() => createRemoteDesktopTiming({ now: () => t, sampleLimit: limit }), RangeError);
  }
});

test("63D-33 no JPEGs, input or credentials enter timing counters", () => {
  const m = createRemoteDesktopTiming({ now: () => 1 });
  const r = m.frameReceived();
  m.frameAssigned({ receivedAt: r, replacedWhileWaiting: 2 });
  m.imageLoaded();
  const keys = Object.keys(m.snapshot()).sort();
  assert.deepEqual(keys, [
    "assigned", "browserP50Ms", "browserP95Ms", "decoded",
    "imageLoadP50Ms", "received", "replaced", "samples",
  ]);
  assert.equal(JSON.stringify(m.snapshot()).includes("data:image"), false);
});

test("63D-33 painter still defers mount and discards pending callbacks on stop", () => {
  let image = null;
  const tasks = new Map();
  let next = 0;
  let assigned = 0;
  const painter = createLatestRemoteFramePainter({
    requestFrame: (cb) => { tasks.set(++next, cb); return next; },
    cancelFrame: (id) => tasks.delete(id),
    getImage: () => image,
    onFrameAssigned: () => { assigned++; },
  });
  painter.push("first");
  tasks.get(1)();
  tasks.delete(1);
  assert.equal(assigned, 0);
  image = { src: "" };
  painter.flush();
  tasks.get(2)();
  tasks.delete(2);
  assert.equal(assigned, 1);
  painter.push("stale");
  painter.clear();
  assert.equal(tasks.size, 0);
  painter.dispose();
  painter.push("too-late");
  assert.equal(image.src, "data:image/jpeg;base64,first");
});
