import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { browserFullscreenLabel, normalizeBrowserFullscreen, visibleBrowserFullscreen } from "../src/utils/browserFullscreen.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const read = (name) => fs.readFileSync(path.join(here, "..", name), "utf8");

test("kiosk fullscreen labels include explicit unknown for old releases", () => {
  assert.equal(browserFullscreenLabel("fullscreen"), "Fuldskærm");
  assert.equal(browserFullscreenLabel("windowed"), "Ikke fuldskærm");
  for (const value of [null, undefined, "", "normal", false, "error"]) {
    assert.equal(normalizeBrowserFullscreen(value), "unknown");
    assert.equal(browserFullscreenLabel(value), "Ukendt");
  }
});

test("fullscreen is transported read-only through the existing Display path", () => {
  const runtime = fs.readFileSync(path.join(here, "..", "..", "client/runtime/clientflow_runtime/display_runtime.py"), "utf8");
  assert.match(runtime, /browser_fullscreen_updated_at/);
});

test("fullscreen is visible in the local GUI, Control Room and detail UI", () => {
  const gui = fs.readFileSync(path.join(here, "..", "..", "client/libexec/local-gui"), "utf8");
  const list = read("src/pages/ClientInfoPage.jsx");
  const details = read("src/pages/clientdetailspage/ClientDetailsInfoSection.jsx");
  const hot = read("src/pages/clientdetailspage/ClientDetailsPage.jsx");
  assert.match(gui, /"Fuldskærm", "browser_fullscreen"/);
  assert.match(list, /visibleBrowserFullscreen\(/);
  assert.match(details, /label: "Fuldskærm"/);
  assert.match(hot, /setLiveBrowserFullscreen\(data\?\.browser_fullscreen/);
});

test("hide fullscreen when browser is stopped, offline or unverified; show in Control Room", () => {
  for (const online of [false, null, undefined]) {
    assert.equal(visibleBrowserFullscreen(online, true, "fullscreen"), null);
  }
  for (const running of [false, null, undefined, "true"]) {
    assert.equal(visibleBrowserFullscreen(true, running, "fullscreen"), null);
  }
  assert.equal(visibleBrowserFullscreen(true, true, "fullscreen"), "Fuldskærm");
  assert.equal(visibleBrowserFullscreen(true, true, "windowed"), "Ikke fuldskærm");
  assert.equal(visibleBrowserFullscreen(true, true, "unknown"), "Ukendt");
  assert.match(read("src/pages/ClientInfoPage.jsx"), /fullscreenLabel !== null/);
  assert.match(read("src/pages/clientdetailspage/ClientDetailsPage.jsx"), /fullscreenLabel !== null/);
  assert.match(read("src/pages/clientdetailspage/ClientDetailsPage.jsx"), /visibleBrowserFullscreen\(clientOnline, client\?\.chrome_running/);
});
