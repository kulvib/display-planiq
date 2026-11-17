import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const read = (name) => fs.readFileSync(new URL(`../src/${name}`, import.meta.url), "utf8");
test("public maintenance checks use same-origin without CORS on Render-generated 502", () => {
  const api = read("auth/maintenanceApi.js");
  assert.match(api, /fetch\("\/api\/maintenance\/status"/);
  assert.doesNotMatch(api, /\$\{apiUrl\}\/api\/maintenance\/status/);
  assert.match(api, /cache: "no-store"/);
  assert.match(api, /credentials: "include"/);
  const render = fs.readFileSync(new URL("../../render.yaml", import.meta.url), "utf8");
  assert.match(render, /source: \/api\/\*/);
  assert.match(render, /destination: https:\/\/api\.display\.planiq\.dk\/api\/\*/);
});

test("maintenance gate does not trust cached open state after 502 and retries bounded", () => {
  const gate = read("auth/MaintenanceGate.jsx");
  assert.match(gate, /if \(statusError\) return <StatusError/);
  assert.match(gate, /Math\.min\(60_000, 5_000/);
  assert.match(gate, /window\.setTimeout\(\(\) => void refresh\(\), delayMs\)/);
  assert.match(gate, /setFailureCount\(0\)/);
});

test("a gateway 502 is distinct from rejected credentials; authentication is not retried automatically", () => {
  const login = read("LoginPage.jsx");
  assert.match(login, /status >= 500/);
  assert.match(login, /Login blev ikke gennemført/);
  assert.doesNotMatch(login, /retryLoginAfter502/);
});
