// Experimental browser-side binary peer. Not loaded by FreeRDP or enabled.
// request is a parent-owned authenticated, bounded, no-retry HTTP function.
// It must not send the access token into the disposable WASM iframe.
export const MAX_FRAME = 65536;
export const MAX_BATCH = 262144;
const MAX_FRAMES = 128;
const MAX_BUFFERED = 2 * 1024 * 1024;
const MAX_QUEUE_FRAMES = 512;
const MAX_SEQUENCE = Number.MAX_SAFE_INTEGER;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const PEER = /^[0-9a-f]{32}$/;

function view(value) {
  if (value instanceof ArrayBuffer) return new Uint8Array(value);
  if (ArrayBuffer.isView(value)) return new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  throw new Error("Invalid binary frame");
}

export function encodeBatch(frames) {
  if (!frames.length || frames.length > MAX_FRAMES) throw new Error("Invalid frame count");
  const bytes = frames.map(view);
  let size = 0;
  for (const frame of bytes) {
    if (!frame.length || frame.length > MAX_FRAME) throw new Error("Invalid binary frame");
    size += 4 + frame.length;
    if (size > MAX_BATCH) throw new Error("Invalid binary batch size");
  }
  const out = new Uint8Array(size);
  const data = new DataView(out.buffer);
  let offset = 0;
  for (const frame of bytes) {
    data.setUint32(offset, frame.length);
    offset += 4;
    out.set(frame, offset);
    offset += frame.length;
  }
  return out;
}

export function decodeBatch(body) {
  const bytes = view(body);
  if (!bytes.length || bytes.length > MAX_BATCH) throw new Error("Invalid binary batch size");
  const data = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const frames = [];
  let offset = 0;
  while (offset < bytes.length) {
    if (frames.length >= MAX_FRAMES || bytes.length - offset < 4) throw new Error("Invalid framing");
    const size = data.getUint32(offset);
    offset += 4;
    if (!size || size > MAX_FRAME || offset + size > bytes.length) throw new Error("Invalid framing");
    frames.push(bytes.slice(offset, offset + size).buffer);
    offset += size;
  }
  return frames;
}

function event(type, fields = {}) {
  return Object.assign(new Event(type), fields);
}

export class NativeHttpsBrowserPeer extends EventTarget {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  constructor({ request, clientId, sessionId, ticket, approved = false }) {
    super();
    if (approved !== true || clientId !== 3 || !UUID.test(sessionId) ||
        typeof ticket !== "string" || !/^[A-Za-z0-9_-]{32,256}$/.test(ticket) ||
        typeof request !== "function") throw new Error("ClientFlow HTTPS is not approved");
    this.CONNECTING = 0; this.OPEN = 1; this.CLOSING = 2; this.CLOSED = 3;
    this.readyState = 0;
    this.binaryType = "arraybuffer";
    this.protocol = "planiq-ws-ticket";
    this.bufferedAmount = 0;
    this._request = request;
    this._base = "/api/remote-desktop/native-https/browser/" + clientId + "/";
    this._peer = null;
    this._queue = [];
    this._sending = false;
    this._up = 0;
    this._down = 0;
    this._abort = new AbortController();
    // Defer so listeners can be attached before open/error.
    void Promise.resolve().then(() => this._open(clientId, sessionId, ticket));
  }

  _emit(type, fields) {
    const message = event(type, fields);
    this.dispatchEvent(message);
    if (typeof this["on" + type] === "function") this["on" + type](message);
  }

  async _call(method, path, body, headers, cap, timeoutMs, closing = false) {
    const controller = new AbortController();
    const abort = () => controller.abort();
    if (!closing) {
      if (this._abort.signal.aborted) controller.abort();
      this._abort.signal.addEventListener("abort", abort, { once: true });
    }
    let timer;
    try {
      const timeout = new Promise((_, reject) => {
        timer = setTimeout(() => { controller.abort(); reject(new Error("Request timed out")); }, timeoutMs);
      });
      const reply = await Promise.race([
        this._request({ method, path, body, headers, cap, signal: controller.signal }), timeout,
      ]);
      const bytes = view(reply.body);
      if (bytes.length > cap) throw new Error("Response too large");
      return { ...reply, body: bytes };
    } finally {
      clearTimeout(timer);
      this._abort.signal.removeEventListener("abort", abort);
    }
  }

