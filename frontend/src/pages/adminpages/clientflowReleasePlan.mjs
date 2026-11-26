/** Pure planning helpers: no method creates a deployment or authorizes a release. */
import { validateDeploymentHistory, validateActiveDeployments } from "./clientflowDeploymentHistory.mjs";

export const MAX_PLAN_CLIENTS = 25;
const VERSION = /^\d+\.\d+\.\d+$/;

export function validateReleaseReadiness(value, releaseId, revision) {
  const required = ["stable_catalog_binding", "physical_pilot", "database_cutover",
    "fleet", "fresh_install", "reproducible_candidate", "physical_recovery"];
  if (!value || value.schema_version !== 1 || value.release_id !== releaseId ||
      value.policy_revision !== revision ||
      value.deployment_authorized !== false ||
      value.automatic_rollout_authorized !== false ||
      value.ready_for_fleet !== false || value.ready_for_fresh_install !== false ||
      !Array.isArray(value.checks) || value.checks.length !== required.length ||
      value.checks.some((item, index) => item?.id !== required[index] ||
        (index === 0
          ? (item.ready !== true || item.reason !== null)
          : (item.ready !== false || typeof item.reason !== "string" || !item.reason.trim())))) {
    throw new Error("Release-readiness kan ikke verificeres – alle installationshandlinger er spærret");
  }
  return value;
}

/** Strict reviewed release bytes. UI never infers permission from an archive. */
const APPROVED_PILOTS = Object.freeze({
  "clientflow-1.3.45-seq-1246": Object.freeze({
    version: "1.3.45", sequence: 1246,
    source_commit: "bc7adef9fec4f4f4bc8382a5a9d212b71b9a9085",
    approved_bundle_sha256: "e37de3250d58d313d57ad7bcbf59682cee342f2727c6ad5b188c8782342d4c78",
    approved_bundle_size: 223682560,
    approval_reference: "CF-1.3.45-1246-20261118-bc7adef-f36bcd0b",
  }),
  "clientflow-1.3.46-seq-1247": Object.freeze({
    version: "1.3.46", sequence: 1247,
    source_commit: "22a8a873899fe736018e8238f4b2ec4bb896f6a2",
    approved_bundle_sha256: "3d6df5ec096a5713866943a67d9f88bba3fc6287458d0ea2f616bd41e42db150",
    approved_bundle_size: 223692800,
    approval_reference: "CF-1.3.46-1247-20261119-22a8a873-d60d63ba",
  }),
  "clientflow-1.3.47-seq-1248": Object.freeze({
    version: "1.3.47", sequence: 1248,
    source_commit: "c0d5a092efe0c4e8638866ad98621481d6f5d0e8",
    approved_bundle_sha256: "9ca8852ba29153f2ec40b58d18007c738a03f9569f14762486fc1953c59eb6ff",
    approved_bundle_size: 223692800,
    approval_reference: "CF-1.3.47-1248-20261121-c0d5a092-f8240014",
  }),
});

/** Source-pinned GitHub approval is NOT Render publication or client permission. */
export function validateStagedPilotCandidate(candidate, activeReleaseId) {
  const pinned = APPROVED_PILOTS[candidate?.release_id];
  if (!candidate || !pinned || candidate.schema_version !== 1 ||
      candidate.phase !== "approved_github_archive_source_staged_only" ||
      Object.entries(pinned).some(([key, value]) => candidate[key] !== value) ||
      candidate.active_release_id !== activeReleaseId ||
      candidate.pilot_client_id !== 3 ||
      candidate.github_artifact_approval_pinned !== true ||
      (candidate.active_catalog_promoted !== false && candidate.active_catalog_promoted !== true) ||
      ["render_store_publication_verified", "physical_pilot_accepted",
       "deployment_authorized", "fleet_authorized", "fresh_install_authorized",
       "database_cutover_authorized"].some((field) => candidate[field] !== false)) {
    throw new Error("1246/1247/1248-arkivstatus er ugyldig eller angiver uautoriseret installation");
  }
  return candidate;
}

