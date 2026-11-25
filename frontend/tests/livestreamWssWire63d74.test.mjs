import assert from "node:assert/strict";
import test from "node:test";
import { decodeLiveWire, LIVE_WIRE_HEADER, LIVE_FRAGMENT } from "../src/pages/clientdetailspage/livestreamWssWire.mjs";

const golden = "43464c5301020000000000000000000100000000000003e800000003616263";
function packet(hex = golden) {
  return Uint8Array.from(hex.match(/../g).map(x => parseInt(x, 16))).buffer;
}
test("63D-74 live wire matches the Python golden vector", () => {
  const result = decodeLiveWire(packet());
  assert.equal(LIVE_WIRE_HEADER, 28);
  assert.equal(result.kind, LIVE_FRAGMENT);
  assert.equal(result.sequence, 1);
  assert.equal(result.timestampUs, 1000);
  assert.deepEqual([...result.payload], [97,98,99]);
});
test("63D-74 live wire rejects malformed, oversized and unsafe integer frames", () => {
  for (const [offset, value] of [[0, 0], [4, 2], [5, 3], [6, 1], [8, 255], [27, 4]]) {
    const buf = packet();
    new Uint8Array(buf)[offset] = value;
    assert.throws(() => decodeLiveWire(buf));
  }
  assert.throws(() => decodeLiveWire(packet().slice(0, -1)));
  assert.throws(() => decodeLiveWire(new ArrayBuffer(28)));
  assert.throws(() => decodeLiveWire(new ArrayBuffer(28 + 2 * 1024 * 1024 + 1)));
  assert.throws(() => decodeLiveWire("not binary"));
});
