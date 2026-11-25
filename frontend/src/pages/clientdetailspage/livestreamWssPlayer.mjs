// Unmounted MSE candidate. The owning view supplies a generation-bound ticket
// request and owns heartbeat, 30-second hidden lifecycle, fallback and cleanup.
import { decodeLiveWire, LIVE_INIT } from "./livestreamWssWire.mjs";
import { avcMime } from "./livestreamFmp4Codec.mjs";

const MAX_PENDING = 2;
const MAX_BEHIND = 4;
const START_RESERVE = 1.5;
const KEEP_BEHIND = 3;
const STARTUP_MS = 8000;
const STALE_MS = 5000;

export function createWssPlayer(video, {
  url, getTicket, onPlayable = () => {}, onFailure = () => {},
  onLatency = () => {}, documentRef = document,
  MediaSourceClass = MediaSource, SocketClass = WebSocket, urlApi = URL,
  clock = () => performance.now(),
}) {
  let disposed = false, failed = false, socket = null, source = null, buffer = null;
  let objectUrl = null, decoderEpoch = 0, decoderCleanup = () => {};
  let cursor = 0, lastTimestamp = -1, queue = [], started = false, announced = false;
  const startedAt = clock();
  let readyAt = startedAt, lastFragmentAt = readyAt, lastProgressAt = readyAt;
  let everPlayable = false;
  let lastInit = null, hiddenInit = null, hiddenFrame = null, wasHidden = false;
  let hiddenCursor = 0, hiddenTimestamp = -1;
  let lastTime = null, lastEdge = null, lastLatencyAt = -Infinity;
  const abort = new AbortController();

  function cleanupDecoder() {
    decoderEpoch++;
    decoderCleanup();
    decoderCleanup = () => {};
    buffer = null; source = null; queue = []; started = false;
    cursor = 0; lastTimestamp = -1; lastEdge = null; lastTime = null;
    video.pause();
    video.removeAttribute("src");
    video.load();
    if (objectUrl !== null) urlApi.revokeObjectURL(objectUrl);
    objectUrl = null;
  }
  function dispose() {
    if (disposed) return;
    disposed = true;
    abort.abort();
    clearInterval(timer);
    documentRef.removeEventListener("visibilitychange", visible);
    video.removeEventListener("timeupdate", progress);
    video.removeEventListener("playing", progress);
    video.removeEventListener("error", mediaError);
    if (socket) {
      socket.onopen = socket.onmessage = socket.onclose = socket.onerror = null;
      try { socket.close(); } catch {}
    }
    cleanupDecoder();
    lastInit = hiddenInit = hiddenFrame = null;
    onLatency(null);
  }
  function fail(reason) {
    if (disposed || failed) return;
    failed = true;
    dispose();
    onFailure(reason);
  }
  function mediaError() { fail("media-error"); }
  function progress() {
    if (disposed || documentRef.visibilityState === "hidden") return;
    const position = video.currentTime;
    if (!Number.isFinite(position)) return;
    if (lastTime === null || position > lastTime + 0.01) {
      if (lastTime !== null && !video.paused && video.readyState >= 2 && !video.seeking && !announced) {
        announced = true;
        everPlayable = true;
        onPlayable();
      }
      lastProgressAt = clock();
      lastTime = position;
    }
    if (announced && lastEdge !== null && clock() - lastLatencyAt >= 1000) {
      lastLatencyAt = clock();
      // Buffered edge distance only; not capture-to-display delay.
      onLatency(Math.max(0, lastEdge - position));
    }
  }
  function pump(epoch) {
    if (disposed || epoch !== decoderEpoch || !buffer || buffer.updating || documentRef.visibilityState === "hidden") return;
    try {
      const ranges = buffer.buffered;
      if (ranges.length) {
        const start = ranges.start(ranges.length - 1);
        const edge = ranges.end(ranges.length - 1);
        lastEdge = edge;
        if (documentRef.visibilityState !== "hidden" && cursor > 0 && edge - start >= START_RESERVE) {
          if (!started || video.currentTime < start || edge - video.currentTime > MAX_BEHIND) {
            video.currentTime = Math.max(start, edge - START_RESERVE);
            lastTime = null;
          }
          if (!started) {
            started = true;
            const attempt = video.play();
            Promise.resolve(attempt).catch(() => {
              if (!disposed && decoderEpoch === epoch) fail("autoplay");
            });
          }
          const cut = Math.min(edge - KEEP_BEHIND, video.currentTime - 1);
          if (ranges.start(0) < cut - 1) {
            buffer.remove(ranges.start(0), cut);
            return;
          }
        }
        // Do not accumulate media indefinitely in a throttled background tab.
        if (ranges.end(ranges.length - 1) - ranges.start(0) > 12) {
          fail("buffer-budget");
          return;
        }
      }
      if (queue.length) buffer.appendBuffer(queue.shift());
    } catch { fail("append-error"); }
  }
  function initialize(payload) {
    let mime;
    try { mime = avcMime(payload); } catch { fail("unsupported-init"); return; }
    if (!MediaSourceClass.isTypeSupported(mime)) { fail("unsupported-codec"); return; }
    cleanupDecoder();
    lastInit = payload;
    if (announced) readyAt = clock();
    announced = false;
    onLatency(null);
    lastProgressAt = clock();
    const epoch = decoderEpoch;
    source = new MediaSourceClass();
    const currentSource = source;
    const opened = () => {
      if (disposed || epoch !== decoderEpoch) return;
      try {
        buffer = currentSource.addSourceBuffer(mime);
        buffer.mode = "segments";
        buffer.addEventListener("updateend", updated);
        buffer.addEventListener("error", sourceError);
        pump(epoch);
      } catch { fail("source-buffer"); }
    };
    const updated = () => pump(epoch);
    const sourceError = () => { if (epoch === decoderEpoch) fail("source-error"); };
    decoderCleanup = () => {
      currentSource.removeEventListener("sourceopen", opened);
      currentSource.removeEventListener("sourceclose", sourceError);
      buffer?.removeEventListener("updateend", updated);
      buffer?.removeEventListener("error", sourceError);
    };
    queue.push(payload);
    currentSource.addEventListener("sourceopen", opened);
    currentSource.addEventListener("sourceclose", sourceError);
    objectUrl = urlApi.createObjectURL(currentSource);
    video.src = objectUrl;
  }
  function acceptFragment(frame) {
    if (!source || (cursor !== 0 && frame.sequence !== cursor + 1) ||
        frame.timestampUs <= lastTimestamp || queue.length >= MAX_PENDING) {
      fail("fragment-discontinuity"); return;
    }
    cursor = frame.sequence;
    lastTimestamp = frame.timestampUs;
    lastFragmentAt = clock();
    queue.push(frame.payload);
    pump(decoderEpoch);
  }
  function enterHidden() {
    if (wasHidden) return;
    wasHidden = true;
    hiddenInit = lastInit;
    hiddenFrame = null;
    hiddenCursor = cursor;
    hiddenTimestamp = lastTimestamp;
  }
  function message(event) {
    if (disposed) return;
    try {
      const frame = decodeLiveWire(event.data);
      if (documentRef.visibilityState === "hidden") {
        enterHidden();
        // Hold only init and the latest complete fragment; no background MSE
        // append queue. A fresh decode point is selected when visible again.
        if (frame.kind === LIVE_INIT) {
          hiddenInit = frame.payload; hiddenFrame = null;
          hiddenCursor = 0; hiddenTimestamp = -1;
        } else {
          if (!hiddenInit || (hiddenCursor !== 0 && frame.sequence !== hiddenCursor + 1) ||
              frame.timestampUs <= hiddenTimestamp) {
            fail("hidden-discontinuity"); return;
          }
          hiddenCursor = frame.sequence; hiddenTimestamp = frame.timestampUs;
          hiddenFrame = frame; lastFragmentAt = clock();
        }
        return;
      }
      if (wasHidden) visible();
      if (disposed) return;
      if (frame.kind === LIVE_INIT) { initialize(frame.payload); return; }
      acceptFragment(frame);
    } catch { fail("wire-error"); }
  }
  function visible() {
    if (disposed) return;
    if (documentRef.visibilityState === "hidden") { enterHidden(); return; }
    if (wasHidden) {
      wasHidden = false;
      const init = hiddenInit, frame = hiddenFrame;
      hiddenInit = hiddenFrame = null;
      if (frame && init && clock() - lastFragmentAt <= STALE_MS) {
        initialize(init);
        if (!disposed) acceptFragment(frame);
        return;
      }
    }
    if (clock() - lastFragmentAt > STALE_MS || clock() - lastProgressAt > STALE_MS) {
      fail("stale-background"); return;
    }
    pump(decoderEpoch);
  }
  function tick() {
    if (disposed || documentRef.visibilityState === "hidden") return;
    const now = clock();
    if ((!everPlayable && now - startedAt > STARTUP_MS) ||
        (!announced && now - readyAt > STARTUP_MS) ||
        now - lastFragmentAt > STARTUP_MS ||
        (announced && now - lastProgressAt > STALE_MS)) fail("media-timeout");
  }
  video.muted = true;
  video.autoplay = false;
  video.playsInline = true;
  const timer = setInterval(tick, 500);
  documentRef.addEventListener("visibilitychange", visible);
  video.addEventListener("timeupdate", progress);
  video.addEventListener("playing", progress);
  video.addEventListener("error", mediaError);
  Promise.resolve().then(async () => {
    const endpoint = new URL(url);
    if (endpoint.protocol !== "wss:" || endpoint.search || endpoint.hash || endpoint.username || endpoint.password) throw new Error("invalid endpoint");
    const ticket = await getTicket({ signal: abort.signal });
    if (disposed) return;
    if (ticket?.subprotocol !== "clientflow-livestream-v1" ||
        !/^[A-Za-z0-9_-]{43}$/.test(ticket.ticket)) throw new Error("invalid ticket");
    socket = new SocketClass(endpoint.href, [ticket.subprotocol, ticket.ticket]);
    socket.binaryType = "arraybuffer";
    socket.onmessage = message;
    socket.onopen = () => { if (socket.protocol !== ticket.subprotocol) fail("protocol"); };
    socket.onclose = () => fail("socket-closed");
    socket.onerror = () => fail("socket-error");
  }).catch(() => fail("connect-error"));
  return { dispose };
}
