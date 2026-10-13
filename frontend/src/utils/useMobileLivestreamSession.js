import { useCallback, useEffect, useState } from "react";
import {
  MOBILE_LIVESTREAM_DEFAULT_SECONDS,
  MOBILE_LIVESTREAM_DURATIONS,
  mobileLivestreamDeadline,
  remainingMobileLivestreamSeconds,
} from "./mobileLivestreamTiming.mjs";

// A viewer-local lease: the backend remains authoritative over the shared producer.
// The deadline is based on wall-clock time, never on interval tick counts.
export function useMobileLivestreamSession(isTouchHandset) {
  const [durationSeconds, setDurationSeconds] = useState(MOBILE_LIVESTREAM_DEFAULT_SECONDS);
  const [endsAtMs, setEndsAtMs] = useState(null);
  const [clockMs, setClockMs] = useState(() => Date.now());
  const [expired, setExpired] = useState(false);

  const stop = useCallback((timedOut = false) => {
    setEndsAtMs(null);
    setExpired(timedOut);
  }, []);

  const start = useCallback(() => {
    if (!isTouchHandset || document.visibilityState === "hidden") return;
    const now = Date.now();
    setClockMs(now);
    setEndsAtMs(mobileLivestreamDeadline(now, durationSeconds));
    setExpired(false);
  }, [isTouchHandset, durationSeconds]);

  const selectDuration = useCallback((seconds) => {
    if (MOBILE_LIVESTREAM_DURATIONS.includes(Number(seconds))) {
      setDurationSeconds(Number(seconds));
    }
  }, []);

  useEffect(() => {
    if (!isTouchHandset || endsAtMs == null) return undefined;
    const tick = () => {
      const now = Date.now();
      setClockMs(now);
      if (remainingMobileLivestreamSeconds(endsAtMs, now) === 0) stop(true);
    };
    tick();
    const interval = window.setInterval(tick, 250);
    return () => window.clearInterval(interval);
  }, [isTouchHandset, endsAtMs, stop]);

  useEffect(() => {
    if (!isTouchHandset || endsAtMs == null) return undefined;
    // Mobile background tabs must stop immediately instead of prolonging the viewer lease.
    const onHide = () => {
      if (document.visibilityState === "hidden") stop(false);
    };
    const onPageHide = () => stop(false);
    document.addEventListener("visibilitychange", onHide);
    window.addEventListener("pagehide", onPageHide);
    return () => {
      document.removeEventListener("visibilitychange", onHide);
      window.removeEventListener("pagehide", onPageHide);
    };
  }, [isTouchHandset, endsAtMs, stop]);

  useEffect(() => {
    // If a phone is rotated or resized out of the handset breakpoint,
    // never resurrect a previously started mobile session on returning.
    if (!isTouchHandset && endsAtMs != null) stop(false);
  }, [isTouchHandset, endsAtMs, stop]);

  const isActive = isTouchHandset && endsAtMs != null && remainingMobileLivestreamSeconds(endsAtMs, Date.now()) > 0;
  return {
    isActive,
    expired,
    durationSeconds,
    remainingSeconds: isActive ? remainingMobileLivestreamSeconds(endsAtMs, clockMs) : 0,
    start,
    stop,
    selectDuration,
  };
}
