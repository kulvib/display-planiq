import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../src/pages/clientdetailspage/remotedesktop/RemoteDesktop.jsx", import.meta.url), "utf8");

test("Shout out is a right-aligned toolbar action, not a desktop panel", () => {
  const files = source.indexOf("aria-pressed={activeTab === \"files\"}");
  const toolbar = source.slice(files, source.indexOf("</Paper>", files));
  assert.match(toolbar, /Shout out/);
  assert.match(toolbar, /ml: "auto"/);
  assert.match(toolbar, /disabled=\{!canControl \|\| shoutSending\}/);
  assert.doesNotMatch(source, /shoutPanel/);
  assert.match(source, /<Dialog\s+open=\{shoutOpen\}/);
  assert.match(source, /htmlInput: \{ maxLength: 120 \}/);
  assert.match(source, /type: "shout",\s+text: message,\s+duration: 8/);
});

test("Shout out closes on agent success, not on socket send, and retains draft on failure", () => {
  const result = source.slice(source.indexOf('if (msg.type === "shout_result")'), source.indexOf('if (msg.type === "file_activity")'));
  assert.match(result, /if \(!shoutAckTimerRef.current\) return;/);
  assert.match(result, /if \(msg.ok === false\) \{\s*setError\([^;]+;\s*\} else \{\s*setShoutText\(""\);\s*setShoutOpen\(false\);/);
  const send = source.slice(source.indexOf("const sendShout ="), source.indexOf("const getTransferFileKey ="));
  assert.doesNotMatch(send, /setShoutText\(""\)|setShoutOpen\(false\)|showActionMessage/);
  assert.match(send, /shoutSending \|\| shoutAckTimerRef.current/);
  assert.match(send, /6000/);
});

test("Shout out dialog preserves keyboard isolation and native viewer placement", () => {
  assert.match(source, /e.stopPropagation\(\);\s*if \(e.key === "Enter" && !e.nativeEvent.isComposing\)/);
  assert.match(source, /disableEscapeKeyDown=\{shoutSending\}/);
  assert.match(source, /\{remoteScreenPanel\}\s*<\/Stack>/);
  assert.match(source, /inert=\{activeTab !== "desktop" \? true : undefined\}/);
});

test("native toolbar displays the actual source resolution, independent of zoom", () => {
  const viewer = readFileSync(new URL("../src/pages/clientdetailspage/remotedesktop/NativeRdpViewer.jsx", import.meta.url), "utf8");
  const toolbar = viewer.slice(viewer.indexOf('aria-label="Zoom"'), viewer.indexOf('title={fullscreen'));
  assert.match(toolbar, /\{resolution && \(/);
  assert.match(toolbar, /\{resolution\.sourceWidth\} × \{resolution\.sourceHeight\}/);
  assert.doesNotMatch(toolbar, /\{resolution\.displayWidth\} × \{resolution\.displayHeight\}/);
  assert.match(viewer, /setResolution\(\{ sourceWidth, sourceHeight, displayWidth, displayHeight, mode \}\)/);
  assert.match(viewer, /setResolution\(null\)/);
});
