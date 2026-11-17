// Non-security browser scheduling hint only. Backend verifies every token,
// refresh-family revocation and absolute timeout independently.
export function decodedAccessTokenExpiryMs(token) {
  try {
    const segments = String(token || "").split(".");
    if (segments.length !== 3 || !segments[1]) return null;
    const encoded = segments[1].replace(/-/g, "+").replace(/_/g, "/");
    const payload = JSON.parse(atob(encoded));
    const seconds = payload?.exp;
    return Number.isSafeInteger(seconds) && seconds > 0 ? seconds * 1000 : null;
  } catch {
    return null;
  }
}

export function needsProactiveRefresh(expiryMs, nowMs = Date.now()) {
  return Number.isFinite(expiryMs) && expiryMs > 0 && expiryMs <= nowMs + 60_000;
}
