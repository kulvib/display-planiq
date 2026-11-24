import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { test } from "node:test";

const source = fs.readFileSync(
  new URL("../public/native-rdp/viewer.js", import.meta.url), "utf8"
);
const ui = fs.readFileSync(
  new URL("../src/pages/clientdetailspage/remotedesktop/NativeRdpViewer.jsx", import.meta.url), "utf8"
);

test("iframe passively measures browser mouse event delay and reports only bounded metrics", () => {
  const listeners = new Map();
  const windowListeners = new Map();
  const out = [];
  let now = 100;
  let onProgress = null;
  const canvas = {
    id: "canvas", tagName: "CANVAS",
    addEventListener(type, callback, options) {
      if (type === "pointermove") {
        assert.equal(options.passive, true);
        listeners.set(type, callback);
      }
    },
  };
  const parent = { postMessage: (data) => out.push(data) };
  const window = {
    performance: { now: () => now },
    location: { origin: "https://display.example.test" },
    parent,
    crossOriginIsolated: true,
    PlanIQNativeRdpViewport: {
      install() { return { dispose() {} }; },
    },
    PlanIQNativeRdpProbe: {
      install({ onProgress: cb }) {
        onProgress = cb;
        return { dispose() {}, confirmVisible() { return true; } };
      },
    },
    addEventListener(name, callback) { windowListeners.set(name, callback); },
  };
  const status = { textContent: "" };
  const document = {
    getElementById(id) {
      if (id === "canvas") return canvas;
      if (id === "viewport") return { id: "viewport" };
      if (id === "status") return status;
      return null;
    },
    querySelector(id) { return id === "#canvas" ? canvas : null; },
    createElement() { return {}; },
    body: { appendChild() {} },
  };
  vm.runInNewContext(source, {
    document, window, URL, SharedArrayBuffer, Date,
    setTimeout: () => 1, clearTimeout: () => {},
  }, { filename: "viewer.js" });

  assert.equal(typeof listeners.get("pointermove"), "function");
  listeners.get("pointermove")({ timeStamp: 97 });
  const request = {
    type: "planiq-native-rdp-start",
    tunnelUrl: "wss://api.example.test/api/remote-desktop/browser/3/native-rdp/12345678-1234-1234-1234-123456789abc/ws",
    ticket: "A".repeat(43), subprotocol: "planiq-ws-ticket",
    username: "localpilot", password: "private-test-only",
    fingerprint: Array(32).fill("aa").join(":"),
  };
  windowListeners.get("message")({
    source: parent, origin: window.location.origin, data: request,
  });
  assert.equal(typeof onProgress, "function");
  onProgress({
    openedAt: 10,
    toAgentBytes: 50, toAgentFrames: 1,
    fromAgentBytes: 51, fromAgentFrames: 1,
    peakOutboundQueueBytes: 9216,
    maxTimerSlipMs: 8,
  });
  const perf = out.find((m) => m.type === "planiq-native-rdp-performance");
  assert.ok(perf);
  assert.equal(status.hidden, true, "normal traffic must not cover the desktop");
  assert.equal(perf.pointerEvents, 1);
  assert.equal(perf.maxBrowserEventLagMs, 3);
  assert.equal(perf.peakOutboundQueueBytes, 9216);
  assert.equal(perf.maxBrowserTimerSlipMs, 8);
  assert.equal(JSON.stringify(perf).includes("private-test-only"), false);
  assert.equal(JSON.stringify(perf).includes("12345678"), false);
  assert.equal(JSON.stringify(perf).includes("example.test"), false);
});

test("display accepts only bounded numeric performance and does not call them RTT", () => {
  assert.match(ui, /planiq-native-rdp-performance/);
  assert.match(ui, /Number\.isSafeInteger\(data\[key\]\)/);
  assert.match(ui, /Målingerne er ikke RDP-returforsinkelse/);
  assert.match(source, /passive: true/);
  assert.doesNotMatch(source, /stopImmediatePropagation/);
  assert.doesNotMatch(source, /preventDefault\(/);
});
