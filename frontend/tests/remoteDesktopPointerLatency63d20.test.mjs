import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createLatestPointerMoveScheduler } from "../src/pages/clientdetailspage/remotedesktop/latestPointerMoveScheduler.mjs";

function harness() {
  let t = 0;
  let nextId = 1;
  const jobs = new Map();
  const sent = [];
  const scheduler = createLatestPointerMoveScheduler({
    now: () => t,
    schedule: (callback, delay) => {
      const id = nextId++;
      jobs.set(id, { at: t + delay, callback });
      return id;
    },
    cancel: (id) => jobs.delete(id),
    send: (payload) => {
      sent.push(payload);
      return true;
    },
  });
  return {
    scheduler,
    sent,
    jobs,
    advance(ms) {
      const target = t + ms;
      while (true) {
        const due = [...jobs].sort((a, b) => a[1].at - b[1].at).find(([, row]) => row.at <= target);
        if (!due) break;
        t = due[1].at;
        jobs.delete(due[0]);
        due[1].callback();
      }
      t = target;
    },
  };
}

test("latest trailing pointer movement reaches the final cursor position", () => {
  const h = harness();
  h.scheduler.move({ action: "move", x: 1 });
  h.advance(10);
  h.scheduler.move({ action: "move", x: 2 });
  h.advance(10);
  h.scheduler.move({ action: "move", x: 3 });
  assert.deepEqual(h.sent.map((item) => item.x), [1]);
  h.advance(13);
  assert.deepEqual(h.sent.map((item) => item.x), [1, 3]);
  assert.equal(h.jobs.size, 0);
});

test("button transition flushes latest cursor before down/up and never replays move", () => {
  const h = harness();
  h.scheduler.move({ action: "move", x: 1 });
  h.advance(8);
  h.scheduler.move({ action: "move", x: 9 });
  h.scheduler.flush();
  h.sent.push({ action: "down" });
  h.sent.push({ action: "up" });
  h.advance(100);
  assert.deepEqual(h.sent, [
    { action: "move", x: 1 },
    { action: "move", x: 9 },
    { action: "down" },
    { action: "up" },
  ]);
});

test("disconnect/unmount clears pending pointer and allows immediate new-session movement", () => {
  const h = harness();
  h.scheduler.move({ action: "move", x: 1 });
  h.advance(8);
  h.scheduler.move({ action: "move", x: 2 });
  h.scheduler.clear();
  h.advance(100);
  assert.deepEqual(h.sent.map((item) => item.x), [1]);
  h.scheduler.move({ action: "move", x: 3 });
  assert.deepEqual(h.sent.map((item) => item.x), [1, 3]);
});

test("remote desktop keeps native geometry while tuning bounded JPEG size and input rate", () => {
  const source = readFileSync(new URL("../src/pages/clientdetailspage/remotedesktop/RemoteDesktop.jsx", import.meta.url), "utf8");
  assert.match(source, /native:\s*true/);
  assert.match(source, /quality:\s*RD_WS_JPEG_QUALITY/);
  assert.match(source, /const RD_ACTIVE_FPS = 8/);
  assert.match(source, /const RD_WS_JPEG_QUALITY = 72/);
  assert.match(source, /pointerMoves\.move\(/);
  assert.match(source, /pointerMoves\.flush\(\)/);
  assert.doesNotMatch(source, /throttleMs = mouseDownRef\.current \? 25 : 80/);
});
