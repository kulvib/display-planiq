/** The displayed catalog is never installation authority. */
import { validateActiveDeployments, validateDeploymentHistory } from "./clientflowDeploymentHistory.mjs";
export const BASELINE_ID = "clientflow-1.4.0-seq-1250";
export const BASELINE_VERSION = "1.4.0";
export const MAX_ORDER_CLIENTS = 25;
export const CLOSED_STANDARD_ID = "clientflow-1.4.1-seq-1251";
export const CLOSED_STANDARD_VERSION = "1.4.1";

export function validateStandardBaselineResponse(data) {
  const successor = data?.stable_release_id === CLOSED_STANDARD_ID;
  const expectedId = successor ? CLOSED_STANDARD_ID : BASELINE_ID;
  const expectedVersion = successor ? CLOSED_STANDARD_VERSION : BASELINE_VERSION;
  if (!data || data.phase !== "standard_baseline" || data.stable_release_id !== expectedId ||
      data.stable_version !== expectedVersion || data.authorization_active !== false ||
      (successor && (data.cutover_enabled !== false || data.fleet_open !== false ||
        data.standard_order_review_available !== false || data.successor_pilot_review_available !== false ||
        typeof data.closed_standard_transition_pending !== "boolean" ||
        data.revision !== (data.closed_standard_transition_pending ? 2 : 3))) ||
      data.rollback_available !== false || data.fresh_install_open !== false ||
      typeof data.standard_order_review_available !== "boolean" ||
      data.client_inventory_complete !== true || !Array.isArray(data.available_clients) ||
      data.available_clients.length > 1000 || !Array.isArray(data.available_releases) ||
      data.available_releases.length !== 1 || data.available_releases[0]?.release_id !== expectedId ||
      data.available_releases[0]?.version !== expectedVersion ||
      data.available_releases[0]?.status !== "stable" ||
      data.available_releases[0]?.deployment_authorized !== false ||
      !Array.isArray(data.waves) || data.waves.length !== 0) {
    throw new Error("Standardrelease-oversigten kunne ikke verificeres");
  }
  validateActiveDeployments(data.active_deployments, data.active_deployments_complete);
  validateDeploymentHistory(data.recent_deployments);
  const ids = new Set();
  for (const row of data.available_clients) {
    if (!row || !Number.isSafeInteger(row.id) || row.id <= 0 || ids.has(row.id) ||
        typeof row.name !== "string" || !row.name.trim() ||
        (row.reported_version != null && !/^\d+\.\d+\.\d+$/.test(row.reported_version))) {
      throw new Error("Ugyldig klientoversigt");
    }
    ids.add(row.id);
  }
  return data;
}

export function eligibleOrderClients(status) {
  if (status?.standard_order_review_available !== true || status?.client_inventory_complete !== true ||
      status?.active_deployments_complete !== true) return [];
  const active = new Set(status.active_deployments.map((row) => row.client_id));
  return status.available_clients.filter((row) => row.reported_version === "1.3.47" && !active.has(row.id));
}

export function validateOrderAvailability(data) {
  if (data?.available !== true || data.target_release_id !== BASELINE_ID ||
      data.target_version !== BASELINE_VERSION || !/^[a-f0-9]{64}$/.test(data.bundle_sha256 || "") ||
      !Number.isSafeInteger(data.revision) || data.revision < 1 ||
      data.max_clients !== MAX_ORDER_CLIENTS || data.rollback_available !== false) {
    throw new Error(data?.available === false ? "Udrulning afventer godkendelse af release og fysisk pilot" : "Releaseautorisation kunne ikke verificeres");
  }
  return data;
}

export function prepareOrderTargets(status, ids) {
  const available = new Map(eligibleOrderClients(status).map((row) => [row.id, row]));
  if (!Array.isArray(ids) || !ids.length || ids.length > MAX_ORDER_CLIENTS ||
      new Set(ids).size !== ids.length || ids.some((id) => !available.has(id))) {
    throw new Error("Klientvalget er ændret eller ikke tilgængeligt – kontrollér oversigten igen");
  }
  return [...ids].sort((a,b) => a-b).map((id) => ({
    client_id: id, expected_source_version: available.get(id).reported_version,
  }));
}

export function verifyOrderResult(result, targets) {
  if (result?.target_release_id !== BASELINE_ID || !Array.isArray(result.deployments) ||
      result.deployments.length !== targets.length) throw new Error("Bestillingens resultat er ukendt – hent status før nyt forsøg");
  const expected = new Set(targets.map((row) => row.client_id));
  const deployments = new Set();
  for (const row of result.deployments) {
    if (!row || row.state !== "authorized" || !expected.delete(row.client_id) ||
        !/^[0-9a-f-]{36}$/i.test(row.deployment_id || "") || deployments.has(row.deployment_id)) {
      throw new Error("Bestillingens resultat er ukendt – hent status før nyt forsøg");
    }
    deployments.add(row.deployment_id);
  }
  return result;
}
