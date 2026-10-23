"""Root-owned offline verification of a backend Ed25519 manual-rollback permit.

The key comes exclusively from the immutable, previously activated source
release, never from a command line, permit, network fetch or editable JSON.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time

from clientflow_release_format.rollback_permit import (
    RollbackPermitError, b64_decode, canonical_bytes, reason_hash,
    verify_envelope_structure,
)
from .filesystem import load_secure_json

_SPKI_ED25519 = bytes.fromhex("302a300506032b6570032100")


def _regular_file(path: Path, *, max_bytes: int, forbidden: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        meta = os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode) or meta.st_mode & forbidden or not 1 <= meta.st_size <= max_bytes:
            raise RollbackPermitError("Rollback-filens type, rettigheder eller størrelse er usikker")
        if os.geteuid() == 0 and meta.st_uid != 0:
            raise RollbackPermitError("Rollback-filen er ikke ejet af root")
        raw = os.read(fd, max_bytes + 1)
    finally:
        os.close(fd)
    if not 1 <= len(raw) <= max_bytes:
        raise RollbackPermitError("Rollback-filen er ugyldig eller for stor")
    return raw


def _trust(layout, source: str) -> dict:
    path = layout.releases / source / "release/rollback-trust.json"
    if not path.exists():
        # Existing approved releases have no opt-in trust root; rollout changes
        # neither their on-disk bytes nor their historical rollback contract.
        return {"schema_version": 1, "enabled": False, "keys": []}
    raw = _regular_file(path, max_bytes=4096, forbidden=0o022)
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise RollbackPermitError("Release mangler et gyldigt rollback-trust root") from exc
    if not isinstance(data, dict) or set(data) != {"schema_version", "enabled", "keys"} or type(data["schema_version"]) is not int or data["schema_version"] != 1 or type(data["enabled"]) is not bool or not isinstance(data["keys"], list):
        raise RollbackPermitError("Rollback-trust har ugyldigt schema")
    if not data["enabled"]:
        if data["keys"]:
            raise RollbackPermitError("Deaktiveret trust må ikke indeholde aktive nøgler")
        return data
    if not 1 <= len(data["keys"]) <= 3:
        raise RollbackPermitError("Rollback-trust kræver en pinning-nøgle")
    seen = set()
    for key in data["keys"]:
        if not isinstance(key, dict) or set(key) != {"key_id", "public_key_b64", "min_policy_revision", "minimum_safe_release_sequence"}:
            raise RollbackPermitError("Rollback trust-nøgle er ugyldig")
        raw_key = b64_decode(key["public_key_b64"], 32)
        key_id = hashlib.sha256(_SPKI_ED25519 + raw_key).hexdigest()[:32]
        if key["key_id"] != key_id or key_id in seen:
            raise RollbackPermitError("Rollback trust-nøglens ID er ugyldigt")
        seen.add(key_id)
        for field in ("min_policy_revision", "minimum_safe_release_sequence"):
            if type(key[field]) is not int or key[field] < 1:
                raise RollbackPermitError("Rollback trust-sikkerhedsgulv er ugyldigt")
    return data


def _time_verified(layout) -> int:
    if layout.root == Path("/"):
        result = subprocess.run(
            ["/usr/bin/timedatectl", "show", "--property=NTPSynchronized", "--value"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15, check=False,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        )
        if result.returncode != 0 or result.stdout.strip().lower() not in {b"yes", b"true", b"1"}:
            raise RollbackPermitError("Manuel offline rollback kræver verificeret NTP-tid")
    return int(time.time())


def _verify_signature(payload: dict, signature: bytes, raw_key: bytes) -> None:
    # Client's immutable Python runtime is not required to bundle cryptography.
    # Ed25519 signature checking is performed by the target Ubuntu host OpenSSL.
    with tempfile.TemporaryDirectory(prefix="clientflow-rollback-verify-") as directory:
        base = Path(directory)
        key_path, message_path, signature_path = base / "key.der", base / "message", base / "signature"
        key_path.write_bytes(_SPKI_ED25519 + raw_key)
        message_path.write_bytes(canonical_bytes(payload))
        signature_path.write_bytes(signature)
        try:
            verified = subprocess.run(
                ["/usr/bin/openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(key_path),
                 "-keyform", "DER", "-rawin", "-in", str(message_path), "-sigfile", str(signature_path)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=15, check=False,
                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RollbackPermitError("Ed25519-signaturkontrol er utilgængelig") from exc
        if verified.returncode != 0:
            raise RollbackPermitError("Rollback-tilladelsens Ed25519-signatur er ugyldig")


def verify_for_transaction(layout, state: dict, *, active: str, target: str,
                           approval: str, reason: str, permit_file: Path | None) -> str | None:
    trust = _trust(layout, active)
    if not trust["enabled"]:
        if permit_file is not None:
            raise RollbackPermitError("Denne release understøtter ikke signerede rollback-permits")
        return None
    if permit_file is None:
        raise RollbackPermitError("Rollback kræver særskilt centralt signeret tilladelse")
    if not permit_file.is_absolute():
        raise RollbackPermitError("Tilladelsen skal læses fra en absolut, root-beskyttet fil")
    raw = _regular_file(permit_file, max_bytes=8192, forbidden=0o077)
    payload, signature = verify_envelope_structure(raw)
    key = next((k for k in trust["keys"] if k["key_id"] == payload["issuer_key_id"]), None)
    if key is None:
        raise RollbackPermitError("Tilladelsen er ikke signeret af en trusted rollback-nøgle")
    _verify_signature(payload, signature, b64_decode(key["public_key_b64"], 32))
    installed = state["installed"]
    record = installed[target]
    if not (payload["from_release_id"] == active
            and payload["to_release_id"] == target
            and payload["from_sequence"] == installed[active]["release_sequence"]
            and payload["to_sequence"] == record["release_sequence"]
            and payload["release_approval_reference"] == approval
            and payload["bundle_sha256"] == record["bundle_sha256"]
            and payload["reason_sha256"] == reason_hash(reason)):
        raise RollbackPermitError("Rollback-tilladelsen matcher ikke den installerede transaktion")
    if (payload["policy_revision"] < key["min_policy_revision"]
            or payload["minimum_safe_release_sequence"] < key["minimum_safe_release_sequence"]
            or payload["to_sequence"] < key["minimum_safe_release_sequence"]):
        raise RollbackPermitError("Rollback overtræder den lokalt pin'de sikkerhedspolitik")
    identity = load_secure_json(layout.path("/etc/clientflow/update/credential.json"), max_bytes=4096)
    if (type(identity.get("client_id")) is not int
            or payload["client_id"] != identity["client_id"]
            or payload["update_credential_id"] != identity.get("credential_id")):
        raise RollbackPermitError("Rollback-tilladelsen matcher ikke klientens update-identitet")
    # An already committed intent may resume even after token expiry, but must
    # have the original durable binding; this is never a new authorization.
    intent = state.get("activation_intent")
    if intent is None:
        now = _time_verified(layout)
        if now < payload["not_before"] or now > payload["expires_at"]:
            raise RollbackPermitError("Rollback-tilladelsen er ikke gyldig på det verificerede tidspunkt")
    elif (intent.get("manual_rollback_permit_id") != payload["permit_id"]
          or intent.get("release_id") != target
          or intent.get("previous_release_id") != active):
        raise RollbackPermitError("Rollback-resume matcher ikke den oprindelige permit-binding")
    return payload["permit_id"]
