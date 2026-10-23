"""Dedicated server-side Ed25519 rollback signing identity; never use update client keys."""
from __future__ import annotations
import base64
import hashlib
import os
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key, Encoding, PublicFormat
from clientflow_release_format.rollback_permit import b64_encode, canonical_bytes, validate_payload

class RollbackSigningUnavailable(RuntimeError):
    pass


def enabled() -> bool:
    flag = os.environ.get("CLIENTFLOW_SIGNED_ROLLBACK_ENABLED", "false").strip().lower()
    if flag not in {"true", "false"}:
        raise RollbackSigningUnavailable("Rollback-featureflag er ugyldigt")
    return flag == "true"


def _signing_key():
    if not enabled():
        raise RollbackSigningUnavailable("Signeret rollback er ikke aktiveret")
    raw = os.environ.get("CLIENTFLOW_ROLLBACK_SIGNING_KEY_PEM_B64", "")
    if not 1 <= len(raw) <= 8192:
        raise RollbackSigningUnavailable("Rollback-signeringsnøglen er ikke konfigureret")
    try:
        key = load_pem_private_key(base64.b64decode(raw, validate=True), password=None)
    except (ValueError, TypeError, base64.binascii.Error) as exc:
        raise RollbackSigningUnavailable("Rollback-signeringsnøglen er ugyldig") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise RollbackSigningUnavailable("Rollback-signeringsnøglen skal være Ed25519")
    der = key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    return key, hashlib.sha256(der).hexdigest()[:32]


def sign_permit(payload: dict) -> tuple[str, str]:
    key, key_id = _signing_key()
    payload = dict(payload, issuer_key_id=key_id)
    validate_payload(payload)
    signature = key.sign(canonical_bytes(payload))
    return canonical_bytes({"payload": payload, "signature_b64": b64_encode(signature)}).decode("ascii"), key_id
