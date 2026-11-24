import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";

const page = fs.readFileSync(new URL("../src/pages/clientdetailspage/remotedesktop/RemoteDesktop.jsx", import.meta.url), "utf8");
const viewer = fs.readFileSync(new URL("../src/pages/clientdetailspage/remotedesktop/NativeRdpViewer.jsx", import.meta.url), "utf8");
test("enabled physical pilot uses native RDP directly, no JPEG or HTTPS fallback", () => {
  assert.match(page, /const nativeRequested = nativeRdpPilotEnabled;/);
  assert.match(page, /nativeRequested \? new WebSocket\(/);
  assert.doesNotMatch(page, /onFallback=|skift til JPEG|GNOME RDP · ny pilot/);
  assert.match(page, /nativeRdpModeRef\.current\) return false/);
  assert.doesNotMatch(viewer, /TextField|onFallback|Diagnostik|Bekræft fysisk billede/);
  assert.match(viewer, /requestAutologin\(\{ \.\.\.handle\.request, managed: true \}\)/);
  assert.match(page, /<RemoteDesktopFileManager/);
});


test("SPA navigation loads isolated document once and never opens an unsafe native socket", () => {
  assert.match(page, /nativeRequested && !window\.crossOriginIsolated/);
  assert.match(page, /url\.searchParams\.get\("native_rdp"\) !== "1"/);
  assert.match(page, /url\.searchParams\.set\("native_rdp", "1"\)/);
  assert.match(page, /window\.location\.replace\(url\.href\)/);
  assert.match(page, /if \(!clientId \|\| \(nativeRequested && !window\.crossOriginIsolated\)\) return/);
});
