/**
 * Phase 63D-35: one bounded, fail-closed raw-RFB socket over the existing
 * authenticated native desktop JSON tunnel (WSS or HTTPS).
 *
 * The noVNC RFB constructor accepts a WebSocket/RTCDataChannel-shaped object.
 * Crucially the original browser runtime opens the socket; this adapter NEVER
 * starts another RDP session, opens a port, requests privileged credentials or
 * changes the currently deployed JPEG Remote Desktop viewer.
 *
 * Native tunnel names are historical: after GNOME -> local FreeRDP/Xvfb,
 * the bytes in this adapter will be RFB, not raw RDP or JPEG.
 */
import {
  MAX_NATIVE_RDP_CHUNK_BYTES,
  MAX_NATIVE_RDP_PENDING_CHUNKS,
  encodeNativeRdpChunk,
  createNativeRdpWindow,
} from "./nativeRdpBridgeProtocol.mjs";

export const MAX_RFB_BUFFERED_BYTES = 256 * 1024;
const CONNECTING = 0, OPEN = 1, CLOSING = 2, CLOSED = 3;
const SESSION_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function error() {
  return new Error("RFB-forbindelsen er ugyldig eller overstiger den sikre datagrænse");
}
function normalizeBytes(value) {
  if (value instanceof ArrayBuffer) return new Uint8Array(value);
  if (ArrayBuffer.isView(value)) {
    return new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  }
  throw error();
}

export function createNativeRfbSocket({ transport, sessionId }) {
  if (!transport || typeof transport.send !== "function" ||
      typeof transport.close !== "function" ||
      !SESSION_RE.test(sessionId)) throw error();

  let streamId = null, recv = null, nextSeq = 0;
  let queuedBytes = 0;
  let awaitingAck = [];
  let outbound = [];
  let terminal = false;
  let currentState = CONNECTING;

  // Own enumerable properties deliberately match noVNC 1.7 Websock.attach()
  // (send, close, binaryType, onerror, onmessage, onopen, protocol, readyState).
  const rawSocket = {
    binaryType: "arraybuffer",
    onerror: null,
    onmessage: null,
    onopen: null,
    onclose: null,
    protocol: "",
    get readyState() { return currentState; },
    send(value) {
      if (terminal || currentState !== OPEN || !streamId) throw error();
      const data = normalizeBytes(value);
      if (!data.byteLength) return;
      if (data.byteLength + queuedBytes > MAX_RFB_BUFFERED_BYTES) {
        fail("RFB output buffer saturated");
        throw error();
      }
      // Clone: noVNC may reuse its outgoing Uint8Array immediately.
      for (let index = 0; index < data.byteLength; index += MAX_NATIVE_RDP_CHUNK_BYTES) {
        const chunk = new Uint8Array(data.slice(index, index + MAX_NATIVE_RDP_CHUNK_BYTES));
        outbound.push(chunk);
      }
      queuedBytes += data.byteLength;
      drain();
    },
    close(code = 1000, reason = "viewer_closed") {
      if (terminal) return;
      if (streamId && currentState === OPEN) {
        try {
          transport.send(JSON.stringify({
            type: "native_rdp_close", protocol: 1,
            session_id: sessionId, stream_id: streamId,
          }));
        } catch { /* transport is already closed; close locally */ }
      }
      stop(code, reason);
    },
  };

  function deliver(data) {
    if (terminal || !recv || currentState !== OPEN) throw error();
    const seq = data.seq;
    const bytes = recv.accept(data);
    // Acknowledge only *after* handing bytes to noVNC's synchronous decoder.
    const copied = bytes.slice();
    rawSocket.onmessage?.({ data: copied.buffer });
    recv.acknowledge(seq);
    transport.send(JSON.stringify({
      type: "native_rdp_ack", protocol: 1, session_id: sessionId,
      stream_id: streamId, seq,
    }));
  }

  function drain() {
    while (!terminal && currentState === OPEN &&
           awaitingAck.length < MAX_NATIVE_RDP_PENDING_CHUNKS && outbound.length) {
      const bytes = outbound.shift();
      const seq = nextSeq++;
      if (seq > 2 ** 31 - 1) {
        fail("RFB sequence exhausted");
        return;
      }
      const frame = encodeNativeRdpChunk({ sessionId, streamId, seq, bytes });
      awaitingAck.push({ seq, size: bytes.length });
      transport.send(JSON.stringify(frame));
    }
  }

  function stop(code = 1000, reason = "RFB closed") {
    if (terminal) return;
    terminal = true;
    currentState = CLOSING;
    outbound.length = 0;
    awaitingAck.length = 0;
    queuedBytes = 0;
    recv?.close();
    recv = null;
    try { transport.close(code, reason); } catch { /* already stopped */ }
    currentState = CLOSED;
    rawSocket.onclose?.({ code, reason, wasClean: code === 1000 });
  }

  function fail(reason) {
    rawSocket.onerror?.(error());
    stop(1008, reason);
  }

  function handle(event) {
    if (terminal) return;
    try {
      const msg = JSON.parse(String(event?.data ?? ""));
      if (!msg || typeof msg !== "object" || Array.isArray(msg) ||
          msg.session_id !== sessionId) throw error();

      if (msg.type === "native_rdp_pending") {
        if (streamId !== null || currentState !== CONNECTING ||
            msg.protocol !== 1 || !SESSION_RE.test(msg.stream_id)) throw error();
        streamId = msg.stream_id;
        recv = createNativeRdpWindow({ sessionId, streamId });
      } else if (msg.type === "native_rdp_ready") {
        if (!recv || msg.stream_id !== streamId ||
            msg.protocol !== 1 || currentState !== CONNECTING) throw error();
        currentState = OPEN;
        rawSocket.onopen?.({});
      } else if (msg.type === "native_rdp_chunk") {
        deliver(msg);
      } else if (msg.type === "native_rdp_ack") {
        if (currentState !== OPEN || msg.stream_id !== streamId ||
            msg.protocol !== 1 || !Number.isSafeInteger(msg.seq) ||
            !awaitingAck.length || awaitingAck[0].seq !== msg.seq) throw error();
        const accepted = awaitingAck.shift();
        queuedBytes -= accepted.size;
        drain();
      } else if (msg.type === "native_rdp_close") {
        if (!streamId || msg.stream_id !== streamId || msg.protocol !== 1) throw error();
        stop(1000, "RFB server closed");
      } else {
        throw error();
      }
    } catch {
      fail("RFB protocol violation");
    }
  }

  // Transport starts its own WSS → HTTPS fallback; noVNC sees only raw RFB
  // binary messages and regular WebSocket-like open/close/error callbacks.
  transport.onmessage = handle;
  transport.onerror = () => fail("RFB relay unavailable");
  transport.onclose = (evt) => stop(evt?.code || 1006, "RFB relay disconnected");

  return rawSocket;
}
