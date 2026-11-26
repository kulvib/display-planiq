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

test("Native RDP is selected only from the authenticated backend capability", () => {
  assert.match(frontend, /getNativeRdpEligibility\(clientId, \{ signal: controller.signal \}\)/);
  assert.match(frontend, /const nativeRequested = nativeAdmissionReady && nativeAdmission.available === true/);
  assert.match(frontend, /if \(!clientId \|\| !nativeAdmissionReady/);
  assert.doesNotMatch(frontend, /VITE_NATIVE_RDP_PILOT|Number\(clientId\) === 3/);
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


test("RDP iframe cannot be blocked by broad clickjacking headers", () => {
  const render = readFileSync(new URL("../../render.yaml", import.meta.url), "utf8");
  // The wildcard applies to the entire static site, including /native-rdp/.
  assert.match(render, /name: X-Frame-Options[\s\S]*?value: SAMEORIGIN/);
  assert.doesNotMatch(render, /name: X-Frame-Options\s*\n\s*value: DENY/);
  const wildcardCsp = render.split("name: Content-Security-Policy")[1]?.split("\n")[1] || "";
  assert.match(wildcardCsp, /frame-ancestors 'self'/);
  assert.match(render, /path: \/remote-desktop\/\*[\s\S]*?name: Cross-Origin-Embedder-Policy/);
  assert.match(render, /path: \/native-rdp\/\*[\s\S]*?name: Cross-Origin-Embedder-Policy/);
  assert.match(render, /name: Content-Security-Policy[\s\S]*?wasm-unsafe-eval/);
});

test("WASM reports early exit and no-socket timeout without exposing secrets", () => {
  assert.match(child, /onExit: \(statusCode\) =>/);
  assert.match(child, /printErr: classifyStderr/);
  assert.match(child, /FreeRDP åbnede ingen RDP-WebSocket inden 15 sekunder/);
  assert.match(child, /if \(!transportOpened\)/);
  assert.doesNotMatch(child, /console\.(?:error|log|warn)\(/);
});

test("pilot uses minimal FreeRDP arguments and keeps mandatory TLS pin", () => {
  const args = child.match(/const args = \[([\s\S]*?)\];/);
  assert.ok(args, "explicit FreeRDP argument list");
  assert.match(args[1], /\/v:127\.0\.0\.1:3389/);
  assert.match(args[1], /\/u:/);
  assert.match(args[1], /\/p:/);
  assert.match(args[1], /\/cert:fingerprint:sha256:/);
  assert.doesNotMatch(args[1].replace(/\/\/[^\n]*/g, ""), /\/gfx|\/network:|\/log-level:/);
});
