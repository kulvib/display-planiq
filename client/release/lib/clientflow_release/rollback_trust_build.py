"""Release-build gate for explicit manual-rollback safety mode.

From sequence 1242 onwards a source release chooses one immutable mode:
- disabled with no keys: manual rollback is blocked by the client verifier;
- signed with pinned Ed25519 keys: permits must verify against those keys.
The release builder never reads a backend signer, environment override or permit.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from clientflow_release_format.rollback_permit import (
    RELEASE_RE,
    SIGNED_ROLLBACK_MIN_SOURCE_SEQUENCE,
    b64_decode,
)

_ED25519_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")


def _read_object(path: Path, *, limit: int) -> dict:
    raw = path.read_bytes()
    if not 1 <= len(raw) <= limit:
        raise ValueError(f"Release trust input har ugyldig størrelse: {path.name}")

    def unique_fields(pairs: list[tuple[str, object]]) -> dict:
        result: dict = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Release trust input har dubleret felt: {key}")
            result[key] = value
        return result

    data = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_fields)
    if not isinstance(data, dict):
        raise ValueError("Release trust input skal være et JSON-objekt")
    return data


def validate_release_rollback_trust(repo: Path, sequence: int) -> None:
    """Require explicit, fail-closed manual-rollback mode from seq 1242.

    A disabled, keyless trust document is an explicit opt-out of *manual*
    rollback, not a request to allow unsigned rollback. The runtime verifier
    independently rejects that mode for sources at or after seq 1242.
    Historical sources below the transition retain their old local behavior.
    """
    if type(sequence) is not int or sequence <= 0:
        raise ValueError("Release-sekvensen er ugyldig")
    if sequence < SIGNED_ROLLBACK_MIN_SOURCE_SEQUENCE:
        return

    try:
        trust = _read_object(repo / "client/release/rollback-trust.json", limit=4096)
        policy = _read_object(repo / "backend/service1/clientflow_release_security_policy.json", limit=16384)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            "Ny ClientFlow-release kræver gyldig, godkendt rollback trust og central policy"
        ) from exc

    if (
        set(trust) != {"schema_version", "enabled", "keys"}
        or type(trust["schema_version"]) is not int
        or trust["schema_version"] != 1
        or type(trust["enabled"]) is not bool
        or not isinstance(trust["keys"], list)
    ):
        raise ValueError("Ny ClientFlow-release kræver eksplicit sikker rollback-mode")

    if (
        set(policy) != {"schema_version", "revision", "minimum_safe_release_sequence", "revoked_release_ids"}
        or type(policy["schema_version"]) is not int
        or policy["schema_version"] != 1
        or type(policy["revision"]) is not int
        or policy["revision"] < 1
        or type(policy["minimum_safe_release_sequence"]) is not int
        or policy["minimum_safe_release_sequence"] < 1
        or not isinstance(policy["revoked_release_ids"], list)
        or len(policy["revoked_release_ids"]) > 200
        or any(
            not isinstance(identifier, str) or RELEASE_RE.fullmatch(identifier) is None
            for identifier in policy["revoked_release_ids"]
        )
        or len(set(policy["revoked_release_ids"])) != len(policy["revoked_release_ids"])
    ):
        raise ValueError(
            "Central releasepolitik er ugyldig under rollback trust release-build"
        )

    # The installed >=1242 verifier raises for this exact disabled/no-keys
    # document, including when the caller presents no permit. Do not silently
    # convert disabled to legacy unsigned root rollback.
    if trust["enabled"] is False:
        if trust["keys"]:
            raise ValueError("Deaktiveret manuel rollback må ikke indeholde nøgler")
        return
    if not 1 <= len(trust["keys"]) <= 3:
        raise ValueError("Signeret manuel rollback kræver 1-3 pinned Ed25519-nøgler")

    seen: set[str] = set()
    for key in trust["keys"]:
        if not isinstance(key, dict) or set(key) != {
            "key_id",
            "public_key_b64",
            "min_policy_revision",
            "minimum_safe_release_sequence",
        }:
            raise ValueError("Rollback trust-nøglen har ugyldigt schema")
        try:
            public_key = b64_decode(key["public_key_b64"], 32)
        except (ValueError, TypeError) as exc:
            raise ValueError("Rollback trust-nøglen har ugyldigt Ed25519-format") from exc
        identifier = hashlib.sha256(_ED25519_SPKI_PREFIX + public_key).hexdigest()[:32]
        if public_key == bytes(32) or key["key_id"] != identifier or identifier in seen:
            raise ValueError("Rollback trust-nøglens ID eller indhold er ugyldigt")
        seen.add(identifier)
        for name, minimum in (
            ("min_policy_revision", policy["revision"]),
            ("minimum_safe_release_sequence", policy["minimum_safe_release_sequence"]),
        ):
            value = key[name]
            if type(value) is not int or value < minimum:
                raise ValueError(
                "Rollback trust har sikkerhedsgulv under den godkendte backend-politik"
            )
