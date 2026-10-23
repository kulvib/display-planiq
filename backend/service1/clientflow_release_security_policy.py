"""Git-reviewed backend release deny policy for canonical ClientFlow operations.

This is a central admission gate, NOT a locally verifiable rollback permit.
Changing the policy requires a normal reviewed deployment; the running clients
and their offline root transactions do not consume this backend-only file.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

POLICY_PATH = Path(__file__).with_name("clientflow_release_security_policy.json")
_RELEASE_ID_RE = re.compile(r"^clientflow-(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)-seq-([1-9]\d*)$")


class ClientFlowReleaseSecurityDenied(RuntimeError):
    """Fail closed when a centrally controlled release is unsafe or unknown."""


def _identity(release_id: str, release_sequence: int) -> str:
    if not isinstance(release_id, str) or len(release_id) > 160 or type(release_sequence) is not int:
        raise ClientFlowReleaseSecurityDenied("Releaseidentitet mangler eller er ugyldig")
    match = _RELEASE_ID_RE.fullmatch(release_id)
    if match is None or int(match.group(1)) != release_sequence:
        raise ClientFlowReleaseSecurityDenied("Release-ID og release-sekvens matcher ikke")
    return release_id


def read_release_security_policy() -> dict[str, Any]:
    """Strict, bounded source-controlled policy; malformed configuration denies all."""
    try:
        if POLICY_PATH.stat().st_size > 16_384:
            raise ValueError("policy file too large")
        document = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or set(document) != {
            "schema_version", "revision", "minimum_safe_release_sequence", "revoked_release_ids"
        }:
            raise ValueError("unexpected policy schema")
        if type(document["schema_version"]) is not int or document["schema_version"] != 1 or type(document["revision"]) is not int or document["revision"] < 1:
            raise ValueError("invalid revision")
        floor = document["minimum_safe_release_sequence"]
        if type(floor) is not int or floor < 1:
            raise ValueError("invalid minimum sequence")
        revoked = document["revoked_release_ids"]
        if not isinstance(revoked, list) or len(revoked) > 200 or len(set(map(str, revoked))) != len(revoked):
            raise ValueError("invalid revocation list")
        for identifier in revoked:
            if not isinstance(identifier, str) or len(identifier) > 160:
                raise ValueError("invalid revoked release id")
            match = _RELEASE_ID_RE.fullmatch(identifier)
            if match is None:
                raise ValueError("invalid revoked release id")
        return document
    except (OSError, ValueError, TypeError, UnicodeError) as exc:
        raise ClientFlowReleaseSecurityDenied("Central release-sikkerhedspolitik er ugyldig eller utilgængelig") from exc


def require_centrally_eligible_release(*, release_id: str, release_sequence: int) -> None:
    """Enforce the same deny decision at order, download and activation boundaries."""
    identifier = _identity(release_id, release_sequence)
    policy = read_release_security_policy()
    if release_sequence < policy["minimum_safe_release_sequence"]:
        raise ClientFlowReleaseSecurityDenied("Releasen er under den centrale minimumssikkerhedssekvens")
    if identifier in policy["revoked_release_ids"]:
        raise ClientFlowReleaseSecurityDenied("Releasen er centralt sikkerhedstilbagekaldt")
