import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (file) => fs.readFileSync(path.join(root, file), "utf8");

test("63D-36 noVNC is exact-version locked with npm integrity and no new service", () => {
  const pkg = JSON.parse(read("package.json"));
  const lock = JSON.parse(read("package-lock.json"));
  assert.equal(pkg.dependencies["@novnc/novnc"], "1.7.0");
  assert.equal(lock.packages[""].dependencies["@novnc/novnc"], "1.7.0");
  const entry = lock.packages["node_modules/@novnc/novnc"];
  assert.deepEqual(entry, {
    version: "1.7.0",
    resolved: "https://registry.npmjs.org/@novnc/novnc/-/novnc-1.7.0.tgz",
    integrity: "sha512-ucEJOx4T2avIRCleodk7YobZj5O2Ga2AeLfQ69A/yjG9HHba2+PDgwSkN3FttrmG+70ZGx21sElNFouK13RzyA==",
    license: "MPL-2.0",
  });
});

test("63D-36 old JPEG viewer remains source-selected; native pilot cannot auto-start", () => {
  const page = read("src/pages/clientdetailspage/remotedesktop/RemoteDesktop.jsx");
  assert.match(page, /const NATIVE_RFB_PILOT_ENABLED = false;/);
  assert.match(page, /<NativeRfbViewer\s/);
  assert.match(page, /\) : remoteScreenPanel}/);
  assert.match(page, /import NativeRfbViewer from/);
  assert.match(page, /const RD_ACTIVE_FPS = 8;/);
});

test("63D-36 noVNC is dynamically imported, attached inside the page and cleaned on logout", () => {
  const viewer = read("src/pages/clientdetailspage/remotedesktop/NativeRfbViewer.jsx");
  assert.match(viewer, /import\("@novnc\/novnc"\)/);
  assert.match(viewer, /new RFB\(targetRef\.current, rawSocket, \{ shared: false \}\)/);
  assert.match(viewer, /createNativeRfbSocket\(\{ transport, sessionId \}\)/);
  assert.match(viewer, /rfb\?\.disconnect\(\)/);
  assert.match(viewer, /rawSocket\?\.close\(1000, "viewer_unmounted"\)/);
  assert.match(viewer, /import\(\s*"@novnc\/novnc"\s*\)/);
  assert.doesNotMatch(viewer, /https:\/\/cdn|unpkg\.com|window\.open\(/i);
});

test("63D-36 browser connection uses PlanIQ one-time ticket, superadmin session and HTTPS fallback", () => {
  const api = read("src/api/api.js");
  const viewer = read("src/pages/clientdetailspage/remotedesktop/NativeRfbViewer.jsx");
  assert.match(api, /export function getNativeRfbBrowserWsUrl/);
  assert.match(api, /export async function openNativeRfbBrowserHttpRelay/);
  assert.match(api, /export async function sendNativeRfbBrowserHttpRelay/);
  assert.match(api, /export async function pollNativeRfbBrowserHttpRelay/);
  assert.match(api, /export async function closeNativeRfbBrowserHttpRelay/);
  assert.match(api, /const ticket = await createBrowserWsTicket\(clientId, "remote_desktop"\)/);
  assert.match(api, /apiFetch\(/);
  assert.match(viewer, /createWebSocketWithHttpsFallback\(/);
  assert.match(viewer, /getBrowserWsProtocols\(ticket\)/);
  assert.match(viewer, /createHttpRelaySocket\(/);
  const backend = fs.readFileSync(
    path.resolve(root, "../backend/service1/routers/native_rdp_pilot.py"),
    "utf8",
  );
  assert.match(backend, /PILOT_ENABLED = False/);
  assert.match(backend, /authenticate_browser_websocket_with_context/);
  assert.match(backend, /_remote_desktop_browser_auth_state/);
  assert.match(backend, /AUTH_RECHECK_SECONDS = 15.0/);
});
