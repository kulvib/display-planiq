/* Disposable iframe side of the approved binary HTTPS bridge. No tokens,
 * URLs, fetch calls or generic request capability cross this port. */
(function (root) {
  "use strict";
  function create(port, exactUrl) {
    if (!port || typeof port.postMessage !== "function") throw new Error("ClientFlow port missing");
    let used = false;
    return class PortSocket extends EventTarget {
      static CONNECTING = 0;
      static OPEN = 1;
      static CLOSING = 2;
      static CLOSED = 3;
      constructor(url) {
        super();
        if (used || String(url) !== exactUrl) throw new Error("ClientFlow socket not approved");
        used = true;
        this.CONNECTING = 0; this.OPEN = 1; this.CLOSING = 2; this.CLOSED = 3;
        this.readyState = 0;
        this.url = exactUrl;
        this.protocol = "planiq-ws-ticket";
        this.extensions = "";
        this.binaryType = "arraybuffer";
        this.bufferedAmount = 0;
        port.onmessage = event => {
          const data = event.data;
          if (data?.type === "open" && this.readyState === 0) {
            this.readyState = 1;
            this.emit("open");
          } else if (data?.type === "data" && this.readyState === 1 &&
                     data.data instanceof ArrayBuffer && data.data.byteLength > 0 && data.data.byteLength <= 65536) {
            const bytes = data.data.byteLength;
            this.emit("message", { data: data.data });
            if (this.readyState === 1) port.postMessage({ type: "received", bytes });
          } else if (data?.type === "drain" && Number.isInteger(data.bytes) && data.bytes > 0 &&
                     data.bytes <= this.bufferedAmount) {
            this.bufferedAmount -= data.bytes;
          } else if (data?.type === "close") {
            this.finish(data.code === 1000 ? 1000 : 1006);
          } else if (data?.type === "error") {
            this.emit("error");
            this.close();
          } else {
            this.emit("error");
            this.close();
          }
        };
        port.onmessageerror = () => { this.emit("error"); this.close(); };
        port.postMessage({ type: "open" });
      }
      emit(type, fields = {}) {
        const event = Object.assign(new Event(type), fields);
        this.dispatchEvent(event);
        this["on" + type]?.(event);
      }
      send(value) {
        if (this.readyState !== 1) throw new Error("ClientFlow socket closed");
        const data = value instanceof ArrayBuffer ? new Uint8Array(value) :
          ArrayBuffer.isView(value) ? new Uint8Array(value.buffer, value.byteOffset, value.byteLength) : null;
        if (!data || !data.byteLength || data.byteLength > 65536 ||
            this.bufferedAmount + data.byteLength + 4 > 2097152) {
          this.close();
          throw new Error("ClientFlow binary queue rejected");
        }
        const copy = data.slice().buffer;
        this.bufferedAmount += copy.byteLength + 4;
        port.postMessage({ type: "data", data: copy }, [copy]);
      }
      finish(code) {
        if (this.readyState === 3) return;
        this.readyState = 3;
        this.bufferedAmount = 0;
        port.close();
        this.emit("close", { code, reason: "", wasClean: code === 1000 });
      }
      close() {
        if (this.readyState === 3) return;
        try { port.postMessage({ type: "close" }); } catch {}
        this.finish(1000);
      }
    };
  }
  root.PlanIQNativeHttpsPort = Object.freeze({ create });
})(window);
