// Browser-only realtime subscription lifecycle. No database access, no shared
// timers and no background traffic after route-unmount or session logout.
export const REALTIME_RETRY_MIN_MS = 2_000;
export const REALTIME_RETRY_MAX_MS = 60_000;

export function realtimeRetryDelayMs(consecutiveFailures, error = null) {
  const failures = Math.max(1, Math.floor(Number(consecutiveFailures) || 1));
  const exponential = Math.min(
    REALTIME_RETRY_MAX_MS,
    REALTIME_RETRY_MIN_MS * 2 ** Math.min(failures - 1, 5),
  );
  const retryAfter = Number(error?.retryAfterSeconds);
  return Number.isFinite(retryAfter) && retryAfter > 0
    ? Math.min(REALTIME_RETRY_MAX_MS, Math.max(exponential, Math.ceil(retryAfter * 1000)))
    : exponential;
}

export function createRealtimeRequestScope(authSessionSignal) {
  const controller = new AbortController();
  const onLogout = () => controller.abort();
  if (authSessionSignal?.aborted) {
    controller.abort();
  } else {
    authSessionSignal?.addEventListener("abort", onLogout, { once: true });
  }
  return {
    signal: controller.signal,
    cancel() {
      controller.abort();
      authSessionSignal?.removeEventListener("abort", onLogout);
    },
  };
}

// Resolve false on abort; never leave a sleeping subscriber behind after logout.
export function waitForRealtimeRetry(delayMs, signal) {
  return new Promise((resolve) => {
    if (signal?.aborted) {
      resolve(false);
      return;
    }
    let timerId;
    const finish = () => {
      clearTimeout(timerId);
      signal?.removeEventListener("abort", onAbort);
      resolve(!signal?.aborted);
    };
    const onAbort = () => finish();
    signal?.addEventListener("abort", onAbort, { once: true });
    timerId = setTimeout(finish, Math.max(0, Number(delayMs) || 0));
  });
}
