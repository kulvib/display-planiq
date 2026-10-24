// The server is authoritative; unknown also covers older kiosk releases.
export function normalizeBrowserFullscreen(value) {
  return value === "fullscreen" || value === "windowed" ? value : "unknown";
}

export function browserFullscreenLabel(value) {
  const state = normalizeBrowserFullscreen(value);
  return state === "fullscreen" ? "Fuldskærm" : state === "windowed" ? "Ikke fuldskærm" : "Ukendt";
}

// Render fullscreen only when canonical Display explicitly confirms Chrome is running.
// Unknown or stale browser states must not masquerade as a running kiosk.
export function visibleBrowserFullscreen(online, chromeRunning, fullscreen) {
  return online === true && chromeRunning === true
    ? browserFullscreenLabel(fullscreen)
    : null;
}
