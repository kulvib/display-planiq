/** ClientFlow deployment states are authoritative backend observations, not % download. */
export const DEPLOYMENT_STEPS = Object.freeze([
  { state: "authorized", label: "Bestilt" },
  { state: "downloading", label: "Downloader" },
  { state: "verified", label: "Verificeret" },
  { state: "staged", label: "Klargjort" },
  { state: "activating", label: "Aktiverer" },
  { state: "health_check", label: "Kontrollerer" },
]);
export const CANCELLABLE_STATES = new Set(["authorized", "downloading", "verified", "staged"]);
export const TERMINAL_STATES = new Set(["succeeded", "failed", "cancelled", "rolled_back", "recovery_failed"]);
export const ALL_STATES = new Set([...DEPLOYMENT_STEPS.map((s) => s.state), ...TERMINAL_STATES, "rolling_back"]);
const VERSION = /^\d+\.\d+\.\d+$/;
const RELEASE_ID = /^clientflow-\d+\.\d+\.\d+-seq-\d+$/;
const DEPLOYMENT_ID = /^[0-9a-f-]{36}$/i;

export function deploymentPresentation(state) {
  const name = String(state || "").toLowerCase();
  const index = DEPLOYMENT_STEPS.findIndex((step) => step.state === name);
  if (index >= 0) return { label: DEPLOYMENT_STEPS[index].label, color: "info", step: index, terminal: false };
  if (name === "succeeded") return { label: "Gennemført", color: "success", step: 6, terminal: true };
  if (name === "rolling_back") return { label: "Gendanner tidligere version", color: "warning", step: -1, terminal: false };
  if (name === "rolled_back") return { label: "Tidligere version gendannet", color: "warning", step: -1, terminal: true };
  if (name === "failed") return { label: "Opdatering fejlede", color: "error", step: -1, terminal: true };
  if (name === "recovery_failed") return { label: "Recovery fejlede", color: "error", step: -1, terminal: true };
  if (name === "cancelled") return { label: "Annulleret", color: "default", step: -1, terminal: true };
  return { label: "Ukendt status", color: "warning", step: -1, terminal: false };
}

export function validateDeploymentHistory(rows, { limit = 20, allowMissing = false } = {}) {
  if (rows == null && allowMissing) return [];
  if (!Array.isArray(rows) || rows.length > limit) throw new Error("Deploymenthistorik er ugyldig");
  const seen = new Set();
  for (const row of rows) {
    if (!row || !DEPLOYMENT_ID.test(row.id || "") || seen.has(row.id) ||
        !Number.isSafeInteger(row.client_id) || row.client_id < 1 ||
        !VERSION.test(row.target_version || "") ||
        !RELEASE_ID.test(row.target_release_id || "") ||
        !ALL_STATES.has(row.state) ||
        !row.requested_at || !row.state_updated_at ||
        (TERMINAL_STATES.has(row.state) ? !row.completed_at : Boolean(row.completed_at)) ||
        (row.client_name != null && (typeof row.client_name !== "string" || row.client_name.length > 255)) ||
        (row.failure_message != null && (typeof row.failure_message !== "string" || row.failure_message.length > 500)) ||
        (row.failure_code != null && (typeof row.failure_code !== "string" || row.failure_code.length > 100))) {
      throw new Error("Deploymenthistorik indeholder en ugyldig eller modstridende status");
    }
    seen.add(row.id);
  }
  return rows;
}


export function validateActiveDeployments(rows, complete) {
  if (typeof complete !== "boolean") throw new Error("Aktiv opdateringsstatus er ufuldstændig");
  validateDeploymentHistory(rows, { limit: 1000 });
  const clientIds = new Set();
  for (const row of rows) {
    if (TERMINAL_STATES.has(row.state) || clientIds.has(row.client_id)) {
      throw new Error("Aktiv opdateringsstatus er modstridende");
    }
    clientIds.add(row.client_id);
  }
  return rows;
}
