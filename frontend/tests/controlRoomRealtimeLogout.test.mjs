import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { createRealtimeRequestScope } from "../src/utils/controlRoomRealtimeLifecycle.mjs";
import { createServer } from "vite";

const frontendRoot = new URL("..", import.meta.url).pathname;
const json = (value, status = 200) => new Response(JSON.stringify(value), {
  status,
  headers: { "Content-Type": "application/json" },
});

let server;
let api;
let fetchHandler;
const requests = [];

before(async () => {
  process.env.VITE_API_URL = "https://api.display.planiq.dk";
  process.env.VITE_WS_API_URL = "https://api.display.planiq.dk";
  globalThis.window = {
    location: { origin: "https://display.planiq.dk", href: "https://display.planiq.dk/clients" },
  };
  globalThis.localStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
  globalThis.fetch = (...args) => {
    requests.push({ url: String(args[0]), init: args[1] || {} });
    return fetchHandler(...args);
  };
  server = await createServer({
    root: frontendRoot,
    logLevel: "silent",
    appType: "custom",
    server: { middlewareMode: true },
  });
  api = await server.ssrLoadModule("/src/api/api.js");
});

after(async () => {
  await server?.close();
});

test("a failed wait does not refresh the ordinary login or replace the scoped bearer token", async () => {
  requests.length = 0;
  api.setAuthToken("login-token");
  fetchHandler = async (input) => {
    if (String(input).includes("/control-room-realtime/wait?")) return json({ detail: "expired capability" }, 401);
    throw new Error(`Unexpected URL ${input}`);
  };
  await assert.rejects(() => api.waitForControlRoomRealtime("scoped-token", 4, 25), (error) => error.status === 401);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].init.headers.Authorization, "Bearer scoped-token");
  assert.equal(requests[0].init.credentials, "omit");
  assert.equal(api.getAuthToken(), "login-token");
});

test("502 from upstream retains the status for bounded transport recovery", async () => {
  requests.length = 0;
  fetchHandler = async () => json({ detail: "upstream failed" }, 502);
  await assert.rejects(() => api.waitForControlRoomRealtime("scoped-token", 4, 25), (error) => {
    assert.equal(error.status, 502);
    assert.equal(error.kind, "server");
    return true;
  });
  assert.equal(requests.length, 1);
});

test("logout aborts an in-flight realtime long-poll; subsequent login gets a new signal", async () => {
  api.setAuthToken("login-token");
  const oldAuthSignal = api.getAuthSessionSignal();
  const scope = createRealtimeRequestScope(oldAuthSignal);
  let onRequestStarted;
  const started = new Promise((resolve) => { onRequestStarted = resolve; });
  fetchHandler = (_input, init) => new Promise((_resolve, reject) => {
    init.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
    onRequestStarted();
  });
  const poll = api.waitForControlRoomRealtime("scoped-token", 4, 25, scope.signal);
  await started;
  api.clearAuthToken();
  assert.equal(oldAuthSignal.aborted, true);
  assert.equal(scope.signal.aborted, true);
  await assert.rejects(poll, { name: "AbortError" });
  scope.cancel();
  api.setAuthToken("next-login-token");
  assert.notEqual(api.getAuthSessionSignal(), oldAuthSignal);
  assert.equal(api.getAuthSessionSignal().aborted, false);
});

test("a refresh finishing after logout cannot resurrect its old access token", async () => {
  api.setAuthToken("old-token");
  let finishRefresh;
  let refreshStarted;
  const started = new Promise((resolve) => { refreshStarted = resolve; });
  fetchHandler = (input) => {
    if (String(input) === "/api/auth/refresh") {
      refreshStarted();
      return new Promise((resolve) => { finishRefresh = resolve; });
    }
    if (String(input).endsWith("/control-room-realtime/capability")) return Promise.resolve(json({}, 401));
    throw new Error(`Unexpected URL ${input}`);
  };
  const issuing = api.createControlRoomRealtimeCapability();
  await started;
  api.clearAuthToken();
  finishRefresh(json({ access_token: "revoked-token", session_expires_at: "2030-01-01T00:00:00Z" }));
  await assert.rejects(issuing, { name: "AbortError" });
  assert.equal(api.getAuthToken(), "");
  assert.equal(api.getAuthSessionSignal().aborted, true);
});
