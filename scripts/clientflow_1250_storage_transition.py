"""One exact storage-only transition, preserving all four verified predecessors.

No generic cap override, deletion, catalog promotion or deployment authorization.
The canonical publisher retains its immutable source, structure and disk checks.
"""
from __future__ import annotations

from scripts.clientflow_63d16_1248_storage_exception import HISTORICAL

RELEASE_ID = "clientflow-1.4.0-seq-1250"
SIZE = 223897600
SHA256 = "cf4a3077975b9740ef7d1e34a58731a83f2f4b1e43f4ab0f2fad54772e35b446"
SOURCE = "6d7e16c4cf6857c50cdd6d88899ef988e2e739a5"
REFERENCE = "ClientFlow-1.4.0-1250-PR428-build56"
CANDIDATE = "681c43bc8e07822a3a4d340d73f9566b9a9df717f66e36801b99ef1e8bf668ff"
INSTALLER = "66bfe26c1e7c0face7572e9e6c7f3f8eec152d96d800e43dcd96b2bc081b9bee"
PREDECESSORS = {
    **HISTORICAL,
    "clientflow-1.3.47-seq-1248": (
        223692800, "9ca8852ba29153f2ec40b58d18007c738a03f9569f14762486fc1953c59eb6ff",
    ),
}
FINAL = {**PREDECESSORS, RELEASE_ID: (SIZE, SHA256)}


def require_identity(release_id, size_bytes, sha256):
    if (release_id, size_bytes, sha256) != (RELEASE_ID, SIZE, SHA256):
        raise ValueError("1250 storage transition requires the exact approved bundle")


def require_provenance(manifest, size_bytes, sha256):
    require_identity(manifest.get("release_id"), size_bytes, sha256)
    approval = manifest.get("release_approval") or {}
    source = manifest.get("source") or {}
    if (approval.get("reference"), approval.get("candidate_sha256"), source.get("commit")) != (
        REFERENCE, CANDIDATE, SOURCE,
    ):
        raise ValueError("1250 approval provenance mismatch")


def _records(rows, expected):
    if len(rows) != len(expected):
        raise ValueError("1250 storage transition requires exact inventory count")
    records = {row["release_id"]: (row["size_bytes"], row["sha256"]) for row in rows}
    if records != expected:
        raise ValueError("1250 storage transition requires exact verified inventory")


def _snapshot(snapshot, expected):
    if snapshot.get("invalid_artifacts") or snapshot.get("approved_count") != len(expected):
        raise ValueError("1250 storage transition requires verified store")
    _records(snapshot["protected_latest"] + snapshot["older_review_only"], expected)


def require_preflight(snapshot, *, release_id, size_bytes, sha256, disposition, projected):
    require_identity(release_id, size_bytes, sha256)
    if disposition == "ready_to_publish":
        _snapshot(snapshot, PREDECESSORS)
    elif disposition == "already_published":
        _snapshot(snapshot, FINAL)
    else:
        raise ValueError("Unexpected 1250 publication disposition")
    _records(projected, FINAL)


def require_postflight(snapshot, *, release_id, size_bytes, sha256):
    require_identity(release_id, size_bytes, sha256)
    _snapshot(snapshot, FINAL)
