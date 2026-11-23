/* 63D-42: Browser-side, content-blind FreeRDP SOCKFS transport guard.
 * Only the disposable same-origin FreeRDP iframe installs this adapter.
 * Observe lengths/counts, never payload bytes, RDP secrets, tickets or URLs.
 */
(function (root) {
  "use strict";
  const CHUNK_SIZE = 16 * 1024;
  const MAX_BUFFERED = 2 * 1024 * 1024;

  function binaryView(value) {
    if (value instanceof ArrayBuffer) return new Uint8Array(value);
    if (ArrayBuffer.isView(value)) {
      return new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
    }
    return null;
  }

  function install(options) {
    if (!options || typeof options.url !== "string" ||
        typeof options.onProgress !== "function" ||
        typeof options.onFailure !== "function") {
      throw new TypeError("Ugyldig RDP-transportkonfiguration");
    }
    const BaseWebSocket = root.WebSocket;
    if (typeof BaseWebSocket !== "function") throw new TypeError("WebSocket mangler");
    const now = options.now || (() => Date.now());
    const setTimer = options.setTimer || root.setInterval.bind(root);
    const clearTimer = options.clearTimer || root.clearInterval.bind(root);
    const state = {
      openedAt: null, firstSendAt: null, firstReceiveAt: null,
      toAgentBytes: 0, toAgentFrames: 0,
      fromAgentBytes: 0, fromAgentFrames: 0,
      visibleConfirmed: false,
      peakOutboundQueueBytes: 0,
      lastOutboundQueueBytes: 0,
      maxTimerSlipMs: 0,
    };
    let currentSocket = null;
    let stopped = false;
    let timer = null;
    const snapshot = () => ({ ...state });
    // Exact packet counters, but only one diagnostic UI callback per second.
    let lastProgressAt = -Infinity;
    const update = () => {
      if (stopped) return;
      const at = now();
      if (at - lastProgressAt < 1000) return;
      lastProgressAt = at;
      options.onProgress(snapshot());
    };
    const fail = (reason) => {
      if (stopped) return;
      stopped = true;
      if (timer !== null) clearTimer(timer);
      options.onFailure(reason);
      try { currentSocket?.close(); } catch { /* socket already closed */ }
    };
    let lastTickAt = now();
    const tick = () => {
      if (stopped) return;
      const current = now();
      const slip = current - lastTickAt - 1000;
      if (slip > 0 && slip < 60000) {
        state.maxTimerSlipMs = Math.max(state.maxTimerSlipMs, Math.round(slip));
      }
      lastTickAt = current;
      if (state.openedAt === null) return;
      const elapsed = current - state.openedAt;
      if (elapsed >= 12000 && state.toAgentBytes === 0) {
        fail("FreeRDP åbnede WSS, men sendte ingen RDP-bytes inden 12 sekunder.");
      } else if (elapsed >= 20000 && state.toAgentBytes > 0 &&
                 state.fromAgentBytes === 0) {
        fail("RDP-data blev sendt, men GNOME svarede ikke inden 20 sekunder. Kontrollér agentens TCP- og WSS-tællere.");
      } else if (elapsed >= 45000 && !state.visibleConfirmed) {
        fail("RDP-forbindelsen blev ikke bekræftet med synligt skrivebord inden 45 sekunder. Kontrollér GNOME-grafik eller vælg JPEG.");
      }
    };
    class RdpSocket extends BaseWebSocket {
      constructor(url, protocols) {
        // Emscripten SOCKFS must not be used as a generic socket proxy.
        if (String(url) !== options.url || currentSocket !== null) {
          throw new TypeError("Ikke-godkendt FreeRDP WebSocket");
        }
        super(url, protocols);
        currentSocket = this;
        this.addEventListener("open", () => {
          state.openedAt = now();
          update();
        });
        this.addEventListener("message", (event) => {
          const payload = binaryView(event.data);
          if (payload === null || payload.byteLength === 0 || payload.byteLength > 64 * 1024) {
            fail("RDP-relæet leverede en ugyldig binær ramme.");
            return;
          }
          state.fromAgentBytes += payload.byteLength;
          state.fromAgentFrames++;
          if (state.firstReceiveAt === null) state.firstReceiveAt = now();
          update();
        });
        this.addEventListener("close", () => {
          if (!stopped) fail("GNOME RDP-forbindelsen blev lukket før en verificeret session.");
        });
        this.addEventListener("error", () => {
          if (!stopped) fail("Binær RDP-WebSocket fik en transportfejl.");
        });
      }
      send(data) {
        const bytes = binaryView(data);
        if (bytes === null || bytes.byteLength === 0) {
          fail("FreeRDP forsøgte at sende en ikke-binær eller tom ramme.");
          throw new TypeError("Kun binære RDP-data accepteres");
        }
        const bufferedBefore = this.bufferedAmount;
        if (bufferedBefore + bytes.byteLength > MAX_BUFFERED) {
          fail("RDP-forbindelsen blev afbrudt på grund af for stor afsendelseskø.");
          throw new Error("RDP backpressure");
        }
        // WebSocket is framed; GNOME TCP is a byte stream. Splitting messages
        // preserves every byte and their order while honoring the 64 KiB relay cap.
        for (let offset = 0; offset < bytes.byteLength; offset += CHUNK_SIZE) {
          const part = bytes.subarray(offset, offset + CHUNK_SIZE);
          super.send(part);
          state.toAgentBytes += part.byteLength;
          state.toAgentFrames++;
        }
        const queued = this.bufferedAmount;
        state.lastOutboundQueueBytes = queued;
        state.peakOutboundQueueBytes = Math.max(
          state.peakOutboundQueueBytes, bufferedBefore, queued
        );
        if (state.firstSendAt === null) state.firstSendAt = now();
        update();
      }
    }
    root.WebSocket = RdpSocket;
    timer = setTimer(tick, 1000);
    return {
      snapshot,
      confirmVisible() {
        if (!stopped && state.toAgentBytes > 0 && state.fromAgentBytes > 0) {
          state.visibleConfirmed = true;
          update();
          return true;
        }
        return false;
      },
      dispose() {
        stopped = true;
        if (timer !== null) clearTimer(timer);
        if (root.WebSocket === RdpSocket) root.WebSocket = BaseWebSocket;
      },
    };
  }

  root.PlanIQNativeRdpProbe = Object.freeze({ install, CHUNK_SIZE, MAX_BUFFERED });
})(window);
