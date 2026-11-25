import assert from "node:assert/strict";
import { test } from "node:test";
import { installNativeRdpPageLifecycle } from "../src/pages/clientdetailspage/remotedesktop/nativeRdpPageLifecycle.mjs";

const event = (name, persisted = false) => Object.assign(new Event(name), { persisted });
test("tab switching, blur and focus do not close a remote desktop", () => {
  const target = new EventTarget();
  const events = [];
  const remove = installNativeRdpPageLifecycle(target, { leave: () => events.push("leave"), restore: () => events.push("restore") });
  for (const name of ["visibilitychange", "blur", "focus", "pageshow"]) target.dispatchEvent(event(name));
  assert.deepEqual(events, []);
  remove();
});
test("document departure closes once; BFCache restoration opens a fresh generation", () => {
  const target = new EventTarget();
  const events = [];
  const remove = installNativeRdpPageLifecycle(target, { leave: () => events.push("leave"), restore: () => events.push("restore") });
  target.dispatchEvent(event("pagehide", true));
  target.dispatchEvent(event("pagehide", true));
  target.dispatchEvent(event("pageshow", true));
  target.dispatchEvent(event("pageshow", true));
  target.dispatchEvent(event("pagehide"));
  assert.deepEqual(events, ["leave", "restore", "leave"]);
  remove();
  target.dispatchEvent(event("pageshow", true));
  target.dispatchEvent(event("pagehide"));
  assert.deepEqual(events, ["leave", "restore", "leave"]);
});
