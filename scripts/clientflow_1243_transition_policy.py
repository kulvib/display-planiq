"""Pinned, non-destructive five-bundle transition for the approved 1243 pilot.

This is an *exception to publication admission only*. The long-term retention
limit remains three, old bundle deletion is NOT authorized and the catalog's
1.3.38 fresh-install pin remains untouched. Only the exact verified four-
bundle store can become the exact verified five-bundle store. No other release,
version, SHA or inventory is permitted through this gate.
"""
from __future__ import annotations

import os
from typing import Any

TRANSITION_RELEASE_ID = "clientflow-1.3.42-seq-1243"
TRANSITION_APPROVED_SHA256 = "ee35cc6caa9304bbc7ee4b1c763ecdeaf03d9d58a6c73cee943805251d8d6914"
TRANSITION_APPROVED_SIZE = 223610880

# These are the exact previously approved artifacts from the independent
# GitHub release archives and the read-only Render inventory.
VERIFIED_BEFORE = {
    "clientflow-1.3.38-seq-1239": (223498240, "02c3d4261eabdac4b9967a3aad4419453f61ca483ef4eb34dacf284d3af16a11"),
    "clientflow-1.3.39-seq-1240": (223498240, "40fb64e3e8e38686f4b03ee8f66afc81fe7a03247ed723d8a6ce636aebbcb798"),
    "clientflow-1.3.40-seq-1241": (223518720, "b63211454c9cee0f24277c51f0d13d75099729e641d13f9ce4ed9ad696468783"),
    "clientflow-1.3.41-seq-1242": (223610880, "5b6603f9169870e867d340a567df1194c57dfb254b306328c07f1366023aabce"),
}
VERIFIED_AFTER = {
    **VERIFIED_BEFORE,
    TRANSITION_RELEASE_ID: (TRANSITION_APPROVED_SIZE, TRANSITION_APPROVED_SHA256),
}


class ClientFlow1243TransitionDenied(RuntimeError):
    """The requested temporary excess is not the exact approved transition."""


def require_quiesced_fresh_install() -> None:
    """No new enrollment/fresh install while crossing the three-release cap."""
    if os.environ.get("CLIENTFLOW_FRESH_INSTALL_SUSPENDED") != "1":
        raise ClientFlow1243TransitionDenied(
            "Fresh install must be explicitly suspended with CLIENTFLOW_FRESH_INSTALL_SUSPENDED=1"
        )
    if any(os.environ.get(flag) for flag in (
        "CLIENTFLOW_1241_PILOT_CLIENT_ID",
        "CLIENTFLOW_1242_PILOT_CLIENT_ID",
        "CLIENTFLOW_1243_PILOT_CLIENT_ID",
    )):
        raise ClientFlow1243TransitionDenied(
            "All client update pilot flags must remain disabled during transitional publication"
        )


def require_exact_store(snapshot: dict[str, Any], *, after: bool) -> None:
    """Validate every independent store-audit result, not just its count."""
    if snapshot.get("invalid_artifacts"):
        raise ClientFlow1243TransitionDenied("Unverified artifacts prevent transitional publication")
    if snapshot.get("retention_target") != 3:
        raise ClientFlow1243TransitionDenied("Permanent three-release policy must remain active")
    expected = VERIFIED_AFTER if after else VERIFIED_BEFORE
    rows = [*(snapshot.get("protected_latest") or []), *(snapshot.get("older_review_only") or [])]
    identities = {}
    for row in rows:
        release_id = row.get("release_id")
        if release_id in identities:
            raise ClientFlow1243TransitionDenied("Duplicate approved release in audited store")
        identities[release_id] = (row.get("size_bytes"), row.get("sha256"))
    if identities != expected or snapshot.get("approved_count") != len(expected):
        raise ClientFlow1243TransitionDenied(
            "Exact 1239-1242/1243 release inventory, sizes and SHA-256 are required"
        )
    if snapshot.get("automatic_deletion_enabled") is not False or snapshot.get("rollback_enabled") is not False:
        raise ClientFlow1243TransitionDenied("Transition may not enable deletion or manual rollback")


def require_1243_admission(
    snapshot: dict[str, Any], *, release_id: str, size_bytes: int, sha256: str
) -> None:
    require_quiesced_fresh_install()
    require_exact_store(snapshot, after=False)
    if (release_id, size_bytes, sha256) != (
        TRANSITION_RELEASE_ID, TRANSITION_APPROVED_SIZE, TRANSITION_APPROVED_SHA256,
    ):
        raise ClientFlow1243TransitionDenied("Only the exact approved 1.3.42/1243 bundle may enter")


def require_1243_postflight(snapshot: dict[str, Any], *, release_id: str, size_bytes: int, sha256: str) -> None:
    require_quiesced_fresh_install()
    require_exact_store(snapshot, after=True)
    if (release_id, size_bytes, sha256) != (
        TRANSITION_RELEASE_ID, TRANSITION_APPROVED_SIZE, TRANSITION_APPROVED_SHA256,
    ):
        raise ClientFlow1243TransitionDenied("Postflight request must name exact approved 1243 bundle")
