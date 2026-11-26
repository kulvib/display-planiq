/** Ordinary updates get bounded audit text; downgrades require a human reason. */
export function buildClientflowUpdateRequest({ targetVersion, sourceVersion, confirmDowngrade = false, reason } = {}) {
  const version = String(targetVersion ?? "").trim();
  const source = String(sourceVersion ?? "").trim();
  const auditReason = String(reason ?? "").trim();
  if (!version || version.toLowerCase() === "latest") {
    throw new Error("ClientFlow-opdatering kræver en konkret målversion");
  }
  if (auditReason.length > 500 || (confirmDowngrade === true && !auditReason)) {
    throw new Error("ClientFlow-opdatering kræver en begrundelse på 1–500 tegn");
  }
  const generated = `ClientFlow-opdatering ${source || "ukendt kildeversion"} → ${version}`;
  if (!auditReason && generated.length > 500) {
    throw new Error("ClientFlow-opdatering kræver en begrundelse på 1–500 tegn");
  }
  return { targetVersion: version, confirmDowngrade: confirmDowngrade === true, reason: auditReason || generated };
}
