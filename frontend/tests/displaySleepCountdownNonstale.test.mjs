import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { receiveBrowserCountdown, formatBrowserCountdownStatus } from "../src/pages/clientdetailspage/browserCountdown.mjs";

const sleepReport = {
  remaining_seconds: 10, reason: "display_power_off", step: "display_sleep_countdown",
  ends_at: "2026-10-13T12:00:10Z", server_now: "2026-10-13T12:00:00Z",
};

test("display sleep counts down based on the same server deadline in both views", () => {
  const snap = receiveBrowserCountdown(sleepReport, 100_000);
  assert.equal(formatBrowserCountdownStatus(snap, 100_000), "Skærm slukkes om 10 sekunder…");
  assert.equal(formatBrowserCountdownStatus(snap, 109_200), "Skærm slukkes om 1 sekund…");
  assert.equal(formatBrowserCountdownStatus(snap, 110_001), "Afventer ny browserstatus fra klienten…");
});

test("client list must never show a stale countdown string when the server deadline has expired", () => {
  const list = readFileSync(new URL("../src/pages/ClientInfoPage.jsx", import.meta.url), "utf8");
  const statusCell = list.slice(list.indexOf("const ClientStatusCell"), list.indexOf("const ClientHealthCell"));
  assert.match(statusCell, /\["countdown", "display_sleep_countdown"\]\.includes\(String\(client\?\.chrome_step/);
  assert.match(statusCell, /Afventer ny browserstatus fra klienten…/);
  assert.match(statusCell, /formatBrowserCountdownStatus\(snapshot, clockMs\)/);
  assert.doesNotMatch(statusCell, /getChromeStatus\(|fetch\(|getControlRoomClients\(/);
  const detail = readFileSync(new URL("../src/pages/clientdetailspage/ClientDetailsPage.jsx", import.meta.url), "utf8");
  assert.match(detail, /\["countdown", "display_sleep_countdown"\]\.includes/);
  assert.match(detail, /Afventer ny browserstatus fra klienten…/);
});

test("GTK kiosk copy buttons use a real themed icon and verify clipboard readback", () => {
  const gui = readFileSync(new URL("../../client/libexec/local-gui", import.meta.url), "utf8");
  assert.match(gui, /Gtk\.Button\.new_from_icon_name\("edit-copy-symbolic"\)/);
  assert.match(gui, /clipboard\.set_text\(value\)/);
  assert.match(gui, /clipboard\.read_text_async\(None, on_read\)/);
  assert.match(gui, /actual = _clipboard\.read_text_finish\(result\)/);
  assert.match(gui, /if actual != value:/);
});

test("status on phones remains readable without changing desktop styling", () => {
  const list = readFileSync(new URL("../src/pages/ClientInfoPage.jsx", import.meta.url), "utf8");
  const control = readFileSync(new URL("../src/pages/clientdetailspage/ClientDetailsPage.jsx", import.meta.url), "utf8");
  assert.match(list, /const isMobile = smallViewport \|\| touchHandset/);
  assert.match(list, /"@media \(hover: none\) and \(pointer: coarse\) and \(max-width: 1023\.95px\)"/);
  assert.match(control, /const compactMobile = isMobile \|\| touchHandset/);
  assert.match(control, /\.MuiChip-label.*whiteSpace: "normal"/s);
});
