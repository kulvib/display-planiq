/**
 * Keep the newest pending pointer move and deliver the trailing position.
 * Pure timing utility: no mouse button/key/scroll transitions are coalesced.
 * Those transitions flush pending movement before being sent.
 */
export function createLatestPointerMoveScheduler({ now, schedule, cancel, send }) {
  let pending = null;
  let timer = null;
  let lastSentAt = -Infinity;

  const flush = () => {
    if (timer !== null) {
      cancel(timer);
      timer = null;
    }
    if (pending === null) return;
    const current = pending;
    pending = null;
    if (send(current)) lastSentAt = now();
  };

  return {
    move(payload, intervalMs = 33) {
      // Never re-order a button transition around an already queued move.
      pending = payload;
      if (timer !== null) return;
      const delay = Math.max(0, lastSentAt + intervalMs - now());
      if (delay === 0) {
        flush();
      } else {
        timer = schedule(() => {
          timer = null;
          flush();
        }, delay);
      }
    },
    flush,
    clear() {
      if (timer !== null) cancel(timer);
      timer = null;
      pending = null;
      lastSentAt = -Infinity;
    },
  };
}
