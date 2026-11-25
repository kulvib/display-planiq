/**
 * In-memory, bounded HLS.js live-edge latency observations (seconds).
 *
 * This is hls.latency (player-estimated live-edge position minus playhead),
 * NOT client capture-to-screen, HLS uploader age or network round-trip.
 * No identifiers, URLs, video data, additional requests or persistence.
 */
export function createLivestreamBrowserTiming(limit = 32) {
  if (!Number.isInteger(limit) || limit < 1 || limit > 128) {
    throw new RangeError("Invalid HLS observation limit");
  }
  const values = [];
  let ignored = 0;
  function quantile(p) {
    if (!values.length) return null;
    const sorted = [...values].sort((a, b) => a - b);
    const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil(p * sorted.length) - 1));
    return Math.round(sorted[index] * 10) / 10;
  }
  return {
    observe(seconds) {
      if (!Number.isFinite(seconds) || seconds < 0 || seconds > 120) {
        ignored++;
        return false;
      }
      values.push(seconds);
      if (values.length > limit) values.shift();
      return true;
    },
    snapshot() {
      return { samples: values.length, ignored, p50Seconds: quantile(0.5), p95Seconds: quantile(0.95) };
    },
    reset() {
      values.length = 0;
      ignored = 0;
    },
  };
}

// 63D-73A: local HLS.js reserve gate. No extra requests, storage or timers.
export function contiguousVideoBuffer(video) {
  const time = video.currentTime;
  if (!Number.isFinite(time)) return null;
  try {
    for (let i = 0; i < video.buffered.length; i++) {
      const start = video.buffered.start(i);
      const end = video.buffered.end(i);
      if (start <= time + 0.05 && time < end) {
        return { start, end, ahead: Math.max(0, end - Math.max(start, time)) };
      }
    }
  } catch { /* MediaSource may be detached during recovery. */ }
  return null;
}

export function latestManifestSegment(details) {
  const fragments = details?.fragments;
  const sn = Array.isArray(fragments) && fragments.length ? fragments[fragments.length - 1]?.sn : null;
  return Number.isSafeInteger(sn) && sn >= 0 ? sn : null;
}

export function hlsHttpTransportLabel(url, base) {
  try {
    const protocol = new URL(url, base).protocol;
    return protocol === "https:" ? "HTTPS" : protocol === "http:" ? "HTTP" : null;
  } catch { return null; }
}

