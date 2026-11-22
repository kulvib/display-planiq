import assert from "node:assert/strict";
import test from "node:test";

if (!globalThis.WebSocket) {
  globalThis.WebSocket = { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 };
}

const { createHttpRelaySocket, createWebSocketWithHttpsFallback } = await import(
  "../src/api/httpRelaySocket.js"
);

function tick() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

test("HTTPS relay serializes JSON sends and closes cleanly", async () => {
  const sent = [];
  let closed = 0;
  let polls = 0;
  let releaseSecondPoll;
  const secondPollGate = new Promise((resolve) => { releaseSecondPoll = resolve; });
  const socket = createHttpRelaySocket({
    relayId: "relay-1",
    sendPayload: async (payload) => {
      await tick();
      sent.push(payload);
    },
    pollMessages: async () => {
      polls += 1;
      if (polls === 1) return { messages: [JSON.stringify({ type: "hello" })], closed: false };
      await secondPollGate;
      return { messages: [], closed: true };
    },
    closeRelay: async () => { closed += 1; },
  });

  const messages = [];
  socket.onmessage = (event) => messages.push(JSON.parse(event.data));
  await tick();
  assert.equal(socket.readyState, WebSocket.OPEN);
  socket.send(JSON.stringify({ sequence: 1 }));
  socket.send(JSON.stringify({ sequence: 2 }));
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.deepEqual(sent, [{ sequence: 1 }, { sequence: 2 }]);
  assert.deepEqual(messages, [{ type: "hello" }]);
  releaseSecondPoll();
  await tick();
  assert.equal(socket.readyState, WebSocket.CLOSED);
  assert.equal(closed, 1);
});

test("transport fails over from WSS to HTTPS without changing message interface", async () => {
  const wss = {
    readyState: WebSocket.CONNECTING,
    onopen: null,
    onmessage: null,
    onclose: null,
    onerror: null,
    send() {},
    close() {},
  };
  let fallbackOpened = 0;
  const fallback = {
    readyState: WebSocket.CONNECTING,
    onopen: null,
    onmessage: null,
    onclose: null,
    onerror: null,
    sent: [],
    send(raw) { this.sent.push(raw); },
    close() {},
  };
  const wrapper = createWebSocketWithHttpsFallback({
    openWebSocket: () => wss,
    openHttpsRelay: async () => {
      fallbackOpened += 1;
      return fallback;
    },
  });

  let opens = 0;
  const received = [];
  wrapper.onopen = () => { opens += 1; };
  wrapper.onmessage = (event) => received.push(event.data);

  wss.onclose?.({ code: 1006, reason: "upgrade_blocked", wasClean: false });
  await tick();
  assert.equal(fallbackOpened, 1);
  assert.equal(wrapper.transport, "https_long_poll");

  fallback.readyState = WebSocket.OPEN;
  fallback.onopen?.();
  assert.equal(wrapper.readyState, WebSocket.OPEN);
  assert.equal(opens, 1);
  wrapper.send(JSON.stringify({ type: "input", data: "x" }));
  assert.equal(fallback.sent.length, 1);
  fallback.onmessage?.({ data: JSON.stringify({ type: "output", data: "ok" }) });
  assert.equal(received.length, 1);
});


test("blocked WSS upgrade is transparent when HTTPS fallback succeeds", async () => {
  const wss = {
    readyState: WebSocket.CONNECTING, onopen: null, onmessage: null, onclose: null, onerror: null,
    send() {}, close() {},
  };
  const fallback = {
    readyState: WebSocket.CONNECTING, onopen: null, onmessage: null, onclose: null, onerror: null,
    send() {}, close() {},
  };
  const wrapper = createWebSocketWithHttpsFallback({
    openWebSocket: () => wss,
    openHttpsRelay: async () => fallback,
  });
  let visibleErrors = 0;
  wrapper.onerror = () => { visibleErrors += 1; };

  wss.onerror?.(new Error("upgrade blocked"));
  wss.onclose?.({ code: 1006, reason: "upgrade blocked", wasClean: false });
  await tick();
  fallback.readyState = WebSocket.OPEN;
  fallback.onopen?.();

  assert.equal(wrapper.transport, "https_long_poll");
  assert.equal(wrapper.readyState, WebSocket.OPEN);
  assert.equal(visibleErrors, 0);
});

