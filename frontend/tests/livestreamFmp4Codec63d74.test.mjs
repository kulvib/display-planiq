import test from "node:test";
import assert from "node:assert/strict";
import { avcMime } from "../src/pages/clientdetailspage/livestreamFmp4Codec.mjs";

function box(kind, ...children) {
  const body = Buffer.concat(children.map(c => Buffer.from(c)));
  const header = Buffer.alloc(8);
  header.writeUInt32BE(body.length + 8);
  header.write(kind, 4, "ascii");
  return Buffer.concat([header, body]);
}
function init(kind = "avc1") {
  const header = Buffer.alloc(8);
  header.writeUInt32BE(1, 4);
  const avcc = box("avcC", Buffer.from([1, 0x64, 0, 0x28, 0xff, 0xe1, 0]));
  const stsd = box("stsd", header, box(kind, Buffer.alloc(78), avcc));
  return Buffer.concat([box("ftyp", Buffer.from("isom")),
    box("moov", box("trak", box("mdia", box("minf", box("stbl", stsd)))))]);
}
test("derive AVC profile from actual sample description", () => {
  const data = init();
  assert.equal(avcMime(data), 'video/mp4; codecs="avc1.640028"');
});
test("reject unsupported or malformed boxes", () => {
  const valid = init();
  for (const data of [valid.subarray(0, -1), Buffer.concat([valid, Buffer.from([1])]),
    init("hev1"), Buffer.alloc(20), Buffer.alloc(128 * 1024 + 1)]) {
    assert.throws(() => avcMime(data));
  }
});
