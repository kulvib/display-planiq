#!/usr/bin/env python3
"""Read-only inventory for an EXISTING ClientFlow rollback Ed25519 signer.

The existing server-side CLIENTFLOW_ROLLBACK_SIGNING_KEY_PEM_B64 is the sole
input. Never generates, stores, transmits or prints a private key. Can inspect
that secret while CLIENTFLOW_SIGNED_ROLLBACK_ENABLED=false: this is NOT
permission to enable the feature.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, load_pem_private_key

REPO = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
SECRET_NAME = "CLIENTFLOW_ROLLBACK_SIGNING_KEY_PEM_B64"
SPKI = bytes.fromhex("302a300506032b6570032100")


def inspect_existing_key(*, environ: dict[str, str] | None = None, repo: Path = REPO) -> dict:
    """Return public-only findings. No secret or exception detail can enter result."""
    env = os.environ if environ is None else environ
    result = {
        "purpose": "clientflow_central_rollback_signer_only",
        "read_only": True,
        "key_generated": False,
        "backend_feature_activation_authorized": False,
        "release_publication_authorized": False,
        "private_key_exported": False,
        "status": "missing",
        "key_id": None,
        "public_key_b64": None,
        "source_trust": "not_checked",
        "feature_flag": "disabled",
        "note": "Fravær i Render betyder ikke, at en nøgle ikke findes i et separat nøglearkiv.",
    }
    flag = env.get("CLIENTFLOW_SIGNED_ROLLBACK_ENABLED", "false")
    if not isinstance(flag, str) or flag.strip().lower() not in {"true", "false"}:
        result.update(status="invalid_config", feature_flag="invalid")
        return result
    result["feature_flag"] = "enabled" if flag.strip().lower() == "true" else "disabled"
    raw = env.get(SECRET_NAME, "")
    if raw == "":
        return result
    if not isinstance(raw, str) or not 1 <= len(raw) <= 8192:
        result["status"] = "invalid_key"
        return result
    try:
        decoded = base64.b64decode(raw, validate=True)
        private = load_pem_private_key(decoded, password=None)
        if not isinstance(private, Ed25519PrivateKey):
            result["status"] = "wrong_key_type"
            return result
        der = private.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
        if len(der) != len(SPKI) + 32 or not der.startswith(SPKI):
            result["status"] = "invalid_key"
            return result
    except Exception:
        # Library error details may contain offending input. Never echo them.
        result["status"] = "invalid_key"
        return result
    # Only this *public* identifier and public bytes can leave the function.
    pub = der[len(SPKI):]
    result.update(
        status="valid_existing_key",
        key_id=hashlib.sha256(der).hexdigest()[:32],
        public_key_b64=base64.urlsafe_b64encode(pub).rstrip(b"=").decode("ascii"),
    )
    try:
        trust = json.loads((repo / "client/release/rollback-trust.json").read_text(encoding="utf-8"))
        if not isinstance(trust, dict) or trust.get("enabled") is not True:
            result["source_trust"] = "disabled"
        elif not isinstance(trust.get("keys"), list):
            result["source_trust"] = "invalid"
        elif any(isinstance(x, dict) and x.get("key_id") == result["key_id"] and x.get("public_key_b64") == result["public_key_b64"] for x in trust["keys"]):
            result["source_trust"] = "matches_existing_signer"
        else:
            result["source_trust"] = "no_matching_public_key"
    except (OSError, ValueError, UnicodeError):
        # A Render rootDir=backend service has no client/release source tree.
        result["source_trust"] = "not_available_in_backend_runtime"
    return result


def public_trust_record(report: dict, policy: dict) -> dict | None:
    """Prepare PUBLIC-only pinning candidate without altering the source."""
    if report["status"] != "valid_existing_key":
        return None
    revision = policy.get("revision") if isinstance(policy, dict) else None
    sequence = policy.get("minimum_safe_release_sequence") if isinstance(policy, dict) else None
    if type(revision) is not int or revision < 1 or type(sequence) is not int or sequence < 1:
        return None
    return {
        "key_id": report["key_id"],
        "public_key_b64": report["public_key_b64"],
        "min_policy_revision": revision,
        "minimum_safe_release_sequence": sequence,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Kontrollér en eksisterende ClientFlow-rollbacknøgle uden at vise den private nøgle")
    parser.add_argument("--repo-root", type=Path, default=REPO)
    parser.add_argument("--public-trust", action="store_true", help="Vis kun den offentlige nøglepost til senere godkendt release-pinning")
    args = parser.parse_args(argv)
    report = inspect_existing_key(repo=args.repo_root)
    label = {
        "missing": "Ingen rollbacknøgle konfigureret i dette miljø. Kontrollér dit sikre nøglearkiv, før du overvejer en ny.",
        "valid_existing_key": "Eksisterende central Ed25519-rollbacknøgle fundet og valideret. GENBRUG DEN.",
        "invalid_key": "Rollbacknøgle er konfigureret, men kan ikke valideres. Stop; opret ikke en ny automatisk.",
        "wrong_key_type": "Konfigureret nøgle er ikke Ed25519. Stop; udskift ikke uden særskilt beslutning.",
        "invalid_config": "Rollback-featureflaget har ugyldig værdi. Stop; foretag ingen ændring.",
    }[report["status"]]
    print(label)
    print("Nøgle-ID (kun offentligt):", report["key_id"] or "ikke tilgængeligt")
    print("Offentlig trust i den aktuelle kilde:", report["source_trust"])
    print("Rollback-feature (kun observation):", report["feature_flag"])
    print("Ingen nøgle er genereret, gemt eller aktiveret. Ingen produktion er ændret.")
    if args.public_trust and report["status"] == "valid_existing_key":
        try:
            policy_path = args.repo_root / "backend/service1/clientflow_release_security_policy.json"
            if not policy_path.is_file() and args.repo_root == REPO:
                policy_path = BACKEND_ROOT / "service1/clientflow_release_security_policy.json"
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            policy = None
        record = public_trust_record(report, policy)
        if record is None:
            print("Central sikkerhedspolitik kan ikke valideres – offentlig nøglepost udeladt.")
            return 3
        print("OFFENTLIG nøglepost (ikke en aktiv release):")
        print(json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if report["status"] == "valid_existing_key" else 2


if __name__ == "__main__":
    raise SystemExit(main())