test("HTTPS relay coalesces only adjacent pending mouse moves, never clicks or keys", async () => {
  const sent = [];
  let resolveFirst;
  const firstGate = new Promise((resolve) => { resolveFirst = resolve; });
  let releasePoll;
  const pollGate = new Promise((resolve) => { releasePoll = resolve; });
  const socket = createHttpRelaySocket({
    relayId: "rd-mouse",
    sendPayload: async (payload) => {
      sent.push(payload);
      if (sent.length === 1) await firstGate;
    },
    pollMessages: () => pollGate,
    closeRelay: async () => {},
  });
  await tick();
  const send = (payload) => socket.send(JSON.stringify(payload));
  send({ type: "mouse", action: "move", x: 1, dragging: false }); // in flight
  send({ type: "mouse", action: "move", x: 2, dragging: false }); // pending
  send({ type: "mouse", action: "move", x: 3, dragging: false }); // replace pending
  send({ type: "mouse", action: "down", button: 1 });
  send({ type: "mouse", action: "move", x: 4, dragging: true });
  send({ type: "mouse", action: "move", x: 5, dragging: true });
  send({ type: "mouse", action: "up", button: 1 });
  send({ type: "key", key: "Escape" });
  resolveFirst();
  await tick();
  await tick();
  assert.deepEqual(sent, [
    { type: "mouse", action: "move", x: 1, dragging: false },
    { type: "mouse", action: "move", x: 3, dragging: false },
    { type: "mouse", action: "down", button: 1 },
    { type: "mouse", action: "move", x: 5, dragging: true },
    { type: "mouse", action: "up", button: 1 },
    { type: "key", key: "Escape" },
  ]);
  releasePoll({ messages: [], closed: true });
  await tick();
});

test("HTTPS relay aborts pending input after a send failure", async () => {
  let closeCount = 0;
  let releasePoll;
  const pollGate = new Promise((resolve) => { releasePoll = resolve; });
  const sent = [];
  const socket = createHttpRelaySocket({
    relayId: "rd-send-failure",
    sendPayload: async (message) => { sent.push(message); throw new Error("offline"); },
    pollMessages: () => pollGate,
    closeRelay: async () => { closeCount++; },
  });
  await tick();
  socket.send(JSON.stringify({ type: "mouse", action: "down" }));
  socket.send(JSON.stringify({ type: "mouse", action: "up" }));
  await tick();
  assert.deepEqual(sent, [{ type: "mouse", action: "down" }]);
  assert.equal(closeCount, 1);
  assert.equal(socket.readyState, WebSocket.CLOSED);
  releasePoll({ messages: [], closed: true });
});

test("63D-8 HTTPS input diagnostics are local and preserve button/key order", async () => {
  const sent = [];
  let releaseFirst;
  const gate = new Promise((resolve) => { releaseFirst = resolve; });
  let releasePoll;
  const poll = new Promise((resolve) => { releasePoll = resolve; });
  const socket = createHttpRelaySocket({
    relayId: "metric-only", pollMessages: () => poll,
    sendPayload: async (payload) => {
      sent.push(payload);
      if (sent.length === 1) await gate;
    },
    closeRelay: async () => {},
  });
  await tick();
  for (const x of [1,2,3]) socket.send(JSON.stringify({ type: "mouse", action: "move", x }));
  socket.send(JSON.stringify({ type: "mouse", action: "down", button: 1 }));
  socket.send(JSON.stringify({ type: "mouse", action: "up", button: 1 }));
  const before = socket.getDiagnostics();
  assert.equal(before.replacedMoves, 1);
  assert.equal(before.pending, 3);
  assert.equal(before.sending, true);
  releaseFirst();
  await tick(); await tick();
  assert.deepEqual(sent.map((p) => p.action), ["move", "move", "down", "up"]);
  assert.equal(socket.getDiagnostics().pending, 0);
  assert.equal(socket.getDiagnostics().sentCount, 4);
  releasePoll({ messages: [], closed: true });
  await tick();
});

