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

// Display the single backend-validated APT inventory; the legacy scalar
// is not independent proof of a current package count.
export function ubuntuInventoryView(client) {
  const inventory = client?.ubuntu_update_inventory;
  const count = inventory?.update_count;
  const known = inventory?.state === "known" && !inventory.error && Number.isSafeInteger(count) && count >= 0;
  const current = known && client?.presence?.is_online === true;
  const label = current
    ? count === 0 ? "Ingen opdateringer" : `${count} pakke${count === 1 ? "" : "r"} klar`
    : known ? `Senest målt: ${count} pakke${count === 1 ? "" : "r"}`
    : inventory?.state === "stale" ? "Pakkeliste forældet" : "Pakkestatus ikke verificeret";
  return { count: current ? count : null, label, level: current ? count > 0 ? "warn" : "ok" : "neutral" };
}

export function diagnosticServiceLevel(value, { expectedActive = true, online = true } = {}) {
  if (!online) return "neutral";
  const state = String(value ?? "").trim().toLowerCase();
  if (["failed", "error", "fejl", "missing", "mangler", "not-found"].includes(state)) return "error";
  if (["active", "running", "aktiv", "kører", "ready", "klar"].includes(state)) return "ok";
  if (["activating", "deactivating", "starting", "starter", "stopper", "reloading", "opdaterer"].includes(state)) return "info";
  if (["inactive", "idle", "stop", "stoppet"].includes(state)) return expectedActive ? "error" : "ok";
  if (["warning", "advarsel"].includes(state)) return "warn";
  return "neutral";
}

export function defaultClientflowTarget(installed, stable, selectable) {
  const parse = (value) => {
    const version = String(value ?? "").replace(/^v/i, "");
    return /^\d+\.\d+\.\d+$/.test(version) ? version.split(".").map(Number) : null;
  };
  const from = parse(installed), to = parse(stable);
  if (!from || !to || !selectable.some((release) => release.version === stable)) return "";
  for (let i = 0; i < 3; i++) {
    if (to[i] < from[i]) return "";
    if (to[i] > from[i]) return stable;
  }
  return stable;
}
