export function getBrowserProcessActionDisabledInfo(key, chromeIsRunning, browserRequested) {
  if (key === "start" && chromeIsRunning === true) {
    return { disabled: true, reason: "Kiosk browser kører allerede" };
  }

  // A stopped process is not enough to disable Stop: the runtime can still have
  // browser_requested=true and be retrying after a crash or waiting for session.
  // A process that is still running can be stopped even when the desired
  // browser_requested state is false (e.g. a delayed shutdown/stray process).
  if (key === "stop" && browserRequested === false && chromeIsRunning !== true) {
    return { disabled: true, reason: "Kiosk browser er allerede stoppet" };
  }

  return null;
}
