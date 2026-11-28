"""68N-D1: exact approved 1252 artifact and bounded storage evidence.

No deployment, catalog promotion, fresh install or rollback authority.
The approved candidate source is immutable; this is post-build backend code.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from .clientflow_1252_transition import (
    CANDIDATE_ID, CANDIDATE_VERSION, CANDIDATE_SEQUENCE, OLDEST_ID,
    PREDECESSOR_ID, Candidate1252Denied, require,
)
from .clientflow_pilot_1251 import (
    BASELINE_ID, RETAINED_IDS, _pinned_json, archive_inventory, successor_release,
)

APPROVAL_PATH = Path(__file__).with_name("clientflow_pilot_1252_approval.json")
APPROVAL_SHA256 = "01e63fd2169795fd25379b918d5b23bdef5aeadb100b2f52fc45f7ef728df8fa"
FINAL_IDS = frozenset({BASELINE_ID, PREDECESSOR_ID, CANDIDATE_ID})
INTERMEDIATE_IDS = frozenset({BASELINE_ID, PREDECESSOR_ID})


def approval_lock_1252() -> dict:
    row = _pinned_json(APPROVAL_PATH, APPROVAL_SHA256)
    require(row.get("approved") is True and row.get("release_id") == CANDIDATE_ID,
            "1252_APPROVAL_IDENTITY_MISMATCH")
    return row


def candidate_release() -> dict:
    return {**successor_release(), "release_id": CANDIDATE_ID, "revision": CANDIDATE_ID,
            "version": CANDIDATE_VERSION, "release_sequence": CANDIDATE_SEQUENCE,
            "min_current_version": "1.4.1", "max_current_version": "1.4.1"}


def candidate_snapshot() -> dict:
    row = approval_lock_1252()
    return dict(target_release_id=CANDIDATE_ID, target_version=CANDIDATE_VERSION,
                target_release_sequence=CANDIDATE_SEQUENCE,
                bundle_sha256=row["approved_bundle_sha256"],
                bundle_size=row["approved_bundle_size"],
                release_approval_reference=row["approval_reference"],
                release_candidate_sha256=row["candidate_sha256"],
                source_commit=row["source_commit"])


def match_candidate_artifact(artifact: Mapping) -> None:
    require(all(type(artifact.get(key)) is type(value) and artifact.get(key) == value
                for key, value in candidate_snapshot().items()), "1252_ARTIFACT_PIN_MISMATCH")


def match_candidate_manifest(manifest: Mapping, *, size: int, digest: str) -> None:
    row = approval_lock_1252()
    approval = manifest.get("release_approval") or {}
    installer = manifest.get("fresh_installer") or {}
    require(manifest.get("deployable") is True
            and manifest.get("source") == {"commit": row["source_commit"], "dirty": False}
            and installer.get("sha256") == row["installer_sha256"],
            "1252_MANIFEST_PROVENANCE_MISMATCH")
    match_candidate_artifact(dict(
        target_release_id=manifest.get("release_id"), target_version=manifest.get("version"),
        target_release_sequence=manifest.get("release_sequence"), bundle_sha256=digest,
        bundle_size=size, release_approval_reference=approval.get("reference"),
        release_candidate_sha256=approval.get("candidate_sha256"),
        source_commit=(manifest.get("source") or {}).get("commit"),
    ))


def rotation_inventory() -> dict:
    row = approval_lock_1252()
    prior = archive_inventory()
    return {**prior, CANDIDATE_ID: {
        "version": CANDIDATE_VERSION, "sequence": CANDIDATE_SEQUENCE,
        "size": row["approved_bundle_size"], "sha256": row["approved_bundle_sha256"],
        "archive_url": "https://github.com/kulvib/display-planiq/releases/download/"
                       + row["github_release_tag"] + "/clientflow-approved-1.4.2-1252.tar",
    }}


def rotation_state(snapshot: Mapping) -> str:
    """Only original 3, intermediate 2, or final 3 exact verified TARs."""
    rows = snapshot.get("protected_latest")
    require(type(rows) is list and snapshot.get("older_review_only") == []
            and snapshot.get("invalid_artifacts") == []
            and type(snapshot.get("approved_count")) is int
            and snapshot["approved_count"] == len(rows), "1252_UNSAFE_INVENTORY")
    pins = rotation_inventory()
    ids = set()
    for item in rows:
        require(isinstance(item, Mapping), "1252_INVALID_INVENTORY_ROW")
        identifier = item.get("release_id")
        require(isinstance(identifier, str) and identifier in pins and identifier not in ids,
                "1252_UNKNOWN_OR_DUPLICATE_ARTIFACT")
        pin = pins[identifier]
        require(type(item.get("size_bytes")) is int and item["size_bytes"] == pin["size"]
                and item.get("sha256") == pin["sha256"], "1252_INVENTORY_PIN_MISMATCH")
        ids.add(identifier)
    if ids == RETAINED_IDS:
        return "original"
    if ids == INTERMEDIATE_IDS:
        return "pruned"
    if ids == FINAL_IDS:
        return "published"
    raise Candidate1252Denied("1252_NONCANONICAL_PARTIAL_ROTATION")


def require_rotated_store() -> dict:
    """Expensive explicit operator check, never a polling or RDP hot path."""
    from .clientflow_release_artifacts import _artifact_root
    from .clientflow_releases import deployment_release_snapshot
    root = _artifact_root()
    names = {path.name for path in root.iterdir()
             if path.name.startswith("clientflow-") and path.name.endswith(".tar")}
    require(names == {rid + ".tar" for rid in FINAL_IDS}, "1252_EXACT_FINAL_STORE_REQUIRED")
    pins = rotation_inventory()
    for rid in sorted(FINAL_IDS):
        pin = pins[rid]
        artifact = deployment_release_snapshot(dict(release_id=rid, version=pin["version"],
                                                    release_sequence=pin["sequence"]))
        require((artifact["bundle_size"], artifact["bundle_sha256"]) == (pin["size"], pin["sha256"]),
                "1252_STORED_ARTIFACT_MISMATCH")
        if rid == CANDIDATE_ID:
            match_candidate_artifact({**artifact, "target_version": pin["version"],
                                      "target_release_sequence": pin["sequence"]})
    return candidate_snapshot()
