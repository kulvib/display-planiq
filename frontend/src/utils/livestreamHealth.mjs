// Retain livestream_last_error as a historical diagnostic value. Suppress
// an *active* error only after a new running stream AND process are reported.
export function hasActiveLivestreamError(client) {
  if (!String(client?.livestream_last_error ?? "").trim()) return false;
  const status = String(client?.livestream_status ?? "").trim().toLowerCase();
  const process = String(client?.livestream_process_status ?? "").trim().toLowerCase();
  return !(status === "running" && process === "running");
}
