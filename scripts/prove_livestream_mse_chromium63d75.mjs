// Offline Chromium MSE proof with generated video and injected socket delivery.
// No client screen, live service, credentials, external requests or browser package.
// The ASGI suite separately exercises the authenticated socket route.
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { mkdtemp, readFile, writeFile, rm, copyFile } from "node:fs/promises";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as sleep } from "node:timers/promises";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const folder = await mkdtemp(join(tmpdir(), "cf-mse-63d75-"));
let server, chrome, cdp;
const binaries = ["google-chrome", "chromium", "chromium-browser"];
const browser = binaries.find(name => spawnSync("which", [name], { encoding: "utf8" }).status === 0);
const moduleNames = ["livestreamWssPlayer.mjs", "livestreamWssWire.mjs", "livestreamFmp4Codec.mjs"];
function boxList(data) {
  const boxes = [];
  for (let i = 0; i < data.length;) {
    assert.ok(i + 8 <= data.length);
    const n = data.readUInt32BE(i);
    assert.ok(n >= 8 && i + n <= data.length);
    boxes.push({ name: data.toString("ascii", i + 4, i + 8), data: data.subarray(i, i + n) });
    i += n;
  }
  return boxes;
}
function wire(kind, sequence, payload) {
  const head = Buffer.alloc(28);
  head.write("CFLS", 0);
  head[4] = 1; head[5] = kind;
  head.writeBigUInt64BE(BigInt(sequence), 8);
  head.writeBigUInt64BE(BigInt(sequence * 1_000_000), 16);
  head.writeUInt32BE(payload.length, 24);
  return Buffer.concat([head, payload]);
}
try {
  assert.ok(browser, "Chromium/Chrome not installed");
  const mp4 = join(folder, "synthetic.mp4");
  const ffmpeg = spawnSync("ffmpeg", [
    "-hide_banner", "-loglevel", "error", "-f", "lavfi",
    "-i", "testsrc2=size=320x180:rate=10", "-t", "18",
    "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
    "-g", "10", "-keyint_min", "10", "-sc_threshold", "0", "-bf", "0",
    "-movflags", "+empty_moov+default_base_moof+frag_keyframe", "-y", mp4,
  ], { timeout: 45000, encoding: "utf8" });
  assert.equal(ffmpeg.status, 0, ffmpeg.stderr);
  const boxes = boxList(await readFile(mp4));
  assert.deepEqual(boxes.slice(0, 2).map(b => b.name), ["ftyp", "moov"]);
  await writeFile(join(folder, "init.bin"), wire(1, 0, Buffer.concat(boxes.slice(0, 2).map(b => b.data))));
  let count = 0;
  for (let i = 2; i < boxes.length && boxes[i].name !== "mfra"; i += 2) {
    assert.deepEqual(boxes.slice(i, i + 2).map(b => b.name), ["moof", "mdat"]);
    const data = Buffer.concat([boxes[i].data, boxes[i + 1].data]);
    await writeFile(join(folder, "fragment-" + (++count) + ".bin"), wire(2, count, data));
  }
  assert.equal(count, 18);
  for (const name of moduleNames) {
    await copyFile(join(ROOT, "frontend/src/pages/clientdetailspage", name), join(folder, name));
  }
  await writeFile(join(folder, "index.html"), '<!doctype html><meta charset="utf-8"><video id="video" width="320" height="180" muted playsinline></video>');
  server = createServer(async (req, res) => {
    const name = req.url === "/" ? "index.html" : req.url?.slice(1);
    if (!["index.html", "init.bin", ...moduleNames].includes(name) && !/^fragment-(?:[1-9]|1[0-8])\.bin$/.test(name || "")) {
      res.writeHead(404).end(); return;
    }
    try {
      const body = await readFile(join(folder, name));
      res.writeHead(200, { "Content-Type": name.endsWith(".mjs") ? "text/javascript" :
        name.endsWith(".html") ? "text/html" : "application/octet-stream", "Cache-Control": "no-store" }).end(body);
    } catch { res.writeHead(404).end(); }
  });
  await new Promise((ok, bad) => { server.once("error", bad); server.listen(0, "127.0.0.1", ok); });
  const pageUrl = "http://127.0.0.1:" + server.address().port + "/";
  const profile = join(folder, "profile");
  chrome = spawn(browser, [
    "--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
    "--disable-background-networking", "--no-first-run", "--no-default-browser-check",
    "--autoplay-policy=no-user-gesture-required", "--remote-debugging-address=127.0.0.1",
    "--remote-debugging-port=0", "--user-data-dir=" + profile, pageUrl,
  ], { stdio: "ignore" });
  let port;
  for (let i = 0; i < 100; i++) {
    try { port = Number((await readFile(join(profile, "DevToolsActivePort"), "utf8")).split("\n")[0]); if (port) break; } catch {}
    await sleep(100);
  }
  assert.ok(port, "Chromium DevTools startup");
  let target;
  for (let i = 0; i < 100; i++) {
    try {
      const list = await (await fetch("http://127.0.0.1:" + port + "/json/list")).json();
      target = list.find(t => t.type === "page" && t.url === pageUrl);
      if (target) break;
    } catch {}
    await sleep(100);
  }
  assert.ok(target?.webSocketDebuggerUrl, "local browser target");
  cdp = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok, bad) => {
    cdp.addEventListener("open", ok, { once: true });
    cdp.addEventListener("error", bad, { once: true });
  });
  // Run the actual repository player against real Chrome MediaSource. Only
  // the socket delivery and visibility events are deterministic test inputs.
  const proof = async () => {
    const { createWssPlayer } = await import("/livestreamWssPlayer.mjs");
    const video = document.querySelector("#video");
    const wait = ms => new Promise(ok => setTimeout(ok, ms));
    const get = async path => {
      const r = await fetch(path); if (!r.ok) throw Error("fixture fetch");
      return r.arrayBuffer();
    };
    const init = await get("/init.bin");
    const fragments = await Promise.all(Array.from({ length: 18 }, (_, i) => get("/fragment-" + (i + 1) + ".bin")));
    const visibility = new EventTarget();
    visibility.visibilityState = "visible";
    let socket, ready = 0, failure = null;
    class InjectedSocket {
      constructor(_url, protocols) {
        socket = this;
        this.protocol = protocols[0];
        queueMicrotask(() => this.onopen?.());
      }
      close() { this.closed = true; }
      deliver(data) { this.onmessage?.({ data }); }
    }
    const player = createWssPlayer(video, {
      url: "wss://example.invalid/unused",
      getTicket: async () => ({ subprotocol: "clientflow-livestream-v1", ticket: "a".repeat(43) }),
      SocketClass: InjectedSocket,
      documentRef: visibility,
      onPlayable: () => { ready++; },
      onFailure: reason => { failure = reason; },
    });
    const check = (condition, label) => { if (!condition) throw Error(label + " failure=" + failure + " ready=" + ready + " time=" + video.currentTime); };
    try {
      for (let i = 0; !socket && i < 50; i++) await wait(20);
      check(socket, "socket created");
      socket.deliver(init);
      for (let i = 0; i < 18; i++) {
        socket.deliver(fragments[i]);
        await wait(1000);
        if (i === 4) {
          check(!failure && ready >= 1 && video.videoWidth === 320 && video.videoHeight === 180 &&
            video.currentTime > 1 && video.getVideoPlaybackQuality().totalVideoFrames > 0, "initial real MSE playback");
          visibility.visibilityState = "hidden";
          visibility.dispatchEvent(new Event("visibilitychange"));
        }
        if (i === 9) {
          check(!failure, "hidden media bounded");
          visibility.visibilityState = "visible";
          visibility.dispatchEvent(new Event("visibilitychange"));
        }
        if (i === 15) {
          check(!failure && ready >= 2 && video.currentTime > 11 &&
            video.getVideoPlaybackQuality().totalVideoFrames > 0, "fresh MSE playback after hidden interval");
        }
        check(!failure, "continuous playback");
      }
      socket.deliver(new Uint8Array([1, 2, 3]).buffer);
      await wait(50);
      check(failure === "wire-error" && socket.closed, "malformed wire closes player");
      return { pass: true, ready, failure };
    } finally { player.dispose(); }
  };
  const result = await new Promise((ok, bad) => {
    const timer = setTimeout(() => bad(Error("Chromium MSE proof timed out")), 40000);
    cdp.addEventListener("message", event => {
      const m = JSON.parse(event.data);
      if (m.id !== 1) return;
      clearTimeout(timer);
      if (m.error || m.result?.exceptionDetails) {
        bad(Error(JSON.stringify(m.error || m.result.exceptionDetails))); return;
      }
      ok(m.result?.result?.value);
    });
    cdp.send(JSON.stringify({ id: 1, method: "Runtime.evaluate", params: {
      expression: "(" + proof.toString() + ")()", awaitPromise: true, returnByValue: true,
    } }));
  });
  assert.equal(result?.pass, true);
  console.log("CHROMIUM_REAL_MSE=PASS", JSON.stringify(result));
} finally {
  cdp?.close();
  if (chrome && chrome.exitCode === null) {
    chrome.kill("SIGTERM");
    await Promise.race([new Promise(ok => chrome.once("exit", ok)), sleep(2000)]);
    if (chrome.exitCode === null) chrome.kill("SIGKILL");
  }
  if (server) await new Promise(ok => server.close(ok));
  await rm(folder, { recursive: true, force: true });
}
