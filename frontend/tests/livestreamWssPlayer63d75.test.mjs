import test from "node:test";
import assert from "node:assert/strict";
import { createWssPlayer } from "../src/pages/clientdetailspage/livestreamWssPlayer.mjs";

function box(kind, ...parts) {
  const body = Buffer.concat(parts.map(p => Buffer.from(p)));
  const head = Buffer.alloc(8);
  head.writeUInt32BE(body.length + 8); head.write(kind, 4);
  return Buffer.concat([head, body]);
}
function initPayload() {
  const header = Buffer.alloc(8); header.writeUInt32BE(1, 4);
  const entry = box("avc1", Buffer.alloc(78), box("avcC", [1, 0x64, 0, 0x28, 0xff, 0xe1, 0]));
  return Buffer.concat([box("ftyp", [1]),
    box("moov", box("trak", box("mdia", box("minf", box("stbl", box("stsd", header, entry))))))]);
}
function wire(kind, seq, payload) {
  const head = Buffer.alloc(28);
  head.write("CFLS"); head[4] = 1; head[5] = kind;
  head.writeBigUInt64BE(BigInt(seq), 8);
  head.writeBigUInt64BE(BigInt(seq * 1000000), 16);
  head.writeUInt32BE(payload.length, 24);
  const data = Buffer.concat([head, payload]);
  return data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength);
}
async function fixture() {
  const failures = [], sources = [];
  let socket, time = 0;
  class SourceBuffer extends EventTarget {
    updating = false;
    appended = [];
    buffered = { length: 0 };
    appendBuffer(payload) {
      assert.equal(this.updating, false);
      this.appended.push(Buffer.from(payload));
      this.updating = true;
    }
    complete() { this.updating = false; this.dispatchEvent(new Event("updateend")); }
  }
  class Source extends EventTarget {
    static isTypeSupported() { return true; }
    readyState = "closed";
    constructor() { super(); sources.push(this); }
    addSourceBuffer() { this.buffer = new SourceBuffer(); return this.buffer; }
    open() { this.readyState = "open"; this.dispatchEvent(new Event("sourceopen")); }
  }
  class Socket {
    constructor(_url, protocols) {
      socket = this; this.protocol = protocols[0];
      queueMicrotask(() => this.onopen?.());
    }
    close() { this.closed = true; }
    send(data) { this.onmessage?.({ data }); }
  }
  const video = new EventTarget();
  Object.assign(video, { paused: true, currentTime: 0, readyState: 0, seeking: false,
    pause() { this.paused = true; }, play() { this.paused = false; return Promise.resolve(); },
    load() {}, removeAttribute() {} });
  const visibility = new EventTarget();
  visibility.visibilityState = "visible";
  const player = createWssPlayer(video, {
    url: "wss://example.invalid/live", getTicket: async () => ({
      subprotocol: "clientflow-livestream-v1", ticket: "a".repeat(43) }),
    MediaSourceClass: Source, SocketClass: Socket,
    documentRef: visibility, clock: () => time,
    urlApi: { createObjectURL: () => "blob:fake", revokeObjectURL() {} },
    onFailure: reason => failures.push(reason),
  });
  for (let i = 0; i < 8; i++) await Promise.resolve();
  assert.ok(socket);
  const send = seq => { time += 100; socket.send(wire(2, seq, Buffer.from([seq]))); };
  return { player, sources, failures, send,
    init: () => socket.send(wire(1, 0, initPayload())),
    visibility(state) { visibility.visibilityState = state; visibility.dispatchEvent(new Event("visibilitychange")); } };
}
test("delayed SourceBuffer opening preserves init and newest two fragments", async () => {
  const f = await fixture();
  try {
    f.init();
    for (let n = 1; n <= 6; n++) f.send(n);
    assert.deepEqual(f.failures, []);
    const source = f.sources[0]; source.open();
    const b = source.buffer;
    assert.deepEqual(b.appended, [initPayload()]);
    b.complete(); b.complete(); b.complete();
    assert.deepEqual(b.appended, [initPayload(), Buffer.from([5]), Buffer.from([6])]);
    f.send(8);
    assert.deepEqual(f.failures, ["fragment-discontinuity"]);
  } finally { f.player.dispose(); }
});
test("hidden interval reuses same open decoder and skips pre-hide backlog", async () => {
  const f = await fixture();
  try {
    f.init();
    const source = f.sources[0]; source.open();
    const b = source.buffer;
    b.complete();
    f.send(1);
    f.send(2); // waiting while fragment 1 is being appended
    f.visibility("hidden");
    for (let n = 3; n <= 8; n++) f.send(n);
    f.visibility("visible");
    assert.equal(f.sources.length, 1);
    // The old in-flight append must finish before fresh fragment 8.
    b.complete();
    assert.deepEqual(b.appended, [initPayload(), Buffer.from([1]), Buffer.from([8])]);
    b.complete();
    f.send(9); b.complete();
    assert.deepEqual(b.appended.at(-1), Buffer.from([9]));
    assert.deepEqual(f.failures, []);
    f.send(9);
    assert.deepEqual(f.failures, ["fragment-discontinuity"]);
  } finally { f.player.dispose(); }
});
test("new init received in hidden tab forces a new decoder", async () => {
  const f = await fixture();
  try {
    f.init(); f.sources[0].open(); f.sources[0].buffer.complete();
    f.send(1); f.sources[0].buffer.complete();
    f.visibility("hidden");
    f.init(); f.send(4); f.send(5);
    f.visibility("visible");
    assert.equal(f.sources.length, 2);
    const source = f.sources[1]; source.open();
    source.buffer.complete();
    assert.deepEqual(source.buffer.appended, [initPayload(), Buffer.from([5])]);
    assert.deepEqual(f.failures, []);
  } finally { f.player.dispose(); }
});
