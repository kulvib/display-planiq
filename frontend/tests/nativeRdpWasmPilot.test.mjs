import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const frontend = readFileSync(
  new URL("../src/pages/clientdetailspage/remotedesktop/RemoteDesktop.jsx", import.meta.url),
  "utf8",
);
const viewer = readFileSync(
  new URL("../src/pages/clientdetailspage/remotedesktop/NativeRdpViewer.jsx", import.meta.url),
  "utf8",
);
const child = readFileSync(new URL("../public/native-rdp/viewer.js", import.meta.url), "utf8");

test("Viborg1-only native RDP is disabled unless explicitly enabled", () => {
  assert.match(frontend, /VITE_NATIVE_RDP_PILOT === "true" && Number\(clientId\) === 3/);
  assert.match(frontend, /nativeRdpModeRef\.current\) return false/);
  assert.match(frontend, /stopStream\(\)/);
});
test("the browser uses a second scoped one-time ticket, never query-string credentials", () => {
  assert.match(viewer, /createBrowserWsTicket\(clientId, "remote_desktop"\)/);
  assert.match(viewer, /getRemoteDesktopBrowserWsUrl/);
  assert.match(viewer, /encodeURIComponent\(sessionId\)/);
  assert.doesNotMatch(viewer, /localStorage|sessionStorage/);
});
test("same-origin disposable WASM iframe and client side GNOME RDP input", () => {
  assert.match(viewer, /<iframe/);
  assert.match(child, /event\.origin !== window\.location\.origin/);
  assert.match(child, /window\.Module\.callMain\(args\)/);
  assert.match(child, /SharedArrayBuffer/);
  assert.match(child, /\/cert:fingerprint:sha256:/);
  assert.doesNotMatch(child, /\/cert:ignore/);
  const executable = child.replace(/\/\*[\s\S]*?\*\/|\/\/[^\n]*/g, "");
  assert.doesNotMatch(executable, /fetch\(|localStorage|document\.cookie/);
});
