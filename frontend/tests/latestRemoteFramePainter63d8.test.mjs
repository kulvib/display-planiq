import assert from "node:assert/strict";
import test from "node:test";
import { createLatestRemoteFramePainter } from "../src/pages/clientdetailspage/remotedesktop/latestRemoteFramePainter.mjs";

function harness() {
  const queue = new Map();
  const image = { src: "" };
  let nextId = 0;
  const painter = createLatestRemoteFramePainter({
    requestFrame: (callback) => { queue.set(++nextId, callback); return nextId; },
    cancelFrame: (id) => queue.delete(id),
    getImage: () => image,
  });
  return { painter, image, queue, paint() { const pending = [...queue.values()]; queue.clear(); pending.forEach((cb) => cb()); } };
}

test("63D-8 100 frames collapse to one current browser paint", () => {
  const { painter, image, queue, paint } = harness();
  for (let i = 0; i < 100; i++) painter.push(`frame-${i}`);
  assert.equal(queue.size, 1);
  paint();
  assert.equal(image.src, "data:image/jpeg;base64,frame-99");
  assert.equal(queue.size, 0);
});

test("63D-8 clear prevents stale frames after reconnect or stop", () => {
  const { painter, image, queue, paint } = harness();
  painter.push("old");
  painter.clear();
  assert.equal(queue.size, 0);
  paint();
  assert.equal(image.src, "");
  painter.push("new");
  paint();
  assert.equal(image.src, "data:image/jpeg;base64,new");
  painter.dispose();
  painter.push("late");
  assert.equal(queue.size, 0);
  assert.equal(image.src, "data:image/jpeg;base64,new");
});

test("63D-8 frames remain pending until image mounts (first React render)", () => {
  let image = null;
  const queue = [];
  const painter = createLatestRemoteFramePainter({
    requestFrame: (cb) => { queue.push(cb); return 1; },
    cancelFrame: () => {},
    getImage: () => image,
  });
  painter.push("one");
  queue.shift()();
  image = { src: "" };
  painter.flush();
  queue.shift()();
  assert.equal(image.src, "data:image/jpeg;base64,one");
});