export function validateReleasePlanningResponse(data) {
  if (!data || data.phase !== "additive_draft_only" ||
      data.authorization_active !== false || data.planning_review_available !== true ||
      data.fresh_install_open !== false || data.fleet_open !== false ||
      data.cutover_enabled !== false || data.physical_pilot_accepted !== false ||
      data.client_inventory_complete !== true ||
      !Array.isArray(data.available_clients) || !Array.isArray(data.available_releases) ||
      !Array.isArray(data.waves) || data.waves.some((wave) =>
        wave.deployment_authorized !== false ||
        !["draft", "paused", "cancelled"].includes(wave.state)) ||
      !Number.isSafeInteger(data.revision) || data.revision < 1 ||
      !data.stable_release_id || !VERSION.test(data.stable_version || "") ||
      !/^[a-f0-9]{64}$/.test(data.bundle_sha256 || "") ||
      data.available_releases.length !== 1 ||
      data.available_releases[0]?.release_id !== data.stable_release_id ||
      data.available_releases[0]?.version !== data.stable_version ||
      data.available_releases[0]?.bundle_sha256 !== data.bundle_sha256 ||
      data.available_releases[0]?.status !== "stable" ||
      data.available_releases[0]?.deployment_authorized !== false) {
    throw new Error("Ukendt eller usikker releaseadministrationskontrakt – planlægning er spærret");
  }
  validateReleaseReadiness(data.release_readiness, data.stable_release_id, data.revision);
  validateDeploymentHistory(data.recent_deployments, { allowMissing: true });
  if (data.active_deployments !== undefined || data.active_deployments_complete !== undefined) {
    validateActiveDeployments(data.active_deployments, data.active_deployments_complete);
  }
  if (data.staged_pilot_candidate !== undefined) {
    validateStagedPilotCandidate(data.staged_pilot_candidate, data.stable_release_id);
  }
  const ids = new Set();
  for (const client of data.available_clients) {
    if (!Number.isSafeInteger(client.id) || client.id < 1 || ids.has(client.id) ||
        typeof client.name !== "string" || !client.name.trim() ||
        (client.reported_version !== null && client.reported_version !== undefined &&
         !VERSION.test(client.reported_version))) {
      throw new Error("Klientoversigten er ufuldstændig eller ugyldig – planlægning er spærret");
    }
    ids.add(client.id);
  }
  return data;
}

export function isOlderRelease(sourceVersion, stableVersion) {
  if (!VERSION.test(sourceVersion || "") || !VERSION.test(stableVersion || "")) return false;
  const oldParts = sourceVersion.split(".").map(Number);
  const newParts = stableVersion.split(".").map(Number);
  for (let i = 0; i < 3; i += 1) {
    if (oldParts[i] !== newParts[i]) return oldParts[i] < newParts[i];
  }
  return false;
}

export function planVersionGroups(clients, stableVersion) {
  const counts = new Map();
  for (const client of clients) {
    const version = client.reported_version;
    if (typeof version !== "string" || !isOlderRelease(version, stableVersion)) continue;
    counts.set(version, (counts.get(version) || 0) + 1);
  }
  return [...counts].sort(([a], [b]) => a.localeCompare(b, "da", { numeric: true }))
    .map(([version, count]) => ({ version, count }));
}

export function preparePlan(clients, selectedIds, sourceVersion, stableVersion, expiryHours) {
  if (!isOlderRelease(sourceVersion, stableVersion) ||
      selectedIds.length < 1 || selectedIds.length > MAX_PLAN_CLIENTS ||
      new Set(selectedIds).size !== selectedIds.length ||
      ![1, 24, 72, 168].includes(Number(expiryHours))) {
    throw new Error("Vælg 1–25 klienter med samme verificerbare kildeversion");
  }
  const lookup = new Map(clients.map((item) => [item.id, item]));
  if (selectedIds.some((id) => !Number.isSafeInteger(id) || lookup.get(id)?.reported_version !== sourceVersion)) {
    throw new Error("Klienter eller kildeversion er ændret. Hent oversigten igen.");
  }
  const kind = selectedIds.length === 1 ? "pilot" : "controlled";
  return {
    kind,
    client_ids: [...selectedIds].sort((a, b) => a - b),
    source_version: sourceVersion,
    expires_in_hours: Number(expiryHours),
    // Retain the backend audit reason, without requiring redundant free text.
    reason: `Inaktiv ${kind === "pilot" ? "pilotplan" : "bølgeplan"} for ${selectedIds.length} klient(er) fra ${sourceVersion} til ${stableVersion}. Ingen installation autoriseret.`,
  };
}


/** Fail closed on malformed or unauthorized server-side planning previews. */
export function validatePlanningPreview(body, selectedIds, sourceVersion, targetReleaseId, revision) {
  const ids = [...selectedIds].sort((a, b) => a - b);
  if (!body || body.planning_eligible !== true || body.deployment_authorized !== false
    || body.release_approved_for_deployment !== false
    || body.target_release_id !== targetReleaseId || body.source_version !== sourceVersion
    || body.policy_revision !== revision || !Array.isArray(body.client_ids)
    || body.client_ids.length !== ids.length
    || body.client_ids.some((id, i) => id !== ids[i])
    || body.kind !== (ids.length === 1 ? "pilot" : "controlled")) {
    throw new Error("Planens serverkontrol var ufuldstændig eller ændret. Opdater siden.");
  }
  return body;
}


// Compare reported versions to the selected standard, not to an unsigned
// candidate. A newer report is not evidence that the standard is installed.
export function fleetVersionStatus(client, stableVersion) {
  const version = client?.reported_version;
  if (!VERSION.test(version || "") || !VERSION.test(stableVersion || "")) return "unknown";
  if (version === stableVersion) return "standard";
  return isOlderRelease(version, stableVersion) ? "older" : "newer";
}

export function summarizeReleaseFleet(clients, stableVersion) {
  const counts = { total: clients.length, standard: 0, older: 0, newer: 0, unknown: 0 };
  for (const client of clients) counts[fleetVersionStatus(client, stableVersion)] += 1;
  return counts;
}
