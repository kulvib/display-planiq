import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { calendarRebootView } from "../src/pages/clientdetailspage/calendarRebootStatus.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

test("Control Room indicator is explicit about calendar proof and errors", () => {
  assert.match(calendarRebootView({state: "completed", source:"calendar", verified_at:"2026-10-15T05:02:00Z"}).title, /Kalendergenstart verificeret/);
  assert.match(calendarRebootView({state: "completed", source:"other"}).title, /ikke dokumenteret som kalender/);
  assert.equal(calendarRebootView({state: "completed", source: "other"}).label, "Opstart i dag");
  assert.equal(calendarRebootView({state: "completed", source: "calendar"}).label, "Kalendergenstart i dag");
  assert.equal(calendarRebootView({state:"not_scheduled"}).label, "Ingen åbning i dag");
  assert.equal(calendarRebootView({state:"error"}).color, "error");
  assert.equal(calendarRebootView(null).label, "Genstart ukendt");
});

test("Control Room reuses already fetched client summary; no additional fetch", () => {
  const page = fs.readFileSync(path.join(root, "src/pages/ClientInfoPage.jsx"), "utf8");
  assert.match(page, /<CalendarRebootIndicator client=\{client\}/);
  assert.equal((page.match(/<CalendarRebootIndicator client=\{client\}/g) || []).length, 2);
  assert.match(page, /ca\.calendar_daily_reboot\?\.state/);
  const marker = page.slice(page.indexOf("const CalendarRebootIndicator"), page.indexOf("const CopyIconButton"));
  assert.doesNotMatch(marker, /fetch\(|getClient\(|getControlRoomClients\(/);
});
