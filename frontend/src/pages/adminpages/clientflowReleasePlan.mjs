/** Pure planning helpers: no method creates a deployment or authorizes a release. */
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
