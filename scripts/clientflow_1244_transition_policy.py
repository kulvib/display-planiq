"""Single-use, pinned admission for the approved 1244 clean-baseline reset.

This only admits one *specific* sixth bundle. No deletion, catalog change,
client activation, automatic rollout or relaxation of the normal 3-bundle cap.
The six-bundle intermediate state must be reconciled in a distinct operation
AFTER the catalog points to the already published 1244 bundle.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from scripts.clientflow_1243_transition_policy import VERIFIED_AFTER as PREVIOUS_FIVE

RELEASE_ID = "clientflow-1.3.43-seq-1244"
APPROVED_SHA256 = "d3fdae8fb2a93f74431780f4aadde21625d10917e99cfbe6095ff2394e1e856b"
APPROVED_SIZE = 223610880
SOURCE_COMMIT = "7ead8cf250b7d9b7c0d1bff5b70f574e76c11f41"
APPROVAL_REFERENCE = "CF-1.3.43-1244-20261109-7ead8cf-2243141d"
CATALOG_PATH = Path(__file__).resolve().parents[1] / "backend/service1/clientflow_release_catalog.json"
EXPECTED_AFTER = {**PREVIOUS_FIVE, RELEASE_ID: (APPROVED_SIZE, APPROVED_SHA256)}


class ClientFlow1244ResetDenied(RuntimeError):
    pass


def require_quiesced() -> None:
    if os.environ.get("CLIENTFLOW_FRESH_INSTALL_SUSPENDED") != "1":
        raise ClientFlow1244ResetDenied("Fresh installs must remain suspended")
    if any(os.environ.get(name) for name in (
        "CLIENTFLOW_1241_PILOT_CLIENT_ID",
        "CLIENTFLOW_1242_PILOT_CLIENT_ID",
        "CLIENTFLOW_1243_PILOT_CLIENT_ID",
    )):
        raise ClientFlow1244ResetDenied("All historical client pilot flags must be unset")


def require_exact_store(snapshot: dict[str, Any], *, after: bool) -> None:
    if snapshot.get("invalid_artifacts"):
        raise ClientFlow1244ResetDenied("Invalid artifacts in store")
    if snapshot.get("retention_target") != 3:
        raise ClientFlow1244ResetDenied("Permanent three-release cap was modified")
    if snapshot.get("automatic_deletion_enabled") is not False or snapshot.get("rollback_enabled") is not False:
        raise ClientFlow1244ResetDenied("Automatic deletion or rollback must remain disabled")
    rows = [*(snapshot.get("protected_latest") or []), *(snapshot.get("older_review_only") or [])]
    expected = EXPECTED_AFTER if after else PREVIOUS_FIVE
    seen = {}
    for row in rows:
        release = row.get("release_id")
        if release in seen:
            raise ClientFlow1244ResetDenied("Duplicate release in inventory")
        seen[release] = (row.get("size_bytes"), row.get("sha256"))
    if snapshot.get("approved_count") != len(expected) or seen != expected:
        raise ClientFlow1244ResetDenied("Exact pinned approved inventory required for 1244 transition")


def require_staged_catalog() -> None:
    try:
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ClientFlow1244ResetDenied("Cannot verify staging catalog") from exc
    if not (
        catalog.get("catalog_sequence") == 1243
        and catalog.get("latest_stable") == "1.3.38"
        and catalog.get("default_install_version") == "1.3.38"
        and [row.get("release_id") for row in catalog.get("releases", [])] == [
            "clientflow-1.3.38-seq-1239",
            "clientflow-1.3.40-seq-1241",
            "clientflow-1.3.41-seq-1242",
            "clientflow-1.3.42-seq-1243",
        ]
    ):
        raise ClientFlow1244ResetDenied("1244 admission requires the unchanged 1243 staging catalog")


def require_admission(snapshot: dict[str, Any], *, release_id: str, size_bytes: int, sha256: str) -> None:
    require_quiesced()
    require_staged_catalog()
    require_exact_store(snapshot, after=False)
    if (release_id, size_bytes, sha256) != (RELEASE_ID, APPROVED_SIZE, APPROVED_SHA256):
        raise ClientFlow1244ResetDenied("Only exact approved 1244 bytes may be admitted")


def require_postflight(snapshot: dict[str, Any], *, release_id: str, size_bytes: int, sha256: str) -> None:
    require_quiesced()
    require_exact_store(snapshot, after=True)
    if (release_id, size_bytes, sha256) != (RELEASE_ID, APPROVED_SIZE, APPROVED_SHA256):
        raise ClientFlow1244ResetDenied("Wrong release in 1244 postflight")
