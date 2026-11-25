// Owns exactly one active player. Factories must return a synchronous disposer
// and cancel all asynchronous work when disposed. The owner supplies a cheap,
// generation-bound availability probe, and handles viewer lifecycle separately.
// This candidate is not yet mounted by either view.
export function createLivestreamTransportController({
  startWss, startHls, probeWss, onTransport = () => {}, onFailure = () => {},
  isVisible = () => document.visibilityState !== "hidden",
  schedule = (fn, ms) => setTimeout(fn, ms), cancel = id => clearTimeout(id),
}) {
  let stopped = false, epoch = 0, current = null, timer = null, probe = null;
  let retry = 0, stableHls = false, permanentHls = false;

  function clearTimer() {
    if (timer !== null) cancel(timer);
    timer = null;
  }
  function clearProbe() {
    if (probe) probe.abort();
    probe = null;
  }
  function detach() {
    epoch++;
    clearTimer();
    clearProbe();
    const old = current;
    current = null;
    stableHls = false;
    old?.dispose();
    onTransport(null);
  }
  function planRetry() {
    clearTimer();
    if (stopped || permanentHls || !stableHls || current?.kind !== "HLS") return;
    const delay = Math.min(120_000, 30_000 * 2 ** Math.min(retry, 2));
    timer = schedule(async () => {
      timer = null;
      if (stopped || !stableHls || current?.kind !== "HLS") return;
      if (!isVisible()) { planRetry(); return; }
      const owner = epoch;
      const controller = new AbortController();
      probe = controller;
      let available = false;
      try { available = await probeWss({ signal: controller.signal }); } catch {}
      if (stopped || epoch !== owner || probe !== controller) return;
      probe = null;
      if (available && isVisible()) { switchTo("WSS"); return; }
      retry++;
      planRetry();
    }, delay);
  }
  function switchTo(kind) {
    if (stopped) return;
    detach();
    const owner = epoch;
    // Factories may call ready/failure synchronously. Defer those callbacks
    // until ownership and its disposer have been installed.
    const callbacks = {
      onPlayable: () => queueMicrotask(() => {
        if (stopped || epoch !== owner) return;
        if (kind === "WSS") {
          retry = 0;
          onTransport("WSS");
        } else {
          stableHls = true;
          planRetry();
        }
      }),
      onFailure: reason => queueMicrotask(() => {
        if (stopped || epoch !== owner) return;
        if (kind === "WSS") {
          if (["unsupported-init", "unsupported-codec", "autoplay"].includes(reason)) permanentHls = true;
          retry++;
          switchTo("HLS");
        } else {
          detach();
          onFailure(reason);
        }
      }),
      // The existing HLS adapter reports actual HTTPS/HTTP only once playable.
      onHttpTransport: label => queueMicrotask(() => {
        if (!stopped && epoch === owner && kind === "HLS" && ["HTTPS", "HTTP"].includes(label)) onTransport(label);
      }),
    };
    try {
      const player = (kind === "WSS" ? startWss : startHls)(callbacks);
      if (typeof player?.dispose !== "function") throw new Error("missing disposer");
      current = { kind, dispose: () => player.dispose() };
    } catch {
      callbacks.onFailure("player-start");
    }
  }
  switchTo("WSS");
  return {
    dispose() {
      if (stopped) return;
      stopped = true;
      detach();
    },
  };
}