test("63D-33 HTTPS input queue closes instead of dropping releases when saturated", async () => {
  let releaseFirst;
  const first = new Promise((resolve) => { releaseFirst = resolve; });
  let releasePoll;
  const poll = new Promise((resolve) => { releasePoll = resolve; });
  const sent = [];
  let closed = 0;
  const socket = createHttpRelaySocket({
    relayId: "rd-bounded",
    sendPayload: async (payload) => {
      sent.push(payload);
      if (sent.length === 1) await first;
    },
    pollMessages: async () => poll,
    closeRelay: async () => { closed++; },
  });
  await tick();
  socket.send(JSON.stringify({ type: "mouse", action: "down", button: 1 }));
  // First request is in-flight; all following inputs are preserved in FIFO.
  for (let i = 0; i < 128; i++) {
    socket.send(JSON.stringify({ type: "key", key: "x", index: i }));
  }
  assert.equal(socket.getDiagnostics().pending, 128);
  assert.throws(() => socket.send(JSON.stringify({ type: "mouse", action: "up", button: 1 })), /saturated/);
  await tick();
  assert.equal(socket.getDiagnostics().overflowClosures, 1);
  assert.equal(socket.readyState, WebSocket.CLOSED);
  assert.equal(closed, 1);
  assert.equal(socket.getDiagnostics().pending, 0);
  releaseFirst();
  releasePoll({ messages: [], closed: true });
  await tick();
  assert.deepEqual(sent, [{ type: "mouse", action: "down", button: 1 }]);
});

test("63D-33 HTTPS queue tracks UTF-8 bytes and rejects oversized unicode payload", async () => {
  let releasePoll;
  const poll = new Promise((resolve) => { releasePoll = resolve; });
  const socket = createHttpRelaySocket({
    relayId: "rd-byte-limit",
    sendPayload: async () => {},
    pollMessages: () => poll,
    closeRelay: async () => {},
  });
  await tick();
  assert.throws(
    () => socket.send(JSON.stringify({ type: "key", value: "ø".repeat(270_000) })),
    /saturated/,
  );
  assert.equal(socket.getDiagnostics().pending, 0);
  assert.equal(socket.getDiagnostics().overflowClosures, 1);
  releasePoll({ messages: [], closed: true });
  await tick();
});

test("63D-33 HTTPS timing diagnostics contain no payload and report poll/send timing", async () => {
  let releasePoll;
  const poll = new Promise((resolve) => { releasePoll = resolve; });
  let now = 0;
  const old = Date.now;
  Date.now = () => (now += 9);
  try {
    const socket = createHttpRelaySocket({
      relayId: "rd-timing",
      sendPayload: async () => {},
      pollMessages: async () => poll,
      closeRelay: async () => {},
    });
    await tick();
    socket.send(JSON.stringify({ type: "key", key: "secret-should-not-enter-metrics" }));
    await tick();
    releasePoll({ messages: [], closed: true });
    await tick();
    const metrics = socket.getDiagnostics();
    assert.equal(metrics.sentCount, 1);
    assert.equal(metrics.lastSendDurationMs, 9);
    assert.equal(metrics.maxSendDurationMs, 9);
    assert.equal(metrics.maxPollDurationMs, 9);
    assert.equal(JSON.stringify(metrics).includes("secret-should-not-enter-metrics"), false);
    assert.equal(metrics.pendingBytes, 0);
  } finally {
    Date.now = old;
  }
});
