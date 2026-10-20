import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  browserStatusTone,
  calendarRebootIsActionable,
  currentClientState,
  currentClientStateTone,
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
