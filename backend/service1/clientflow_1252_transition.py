"""68N-B4: 1252 outcome and retention contracts, NOT approval or rollout.

The exact 1252 artifact and authorization path do not exist yet. These
contracts only constrain future observations and produce a non-executable
rotation plan for the approved closed 1251 baseline.
"""
from __future__ import annotations

from collections.abc import Mapping

from .clientflow_closed_standard_1251 import require_closed_standard_control
from .clientflow_pilot_1251 import (
    RETAINED_IDS, SUCCESSOR_ID as PREDECESSOR_ID,
    archive_inventory,
)

CANDIDATE_ID = "clientflow-1.4.2-seq-1252"
CANDIDATE_VERSION = "1.4.2"
CANDIDATE_SEQUENCE = 1252
OLDEST_ID = "clientflow-1.3.47-seq-1248"


class Candidate1252Denied(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise Candidate1252Denied(reason)


def is_candidate_order(row) -> bool:
    # Also catch mixed identities: no version/sequence alias can bypass the
    # stricter contract. This is classification, not an authorization check.
    return (row.target_release_id == CANDIDATE_ID
            or row.target_version == CANDIDATE_VERSION
            or row.target_release_sequence == CANDIDATE_SEQUENCE)


def require_candidate_observation(row, event_type: str, payload: Mapping) -> None:
    require(type(row.client_id) is int and row.client_id > 0
            and row.target_release_id == CANDIDATE_ID
            and row.target_version == CANDIDATE_VERSION
            and type(row.target_release_sequence) is int
            and row.target_release_sequence == CANDIDATE_SEQUENCE
            and row.allow_downgrade is False,
            "1252 kræver eksakt forward-update")
    if event_type == "succeeded":
        require(payload.get("observed_release_id") == CANDIDATE_ID
                and type(payload.get("observed_release_sequence")) is int
                and payload["observed_release_sequence"] == CANDIDATE_SEQUENCE
                and payload.get("observed_previous_release_id") == PREDECESSOR_ID,
                "1252 success mangler eksakt 1251-forgænger")
    elif event_type in {"rollback_started", "rolled_back"}:
        require(payload.get("failed_release_id") == CANDIDATE_ID
                and payload.get("restored_release_id") == PREDECESSOR_ID,
                "1252 recovery matcher ikke eksakt 1251-forgænger")
    elif event_type == "health_check_started":
        require(payload.get("release_id") == CANDIDATE_ID,
                "1252 health-check matcher ikke eksakt kandidat")


def plan_rotation(catalog: Mapping, control: Mapping, snapshot: Mapping) -> dict:
    """Pure plan. Inputs are observations, never a proof of remote archive.

    A future reviewed artifact-bound workflow must repeat the checks against
    live storage, verify the external copy, and use the locked prune path.
    """
    require(require_closed_standard_control(catalog, control) == "bound",
            "CLOSED_1251_REQUIRED")
    require(type(snapshot.get("approved_count")) is int
            and snapshot["approved_count"] == 3
            and snapshot.get("invalid_artifacts") == [],
            "EXACT_THREE_ARTIFACTS_REQUIRED")
    protected = snapshot.get("protected_latest")
    older = snapshot.get("older_review_only")
    require(type(protected) is list and type(older) is list
            and older == [] and len(protected) == 3,
            "EXACT_PROTECTED_INVENTORY_REQUIRED")
    pins = archive_inventory()
    seen = set()
    for row in protected:
        require(isinstance(row, Mapping), "INVALID_INVENTORY_ROW")
        identifier = row.get("release_id")
        require(isinstance(identifier, str) and identifier in RETAINED_IDS
                and identifier not in seen, "INVALID_OR_DUPLICATE_RELEASE")
        pin = pins[identifier]
        require(type(row.get("size_bytes")) is int and row["size_bytes"] == pin["size"]
                and row.get("sha256") == pin["sha256"], "ARCHIVE_PIN_MISMATCH")
        seen.add(identifier)
    require(seen == RETAINED_IDS, "INVENTORY_MISMATCH")
    return {
        "candidate_release_id": CANDIDATE_ID,
        "stable_release_id": PREDECESSOR_ID,
        "control_revision": 3,
        "verify_offsite_archive_before_removal": {OLDEST_ID: pins[OLDEST_ID]},
        "retain_before_publication": sorted(RETAINED_IDS - {OLDEST_ID}),
        "retain_after_publication": sorted((RETAINED_IDS - {OLDEST_ID}) | {CANDIDATE_ID}),
        "projected_counts": [3, 2, 3],
        "candidate_artifact_verified": False,
        "offsite_archive_verified": False,
        "destructive_action_authorized": False,
        "deployment_authorized": False,
        "fleet_authorized": False,
        "fresh_install_authorized": False,
        "manual_rollback_authorized": False,
    }
