import assert from "node:assert/strict";
import test from "node:test";
import { receiveBrowserCountdown, browserCountdownSeconds, formatBrowserCountdownStatus } from "../src/pages/clientdetailspage/browserCountdown.mjs";
import { readFileSync } from "node:fs";

const sample = (seconds = 10, reason = "system_start", step = "countdown") => ({
  remaining_seconds: seconds,
  reason,
  step,
  ends_at: "2026-10-12T16:00:10Z",
  server_now: "2026-10-12T16:00:00Z",
});

test("counts down locally on elapsed time with no network requests", () => {
  const snapshot = receiveBrowserCountdown(sample(), 10_000);
  assert.equal(formatBrowserCountdownStatus(snapshot, 10_000), "Kiosk browser starter om 10 sekunder…");
  assert.equal(browserCountdownSeconds(snapshot, 11_001), 9);
  assert.equal(browserCountdownSeconds(snapshot, 17_050), 3);
  assert.equal(formatBrowserCountdownStatus(snapshot, 19_050), "Kiosk browser starter om 1 sekund…");
  assert.equal(formatBrowserCountdownStatus(snapshot, 20_000), "Afventer ny browserstatus fra klienten…");
});

test("corrects for client/browser clock differences with server-supplied times", () => {
  const snapshot = receiveBrowserCountdown({ ...sample(6), server_now: "2026-10-12T16:00:04Z" }, 5_000_000);
  assert.equal(browserCountdownSeconds(snapshot, 5_000_000), 6);
  assert.equal(browserCountdownSeconds(snapshot, 5_002_000), 4);
});

test("displays the correct reason without implying the countdown finished successfully", () => {
  const reset = receiveBrowserCountdown({ ...sample(), reason: "reset_browser" }, 0);
  assert.equal(formatBrowserCountdownStatus(reset, 0), "Kiosk browser nulstilles — starter om 10 sekunder…");
  const sleep = receiveBrowserCountdown({ ...sample(), reason: "display_power_off", step: "display_sleep_countdown" }, 0);
  assert.equal(formatBrowserCountdownStatus(sleep, 0), "Skærm slukkes om 10 sekunder…");
  const change = receiveBrowserCountdown({ ...sample(), reason: "configuration_change" }, 0);
  assert.equal(formatBrowserCountdownStatus(change, 0), "Kiosk browser starter ved URL-skift om 10 sekunder…");
});

test("invalid, stale or future countdown data never starts a local clock", () => {
  assert.equal(receiveBrowserCountdown(null, 0), null);
  assert.equal(receiveBrowserCountdown(sample(11), 0), null);
  assert.equal(receiveBrowserCountdown({ ...sample(), remaining_seconds: "10" }, 0), null);
  assert.equal(receiveBrowserCountdown({ ...sample(), server_now: "2026-10-12T16:00:11Z" }, 0), null);
  assert.equal(receiveBrowserCountdown({ ...sample(), server_now: "2026-10-12T15:59:00Z" }, 0), null);
  assert.equal(receiveBrowserCountdown({ ...sample(), ends_at: "invalid" }, 0), null);
});

test("the UI reuses existing chrome-status polling and releases its local timer", () => {
  const src = readFileSync(new URL("../src/pages/clientdetailspage/ClientDetailsPage.jsx", import.meta.url), "utf8");
  assert.match(src, /receiveBrowserCountdown\(data\?\.browser_countdown, Date\.now\(\)\)/);
  assert.match(src, /snapshot \? \{ \.\.\.snapshot, clientId: client.id \} : null/);
  assert.match(src, /window\.clearInterval\(interval\)/);
  assert.match(src, /document\.addEventListener\("visibilitychange", tick\)/);
  assert.match(src, /chrome_status: visibleChromeStatus/);
  assert.doesNotMatch(src, /getChromeStatus\(client\.id\)[\s\S]{0,50}setInterval/);
});
