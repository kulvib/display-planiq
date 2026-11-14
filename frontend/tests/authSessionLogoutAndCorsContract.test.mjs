import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const read = (path) => fs.readFileSync(new URL(`../${path}`, import.meta.url), "utf8");

test("public maintenance GET stays no-store without preflight-triggering request headers", () => {
  const api = read("src/auth/maintenanceApi.js");
  assert.match(api, /\/api\/maintenance\/status/);
  assert.match(api, /cache: "no-store"/);
  assert.doesNotMatch(api, /headers:\s*\{\s*"Cache-Control"/);
  const router = fs.readFileSync(new URL("../../backend/service1/routers/maintenance.py", import.meta.url), "utf8");
  assert.match(router, /no-store, max-age=0/);
});

test("CORS allowlist remains explicit and credentialed, never wildcard", () => {
  const main = fs.readFileSync(new URL("../../backend/service1/main.py", import.meta.url), "utf8");
  assert.match(main, /"https:\/\/display\.planiq\.dk"/);
  assert.match(main, /allow_origins=ALLOWED_ORIGINS/);
  assert.match(main, /allow_credentials=True/);
  assert.doesNotMatch(main, /allow_origins=\["\*"\]/);
});

test("protected requests use session-bound AbortSignal, including retry and centralized client", () => {
  const api = read("src/api/api.js");
  const client = read("src/api/client.js");
  assert.match(api, /AbortSignal\.any\(\[callerSignal, sessionSignal\]\)/);
  assert.match(api, /if \(requiresSession\) assertActiveAuthSession\(signal\)/);
  assert.match(api, /signal\?\.throwIfAborted\?\.\(\)/);
  assert.match(client, /const signal = boundAuthSessionSignal\(config\?\.signal\)/);
  assert.match(client, /signal\.throwIfAborted\(\)/);
});

test("logout aborts prior session requests and refresh cannot revive a logged-out session", () => {
  const api = read("src/api/api.js");
  assert.match(api, /authSessionController\.abort\(\)/);
  assert.match(api, /generationAtStart !== authSessionGeneration/);
  assert.match(api, /authSessionController = new AbortController\(\)/);
});

test("HLS capability health polls stop at logout", () => {
  for (const path of [
    "src/pages/clientdetailspage/ClientDetailsLivestreamSection.jsx",
    "src/pages/adminpages/LivestreamOverview.jsx",
  ]) {
    const source = read(path);
    assert.match(source, /getAuthSessionSignal/);
    assert.match(source, /signal: AbortSignal\.any\(\[getAuthSessionSignal\(\), AbortSignal\.timeout\(/);
  }
});
