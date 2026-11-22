/**
 * Bounded newest-only JPEG presentation with optional content-free timings.
 *
 * At most one JPEG waits for a browser animation frame. Metadata contains
 * timestamps and discard counts, NEVER image bytes. Optional callbacks are
 * purely local; transport and authentication remain untouched.
 */
export function createLatestRemoteFramePainter({
  requestFrame, cancelFrame, getImage, onFrameAssigned = null,
  onFrameReceived = null, now = () => Date.now(),
}) {
  let pending = null;
  let pendingTiming = null;
  let scheduled = null;
  let disposed = false;

  function flush() {
    if (disposed || pending === null || scheduled !== null) return;
    scheduled = requestFrame(() => {
      scheduled = null;
      if (disposed) return;
      const element = getImage();
      if (element && pending !== null) {
        const next = pending;
        const timing = pendingTiming;
        pending = null;
        pendingTiming = null;
        element.src = next;
        onFrameAssigned?.({
          receivedAt: timing.receivedAt,
          replacedWhileWaiting: timing.replacedWhileWaiting,
        });
      }
    });
  }

  return {
    push(encodedJpeg, { receivedAt } = {}) {
      if (disposed || typeof encodedJpeg !== "string" || !encodedJpeg) return;
      const replacedWhileWaiting = pending ? pendingTiming.replacedWhileWaiting + 1 : 0;
      const measuredAt = Number.isFinite(receivedAt) ? receivedAt : onFrameReceived?.();
      pending = `data:image/jpeg;base64,${encodedJpeg}`;
      pendingTiming = {
        receivedAt: Number.isFinite(measuredAt) ? measuredAt : now(),
        replacedWhileWaiting,
      };
      flush();
    },
    flush,
    clear() {
      if (scheduled !== null) cancelFrame(scheduled);
      scheduled = null;
      pending = null;
      pendingTiming = null;
    },
    dispose() {
      this.clear();
      disposed = true;
    },
  };
}
