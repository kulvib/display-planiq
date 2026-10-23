"""Canonical ClientFlow manual-rollback authorization payload; no runtime dependencies.

An Ed25519 signature authenticates precisely the UTF-8 canonical JSON payload.
Unlike the existing release approval, a permit binds one physical client and one
specific local predecessor transition for a short period.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid

PURPOSE = "planiq.clientflow.manual-rollback.v1"
# Source releases beginning at this sequence must fail closed without pinned trust.
SIGNED_ROLLBACK_MIN_SOURCE_SEQUENCE = 1242
KEY_FIELDS = frozenset({
    "schema_version", "purpose", "algorithm", "issuer_key_id", "permit_id",
    "client_id", "update_credential_id", "from_release_id", "from_sequence",
    "to_release_id", "to_sequence", "release_approval_reference", "bundle_sha256",
    "reason_sha256", "policy_revision", "minimum_safe_release_sequence",
    "issued_at", "not_before", "expires_at",
})
RELEASE_RE = re.compile(r"^clientflow-(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)-seq-([1-9][0-9]*)$")
HEX_RE = re.compile(r"^[a-f0-9]{64}$")
KEY_RE = re.compile(r"^[a-f0-9]{32}$")


class RollbackPermitError(ValueError):
    pass


def canonical_bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")


def strict_load(raw: bytes) -> dict:
    if len(raw) > 8192:
        raise RollbackPermitError("Rollback-tilladelsen er for stor")
    def no_duplicates(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise RollbackPermitError("Rollback-tilladelsen har dublerede felter")
            out[k] = v
        return out
    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=no_duplicates,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite")))
    except (UnicodeError, ValueError, TypeError) as exc:
        raise RollbackPermitError("Rollback-tilladelsen har ugyldig JSON") from exc
    if not isinstance(result, dict) or canonical_bytes(result) != raw:
        raise RollbackPermitError("Rollback-tilladelsen er ikke kanonisk kodet")
    return result


def b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64_decode(value: str, size: int) -> bytes:
    if not isinstance(value, str) or len(value) > 160 or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise RollbackPermitError("Ugyldig Ed25519-kodning")
    try:
        raw = base64.urlsafe_b64decode(value + "=" * ((-len(value)) % 4))
    except (ValueError, base64.binascii.Error) as exc:
        raise RollbackPermitError("Ugyldig Ed25519-kodning") from exc
    if len(raw) != size or b64_encode(raw) != value:
        raise RollbackPermitError("Ed25519-data matcher ikke canonical base64url")
    return raw


def reason_hash(reason: str) -> str:
    if not isinstance(reason, str) or reason != reason.strip() or not 3 <= len(reason) <= 500 or any(ord(c) < 32 and c != "\t" for c in reason):
        raise RollbackPermitError("Rollback-begrundelsen er ugyldig")
    return hashlib.sha256(reason.encode("utf-8")).hexdigest()


def validate_payload(p: dict) -> None:
    if not isinstance(p, dict) or set(p) != KEY_FIELDS:
        raise RollbackPermitError("Rollback-tilladelsens felter matcher ikke kontrakten")
    if p["schema_version"] != 1 or type(p["schema_version"]) is not int or p["purpose"] != PURPOSE or p["algorithm"] != "Ed25519":
        raise RollbackPermitError("Rollback-tilladelsens format er ugyldigt")
    if not isinstance(p["issuer_key_id"], str) or not KEY_RE.fullmatch(p["issuer_key_id"]):
        raise RollbackPermitError("Rollback-signaturens key-id er ugyldigt")
    for f in ("permit_id", "update_credential_id"):
        if not isinstance(p[f], str) or str(uuid.UUID(p[f])) != p[f]:
            raise RollbackPermitError("Rollback-tilladelsens ID er ugyldigt")
    for f in ("client_id", "from_sequence", "to_sequence", "policy_revision", "minimum_safe_release_sequence",
              "issued_at", "not_before", "expires_at"):
        if type(p[f]) is not int or p[f] <= 0:
            raise RollbackPermitError("Rollback-tilladelsens numeriske felter er ugyldige")
    for id_field, seq_field in (("from_release_id", "from_sequence"), ("to_release_id", "to_sequence")):
        name = p[id_field]
        match = RELEASE_RE.fullmatch(name) if isinstance(name, str) else None
        if not match or int(match.group(1)) != p[seq_field]:
            raise RollbackPermitError("Rollback-tilladelsens releaseidentitet er ugyldig")
    if p["to_sequence"] >= p["from_sequence"] or p["to_sequence"] < p["minimum_safe_release_sequence"]:
        raise RollbackPermitError("Rollback-tilladelsen overtræder den signerede sikkerhedsgrænse")
    for f in ("bundle_sha256", "reason_sha256"):
        if not isinstance(p[f], str) or not HEX_RE.fullmatch(p[f]):
            raise RollbackPermitError("Rollback-tilladelsens hash er ugyldig")
    approval = p["release_approval_reference"]
    if not isinstance(approval, str) or not 1 <= len(approval) <= 200 or any(ord(c) < 32 for c in approval):
        raise RollbackPermitError("Rollback-tilladelsens releaseprovenance er ugyldig")
    if not (p["issued_at"] == p["not_before"] < p["expires_at"] <= p["issued_at"] + 300):
        raise RollbackPermitError("Rollback-tilladelsens tid er ugyldig")


def verify_envelope_structure(raw: bytes) -> tuple[dict, bytes]:
    outer = strict_load(raw)
    if set(outer) != {"payload", "signature_b64"}:
        raise RollbackPermitError("Rollback-tilladelsens envelope er ugyldig")
    payload = outer["payload"]
    validate_payload(payload)
    return payload, b64_decode(outer["signature_b64"], 64)
