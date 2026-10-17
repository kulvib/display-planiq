/** Construct a deployment request only with an explicit, bounded audit reason. */
export function buildClientflowUpdateRequest({ targetVersion, confirmDowngrade = false, reason } = {}) {
  const version = String(targetVersion ?? "").trim();
  const auditReason = String(reason ?? "").trim();
  if (!version || version.toLowerCase() === "latest") {
    throw new Error("ClientFlow-opdatering kræver en konkret målversion");
  }
  if (!auditReason || auditReason.length > 500) {
    throw new Error("ClientFlow-opdatering kræver en begrundelse på 1–500 tegn");
  }
  return { targetVersion: version, confirmDowngrade: confirmDowngrade === true, reason: auditReason };
}
