// Unknown, idle and transitioning service states are NOT verified OK.
// Keep issue severity separate from absence of a reliable measurement.
export function summarizeServiceLevels(levels = []) {
  const summary = { ok: 0, issues: 0, unverified: 0, total: levels.length };
  for (const level of levels) {
    if (level === "ok") summary.ok += 1;
    else if (level === "warn" || level === "error") summary.issues += 1;
    else summary.unverified += 1;
  }
  return summary;
}
