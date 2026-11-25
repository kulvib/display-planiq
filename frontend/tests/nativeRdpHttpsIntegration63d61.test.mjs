import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { test } from "node:test";
import { MessageChannel } from "node:worker_threads";
const source = fs.readFileSync(new URL("../public/native-rdp/https-port.js", import.meta.url), "utf8");

test("iframe socket uses only a single generation port; ordered data and acknowledged backpressure", async () => {
  const window = {};
  vm.runInNewContext(source, { window, EventTarget, Event, ArrayBuffer, Uint8Array, Object, Number, Error });
  const { port1, port2 } = new MessageChannel();
  const url = "wss://example.invalid/api/remote-desktop/browser/3/native-rdp/session/ws";
  const Socket = window.PlanIQNativeHttpsPort.create(port2, url);
  assert.throws(() => new Socket("wss://other.invalid"));
  const socket = new Socket(url);
  assert.throws(() => new Socket(url));
  const opened = new Promise(resolve => socket.addEventListener("open", resolve, { once: true }));
  port1.on("message", data => {
    if (data.type === "open") port1.postMessage({ type: "open" });
    if (data.type === "data") {
      assert.deepEqual([...new Uint8Array(data.data)], [0, 255, 7]);
      port1.postMessage({ type: "drain", bytes: 7 });
      const response = new Uint8Array([9, 8]).buffer;
      port1.postMessage({ type: "data", data: response }, [response]);
    }
  });
  try {
    await opened;
    const received = new Promise(resolve => socket.addEventListener("message", resolve, { once: true }));
    socket.send(new Uint8Array([0, 255, 7]));
    assert.equal(socket.bufferedAmount, 7);
    assert.deepEqual([...new Uint8Array((await received).data)], [9, 8]);
    assert.equal(socket.bufferedAmount, 0);
  } finally {
    socket.close();
    port1.close();
  }
});

test("HTTPS is opt-in and WSS remains the direct default", () => {
  const page = fs.readFileSync(new URL("../src/pages/clientdetailspage/remotedesktop/RemoteDesktop.jsx", import.meta.url), "utf8");
  const viewer = fs.readFileSync(new URL("../src/pages/clientdetailspage/remotedesktop/NativeRdpViewer.jsx", import.meta.url), "utf8");
  assert.match(page, /VITE_NATIVE_BINARY_HTTPS_ENABLED !== "true"/);
  assert.match(page, /nativeRequested \? new WebSocket/);
  assert.match(viewer, /httpsBridgeRef\.current\?\.close/);
  assert.match(viewer, /window\.location\.origin, transfers/);
});
