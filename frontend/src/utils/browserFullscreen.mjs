// The server is authoritative; unknown also covers older kiosk releases.
export function normalizeBrowserFullscreen(value) {
  return value === "fullscreen" || value === "windowed" ? value : "unknown";
}

export function browserFullscreenLabel(value) {
  const state = normalizeBrowserFullscreen(value);
  return state === "fullscreen" ? "Fuldskærm" : state === "windowed" ? "Ikke fuldskærm" : "Ukendt";
}
