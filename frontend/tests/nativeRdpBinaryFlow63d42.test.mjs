import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { test } from "node:test";

const source = fs.readFileSync(
  new URL("../public/native-rdp/transport-probe.js", import.meta.url), "utf8"
);

function harness() {
  const signals = [];
  let now = 0;
  let tick = () => {};
  let cleared = false;
  class FakeSocket {
    constructor(url, protocols) {
      this.url = url;
      this.protocols = protocols;
      this.bufferedAmount = 0;
      this.sent = [];
      this.listeners = new Map();
      this.closed = false;
    }
    addEventListener(type, fn) {
      this.listeners.set(type, [...(this.listeners.get(type) || []), fn]);
    }
    emit(type, data) {
      for (const fn of this.listeners.get(type) || []) fn({ data });
    }
    send(data) { this.sent.push(Uint8Array.from(data)); }
    close() { this.closed = true; }
  }
  const root = {
    WebSocket: FakeSocket,
    setInterval: fn => { tick = fn; return 1; },
    clearInterval: () => { cleared = true; },
  };
  const context = { window: root, ArrayBuffer, Uint8Array, Date };
  vm.runInNewContext(source, context, { filename: "transport-probe.js" });
  const failures = [];
  const protocol = ["binary", "planiq-ws-ticket", "A".repeat(43)];
  const install = () => root.PlanIQNativeRdpProbe.install({
    url: "wss://api.example.test/api/remote-desktop/browser/3/native-rdp/test/ws",
    now: () => now,
    onProgress: snapshot => signals.push(snapshot),
    onFailure: msg => failures.push(msg),
  });
  return {
    root, FakeSocket, failures, signals, protocol, install,
    tick: () => tick(), clock: v => { now = v; }, wasCleared: () => cleared,
  };
}

test("binary SOCKFS frames are split without copying, dropping or reordering any bytes", () => {
  const h = harness();
  const probe = h.install();
  const ws = new h.root.WebSocket(
    "wss://api.example.test/api/remote-desktop/browser/3/native-rdp/test/ws",
    h.protocol
  );
  ws.emit("open");
  const payload = Uint8Array.from({ length: 100001 }, (_, i) => i % 251);
  ws.send(payload.buffer);
  assert.ok(ws.sent.length > 1);
  assert.ok(ws.sent.every(frame => frame.length <= 16384));
  assert.deepEqual([...Buffer.concat(ws.sent.map(v => Buffer.from(v)))], [...payload]);
  assert.equal(probe.snapshot().toAgentBytes, payload.length);
  assert.equal(probe.snapshot().toAgentFrames, ws.sent.length);
  ws.emit("message", new Uint8Array([7, 8, 9]).buffer);
  assert.equal(probe.snapshot().fromAgentBytes, 3);
  assert.equal(probe.confirmVisible(), true);
  h.clock(60000);
  h.tick();
  assert.deepEqual(h.failures, []);
  assert.equal(JSON.stringify(probe.snapshot()).includes("api.example"), false);
  probe.dispose();
  assert.equal(h.root.WebSocket, h.FakeSocket);
});

test("invalid target or nonbinary websocket data fails closed", () => {
  const h = harness();
  h.install();
  assert.throws(() => new h.root.WebSocket("wss://attacker.invalid/", h.protocol), /Ikke-godkendt/);
  const ws = new h.root.WebSocket(
    "wss://api.example.test/api/remote-desktop/browser/3/native-rdp/test/ws",
    h.protocol
  );
  ws.emit("open");
  assert.throws(() => ws.send("RDP as text"), /binære/);
  assert.equal(ws.closed, true);
  assert.equal(h.failures.length, 1);
  assert.match(h.failures[0], /ikke-binær/);
});

test("all stalled handshakes and unconfirmed black screens have bounded outcomes", () => {
  for (const variant of ["no-send", "no-reply", "no-confirm"]) {
    const h = harness();
    const probe = h.install();
    const ws = new h.root.WebSocket(
      "wss://api.example.test/api/remote-desktop/browser/3/native-rdp/test/ws",
      h.protocol
    );
    ws.emit("open");
    if (variant !== "no-send") ws.send(new Uint8Array([1, 2]));
    if (variant === "no-confirm") ws.emit("message", new Uint8Array([3]).buffer);
    h.clock(variant === "no-send" ? 12000 : variant === "no-reply" ? 20000 : 45000);
    h.tick();
    assert.equal(h.failures.length, 1, variant);
    assert.equal(ws.closed, true, variant);
    assert.ok(h.wasCleared());
    assert.equal(probe.snapshot().visibleConfirmed, false);
    assert.equal(h.failures[0].includes("password"), false);
  }
});

test("bounded websocket buffer prevents silent unbounded queue growth", () => {
  const h = harness();
  h.install();
  const ws = new h.root.WebSocket(
    "wss://api.example.test/api/remote-desktop/browser/3/native-rdp/test/ws",
    h.protocol
  );
  ws.emit("open");
  ws.bufferedAmount = 2 * 1024 * 1024;
  assert.throws(() => ws.send(new Uint8Array([1])), /backpressure/);
  assert.equal(h.failures.length, 1);
  assert.equal(ws.sent.length, 0);
});
