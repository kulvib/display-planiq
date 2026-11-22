/** Phase 63D-34: session-bound native-RDP framing; NO browser RDP decoder yet.
 * Compatible with existing JSON-based WSS and authenticated HTTPS relay.
 * Never store/log packet payloads or RDP credentials. Do not use for JPEG.
 */
export const NATIVE_RDP_PROTOCOL = 1;
export const MAX_NATIVE_RDP_CHUNK_BYTES = 16 * 1024;
export const MAX_NATIVE_RDP_PENDING_CHUNKS = 8;
export const MAX_NATIVE_RDP_SEQ = 2 ** 31 - 1;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const B64_RE = /^[A-Za-z0-9+/]*={0,2}$/;
const KEYS = ["data", "protocol", "seq", "session_id", "stream_id", "type"];

function fail() { throw new Error("Ugyldig eller forældet RDP-stream"); }
function identity(value) {
  if (typeof value !== "string" || !UUID_RE.test(value)) fail();
  return value;
}
function sequence(value) {
  if (!Number.isSafeInteger(value) || value < 0 || value > MAX_NATIVE_RDP_SEQ) fail();
  return value;
}
function bytesToBase64(bytes) {
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}
function base64ToBytes(data) {
  if (typeof data !== "string" || !data || data.length > Math.ceil(MAX_NATIVE_RDP_CHUNK_BYTES / 3) * 4 || !B64_RE.test(data)) fail();
  let decoded;
  try { decoded = atob(data); } catch { fail(); }
  if (!decoded || decoded.length > MAX_NATIVE_RDP_CHUNK_BYTES) fail();
  const result = Uint8Array.from(decoded, ch => ch.charCodeAt(0));
  if (bytesToBase64(result) !== data) fail();
  return result;
}
export function encodeNativeRdpChunk({sessionId, streamId, seq, bytes}) {
  identity(sessionId); identity(streamId); sequence(seq);
  if (!(bytes instanceof Uint8Array) || bytes.length === 0 || bytes.length > MAX_NATIVE_RDP_CHUNK_BYTES) fail();
  return {type:"native_rdp_chunk", protocol:NATIVE_RDP_PROTOCOL,
    session_id:sessionId, stream_id:streamId, seq, data:bytesToBase64(bytes)};
}
export function decodeNativeRdpChunk(message, {sessionId, streamId}) {
  identity(sessionId); identity(streamId);
  if (!message || typeof message !== "object" || Array.isArray(message) ||
      Object.keys(message).sort().join(",") !== KEYS.join(",") ||
      message.type !== "native_rdp_chunk" || message.protocol !== NATIVE_RDP_PROTOCOL ||
      message.session_id !== sessionId || message.stream_id !== streamId) fail();
  const seq = sequence(message.seq);
  return {seq, bytes:base64ToBytes(message.data)};
}
export function createNativeRdpWindow({sessionId, streamId}) {
  identity(sessionId); identity(streamId);
  let nextSeq = 0;
  const pending = [];
  let closed = false;
  return {
    accept(message) {
      if (closed) fail();
      const parsed = decodeNativeRdpChunk(message, {sessionId, streamId});
      if (parsed.seq !== nextSeq || nextSeq >= MAX_NATIVE_RDP_SEQ ||
          pending.length >= MAX_NATIVE_RDP_PENDING_CHUNKS) fail();
      pending.push(parsed.seq);
      nextSeq++;
      return parsed.bytes;
    },
    acknowledge(seq) {
      if (closed || !pending.length || pending[0] !== seq) fail();
      pending.shift();
    },
    close() { closed = true; pending.length = 0; },
    get pendingCount() { return pending.length; },
  };
}
