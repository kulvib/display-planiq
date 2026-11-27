import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  browserStatusTone,
  calendarRebootIsActionable,
  currentClientState,
  currentClientStateTone,
  ubuntuInventoryView,
  firmwareInventoryView,
  livestreamDiagnosticsView,
  diagnosticServiceLevel,
  defaultClientflowTarget,
} from "../src/utils/controlRoomPresentation.mjs";

const detail = readFileSync(new URL("../src/pages/clientdetailspage/ClientDetailsPage.jsx", import.meta.url), "utf8");
const diagnostics = readFileSync(new URL("../src/pages/clientdetailspage/ClientDetailsInfoSection.jsx", import.meta.url), "utf8");
const listing = readFileSync(new URL("../src/pages/ClientInfoPage.jsx", import.meta.url), "utf8");

test("header shows only non-normal current action, not historic successful events", () => {
  assert.equal(currentClientState("normal"), null);
  assert.equal(currentClientState("approved"), null);
  assert.equal(currentClientState("rebooting"), "rebooting");
  assert.equal(currentClientStateTone("rebooting"), "warning");
  assert.equal(currentClientStateTone("error"), "error");
  const topbar = detail.slice(detail.indexOf("function ControlRoomTopbar"), detail.indexOf("function SectionTitle"));
  assert.match(topbar, /currentClientState\(clientState\)/);
  assert.match(topbar, /\{currentState && \(/);
  assert.doesNotMatch(topbar, /last_power_event|formatPowerEventLabel|powerEventColor/);
  assert.match(diagnostics, /title: "Lifecycle \/ strøm"/);
  assert.match(diagnostics, /label: "Seneste hændelse", value: lifecycleEventLabel/);
});

test("browser color is honest for disconnected, unknown, error and verified OK", () => {
  assert.equal(browserStatusTone(false, "green", "Chrome kører"), "default");
  assert.equal(browserStatusTone(true, "green", "Browserstatus ukendt"), "default");
  assert.equal(browserStatusTone(true, "green", "stale"), "default");
  assert.equal(browserStatusTone(true, "green", "Chrome kører"), "success");
  assert.equal(browserStatusTone(true, "orange", "Starter"), "warning");
  assert.equal(browserStatusTone(true, "red", "Fejl"), "error");
  assert.equal(browserStatusTone(true, "blue", "Aktiverer"), "info");
  assert.equal(browserStatusTone(true, null, "Chrome kører"), "default");
  assert.match(detail, /browserStatusTone\(clientOnline, client\?\.chrome_color, browserLabel\)/);
  assert.match(listing, /browserStatusTone\(isOnline, browserColor, browserStatus\)/);
  assert.doesNotMatch(listing.slice(listing.indexOf("const ClientStatusCell"), listing.indexOf("const ClientHealthCell")), /:\s*"success";/);
});

test("calendar status warns only about current pending or failure; history is retained", () => {
  assert.equal(calendarRebootIsActionable({ state: "completed", source: "calendar" }), false);
  assert.equal(calendarRebootIsActionable({ state: "not_scheduled" }), false);
  assert.equal(calendarRebootIsActionable({ state: "pending" }), true);
  assert.equal(calendarRebootIsActionable({ state: "error" }), true);
  assert.equal(calendarRebootIsActionable(null), false);
  assert.match(detail, /calendarRebootIsActionable\(client\?\.calendar_daily_reboot\)/);
  assert.match(diagnostics, /label: "Kalendergenstart", value: dailyReboot.label/);
});

test("diagnostics prioritizes issues and preserves all details behind accessible disclosures", () => {
  assert.match(diagnostics, /const \[showOverviewDetails, setShowOverviewDetails\] = React.useState\(false\)/);
  assert.match(diagnostics, /aria-expanded=\{showOverviewDetails\}/);
  assert.match(diagnostics, /showOverviewDetails && \(/);
  assert.match(diagnostics, /overviewSections.map\(renderSection\)/);
  assert.match(diagnostics, /aria-expanded=\{showTechnicalDetails\}/);
  assert.match(diagnostics, /technicalSections.map\(renderSection\)/);
  assert.match(diagnostics, /serviceSummary.unverified > 0/);
  assert.match(diagnostics, /Synlig for superadministratorer og brugere med Se-adgang/);
  assert.match(diagnostics, /const canViewDiagnostics = isSuperadmin \|\| isViewer/);
  assert.equal((diagnostics.match(/\{ label: "Diagnostik opdateret"/g) || []).length, 0);
});

test("mobile client overview preserves access to all data with discoverable scrolling", () => {
  assert.match(listing, /Oversigten kan rulles vandret/);
  assert.match(listing, /WebkitOverflowScrolling: "touch"/);
  assert.match(detail, /overflowWrap: "anywhere"/);
  assert.match(detail, /maxWidth: "100%", minWidth: 0/);
});


test("System, Network and Diagnostics retain technical details without false current status", () => {
  assert.match(diagnostics, /Tekniske driftsoplysninger/);
  assert.match(diagnostics, /NetworkPanel client=\{client\} clientOnline=\{clientOnline\}/);
  assert.match(diagnostics, /Senest rapporteret · ikke aktuel/);
  assert.match(diagnostics, /Tekniske netværksoplysninger/);
  assert.match(diagnostics, /onlineValue !== true && onlineValue !== false/);
  assert.ok(diagnostics.indexOf("Kræver opmærksomhed") < diagnostics.indexOf("summaryCards.map(renderSummaryCard)"));
  assert.match(diagnostics, /Faktiske ClientFlow-opdateringstrin/);
});


test("calendar rolls its seven-day view forward at midnight without another network timer", () => {
  assert.match(diagnostics, /calendarDayStart = startOfLocalDay\(now\)\.getTime\(\)/);
  assert.match(diagnostics, /const base = new Date\(calendarDayStart\)/);
  assert.match(diagnostics, /\[markedDays, calendarDayStart\]/);
});


test("Control Room overview distinguishes a failed inventory read from verified empty data", () => {
  assert.match(listing, /setClientListStatus\("error"\)/);
  assert.match(listing, /setClientListStatus\("ready"\)/);
  assert.match(listing, /Klientlisten kunne ikke opdateres/);
  assert.match(listing, /clientListStatus !== "ready" \? "Afventer verificeret klientliste\."/);
  assert.match(listing, /presence\?\.is_online === false/);
  assert.match(listing, /aria-expanded=\{trashExpanded\}/);
});

test("operational inventory never substitutes a stale legacy package count", () => {
  const client = { presence: { is_online: true }, ubuntu_updates_available: 69 };
  assert.equal(ubuntuInventoryView(client).count, null);
  const known = { ...client, ubuntu_update_inventory: { state: "known", update_count: 69 } };
  assert.equal(ubuntuInventoryView(known).label, "69 pakker klar");
  assert.equal(ubuntuInventoryView({ ...known, presence: { is_online: false } }).count, null);
  assert.equal(ubuntuInventoryView({ ...client, ubuntu_update_inventory: { state: "known", update_count: 0 } }).label, "Ingen opdateringer");
  assert.equal(ubuntuInventoryView({ ...known, ubuntu_update_inventory: { state: "stale", update_count: 69 } }).count, null);
});
test("missing and standby services are not falsely classified as failed", () => {
  assert.equal(diagnosticServiceLevel(null), "neutral");
  assert.equal(diagnosticServiceLevel("inactive", { expectedActive: false }), "ok");
  assert.equal(diagnosticServiceLevel("inactive"), "error");
  assert.equal(diagnosticServiceLevel("failed", { expectedActive: false }), "error");
  assert.equal(diagnosticServiceLevel("active", { online: false }), "neutral");
});
test("newer installed release never defaults to a downgrade", () => {
  const releases = [{version: "1.3.44"}];
  assert.equal(defaultClientflowTarget("1.4.0", "1.3.44", releases), "");
  assert.equal(defaultClientflowTarget("1.3.43", "1.3.44", releases), "1.3.44");
  assert.equal(defaultClientflowTarget("1.3.44", "1.3.44", []), "");
});


test("firmware inventory distinguishes zero, available, stale, offline and inconsistent evidence", () => {
  const base = { presence: { is_online: true, system: { is_online: true } },
    firmware: { supported: true, stale: false, error: null, update_count: 0, update_available: false } };
  assert.equal(firmwareInventoryView(base).count, 0);
  assert.equal(firmwareInventoryView(base).level, "ok");
  assert.equal(firmwareInventoryView({ ...base, firmware: { ...base.firmware, update_count: 3, update_available: true } }).count, 3);
  assert.equal(firmwareInventoryView({ ...base, firmware: { ...base.firmware, stale: true } }).count, null);
  assert.equal(firmwareInventoryView({ ...base, firmware: { ...base.firmware, update_count: 3 } }).count, null);
  assert.equal(firmwareInventoryView({ ...base, presence: { is_online: true, system: { is_online: false } } }).count, null);
  assert.equal(firmwareInventoryView({ ...base, firmware: null }).count, null);
});


test("Livestream diagnostics do not confuse process, generation and recent media", () => {
  const live = { generation_state: "running", generation_current: true, agent_fresh: true, producer_state: "running", media_recent: true };
  assert.equal(livestreamDiagnosticsView(live).level, "ok");
  assert.equal(livestreamDiagnosticsView(live).processLevel, "ok");
  assert.equal(livestreamDiagnosticsView({ ...live, media_recent: false }).level, "warn");
  assert.equal(livestreamDiagnosticsView({ ...live, agent_fresh: false }).processLevel, "neutral");
  assert.equal(livestreamDiagnosticsView({ ...live, generation_current: false, generation_state: "stopped" }).processLevel, "neutral");
  assert.equal(livestreamDiagnosticsView(null).level, "neutral");
  assert.match(diagnostics, /livestream-diagnostics/);
  assert.match(diagnostics, /window.setTimeout\(load, 30_000\)/);
  assert.doesNotMatch(diagnostics, /formatDiagnosticDate\(client\?\.livestream_last_segment\)/);
});


test("Control Room data panels, inner sections and fields have explicit distinct surfaces", () => {
  assert.match(diagnostics, /className="control-room-data-panel"/);
  assert.match(detail, /\.MuiCard-root\.control-room-data-panel[\s\S]*?rgba\(148,163,184,0\.36\)/);
  assert.match(diagnostics, /const sectionSx = [^\n]*rgba\(15,23,42,0\.72\)[^\n]*rgba\(148,163,184,0\.24\)/);
  assert.match(diagnostics, /MuiInputBase-root[^\n]*rgba\(2,6,23,0\.48\)/);
  assert.match(diagnostics, /Mui-focused \.MuiOutlinedInput-notchedOutline/);
});

test("diagnostics names unverified rows without converting them to errors or OK", () => {
  assert.match(diagnostics, /const unverifiedServiceRows = serviceRows\.filter/);
  assert.match(diagnostics, /!\["ok", "warn", "error"\]\.includes\(serviceLevels\[index\]\)/);
  assert.match(diagnostics, /unverifiedServiceRows\.map\(\(row\) => row\.label\)\.join/);
});
