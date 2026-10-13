// Mobile-only bounded viewing sessions; no server-side producer stop commands.
export const MOBILE_LIVESTREAM_DURATIONS = Object.freeze([15, 30, 60, 120]);
export const MOBILE_LIVESTREAM_DEFAULT_SECONDS = 30;

export function remainingMobileLivestreamSeconds(endsAtMs, nowMs) {
  if (!Number.isFinite(endsAtMs) || !Number.isFinite(nowMs)) return 0;
  return Math.max(0, Math.ceil((endsAtMs - nowMs) / 1000));
}

export function mobileLivestreamDeadline(nowMs, seconds) {
  if (!Number.isFinite(nowMs) || !MOBILE_LIVESTREAM_DURATIONS.includes(seconds)) {
    throw new RangeError("Ugyldig mobil livestream-varighed");
  }
  return nowMs + seconds * 1000;
}
