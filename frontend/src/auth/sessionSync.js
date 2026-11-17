// Pure, browser-independent validation for cross-tab session messages.
// Session IDs are identifiers, not authentication credentials. JWT and
// refresh-cookie verification remain exclusively server-owned.
export const SESSION_SYNC_STORAGE_KEY = "planiq.session.sync.v2";
const SESSION_ID_PATTERN = /^[a-f0-9]{32}$/;
const MAX_EVENT_AGE_MS = 60_000;
const CLOCK_SKEW_MS = 5_000;

export function isSessionId(value) {
  return typeof value === "string" && SESSION_ID_PATTERN.test(value);
}

export function isCurrentSessionEvent(message, sessionId, now = Date.now()) {
  if (!message || typeof message !== "object" || Array.isArray(message)) return false;
  if (!Number.isSafeInteger(message.writtenAt)) return false;
  if (message.writtenAt < now - MAX_EVENT_AGE_MS || message.writtenAt > now + CLOCK_SKEW_MS) return false;
  if (typeof message.source !== "string" || !message.source || message.source.length > 100) return false;
  if (message.type === "context") return true; // Trigger server validation only.
  if (!isSessionId(sessionId) || message.sessionId !== sessionId) return false;
  if (message.type === "logout") return ["idle", "absolute", "expired", "explicit"].includes(message.reason);
  if (message.type === "activity") {
    return Number.isSafeInteger(message.at) && message.at <= now + CLOCK_SKEW_MS &&
      message.at >= now - MAX_EVENT_AGE_MS;
  }
  return false;
}
