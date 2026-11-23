import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { test } from "node:test";

const fitSource = fs.readFileSync(
  new URL("../public/native-rdp/viewport-fit.js", import.meta.url), "utf8"
);
const html = fs.readFileSync(
  new URL("../public/native-rdp/viewer.html", import.meta.url), "utf8"
);
const viewer = fs.readFileSync(
  new URL("../public/native-rdp/viewer.js", import.meta.url), "utf8"
);

function harness({ sourceWidth = 520, sourceHeight = 390, width = 1480, height = 720 } = {}) {
  const frames = [];
  const resize = [];
  const mutation = [];
  const listeners = new Map();
  const properties = new Map();
  const canvas = {
    id: "canvas", tagName: "CANVAS", width: sourceWidth, height: sourceHeight,
    style: {
      getPropertyValue(key) { return properties.get(key) || ""; },
      setProperty(key, value) { properties.set(key, value); },
    },
  };
  const viewport = {
    id: "viewport", clientWidth: width, clientHeight: height,
    contains(element) { return element === canvas; },
  };
  const root = {
    ResizeObserver: class {
      constructor(callback) { this.callback = callback; resize.push(this); }
      observe(element) { assert.equal(element, viewport); }
      disconnect() { this.disconnected = true; }
    },
    MutationObserver: class {
      constructor(callback) { this.callback = callback; mutation.push(this); }
      observe(element, args) {
        assert.equal(element, canvas);
        assert.deepEqual(Array.from(args.attributeFilter), ["width", "height"]);
        assert.equal(args.attributes, true);
      }
      disconnect() { this.disconnected = true; }
    },
    requestAnimationFrame(callback) { frames.push(callback); return frames.length; },
    cancelAnimationFrame() {},
    addEventListener(name, callback) { listeners.set(name, callback); },
    removeEventListener(name, callback) {
      if (listeners.get(name) === callback) listeners.delete(name);
    },
  };
  vm.runInNewContext(fitSource, { window: root }, { filename: "viewport-fit.js" });
  return {
    root, canvas, viewport, resize, mutation, listeners,
    flush() { const cb = frames.shift(); assert.ok(cb); cb(); },
    pending() { return frames.length; },
    get width() { return properties.get("--rdp-fit-width"); },
    get height() { return properties.get("--rdp-fit-height"); },
  };
}

test("SDL3 canvas scales from 520x390 to fill the 1480x720 viewport without stretching", () => {
  const h = harness();
  const viewportFit = h.root.PlanIQNativeRdpViewport.install({
    canvas: h.canvas, viewport: h.viewport,
  });
  h.flush();
  assert.equal(h.width, "960px");
  assert.equal(h.height, "720px");
  assert.equal(960 / 720, 520 / 390);
  assert.equal(h.mutation.length, 1);
  viewportFit.dispose();
  assert.equal(h.resize[0].disconnected, true);
  assert.equal(h.mutation[0].disconnected, true);
  assert.equal(h.listeners.size, 0);
});

test("browser resize and SDL3 framebuffer resize preserve aspect and coalesce observers", () => {
  const h = harness();
  h.root.PlanIQNativeRdpViewport.install({ canvas: h.canvas, viewport: h.viewport });
  h.flush();
  h.viewport.clientWidth = 450;
  h.viewport.clientHeight = 700;
  h.resize[0].callback();
  h.resize[0].callback();
  assert.equal(h.pending(), 1);
  h.flush();
  assert.equal(h.width, "450px");
  assert.equal(h.height, "337px");
  h.canvas.width = 1600;
  h.canvas.height = 900;
  h.mutation[0].callback();
  h.flush();
  assert.equal(h.width, "450px");
  assert.equal(h.height, "253px");
});

test("1x1 SDL initialization and invalid dimensions cannot stretch or mutate framebuffer", () => {
  const h = harness({ sourceWidth: 1, sourceHeight: 1 });
  const fit = h.root.PlanIQNativeRdpViewport.install({ canvas: h.canvas, viewport: h.viewport });
  h.flush();
  assert.equal(h.width, undefined);
  assert.equal(h.height, undefined);
  assert.equal(h.canvas.width, 1);
  h.canvas.width = 520;
  h.canvas.height = 390;
  h.mutation[0].callback();
  h.flush();
  assert.equal(h.width, "960px");
  assert.equal(h.height, "720px");
  assert.equal(h.canvas.width, 520);
  assert.equal(h.canvas.height, 390);
  assert.equal(h.root.PlanIQNativeRdpViewport.calculateFit(0, 390, 1480, 720), null);
  assert.equal(h.root.PlanIQNativeRdpViewport.calculateFit(520, 390, 0, 720), null);
  fit.dispose();
  h.mutation[0].callback();
  assert.equal(h.pending(), 0);
});

test("the iframe retains the exact SDL3 canvas contract and transport-isolated load order", () => {
  assert.match(html, /<div id="viewport"><canvas id="canvas"/);
  assert.match(html, /#canvas\s*\{/);
  assert.doesNotMatch(html, /#desktop\s*\{/);
  assert.match(html, /--rdp-fit-width/);
  assert.match(html, /--rdp-fit-height/);
  assert.ok(html.indexOf('src="/native-rdp/transport-probe.js"') <
            html.indexOf('src="/native-rdp/viewport-fit.js"'));
  assert.ok(html.indexOf('src="/native-rdp/viewport-fit.js"') <
            html.indexOf('src="/native-rdp/viewer.js"'));
  assert.match(viewer, /PlanIQNativeRdpViewport\.install/);
  assert.match(viewer, /viewportFit\?\.dispose\(\)/);
  assert.match(viewer, /canvas: element, viewport: document\.getElementById\("viewport"\)/);
  assert.doesNotMatch(viewer, /canvas\.width\s*=/);
  assert.doesNotMatch(viewer, /canvas\.height\s*=/);
});