  async _open(clientId, sessionId, ticket) {
    try {
      if (this.readyState !== this.CONNECTING) return;
      const result = await this._call("POST",
        "/api/remote-desktop/browser/" + clientId + "/native-https/" + sessionId + "/open",
        undefined, { "X-ClientFlow-Ticket": ticket }, 1024, 12000);
      if (result.status !== 200) throw new Error("Open rejected");
      const value = JSON.parse(new TextDecoder().decode(result.body));
      if (typeof value.peer_id !== "string" || !PEER.test(value.peer_id) ||
          value.upload_sequence !== 0 || value.download_sequence !== 0) throw new Error("Invalid peer");
      this._peer = value.peer_id;
      if (this.readyState !== this.CONNECTING) {
        await this._delete();
        return;
      }
      this.readyState = this.OPEN;
      this._emit("open");
      void this._poll();
    } catch {
      this._fail();
    }
  }

  send(value) {
    if (this.readyState !== this.OPEN) throw new Error("ClientFlow peer closed");
    try {
      const bytes = view(value);
      if (!bytes.length || bytes.length > MAX_FRAME ||
          this.bufferedAmount + bytes.length + 4 > MAX_BUFFERED ||
          this._queue.length >= MAX_QUEUE_FRAMES) throw new Error("Invalid binary queue");
      this._queue.push(bytes.slice());
      this.bufferedAmount += bytes.length + 4;
      if (!this._sending) void this._flush();
    } catch (error) {
      this._fail();
      throw error;
    }
  }

  async _flush() {
    this._sending = true;
    try {
      while (this.readyState === this.OPEN && this._queue.length) {
        const batch = [];
        let size = 0;
        while (this._queue.length && batch.length < MAX_FRAMES) {
          const next = this._queue[0];
          if (size + next.length + 4 > MAX_BATCH) break;
          size += next.length + 4;
          batch.push(this._queue.shift());
        }
        if (this._up >= MAX_SEQUENCE) throw new Error("Upload sequence exhausted");
        const result = await this._call("POST", this._base + this._peer + "/send",
          encodeBatch(batch), { "Content-Type": "application/octet-stream", "X-ClientFlow-Sequence": String(this._up) }, 0, 12000);
        if (this.readyState !== this.OPEN) return;
        if (result.status !== 204 || result.headers["x-clientflow-sequence"] !== String(this._up + 1)) {
          throw new Error("Upload rejected");
        }
        this._up++;
        this.bufferedAmount -= size;
        this._emit("drain", { bytes: size });
      }
    } catch {
      this._fail();
    } finally {
      this._sending = false;
    }
  }

  async _poll() {
    try {
      while (this.readyState === this.OPEN) {
        if (this._down >= MAX_SEQUENCE) throw new Error("Download sequence exhausted");
        const result = await this._call("GET", this._base + this._peer + "/poll",
          undefined, { "X-ClientFlow-Sequence": String(this._down) }, MAX_BATCH, 28000);
        if (this.readyState !== this.OPEN) return;
        if (result.status !== 200 || result.headers["content-type"] !== "application/octet-stream" ||
            result.headers["x-clientflow-sequence"] !== String(this._down)) throw new Error("Poll rejected");
        if (result.body.length) {
          const frames = decodeBatch(result.body);
          this._down++;
          for (const data of frames) {
            if (this.readyState !== this.OPEN) return;
            this._emit("message", { data });
          }
        } else {
          await new Promise(resolve => setTimeout(resolve, 10));
        }
      }
    } catch {
      this._fail();
    }
  }

  async _delete() {
    const peer = this._peer;
    this._peer = null;
    if (peer) {
      try { await this._call("DELETE", this._base + peer, undefined, {}, 0, 3000, true); }
      catch { /* backend independent contact supervision */ }
    }
  }

  _fail() {
    if (this.readyState >= this.CLOSING) return;
    this._emit("error");
    this._stop(1006, false);
  }

  close() { this._stop(1000, true); }

  _stop(code, wasClean) {
    if (this.readyState >= this.CLOSING) return;
    this.readyState = this.CLOSING;
    this._abort.abort();
    this._queue = [];
    this.bufferedAmount = 0;
    void this._delete();
    this.readyState = this.CLOSED;
    this._emit("close", { code, reason: "", wasClean });
  }
}
