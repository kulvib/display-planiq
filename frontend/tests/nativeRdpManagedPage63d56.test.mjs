import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";

const page = fs.readFileSync(new URL("../src/pages/clientdetailspage/remotedesktop/RemoteDesktop.jsx", import.meta.url), "utf8");
const viewer = fs.readFileSync(new URL("../src/pages/clientdetailspage/remotedesktop/NativeRdpViewer.jsx", import.meta.url), "utf8");
test("enabled physical pilot defaults to native WSS, no JPEG fallback", () => {
  assert.match(page, /const nativeRequested = nativeRdpPilotEnabled;/);
  assert.match(page, /nativeRequested \? new WebSocket\(/);
  assert.doesNotMatch(page, /onFallback=|skift til JPEG|GNOME RDP · ny pilot/);
  assert.match(page, /nativeRdpModeRef\.current\) return false/);
  assert.doesNotMatch(viewer, /TextField|onFallback|Diagnostik|Bekræft fysisk billede/);
  assert.match(viewer, /requestAutologin\(\{ \.\.\.handle\.request, managed: true \}\)/);
  assert.match(page, /<RemoteDesktopFileManager/);
});


test("Terminal-style header keeps Shout out directly below desktop and files on their existing tab", () => {
  assert.match(page, /<MonitorIcon\s*\/>/);
  assert.match(page, /Klient ID:/);
  assert.match(page, /\{remoteScreenPanel\}\s*\{shoutPanel\}/);
  assert.match(page, /<RemoteDesktopFileManager/);
  assert.doesNotMatch(page, /setActiveTab\("shout"\)/);
});
test("automatic opening follows authorized generation and user intent", () => {
  assert.match(page, /desired=\{nativeDesktopWanted\}/);
  assert.match(page, /onDesiredChange=\{setNativeDesktopWanted\}/);
  assert.match(viewer, /!desired \|\| !sessionId \|\| working \|\| autoAttemptedRef.current/);
  assert.match(viewer, /onDesiredChange\?\.\(false\)/);
  assert.match(page, /url.searchParams.set\("native_rdp", "1"\)/);
  assert.match(page, /window.location.replace\(url.href\)/);
});


test("native document departure cancels old connection generation; hidden tabs do not use legacy idle stop", () => {
  assert.match(page, /installNativeRdpPageLifecycle\(window/);
  assert.match(page, /connectAttemptRef\.current \+= 1;[\s\S]*?const socket = wsRef\.current;[\s\S]*?socket\?\.close\(\)/);
  assert.match(page, /restore: \(\) => \{ void connectRef\.current\?\.\(\); \}/);
  assert.match(page, /if \(nativeRequested \|\| !connected \|\| !agentConnected\) return undefined;/);
  assert.match(viewer, /setTimeout\(\(\) => \{ void startAutomatic\(\); \}, 0\)/);
});


test("initial auto-start and recovery never display a manual connect button", () => {
  assert.match(viewer, /const \[retryAllowed, setRetryAllowed\] = useState\(false\)/);
  assert.match(viewer, /automatic && sessionId && \(!desired \|\| retryAllowed\) && \(/);
  assert.match(viewer, /launchInProgressRef.current \|\| !requestAutologin/);
  assert.match(viewer, /setRetryAllowed\(!shouldRecover\)/);
  assert.match(viewer, /onDesiredChange\?\.\(false\);\s*autoAttemptedRef.current = true/);
});


test("Files tab keeps the RDP iframe mounted but disables hidden input", () => {
  assert.match(page, /\(nativeRequested \|\| activeTab === "desktop"\) && \(/);
  assert.match(page, /inert=\{activeTab !== "desktop" \? true : undefined\}/);
  assert.match(page, /visibility: "hidden", pointerEvents: "none"/);
  assert.match(page, /activeTab === "files" && \(\s*<RemoteDesktopFileManager/);
  assert.match(viewer, /<ButtonGroup[^>]*aria-label="Visning"/);
  assert.match(viewer, /role="group" aria-label="Zoom"/);
  assert.match(viewer, /color="error" startIcon=\{<LinkOffIcon \/>\}/);
});


test("native transport chip uses server-observed binary hops, not build-time config", () => {
  assert.match(page, /msg\.type === "native_rdp_transport"/);
  assert.match(page, /previous\?\.tunnel_id === msg\.tunnel_id/);
  assert.match(page, /\["wss", "https"\]\.includes\(msg\.browser\)/);
  assert.match(page, /\["wss", "https"\]\.includes\(msg\.agent\)/);
  assert.match(page, /canControl && nativeDesktopWanted && !idleStopped && nativeTransport\?\.session_id === sessionId/);
  assert.match(page, /Browser → Render:.*Render → ClientFlow:/);
});
