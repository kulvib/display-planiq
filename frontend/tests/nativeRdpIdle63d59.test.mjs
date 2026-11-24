import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";
const page = fs.readFileSync(new URL("../src/pages/clientdetailspage/remotedesktop/RemoteDesktop.jsx", import.meta.url), "utf8");
const viewer = fs.readFileSync(new URL("../src/pages/clientdetailspage/remotedesktop/NativeRdpViewer.jsx", import.meta.url), "utf8");
const child = fs.readFileSync(new URL("../public/native-rdp/viewer.js", import.meta.url), "utf8");
test("idle timeout is distinct from a transport failure and stops auto reconnect", () => {
  assert.match(page, /event.code === 4408/);
  assert.match(page, /reconnectTimerRef.current \|\| idleStoppedRef.current/);
  assert.match(page, /setNativeDesktopWanted\(false\)/);
  assert.match(page, /Fortsæt session/);
  assert.match(viewer, /if \(!idleStopped\) return/);
});
test("only trusted user input, not progress or keepalive, reports idle activity", () => {
  assert.match(child, /!event.isTrusted/);
  assert.match(viewer, /event.isTrusted\) reportActivity/);
  assert.match(viewer, /event.source !== iframeRef.current\?\.contentWindow/);
  assert.match(viewer, /type: "native_rdp_user_activity", request_id: requestId/);
  assert.match(child, /ClientFlow-forbindelsen blev afbrudt/);
});
