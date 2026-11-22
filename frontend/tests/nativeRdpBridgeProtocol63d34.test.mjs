import test from "node:test";
import assert from "node:assert/strict";
import {
  MAX_NATIVE_RDP_CHUNK_BYTES, MAX_NATIVE_RDP_PENDING_CHUNKS,
  encodeNativeRdpChunk, decodeNativeRdpChunk, createNativeRdpWindow,
} from "../src/pages/clientdetailspage/remotedesktop/nativeRdpBridgeProtocol.mjs";

const sessionId = "11111111-1111-4111-8111-111111111111";
const streamId = "22222222-2222-4222-8222-222222222222";
const otherId = "33333333-3333-4333-8333-333333333333";
const frame = (seq=0) => encodeNativeRdpChunk({
  sessionId, streamId, seq, bytes:new Uint8Array([0, 255, 117, 0]),
});

test("native RDP roundtrip preserves binary and 16KiB bound", () => {
  for (const count of [1, 512, MAX_NATIVE_RDP_CHUNK_BYTES]) {
    const bytes = Uint8Array.from({length:count}, (_, i) => i % 256);
    const wire = encodeNativeRdpChunk({sessionId, streamId, seq:0, bytes});
    assert.deepEqual(decodeNativeRdpChunk(wire, {sessionId,streamId}).bytes, bytes);
  }
  assert.throws(() => encodeNativeRdpChunk({
    sessionId,streamId,seq:0,bytes:new Uint8Array(MAX_NATIVE_RDP_CHUNK_BYTES+1),
  }));
});
test("native RDP strictly binds client session and connection generation", () => {
  assert.throws(() => decodeNativeRdpChunk(frame(), {sessionId:otherId,streamId}));
  assert.throws(() => decodeNativeRdpChunk(frame(), {sessionId,streamId:otherId}));
  assert.throws(() => encodeNativeRdpChunk({
    sessionId:sessionId.toUpperCase(),streamId,seq:0,bytes:new Uint8Array([1]),
  }));
});
test("native RDP rejects unknown fields, malformed Base64, invalid sequences", () => {
  for (const edit of [
    {password:"no"}, {protocol:2}, {seq:-1}, {seq:2**31},
    {seq:1.2}, {data:""}, {data:"?"}, {data:"YQ="}, {data:"YR=="},
    {type:"native_rdp_password"}, {data:"YQ==\n"},
  ]) {
    assert.throws(() => decodeNativeRdpChunk({...frame(), ...edit}, {sessionId,streamId}));
  }
});
test("native RDP ordered stream never drops/replaces chunks", () => {
  const window = createNativeRdpWindow({sessionId,streamId});
  assert.deepEqual(window.accept(frame(0)),new Uint8Array([0,255,117,0]));
  assert.throws(() => window.accept(frame(0)));
  assert.throws(() => window.accept(frame(2)));
  for (let i=1;i<MAX_NATIVE_RDP_PENDING_CHUNKS;i++) window.accept(frame(i));
  assert.throws(() => window.accept(frame(MAX_NATIVE_RDP_PENDING_CHUNKS)));
  assert.throws(() => window.acknowledge(1));
  window.acknowledge(0);
  window.accept(frame(MAX_NATIVE_RDP_PENDING_CHUNKS));
  window.close();
  assert.throws(() => window.accept(frame(MAX_NATIVE_RDP_PENDING_CHUNKS+1)));
});
test("new native RDP stream cannot reuse stale connection frame", () => {
  const newWindow = createNativeRdpWindow({sessionId,streamId:otherId});
  assert.throws(() => newWindow.accept(frame(0)));
});
