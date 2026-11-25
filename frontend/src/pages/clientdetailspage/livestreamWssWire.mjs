// Wire parser only: does not connect a socket, authenticate or claim playback.
export const LIVE_WIRE_HEADER = 28;
export const LIVE_INIT = 1;
export const LIVE_FRAGMENT = 2;
const MAX_INIT = 128 * 1024;
const MAX_FRAGMENT = 2 * 1024 * 1024;
const MAX_SAFE = BigInt(Number.MAX_SAFE_INTEGER);

export function decodeLiveWire(buffer) {
  if (!(buffer instanceof ArrayBuffer) || buffer.byteLength <= LIVE_WIRE_HEADER ||
      buffer.byteLength > LIVE_WIRE_HEADER + MAX_FRAGMENT) throw new Error("invalid live frame size");
  const v = new DataView(buffer);
  if (v.getUint32(0) !== 0x43464c53 || v.getUint8(4) !== 1 || v.getUint16(6) !== 0) {
    throw new Error("invalid live frame header");
  }
  const kind = v.getUint8(5);
  const seq = v.getBigUint64(8);
  const timestamp = v.getBigUint64(16);
  const size = v.getUint32(24);
  if (seq > MAX_SAFE || timestamp > MAX_SAFE || size !== buffer.byteLength - LIVE_WIRE_HEADER) {
    throw new Error("invalid live frame fields");
  }
  if (kind === LIVE_INIT) {
    if (seq !== 0n || timestamp !== 0n || size > MAX_INIT) throw new Error("invalid live init");
  } else if (kind === LIVE_FRAGMENT) {
    if (seq === 0n || size > MAX_FRAGMENT) throw new Error("invalid live fragment");
  } else throw new Error("invalid live frame kind");
  return { kind, sequence: Number(seq), timestampUs: Number(timestamp),
    payload: new Uint8Array(buffer, LIVE_WIRE_HEADER, size) };
}
