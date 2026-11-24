import assert from "node:assert/strict";
import { test } from "node:test";
import { encodeBatch, decodeBatch, NativeHttpsBrowserPeer, MAX_FRAME } from
  "../src/pages/clientdetailspage/remotedesktop/nativeRdpHttpsPeer.mjs";

const sessionId = "12345678-1234-4234-8234-123456789abc";
const ticket = "A".repeat(43);
const peerId = "a".repeat(32);
const empty = new Uint8Array(0);
const opened = new TextEncoder().encode(JSON.stringify({
  peer_id: peerId, upload_sequence: 0, download_sequence: 0,
}));
const reply = (status, body = empty, headers = {}) => ({ status, body, headers });
const waitEvent = (peer, type) => new Promise(resolve => peer.addEventListener(type, resolve, { once: true }));

test("binary codec matches canonical big-endian framing and validates complete batches", () => {
  const encoded = encodeBatch([new Uint8Array([0, 255]), new Uint8Array([3])]);
  assert.deepEqual([...encoded], [0, 0, 0, 2, 0, 255, 0, 0, 0, 1, 3]);
  assert.deepEqual(decodeBatch(encoded).map(x => [...new Uint8Array(x)]), [[0, 255], [3]]);
  assert.throws(() => decodeBatch(encoded.slice(0, -1)));
  assert.throws(() => encodeBatch([new Uint8Array(MAX_FRAME + 1)]));
});

test("browser peer sends one ordered binary upload, delivers poll bytes, closes on rejection", async () => {
  const calls = [];
  let resolvePoll;
  const request = async ({ method, path, body, signal }) => {
    calls.push([method, path]);
    if (path.endsWith("/open")) return reply(200, opened);
    if (path.endsWith("/send/0")) {
      assert.deepEqual(decodeBatch(body).map(x => [...new Uint8Array(x)]), [[9, 8]]);
      return reply(204, empty, { "x-clientflow-sequence": "1" });
    }
    if (path.endsWith("/send/1")) return reply(401);
    if (path.endsWith("/poll/0")) return new Promise((resolve, reject) => {
      resolvePoll = resolve;
      signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
    });
    if (method === "DELETE") return reply(204);
    return new Promise((resolve, reject) => {
      signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
    });
  };
  const peer = new NativeHttpsBrowserPeer({ request, clientId: 3, sessionId, ticket, approved: true });
  await waitEvent(peer, "open");
  const delivered = waitEvent(peer, "message");
  resolvePoll(reply(200, encodeBatch([new Uint8Array([1, 2])]),
    { "content-type": "application/octet-stream", "x-clientflow-sequence": "0" }));
  assert.deepEqual([...new Uint8Array((await delivered).data)], [1, 2]);
  peer.send(new Uint8Array([9, 8]));
  await new Promise(resolve => setTimeout(resolve, 5));
  assert.equal(peer.bufferedAmount, 0);
  const closed = waitEvent(peer, "close");
  peer.send(new Uint8Array([7]));
  assert.equal((await closed).code, 1006);
  assert.equal(peer.readyState, peer.CLOSED);
  assert.equal(calls.filter(([, path]) => path.endsWith("/send/1")).length, 1);
  assert.equal(calls.filter(([method]) => method === "DELETE").length, 1);
});

test("browser peer never starts without explicit approval", () => {
  const request = () => { throw new Error("must not connect"); };
  assert.throws(() => new NativeHttpsBrowserPeer({ request, clientId: 3, sessionId, ticket }));
  assert.throws(() => new NativeHttpsBrowserPeer({ request, clientId: 4, sessionId, ticket, approved: true }));
});
