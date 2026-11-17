import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (relative) => readFileSync(new URL(`../${relative}`, import.meta.url), "utf8");
const { decodedAccessTokenExpiryMs, needsProactiveRefresh } = await import("../src/api/tokenTiming.mjs");
const sessionSyncSource = read("src/auth/sessionSync.js");
const sync = await import(`data:text/javascript,${encodeURIComponent(sessionSyncSource)}`);
const SID = "a".repeat(32);
const OTHER = "b".repeat(32);
const NOW = Date.now();
const msg = (type, sessionId = SID, extra = {}) => ({
  type, sessionId, source: "other-browser-tab", writtenAt: NOW, ...extra,
});

test("only matching, fresh logout from SAME session can end another tab", () => {
  assert.equal(sync.isCurrentSessionEvent(msg("logout", SID, { reason: "idle" }), SID, NOW), true);
  assert.equal(sync.isCurrentSessionEvent(msg("logout", OTHER, { reason: "idle" }), SID, NOW), false);
  assert.equal(sync.isCurrentSessionEvent(msg("logout", SID, { reason: "idle", writtenAt: NOW - 100000 }), SID, NOW), false);
  assert.equal(sync.isCurrentSessionEvent(msg("logout", SID, { reason: "mystery" }), SID, NOW), false);
  assert.equal(sync.isCurrentSessionEvent(msg("logout", SID, { reason: "idle" }), null, NOW), false);
});

test("cross-tab activity cannot extend a different session", () => {
  assert.equal(sync.isCurrentSessionEvent(msg("activity", SID, { at: NOW }), SID, NOW), true);
  assert.equal(sync.isCurrentSessionEvent(msg("activity", OTHER, { at: NOW }), SID, NOW), false);
  assert.equal(sync.isCurrentSessionEvent(msg("activity", SID, { at: NOW + 100000 }), SID, NOW), false);
});

test("context changes only cause a new server validation; never authorize an action", () => {
  assert.equal(sync.isCurrentSessionEvent(msg("context", OTHER), SID, NOW), true);
  assert.equal(sync.isCurrentSessionEvent(msg("strange", SID), SID, NOW), false);
});

test("exp decoding is best-effort only, and pre-expiry check has a one-minute window", () => {
  const now = Date.now();
  const exp = Math.floor((now + 15 * 60_000) / 1000);
  const token = ["header", Buffer.from(JSON.stringify({ exp })).toString("base64url"), "signature"].join(".");
  assert.equal(decodedAccessTokenExpiryMs(token), exp * 1000);
  assert.equal(decodedAccessTokenExpiryMs("invalid"), null);
  assert.equal(decodedAccessTokenExpiryMs("a.notjson.b"), null);
  assert.equal(needsProactiveRefresh(exp * 1000, now), false);
  assert.equal(needsProactiveRefresh(now + 45_000, now), true);
  assert.equal(needsProactiveRefresh(null, now), false);
});

test("API uses pre-expiry single-flight refresh for both transports, not background polling", () => {
  const api = read("src/api/api.js");
  const client = read("src/api/client.js");
  assert.match(api, /export async function ensureFreshAuthToken\(signal\)/);
  assert.match(api, /needsProactiveRefresh\(accessTokenExpiresAtMs\)/);
  assert.match(api, /await refreshAccessToken\(\)/);
  assert.match(api, /if \(requiresSession\) \{[\s\S]*await ensureFreshAuthToken\(signal\)/);
  assert.match(client, /await ensureFreshAuthToken\(signal\)/);
  assert.match(api, /if \(first\.status !== 401[\s\S]*await refreshAccessToken\(\)/);
  assert.doesNotMatch(api, /setInterval\(refreshAccessToken/);
});

test("transient Render auth failure stays fail-closed without clearing session", () => {
  const api = read("src/api/api.js");
  const provider = read("src/auth/authcontext.jsx");
  assert.match(api, /if \(isTerminalSessionRefreshError\(error\)\) return false/);
  assert.match(provider, /setBootUnavailable\(true\)/);
  assert.match(provider, /Ingen beskyttede sider vises/);
  assert.match(provider, /setBootAttempt\(\(previous\) => previous \+ 1\)/);
});

test("HEAD /health is explicitly supported and does not require database", () => {
  const main = readFileSync(new URL("../../backend/service1/main.py", import.meta.url), "utf8");
  assert.match(main, /@app\.head\("\/health", include_in_schema=False\)/);
  assert.match(main, /@app\.get\("\/health"\)[\s\S]*def health\(\):\s*return \{"status": "ok"\}/);
  assert.match(main, /def head_health\(\):[\s\S]*return Response\(status_code=200\)/);
});
