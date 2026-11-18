/**
 * Bounded, newest-only JPEG presentation. The renderer owns exactly one
 * waiting frame and never copies multi-megabyte JPEGs through React state.
 * All scheduling is local to the browser; no database or transport polling.
 */
export function createLatestRemoteFramePainter({ requestFrame, cancelFrame, getImage }) {
  let pending = null;
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
        pending = null;
        element.src = next;
      }
    });
  }

  return {
    push(encodedJpeg) {
      if (disposed || typeof encodedJpeg !== "string" || !encodedJpeg) return;
      pending = `data:image/jpeg;base64,${encodedJpeg}`;
      flush();
    },
    flush,
    clear() {
      if (scheduled !== null) cancelFrame(scheduled);
      scheduled = null;
      pending = null;
    },
    dispose() {
      this.clear();
      disposed = true;
    },
  };
}
