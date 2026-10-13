import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { controlRoomRoleAllows, controlRoomActionDecision } from "../src/pages/clientdetailspage/controlRoomActionMatrix.mjs";

const ACTIONS = ["start", "stop", "sleep", "wakeup", "reboot", "shutdown", "terminal", "remote"];
const ROLES = ["viewer", "bruger", "admin", "superadmin"];
const baseline = { role: "superadmin", online: true, clientStatus: "approved", sleeping: false,
  systemLocked: false, clientflowBusy: false, ubuntuBusy: false, wakeInProgress: false,
  pendingAction: "none", chromeRunning: false, browserRequested: true, busy: false };
const check = (action, patch = {}) => controlRoomActionDecision(action, { ...baseline, ...patch });
const enabled = (action, patch = {}) => !check(action, patch).disabled;
const disabled = (action, patch = {}) => check(action, patch).disabled;

test("roles exactly match backend client, power and support action grants", () => {
  const rolesByAction = {
    start: ["bruger", "admin", "superadmin"],
    stop: ["bruger", "admin", "superadmin"],
    sleep: ["bruger", "admin", "superadmin"],
    wakeup: ["bruger", "admin", "superadmin"],
    reboot: ["admin", "superadmin"],
    shutdown: ["superadmin"],
    terminal: ["superadmin"],
    remote: ["superadmin"],
  };
  for (const action of ACTIONS) for (const role of ROLES) {
    assert.equal(controlRoomRoleAllows(role, action), rolesByAction[action].includes(role), `${role}/${action}`);
    if (!rolesByAction[action].includes(role)) assert.equal(disabled(action, { role }), true);
  }
  assert.equal(disabled("reset_browser"), true, "no undocumented buttons");
});

test("offline, unapproved and busy clients fail closed; support tools remain accessible", () => {
  for (const action of ACTIONS.filter((a) => !["terminal", "remote"].includes(a))) {
    assert.ok(disabled(action, { online: false }), `${action} offline`);
    for (const blocked of [
      { systemLocked: true }, { pendingAction: "reboot" }, { pendingAction: "shutdown" },
      { ubuntuBusy: true }, { clientflowBusy: true }, { busy: true },
    ]) assert.ok(disabled(action, blocked), `${action}/${JSON.stringify(blocked)}`);
  }
  for (const action of ["terminal", "remote"]) {
    assert.ok(enabled(action, { online: false, systemLocked: true, busy: true }));
  }
  assert.ok(disabled("start", { clientStatus: "pending" }));
  assert.ok(disabled("stop", { clientStatus: "" }));
});

test("screen on/off and wake are mutually exclusive across pending transitions", () => {
  assert.ok(enabled("sleep"));
  assert.ok(disabled("wakeup"));
  assert.ok(disabled("sleep", { sleeping: true }));
  assert.ok(enabled("wakeup", { sleeping: true }));
  assert.ok(disabled("wakeup", { sleeping: true, wakeInProgress: true }));
  assert.ok(disabled("wakeup", { sleeping: true, pendingAction: "wakeup", busy: true }));
  assert.ok(disabled("start", { sleeping: true }));
  assert.ok(disabled("stop", { sleeping: true }));
  assert.ok(disabled("reboot", { sleeping: true }));
  assert.ok(disabled("shutdown", { sleeping: true }));
  assert.ok(disabled("sleep", { pendingAction: "sleep", busy: true }));
});

test("start/stop uses canonical browser process and desired state", () => {
  assert.ok(disabled("start", { chromeRunning: true }));
  assert.ok(enabled("start", { chromeRunning: false, browserRequested: true }));
  assert.ok(enabled("stop", { chromeRunning: false, browserRequested: true }));
  assert.ok(enabled("stop", { chromeRunning: false, browserRequested: null }));
  assert.ok(enabled("stop", { chromeRunning: true, browserRequested: false }), "stray browser process must remain stoppable");
  assert.ok(disabled("stop", { chromeRunning: false, browserRequested: false }));
});

test("button clicks recheck matrix and synchronously lock before awaiting the API", () => {
  const src = readFileSync(new URL("../src/pages/clientdetailspage/ClientDetailsActionsSection.jsx", import.meta.url), "utf8");
  assert.match(src, /getActionDisabledInfo\(action\)/);
  assert.match(src, /inFlightActionRef\.current = action;[\s\S]*?await handleClientAction\(action\)/);
  assert.match(src, /inFlightActionRef\.current = null;/);
  assert.match(src, /pendingReboot === true \|\|/);
  assert.match(src, /pendingShutdown === true \|\|/);
  assert.match(src, /controlRoomActionDecision\(key, \{/);
  assert.match(src, /size=\{isTouchHandset \? 6 : 12\}/);
  assert.match(src, /"@media \(hover: none\) and \(pointer: coarse\) and \(min-width: 600px\) and \(max-width: 1023\.95px\)"/);
  assert.match(src, /isSuperadmin\s*\?\s*row2Admin/);
  assert.match(src, /isAdministrator[\s\S]*?row2Admin\.filter/);
  assert.match(src, /const supportButtons = isSuperadmin \? row2Superadmin : \[\]/);
});

test("Control Room matrix maps to backend-authorized canonical commands", () => {
  const backend = readFileSync(new URL("../../backend/service1/routers/clients.py", import.meta.url), "utf8");
  const local = readFileSync(new URL("../../client/runtime/clientflow_runtime/display_local_control.py", import.meta.url), "utf8");
  assert.match(backend, /USER_CHROME_COMMANDS = \{"start", "stop", "reset_browser", "sleep", "wakeup"\}/);
  assert.match(backend, /ADMIN_CHROME_COMMANDS = USER_CHROME_COMMANDS \| \{"reboot"\}/);
  assert.match(backend, /_require_system_action_access\(user, client, action\)/);
  assert.match(backend, /_require_client_operator_access\(user, client, action\)/);
  assert.match(backend, /if action == "start":\s*command_type, payload = "start_browser", \{\}/);
  assert.match(backend, /elif action == "stop":\s*command_type, payload = "stop_browser", \{\}/);
  assert.match(backend, /elif action == "sleep":\s*command_type, payload = "set_display_power", \{"state": "off"\}/);
  assert.match(backend, /command_type, payload = "set_display_power", \{"state": "on"\}/);
  assert.match(local, /if state == "off":\s*# Product contract:[\s\S]*?"action": "stop_browser"[\s\S]*?"action": "display_sleep_countdown"/);
  assert.match(local, /call\(POWER_SOCKET, \{"action": "set_display_power", "state": state\}\)/);
});
