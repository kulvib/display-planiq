// Render intermediate seconds from a single authoritative Display report.
// Never infer a countdown from a stale status string or a client-side action.
const MAX_COUNTDOWN_SECONDS = 10;

export function receiveBrowserCountdown(value, receivedAtMs) {
  if (!value || typeof value !== "object") return null;
  if (!Number.isFinite(receivedAtMs)) return null;
  if (!Number.isInteger(value.remaining_seconds) || value.remaining_seconds < 1 || value.remaining_seconds > MAX_COUNTDOWN_SECONDS) return null;
  if (typeof value.ends_at !== "string" || typeof value.server_now !== "string") return null;
  const endsAtMs = Date.parse(value.ends_at);
  const serverNowMs = Date.parse(value.server_now);
  const remainingMs = endsAtMs - serverNowMs;
  if (!Number.isFinite(remainingMs) || remainingMs <= 0 || remainingMs > (value.remaining_seconds + 2) * 1000) return null;
  const reason = typeof value.reason === "string" ? value.reason : "";
  const step = typeof value.step === "string" ? value.step : "";
  return { deadlineMs: receivedAtMs + remainingMs, reason, step };
}

export function browserCountdownSeconds(snapshot, nowMs) {
  if (!snapshot || !Number.isFinite(nowMs)) return null;
  const msLeft = snapshot.deadlineMs - nowMs;
  return msLeft > 0 ? Math.ceil(msLeft / 1000) : 0;
}

export function formatBrowserCountdownStatus(snapshot, nowMs) {
  const seconds = browserCountdownSeconds(snapshot, nowMs);
  if (seconds === null) return null;
  // Reaching zero does NOT prove that Chrome started; await the agent's state.
  if (seconds === 0) return "Afventer ny browserstatus fra klienten…";
  const unit = seconds === 1 ? "sekund" : "sekunder";
  if (snapshot.step === "display_sleep_countdown" || snapshot.reason === "display_power_off") {
    return `Skærm slukkes om ${seconds} ${unit}…`;
  }
  const prefix = snapshot.reason === "configuration_change"
    ? "Kiosk browser starter ved URL-skift"
    : snapshot.reason === "reset_browser"
      ? "Kiosk browser nulstilles — starter"
      : snapshot.reason.startsWith("calendar")
        ? "Kiosk browser starter fra kalender"
        : "Kiosk browser starter";
  return `${prefix} om ${seconds} ${unit}…`;
}
