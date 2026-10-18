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
