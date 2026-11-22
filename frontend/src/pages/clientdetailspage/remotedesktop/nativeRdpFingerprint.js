/** Normalize an operator-verified GNOME TLS SHA256 fingerprint. */
export function normalizeNativeRdpFingerprint(input) {
  if (typeof input !== "string") return null;
  const stripped = input.trim().replace(/^sha256\s*[:=]\s*/i, "");
  if (!/^[a-fA-F0-9: \t-]+$/.test(stripped)) return null;
  const plain = stripped.replace(/[: \t-]/g, "");
  if (!/^[a-fA-F0-9]{64}$/.test(plain)) return null;
  return plain.toLowerCase().match(/.{2}/g).join(":");
}