export function createHlsReserveController(video, { onReady = () => {}, onBuffering = () => {}, onTapRequired = () => {}, onSnapshot = () => {}, now = () => performance.now() } = {}) {
  let duration = 2;
  let segments = 2;
  let phase = "priming";
  let pending = false;
  let blocked = false;
  let disposed = false;
  let epoch = 0;
  let ready = false;
  let stableSince = null;
  let refills = 0;
  let stalls = 0;
  let stallStarted = null;
  let stalledMs = 0;
  let lastSampleAt = -Infinity;
  let rate = 1;
  const minimum = () => duration * segments;
  const buffer = () => contiguousVideoBuffer(video);
  // Container timestamps may differ by a few frames from EXTINF/targetduration.
  const enough = (range) => Boolean(range && range.ahead >= minimum() - 0.05);
  function setRate(value) {
    if (rate === value && video.playbackRate === value) return;
    try { video.playbackRate = value; rate = value; } catch { rate = 1; }
  }
  function snapshot() {
    return {
      phase, aheadSeconds: buffer()?.ahead ?? 0, requiredSeconds: minimum(), reserveTargetSeconds: duration,
      refills, stalls, stalledSeconds: (stalledMs + (stallStarted === null ? 0 : Math.max(0, now() - stallStarted))) / 1000,
      playbackRate: rate,
    };
  }
  function publish(force = false) {
    if (disposed || (!force && now() - lastSampleAt < 1000)) return;
    lastSampleAt = now();
    onSnapshot(snapshot());
  }
  function finishStall() {
    if (stallStarted !== null) {
      stalledMs += Math.max(0, now() - stallStarted);
      stallStarted = null;
    }
  }
  function regulate() {
    if (disposed || phase !== "playing" || video.paused || video.seeking) return;
    const ahead = buffer()?.ahead ?? 0;
    // Hysteretic slowdown preserves headroom without a deliberate pause.
    // Reserve is a target, not a guarantee under arbitrary network loss.
    if (ahead < duration * 1.25) setRate(0.95);
    else if (ahead >= duration * 2) setRate(1);
  }
  function playing() {
    if (disposed || phase === "playing") return;
    phase = "playing";
    stableSince = now();
    finishStall();
    onTapRequired(false);
    onBuffering(false);
    regulate();
    publish(true);
  }
  function pump() {
    if (disposed) return false;
    if (phase === "playing") { regulate(); publish(); return false; }
    publish();
    if (pending || blocked || video.seeking || video.readyState < 2) return false;
    if (!enough(buffer())) return false;
    if (!ready) {
      ready = true;
      onReady();
    }
    const attempt = ++epoch;
    pending = true;
    // Invoke synchronously, so a user's tap still carries activation.
    let promise;
    try { promise = video.play(); } catch (error) { promise = Promise.reject(error); }
    Promise.resolve(promise).then(() => {
      if (disposed || attempt !== epoch) return;
      pending = false;
      playing();
    }, (error) => {
      if (disposed || attempt !== epoch) return;
      pending = false;
      if (error?.name !== "AbortError") {
        blocked = true;
        onTapRequired(true);
      }
    });
    return true;
  }
  function rearm() {
    if (disposed) return;
    epoch++;
    pending = false;
    blocked = false;
    stableSince = null;
    phase = ready ? "refilling" : "priming";
    video.pause();
    setRate(1);
    onTapRequired(false);
    if (ready) onBuffering(true);
    publish(true);
  }
  function waiting() {
    if (disposed || phase !== "playing" || video.paused || video.seeking) return;
    if (stallStarted === null) {
      stalls++;
      stallStarted = now();
      stableSince = null;
    }
    onBuffering(true);
    publish(true);
    if ((buffer()?.ahead ?? 0) >= duration - 0.05) return;
    refills++;
    segments = Math.min(3, segments + 0.5);
    rearm();
  }
  function tick() {
    if (disposed) return;
    if (phase === "playing") {
      regulate();
      if (stableSince !== null && now() - stableSince >= 30_000 && (buffer()?.ahead ?? 0) >= duration) {
        segments = Math.max(2, segments - 0.5);
        stableSince = now();
      }
      publish();
    } else {
      pump();
    }
  }
  function onPlaying() {
    if (disposed) return;
    // The gate owns autoplay. If an external caller attempts premature playback,
    // pause it rather than silently bypassing the minimum reserve.
    if (phase !== "playing" && !pending) {
      video.pause();
      pump();
      return;
    }
    if (stallStarted !== null) {
      finishStall();
      stableSince = now();
      publish(true);
    }
    playing();
    onBuffering(false);
  }
  const listeners = { progress: pump, loadeddata: pump, canplay: pump, seeked: pump, timeupdate: tick, waiting, playing: onPlaying };
  video.autoplay = false;
  for (const [event, handler] of Object.entries(listeners)) video.addEventListener(event, handler);
  return {
    pump,
    rearm,
    setTargetDuration(value) {
      if (Number.isFinite(value) && value >= 0.25 && value <= 10) duration = value;
      pump();
    },
    playFromGesture() {
      if (disposed) return false;
      blocked = false;
      return pump();
    },
    catchUp(livePosition) {
      if (disposed || phase !== "playing" || video.paused || video.seeking || !Number.isFinite(livePosition)) return false;
      if (livePosition - video.currentTime <= Math.max(6, duration * 3)) return false;
      const range = buffer();
      if (!range) return false;
      const target = Math.min(livePosition, range.end - minimum());
      if (target <= video.currentTime + 1) return false;
      video.currentTime = target;
      return true;
    },
    snapshot,
    dispose() {
      if (disposed) return;
      disposed = true;
      epoch++;
      setRate(1);
      for (const [event, handler] of Object.entries(listeners)) video.removeEventListener(event, handler);
    },
  };
}
