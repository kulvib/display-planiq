// One pure decision for Control Room button visibility, disabled state and
// click-time authorization. The backend is still authoritative for API calls.
const BROWSER = new Set(["start", "stop"]);
const DISPLAY = new Set(["sleep", "wakeup"]);
const SUPPORT = new Set(["terminal", "remote"]);

export function controlRoomRoleAllows(role, action) {
  if (SUPPORT.has(action) || action === "shutdown") return role === "superadmin";
  if (action === "reboot") return role === "admin" || role === "superadmin";
  if (BROWSER.has(action) || DISPLAY.has(action)) return ["bruger", "admin", "superadmin"].includes(role);
  return false;
}

export function controlRoomActionDecision(action, state) {
  if (!controlRoomRoleAllows(state.role, action)) {
    return { disabled: true, reason: "Du har ikke rettighed til denne handling" };
  }
  // Support remains accessible regardless of client state: the remote tool
  // reports connection failures itself. Permission checks still apply.
  if (SUPPORT.has(action)) return { disabled: false, reason: null };
  if (!state.online) return { disabled: true, reason: "Klienten er ikke online via canonical Status-domain" };
  if (state.systemLocked || ["reboot", "shutdown", "pending_reboot", "pending_shutdown"].includes(state.pendingAction)) {
    return { disabled: true, reason: "Klienten genstarter eller lukker ned" };
  }
  if (state.clientflowBusy) return { disabled: true, reason: "ClientFlow-deployment er i gang" };
  if (state.ubuntuBusy) return { disabled: true, reason: "Ubuntu opdateres — vent til opdateringen er færdig" };
  if (BROWSER.has(action) && state.clientStatus !== "approved") {
    return { disabled: true, reason: "Kiosk browser kan først styres, når klienten er godkendt" };
  }
  if (state.wakeInProgress && action === "wakeup") return { disabled: true, reason: "Tænd skærm er allerede sendt" };
  if (state.sleeping) {
    if (action === "wakeup") {
      if (state.busy) return { disabled: true, reason: "Der er allerede en handling i gang" };
      return { disabled: false, reason: null };
    }
    return { disabled: true, reason: "Skærmen er slukket — brug Tænd skærm først" };
  }
  if (action === "wakeup") return { disabled: true, reason: "Skærmen er allerede tændt" };
  if (state.busy) return { disabled: true, reason: "Der er allerede en handling i gang" };
  if (action === "start" && state.chromeRunning === true) return { disabled: true, reason: "Kiosk browser kører allerede" };
  if (action === "stop" && state.browserRequested === false && state.chromeRunning !== true) {
    return { disabled: true, reason: "Kiosk browser er allerede stoppet" };
  }
  return { disabled: false, reason: null };
}
