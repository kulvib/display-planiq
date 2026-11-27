/** Validate a successful catalog response; never turn malformed data into update choices. */
export function normalizeClientflowReleaseCatalog(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw) ||
      typeof raw.latest_stable !== "string" || !raw.latest_stable.trim() ||
      !Array.isArray(raw.releases)) {
    throw new Error("ClientFlow-versionskataloget har et ugyldigt format");
  }
  return raw;
}

/** This is a UI selector, NOT deployment authorization. Backend pilot gate is authoritative. */
export function selectableClientflowUpdateReleases(catalog) {
  if (!catalog || !Array.isArray(catalog.releases)) return [];
  return catalog.releases.filter((release) =>
    release &&
    ["stable", "supported"].includes(release.status) &&
    release.update_allowed === true &&
    Array.isArray(release.install_modes) &&
    release.install_modes.includes("in_place_update") &&
    typeof release.version === "string" &&
    /^\d+\.\d+\.\d+$/.test(release.version)
  );
}

function parseVersion(value) {
  const normalized = String(value ?? "").trim().replace(/^v/i, "");
  return /^\d+\.\d+\.\d+$/.test(normalized) ? normalized.split(".").map(Number) : null;
}

function compareVersions(left, right) {
  for (let index = 0; index < 3; index += 1) {
    if (left[index] !== right[index]) return left[index] < right[index] ? -1 : 1;
  }
  return 0;
}

/** A catalog entry can be globally selectable but incompatible with this installed version.
 * This is presentation only: the backend still checks authoritative version, platform,
 * pilot authorization, artifact provenance, permissions and recovery gates. */
export function compatibleClientflowUpdateReleases(catalog, installedVersion) {
  const current = parseVersion(installedVersion);
  if (!current) return [];
  return selectableClientflowUpdateReleases(catalog).filter((release) => {
    const target = parseVersion(release.version);
    if (!target) return false;
    const direction = compareVersions(target, current);
    if (direction === 0 || (direction < 0 && release.rollback_allowed !== true)) return false;
    for (const [field, direction] of [["min_current_version", -1], ["max_current_version", 1]]) {
      const bound = release[field];
      if (bound == null || bound === "") continue;
      const parsed = parseVersion(bound);
      if (!parsed || compareVersions(current, parsed) === direction) return false;
    }
    return true;
  });
}
