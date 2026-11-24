// The application parent retains the existing access token and derives every
// URL from the approved peer; the iframe gets only one generation-bound port.
import { apiUrl, authHeaders, boundAuthSessionSignal, ensureFreshAuthToken } from "../../../api";
import { NativeHttpsBrowserPeer } from "./nativeRdpHttpsPeer.mjs";

async function request({ method, path, body, headers, cap, signal }) {
  if (!path.startsWith("/api/remote-desktop/") || path.includes("..") ||
      path.includes("?") || path.includes("#") || cap < 0 || cap > 262144) {
    throw new Error("Invalid ClientFlow request");
  }
  const bound = boundAuthSessionSignal(signal);
  await ensureFreshAuthToken(bound);
  const response = await fetch(apiUrl + path, {
    method, body, headers: authHeaders(headers), credentials: "omit",
    redirect: "error", cache: "no-store", signal: bound,
  });
  // Never refresh-and-replay a binary POST, even after 401. Cancel error body.
  if (!response.ok) {
    await response.body?.cancel();
    throw new Error("ClientFlow request rejected");
  }
  const reader = response.body?.getReader();
  const chunks = [];
  let size = 0;
  try {
    if (reader) {
      while (true) {
        const item = await reader.read();
        if (item.done) break;
        size += item.value.byteLength;
        if (size > cap) throw new Error("ClientFlow response exceeds limit");
        chunks.push(item.value);
      }
    }
  } finally {
    if (reader) {
      try { await reader.cancel(); } catch {}
      reader.releaseLock();
    }
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  return { status: response.status, body: bytes, headers: Object.fromEntries(response.headers.entries()) };
}

export function createNativeHttpsBridge({ clientId, sessionId, ticket }) {
  const { port1, port2 } = new MessageChannel();
  let peer = null;
  let closed = false;
  const emit = (data, transfer = []) => {
    if (!closed) port1.postMessage(data, transfer);
  };
  const close = () => {
    if (closed) return;
    closed = true;
    peer?.close();
    peer = null;
    port1.close();
  };
  port1.onmessage = event => {
    try {
      const data = event.data;
      if (data?.type === "open" && !peer && !closed) {
        peer = new NativeHttpsBrowserPeer({ request, clientId, sessionId, ticket, approved: true });
        peer.addEventListener("open", () => emit({ type: "open" }));
        peer.addEventListener("message", message => emit({ type: "data", data: message.data }, [message.data]));
        peer.addEventListener("drain", message => emit({ type: "drain", bytes: message.bytes }));
        peer.addEventListener("error", () => emit({ type: "error" }));
        peer.addEventListener("close", message => { emit({ type: "close", code: message.code }); close(); });
      } else if (data?.type === "data" && peer && data.data instanceof ArrayBuffer) {
        peer.send(data.data);
      } else if (data?.type === "close") {
        close();
      } else {
        throw new Error("Invalid ClientFlow port message");
      }
    } catch {
      emit({ type: "error" });
      emit({ type: "close", code: 1006 });
      close();
    }
  };
  port1.onmessageerror = close;
  return { port: port2, close };
}
