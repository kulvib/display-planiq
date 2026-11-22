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
