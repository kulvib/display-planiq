// Display-only policy. Historical power events belong to diagnostics; never
// convert a completed event into a current warning in the Control Room header.
export function currentClientState(state) {
  const value = String(state ?? "").trim().toLowerCase();
  return value && !["normal", "approved"].includes(value) ? value : null;
}

export function currentClientStateTone(state) {
  const value = currentClientState(state);
  if (!value) return "default";
  if (["error", "failed", "recovery_failed"].includes(value)) return "error";
  if (["rebooting", "wakeup", "updating", "shutting_down", "shutdown"].includes(value)) return "warning";
  return "default";
}

export function browserStatusTone(online, chromeColor, chromeStatus) {
  if (!online) return "default";
  const status = String(chromeStatus ?? "").trim().toLowerCase();
  // Missing/ambiguous status must never look verified healthy, even if an old
  // green color was cached from a previous report.
  if (!status || /ukendt|unknown|stale|ikke rapporteret/.test(status)) return "default";
  const color = String(chromeColor ?? "").trim().toLowerCase();
  if (["red", "error"].includes(color)) return "error";
  if (["orange", "yellow", "warning"].includes(color)) return "warning";
  if (["blue", "info"].includes(color)) return "info";
  if (["green", "success"].includes(color)) return "success";
  return "default";
}

export function calendarRebootIsActionable(status) {
  return ["error", "pending"].includes(String(status?.state ?? "").trim().toLowerCase());
}
