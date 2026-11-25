import test from "node:test";
import assert from "node:assert/strict";
import { createLivestreamTransportController } from "../src/pages/clientdetailspage/livestreamTransportController.mjs";

const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
function fixture() {
  let active = 0, peak = 0, next = 0;
  const timers = new Map(), players = [], labels = [];
  let available = true, visible = true;
  function factory(kind) {
    return callbacks => {
      active++; peak = Math.max(peak, active);
      const player = { kind, callbacks, dispose() { active--; } };
      players.push(player);
      return player;
    };
  }
  const controller = createLivestreamTransportController({
    startWss: factory("WSS"), startHls: factory("HLS"),
    probeWss: async () => available,
    onTransport: value => labels.push(value),
    isVisible: () => visible,
    schedule(fn, ms) { const id = ++next; timers.set(id, { fn, ms }); return id; },
    cancel(id) { timers.delete(id); },
  });
  return { controller, players, labels, timers, active: () => active, peak: () => peak,
    setAvailable: value => { available = value; }, setVisible: value => { visible = value; },
    async fire() {
      const [id, entry] = timers.entries().next().value;
      timers.delete(id); await entry.fn(); await flush();
    },
  };
}
test("fallback, bounded retry, recovery, stale callbacks and disposal", async () => {
  const f = fixture();
  assert.deepEqual(f.players.map(p => p.kind), ["WSS"]);
  const wss = f.players[0];
  wss.callbacks.onPlayable();
  await flush();
  assert.equal(f.labels.at(-1), "WSS");
  wss.callbacks.onFailure("socket-closed");
  await flush();
  const hls = f.players[1];
  assert.equal(hls.kind, "HLS");
  wss.callbacks.onPlayable();
  hls.callbacks.onHttpTransport("HTTPS");
  hls.callbacks.onPlayable();
  await flush();
  assert.equal(f.labels.at(-1), "HTTPS");
  assert.equal(f.timers.size, 1);
  f.setVisible(false);
  await f.fire();
  assert.equal(f.players.length, 2);
  f.setVisible(true); f.setAvailable(false);
  await f.fire();
  assert.equal(f.players.length, 2);
  f.setAvailable(true);
  await f.fire();
  assert.equal(f.players[2].kind, "WSS");
  assert.equal(f.peak(), 1);
  hls.callbacks.onFailure("late");
  f.controller.dispose();
  f.players[2].callbacks.onPlayable();
  await flush();
  assert.equal(f.active(), 0);
  assert.equal(f.timers.size, 0);
  assert.equal(f.labels.at(-1), null);
});
test("unsupported codec remains on HLS without retry", async () => {
  const f = fixture();
  f.players[0].callbacks.onFailure("unsupported-codec");
  await flush();
  f.players[1].callbacks.onPlayable();
  await flush();
  assert.equal(f.timers.size, 0);
  f.controller.dispose();
});
