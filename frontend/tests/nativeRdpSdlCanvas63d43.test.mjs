import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { test } from "node:test";

const html = fs.readFileSync(new URL("../public/native-rdp/viewer.html", import.meta.url), "utf8");
const viewer = fs.readFileSync(new URL("../public/native-rdp/viewer.js", import.meta.url), "utf8");
const compiled = fs.readFileSync(new URL("../public/native-rdp/sdl-freerdp.js", import.meta.url), "utf8");

// SDL3's Emscripten window driver defaults to the CSS selector "#canvas".
// The pinned FreeRDP SDL3 client does not override that window property.
// This contract must never diverge from the iframe's Module.canvas binding.
test("HTML and Module.canvas use the same SDL3 default canvas target", () => {
  assert.match(html, /<canvas\s+id="canvas"\s+tabindex="0"/);
  assert.doesNotMatch(html, /<canvas\s+id="desktop"/);
  assert.match(viewer, /document\.getElementById\("canvas"\)/);
  assert.match(viewer, /document\.querySelector\("#canvas"\)\s*!==\s*element/);
  assert.match(compiled, /document\.querySelector\(canvasId\)/);
  assert.ok(html.indexOf('src="/native-rdp/transport-probe.js"') <
            html.indexOf('src="/native-rdp/viewer.js"'));
});

test("GNOME RDP startup binds FreeRDP to SDL3's real iframe canvas, not another element", () => {
  const canvas = { tagName: "CANVAS", id: "canvas", width: 300, height: 150 };
  const viewport = { id: "viewport", contains: (element) => element === canvas };
  const status = { textContent: "" };
  const listeners = new Map();
  const parent = { postMessage() {} };
  const window = {
    location: { origin: "https://display.example.test" },
    parent,
    crossOriginIsolated: true,
    PlanIQNativeRdpProbe: {
      install() { return { dispose() {}, confirmVisible() { return false; } }; }
    },
    PlanIQNativeRdpViewport: {
      install({ canvas: actualCanvas, viewport: actualViewport }) {
        assert.equal(actualCanvas, canvas);
        assert.equal(actualViewport, viewport);
        return { dispose() {} };
      }
    },
    addEventListener(type, callback) { listeners.set(type, callback); },
  };
  const requests = [];
  const document = {
    getElementById(id) { return id === "canvas" ? canvas : id === "viewport" ? viewport : id === "status" ? status : null; },
    querySelector(selector) { return selector === "#canvas" ? canvas : null; },
    createElement(tag) { return { tagName: tag }; },
    body: { appendChild(element) { requests.push(element); } },
  };
  const context = {
    document, window, URL, SharedArrayBuffer,
    setTimeout() { return 1; }, clearTimeout() {},
  };
  vm.runInNewContext(viewer, context, { filename: "viewer.js" });
  const request = {
    type: "planiq-native-rdp-start",
    tunnelUrl: "wss://api.example.test/api/remote-desktop/browser/3/native-rdp/12345678-1234-1234-1234-123456789abc/ws",
    ticket: "A".repeat(43), subprotocol: "planiq-ws-ticket",
    username: "localpilot", password: "private-test-only",
    fingerprint: Array(32).fill("aa").join(":"),
  };
  listeners.get("message")({ source: parent, origin: window.location.origin, data: request });
  assert.equal(window.Module.canvas, canvas);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].src, "/native-rdp/sdl-freerdp.js");
  assert.equal(request.password, "");
  assert.equal(request.ticket, "");
});

test("missing SDL3 canvas fails closed before FreeRDP or transport starts", () => {
  const listeners = new Map();
  const status = { textContent: "" };
  const parent = { postMessage() {} };
  let transportStarts = 0;
  const window = {
    location: { origin: "https://display.example.test" }, parent,
    crossOriginIsolated: true,
    PlanIQNativeRdpProbe: { install() { transportStarts++; throw Error("not reached"); } },
    addEventListener(type, callback) { listeners.set(type, callback); },
  };
  const document = {
    getElementById(id) { return id === "status" ? status : null; },
    querySelector() { return null; },
  };
  vm.runInNewContext(viewer, {
    document, window, URL, SharedArrayBuffer,
    setTimeout() { return 1; }, clearTimeout() {}
  }, { filename: "viewer.js" });
  const data = {
    type: "planiq-native-rdp-start",
    tunnelUrl: "wss://api.example.test/api/remote-desktop/browser/3/native-rdp/12345678-1234-1234-1234-123456789abc/ws",
    ticket: "B".repeat(43), subprotocol: "planiq-ws-ticket",
    username: "localpilot", password: "private-test-only",
    fingerprint: Array(32).fill("aa").join(":"),
  };
  listeners.get("message")({ source: parent, origin: window.location.origin, data });
  assert.equal(transportStarts, 0);
  assert.equal(status.textContent, "ClientFlow-forbindelsen blev afbrudt. Prøv igen.");
});
