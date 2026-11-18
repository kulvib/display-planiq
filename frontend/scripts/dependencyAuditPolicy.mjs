/**
 * Fail-closed interpretation of npm audit's direct advisories and inherited metadvisories.
 * Only the exact, short-lived picomatch dev-tool exception in the lockfile can be accepted.
 * An inherited meta-advisory is accepted only if every upstream cause is accepted and every
 * dependency edge and all involved dev-only package records are present in the audited lock.
 */
const GHSA_RE = /GHSA-[23456789cfghjmpqrvwx]{4}-[23456789cfghjmpqrvwx]{4}-[23456789cfghjmpqrvwx]{4}/i;

function idFor(advisory) {
  for (const candidate of [advisory?.github_advisory_id, advisory?.url, advisory?.id]) {
    const matched = String(candidate ?? "").match(GHSA_RE);
    if (matched) return matched[0].toUpperCase();
  }
  return null;
}

function packageRecords(lock, name) {
  const entries = Object.entries(lock?.packages ?? {});
  return entries.filter(([key]) => key === `node_modules/${name}` || key.endsWith(`/node_modules/${name}`));
}

function devOnly(lock, name) {
  const entries = packageRecords(lock, name);
  return entries.length > 0 && entries.every(([, info]) => info?.dev === true && info?.devOptional !== true);
}

function dependsOn(lock, parent, child) {
  const entries = packageRecords(lock, parent);
  return entries.length > 0 && entries.every(([, info]) => [
    info.dependencies, info.optionalDependencies, info.peerDependencies,
  ].some((deps) => Object.prototype.hasOwnProperty.call(deps ?? {}, child)));
}

function validateExceptions(exceptions, today) {
  if (!Array.isArray(exceptions)) throw new Error("Audit-undtagelser skal være en liste");
  const seen = new Set();
  for (const entry of exceptions) {
    if (typeof entry !== "object" || !entry || typeof entry.package !== "string"
      || seen.has(entry.package) || entry.scope !== "dev-only"
      || typeof entry.lockedVersion !== "string"
      || !/^\d+\.\d+\.\d+$/.test(entry.lockedVersion)
      || !Array.isArray(entry.advisories) || entry.advisories.length === 0
      || !entry.advisories.every((id) => typeof id === "string" && GHSA_RE.test(id))
      || new Set(entry.advisories).size !== entry.advisories.length
      || typeof entry.expires !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(entry.expires)
      || !Number.isFinite(Date.parse(`${entry.expires}T00:00:00Z`))
      || typeof entry.replacementPlan !== "string" || !entry.replacementPlan.trim()) {
      throw new Error(`Ugyldig, dubleret eller for bred audit-undtagelse: ${entry?.package ?? "ukendt"}`);
    }
    seen.add(entry.package);
    if (entry.expires < today) throw new Error(`Audit-undtagelse udløbet: ${entry.package}`);
  }
}

/** Pure audit policy for local regression tests; no npm invocation, environment or file access. */
export function evaluateDependencyAudit(report, allowlist, lock, today) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(today)) throw new Error("Ugyldig audit-dato");
  const exceptions = allowlist?.exceptions ?? [];
  validateExceptions(exceptions, today);
  const acceptedExceptions = new Map(exceptions.map((entry) => [entry.package, entry]));
  const records = new Map();
  const get = (name, severity) => {
    if (!records.has(name)) records.set(name, { name, severity: severity || "unknown", ids: new Set(), inherited: new Set(), unknownDirect: false });
    return records.get(name);
  };

  // Keep support for the older npm report format. Unidentified advisories must fail closed.
  for (const advisory of Object.values(report?.advisories ?? {})) {
    if (typeof advisory?.module_name !== "string" || !advisory.module_name) continue;
    const record = get(advisory.module_name, advisory.severity);
    const id = idFor(advisory);
    if (id) record.ids.add(id); else record.unknownDirect = true;
  }
  for (const [name, vulnerability] of Object.entries(report?.vulnerabilities ?? {})) {
    const record = get(name, vulnerability?.severity);
    if (!Array.isArray(vulnerability?.via)) {
      record.unknownDirect = true;
      continue;
    }
    for (const via of vulnerability.via) {
      if (typeof via === "string" && via) {
        record.inherited.add(via);
      } else if (via && typeof via === "object") {
        const id = idFor(via);
        if (id) record.ids.add(id); else record.unknownDirect = true;
      } else {
        record.unknownDirect = true;
      }
    }
    if (vulnerability.via.length === 0) record.unknownDirect = true;
  }

  const accepted = new Set();
  const exceptionsUsed = new Set();
  // Direct findings require one exact audited dev-only, version-pinned exception.
  for (const record of records.values()) {
    const exception = acceptedExceptions.get(record.name);
    if (!exception || record.unknownDirect || record.inherited.size || !record.ids.size) continue;
    const ids = [...record.ids].sort();
    const allowed = [...exception.advisories].map((id) => id.toUpperCase()).sort();
    const versions = packageRecords(lock, record.name);
    if (JSON.stringify(ids) === JSON.stringify(allowed)
      && devOnly(lock, record.name)
      && versions.every(([, info]) => info.version === exception.lockedVersion)) {
      accepted.add(record.name);
      exceptionsUsed.add(record.name);
    }
  }
  // A package that merely inherits the above finding is NOT an independent exemption.
  // Its dev-only dependency path must be verified all the way back to the root finding.
  let changed;
  do {
    changed = false;
    for (const record of records.values()) {
      if (accepted.has(record.name) || record.unknownDirect || record.ids.size
        || record.inherited.size === 0 || !devOnly(lock, record.name)) continue;
      if ([...record.inherited].every((source) => accepted.has(source) && dependsOn(lock, record.name, source))) {
        accepted.add(record.name);
        changed = true;
      }
    }
  } while (changed);

  const unexpected = [...records.values()]
    .filter((record) => !accepted.has(record.name))
    .map((record) => ({
      packageName: record.name,
      severity: record.severity,
      advisoryIds: [...record.ids],
      inheritedFrom: [...record.inherited],
      unidentified: record.unknownDirect,
    }));

  // Stale exceptions must not silently remain after upstream has removed the issue.
  for (const name of acceptedExceptions.keys()) {
    if (!exceptionsUsed.has(name) && !records.has(name)) unexpected.push({
      packageName: name, severity: "policy", advisoryIds: [], inheritedFrom: [],
      unidentified: false, reason: "Undtagelse er overflødig eller lock-versionen er ændret",
    });
  }
  const totals = report?.metadata?.vulnerabilities;
  if (typeof totals?.total === "number" && totals.total > 0 && records.size === 0) {
    unexpected.push({ packageName: "npm audit", severity: "unknown", advisoryIds: [],
      inheritedFrom: [], unidentified: true, reason: "Audit-metadata rapporterer sårbarheder uden detaljer" });
  }
  return {
    accepted: [...accepted].sort(),
    exceptionsUsed: [...exceptionsUsed],
    unexpected,
    total: totals?.total ?? records.size,
  };
}
