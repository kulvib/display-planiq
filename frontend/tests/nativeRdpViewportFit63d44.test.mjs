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

test("a 520x390 source is never upscaled merely to fill a 1480x720 viewport", () => {
  const h = harness();
  const viewportFit = h.root.PlanIQNativeRdpViewport.install({
    canvas: h.canvas, viewport: h.viewport,
  });
  h.flush();
  assert.equal(h.width, "520px");
  assert.equal(h.height, "390px");
  assert.equal(h.canvas.width, 520);
  assert.equal(h.canvas.height, 390);
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
  assert.equal(h.width, "520px");
  assert.equal(h.height, "390px");
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

test("native 1:1 pixels, CSS downscale and reports never change GNOME framebuffer", () => {
  const h = harness({ sourceWidth: 1920, sourceHeight: 1080, width: 1280, height: 720 });
  const dimensions = [];
  const fit = h.root.PlanIQNativeRdpViewport.install({
    canvas: h.canvas, viewport: h.viewport, onResize: (data) => dimensions.push(data),
  });
  h.flush();
  assert.equal(h.width, "1280px");
  assert.equal(h.height, "720px");
  assert.equal(dimensions.length, 1);
  assert.equal(dimensions[0].sourceWidth, 1920);
  assert.equal(dimensions[0].sourceHeight, 1080);
  assert.equal(dimensions[0].displayWidth, 1280);
  assert.equal(dimensions[0].mode, "fit");
  h.resize[0].callback();
  h.flush();
  assert.equal(dimensions.length, 1, "unchanged dimensions must not flood the UI");

  fit.setMode("native");
  h.flush();
  assert.equal(h.width, "1920px");
  assert.equal(h.height, "1080px");
  assert.equal(dimensions.length, 2);
  assert.equal(dimensions[1].mode, "native");
  assert.equal(h.canvas.width, 1920);
  assert.equal(h.canvas.height, 1080);

  assert.throws(() => fit.setMode("stretch"), /Ugyldig/);
  fit.setMode("fit");
  h.flush();
  assert.equal(h.width, "1280px");
  assert.equal(h.height, "720px");
  assert.equal(dimensions.length, 3);
  fit.dispose();
  fit.setMode("native");
  assert.equal(h.pending(), 0);
});

test("native mode does not crop a large framebuffer via CSS max-size and supports scrolling", () => {
  assert.match(html, /#viewport[^}]*overflow:auto/);
  assert.match(html, /#canvas[^}]*margin:auto/);
  assert.doesNotMatch(html, /#canvas[^}]*max-width:100%/);
  assert.doesNotMatch(html, /#canvas[^}]*max-height:100%/);
  const h = harness({ sourceWidth: 3840, sourceHeight: 2160, width: 800, height: 600 });
  const fit = h.root.PlanIQNativeRdpViewport.install({
    canvas: h.canvas, viewport: h.viewport, mode: "native",
  });
  h.flush();
  assert.equal(h.width, "3840px");
  assert.equal(h.height, "2160px");
  assert.equal(h.canvas.width, 3840);
  fit.dispose();
});

test("resolution reporting is same-origin, bounded and cannot request GNOME resolution changes", () => {
  const ui = fs.readFileSync(
    new URL("../src/pages/clientdetailspage/remotedesktop/NativeRdpViewer.jsx", import.meta.url),
    "utf8"
  );
  assert.match(viewer, /planiq-native-rdp-resolution/);
  assert.match(viewer, /planiq-native-rdp-display-mode/);
  assert.match(viewer, /onResize:.*sourceWidth/s);
  assert.match(ui, /Tilpas uden opskalering/);
  assert.match(ui, /Original pixelstørrelse \(1:1\)/);
  assert.match(ui, /Number\.isSafeInteger\(n\)/);
  assert.doesNotMatch(ui, /FreeRDP-canvas|CSS-px/);
  assert.doesNotMatch(viewer, /\/(?:dynamic-resolution|smart-sizing)(?:"|:)/);
  assert.match(viewer, /\.\.\.\(isViborg1 \? \["\/size:2560x1080"\] : \[\]\)/);
  assert.equal((viewer.match(/\/size:/g) || []).length, 1);
});


test("initial size experiment is scoped to exact physical client 3", () => {
  const expression = viewer.match(/const isViborg1 = (\/[^\n]+\/)\s*\n\s*\.test\(new URL\(data\.tunnelUrl\)\.pathname\);/);
  assert.ok(expression, "initial size must be scoped by the validated tunnel path");
  const re = new RegExp(expression[1].slice(1, -1));
  const session = "c8e4a40e-a48c-48a1-9a2c-35035cb9e9bc";
  assert.equal(re.test("/api/remote-desktop/browser/3/native-rdp/" + session + "/ws"), true);
  for (const client of ["30", "13", "56", "03"]) {
    assert.equal(re.test("/api/remote-desktop/browser/" + client + "/native-rdp/" + session + "/ws"), false);
  }
});


test("explicit zoom 25–200 percent preserves the framebuffer and aspect ratio", () => {
  const h = harness({ sourceWidth: 2560, sourceHeight: 1080, width: 1454, height: 720 });
  const fit = h.root.PlanIQNativeRdpViewport.install({ canvas: h.canvas, viewport: h.viewport });
  h.flush();
  assert.equal(h.width, "1454px");
  for (const [zoom, width, height] of [[25,640,270],[50,1280,540],[100,2560,1080],[150,3840,1620],[200,5120,2160]]) {
    fit.setMode("zoom", zoom);
    h.flush();
    assert.equal(h.width, width + "px");
    assert.equal(h.height, height + "px");
    assert.equal(h.canvas.width, 2560);
    assert.equal(h.canvas.height, 1080);
  }
  for (const invalid of [0,24,201,Infinity,NaN,"125",125.5]) {
    assert.throws(() => fit.setMode("zoom", invalid), /Ugyldig/);
  }
  fit.setMode("fit");
  h.flush();
  assert.equal(h.width, "1454px");
  fit.dispose();
});

test("compact controls exclude diagnostics and use browser fullscreen", () => {
  assert.doesNotMatch(ui, /component="details"|Diagnostik|Bekræft fysisk billede|onFallback/);
  assert.match(ui, /requestFullscreen\(\)/);
  assert.match(ui, /exitFullscreen\(\)/);
  assert.match(ui, /fullscreenchange/);
  assert.match(ui, /aria-label="Zoomniveau"/);
  assert.match(viewer, /viewportFit\?\.setMode\("zoom", data.zoom\)/);
  assert.match(viewer, /status.hidden = type !== "planiq-native-rdp-error" && bidirectionalTraffic/);
  assert.match(html, /#status\[hidden\]/);
});
