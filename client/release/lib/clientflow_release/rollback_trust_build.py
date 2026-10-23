"""Release-build gate for pinned Ed25519 manual-rollback trust.

New immutable releases MUST carry trustworthy, enabled public keys before
candidate publication. This validates the exact source artifact, not an
environment variable or an operator-provided permit.
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
    """Block seq >=1242 release builds unless exact immutable trust is pinned.

    Releases below the transition retain their historical unsigned rollback
    semantics. The backend signing key and activation flag are deliberately
    never read by the release builder.
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
        or trust["enabled"] is not True
        or not isinstance(trust["keys"], list)
        or not 1 <= len(trust["keys"]) <= 3
    ):
        raise ValueError(
            "Ny ClientFlow-release kræver aktiveret immutable rollback-trust"
        )

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
