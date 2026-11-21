"""63D-16: one-time fourth *stored* signed artifact, not a fourth selectable release.

The sole allowed transition is 1245+1246+1247 -> 1245+1246+1247+1248.
This module has no I/O or deployment capability; the publisher still checks
immutable approval, source SHA, bundle content, store owner, disk and flock.
"""
from __future__ import annotations

from typing import Any

EXCEPTION_RELEASE_ID = "clientflow-1.3.47-seq-1248"
# Exact immutable historically approved artifacts. The publisher's independent
# structural verifier must accept their signed TARs before this guard runs.
HISTORICAL = {
    "clientflow-1.3.44-seq-1245": (
        223610880, "28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5",
    ),
    "clientflow-1.3.45-seq-1246": (
        223682560, "e37de3250d58d313d57ad7bcbf59682cee342f2727c6ad5b188c8782342d4c78",
    ),
    "clientflow-1.3.46-seq-1247": (
        223692800, "3d6df5ec096a5713866943a67d9f88bba3fc6287458d0ea2f616bd41e42db150",
    ),
}


class FourthReleaseDenied(ValueError):
    pass


def _verified_records(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if snapshot.get("invalid_artifacts"):
        raise FourthReleaseDenied("Unverified artifacts in the release store")
    items = snapshot.get("protected_latest", []) + snapshot.get("older_review_only", [])
    if len(items) != snapshot.get("approved_count"):
        raise FourthReleaseDenied("Inconsistent release-store inventory")
    records = {str(item["release_id"]): item for item in items}
    if len(records) != len(items):
        raise FourthReleaseDenied("Duplicate artifact identity")
    return records


def _check_historical(records: dict[str, dict[str, Any]]) -> None:
    for release_id, (size, digest) in HISTORICAL.items():
        row = records.get(release_id)
        if not row or (row.get("size_bytes"), row.get("sha256")) != (size, digest):
            raise FourthReleaseDenied("Missing or changed immutable historical approval: " + release_id)


def require_preflight(
    snapshot: dict[str, Any], *, release_id: str,
    disposition: str, projected: list[dict[str, Any]],
) -> None:
    if release_id != EXCEPTION_RELEASE_ID:
        raise FourthReleaseDenied("Fourth-release exception only applies to 1248")
    records = _verified_records(snapshot)
    if disposition == "ready_to_publish":
        if set(records) != set(HISTORICAL) or snapshot.get("approved_count") != 3:
            raise FourthReleaseDenied("1248 requires the exact three pinned predecessor artifacts")
    elif disposition == "already_published":
        if set(records) != set(HISTORICAL) | {EXCEPTION_RELEASE_ID} or snapshot.get("approved_count") != 4:
            raise FourthReleaseDenied("1248 rerun requires the exact four approved artifacts")
    else:
        raise FourthReleaseDenied("Unexpected publication disposition")
    _check_historical(records)
    if {item["release_id"] for item in projected} != set(HISTORICAL) | {EXCEPTION_RELEASE_ID}:
        raise FourthReleaseDenied("Proposed fourth-artifact inventory differs from the pinned transition")
    if len(projected) != 4:
        raise FourthReleaseDenied("Fifth stored artifact is never allowed")


def require_postflight(
    snapshot: dict[str, Any], *, release_id: str, size_bytes: int, sha256: str,
) -> None:
    if release_id != EXCEPTION_RELEASE_ID:
        raise FourthReleaseDenied("Fourth-release exception only applies to 1248")
    records = _verified_records(snapshot)
    if snapshot.get("approved_count") != 4 or set(records) != set(HISTORICAL) | {EXCEPTION_RELEASE_ID}:
        raise FourthReleaseDenied("Postflight must contain exactly 1245, 1246, 1247 and 1248")
    _check_historical(records)
    current = records[EXCEPTION_RELEASE_ID]
    if (current.get("size_bytes"), current.get("sha256")) != (size_bytes, sha256):
        raise FourthReleaseDenied("Stored 1248 differs from the signed incoming artifact")
