// Pure, bounded polling policy. An old Chrome step or permanently rejected
// enrollment must not hold an otherwise healthy fleet at 10s reconciliation.
const ACTIVE_STATES = new Set(["wakeup", "rebooting", "updating"]);
const PENDING_ENROLLMENT = new Set(["pending", "enrolling", "awaiting_approval"]);
const BUSY_CLIENT_LIST_CHROME_STEPS = new Set([
  "clear_cookies", "terminate_chrome", "kill_chrome", "starting_chrome",
  "countdown", "display_sleep_countdown", "system_reboot_countdown",
  "system_rebooting", "system_shutting_down",
]);

function deadlineMs(value) {
  if (!value) return 0;
  const timestamp = String(value);
  const parsed = Date.parse(/[zZ]$|[+-]\d{2}:?\d{2}$/.test(timestamp) ? timestamp : timestamp + "Z");
  return Number.isFinite(parsed) ? parsed : 0;
}

export function clientListNeedsFastPolling(items = [], nowMs = Date.now()) {
  return items.some((client) => {
    const status = String(client?.status || "").trim().toLowerCase();
    const state = String(client?.state || "").trim().toLowerCase();
    const pendingAction = String(client?.pending_chrome_action || "none").trim().toLowerCase();
    const chromeStep = String(client?.chrome_step || "").trim().toLowerCase();
    const activeState = ACTIVE_STATES.has(state);
    const countdown = client?.browser_countdown;
    const liveCountdown = BUSY_CLIENT_LIST_CHROME_STEPS.has(chromeStep)
      && deadlineMs(countdown?.ends_at) > nowMs;
    return (
      PENDING_ENROLLMENT.has(status) ||
      (pendingAction && pendingAction !== "none") ||
      activeState || liveCountdown ||
      client?.pending_reboot === true ||
      client?.pending_shutdown === true ||
      client?.pending_os_update === true
    );
  });
}

export function clientListPollDelay(items = [], nowMs = Date.now()) {
  return clientListNeedsFastPolling(items, nowMs) ? 10_000 : 60_000;
}
