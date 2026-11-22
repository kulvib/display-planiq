/**
 * Bounded, content-free browser-only Remote Desktop delivery metrics.
 *
 * Measurements are on one browser performance clock:
 *   websocket/HTTPS message received -> queued RAF -> <img> load
 * They exclude network travel *before* the browser event, GTK input handling,
 * remote capture and physical display scan-out. They are NOT mouse-to-pixel
 * latency. This module never handles the JPEG payload, credentials or user input.
 */
export function createRemoteDesktopTiming({ now, sampleLimit = 32 }) {
  if (typeof now !== "function") throw new TypeError("Monotonic clock required");
  if (!Number.isInteger(sampleLimit) || sampleLimit < 1 || sampleLimit > 128) {
    throw new RangeError("Invalid timing sample limit");
  }

  let received = 0;
  let assigned = 0;
  let decoded = 0;
  let replaced = 0;
  let active = null;
  let decodedSerial = 0;
  let serial = 0;
  const samples = [];

  function validDuration(start, end) {
    if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return null;
    return Math.min(60_000, Math.max(0, end - start));
  }

  function percentile(values, p) {
    if (!values.length) return null;
    const sorted = [...values].sort((a, b) => a - b);
    return Math.round(sorted[Math.floor((sorted.length - 1) * p)] * 10) / 10;
  }

  return {
    frameReceived() {
      received++;
      return now();
    },
    frameAssigned({ receivedAt, replacedWhileWaiting = 0 } = {}) {
      const at = now();
      replaced += Number.isFinite(replacedWhileWaiting)
        ? Math.max(0, Math.floor(replacedWhileWaiting)) : 0;
      assigned++;
      active = { serial: ++serial, at, receivedAt };
    },
    imageLoaded() {
      if (!active || active.serial === decodedSerial) return false;
      const at = now();
      const browserMs = validDuration(active.receivedAt, at);
      const decodeMs = validDuration(active.at, at);
      if (browserMs === null || decodeMs === null) return false;
      decodedSerial = active.serial;
      decoded++;
      samples.push({ browserMs, decodeMs });
      if (samples.length > sampleLimit) samples.shift();
      return true;
    },
    snapshot() {
      return {
        received, assigned, decoded, replaced,
        samples: samples.length,
        browserP50Ms: percentile(samples.map((s) => s.browserMs), 0.5),
        browserP95Ms: percentile(samples.map((s) => s.browserMs), 0.95),
        imageLoadP50Ms: percentile(samples.map((s) => s.decodeMs), 0.5),
      };
    },
    reset() {
      received = 0;
      assigned = 0;
      decoded = 0;
      replaced = 0;
      active = null;
      decodedSerial = 0;
      serial = 0;
      samples.length = 0;
    },
  };
}
