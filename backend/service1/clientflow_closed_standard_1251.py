"""68M-A: exact closed 1251 standard transition, not rollout authority."""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from .clientflow_pilot_1250 import approval_lock_1250
from .clientflow_pilot_1251 import (
    BASELINE_ID, BASELINE_VERSION, SUCCESSOR_ID,
    Pilot1251Denied, _pinned_json, approval_lock_1251, closed_baseline_catalog,
    require_closed_baseline, match_successor_order, successor_snapshot,
)

STAGE_PATH = Path(__file__).with_name("clientflow_release_catalog_1251_closed.stage.json")
STAGE_SHA256 = "c3c98d8e30791483d1f5e5ade7a70dc96a732b8b69f7dc7440740c025c2d10a5"


def closed_standard_catalog() -> dict:
    return _pinned_json(STAGE_PATH, STAGE_SHA256)


def validate_closed_standard_catalog(catalog: Mapping, *, source_sha256: str | None = None) -> None:
    expected = closed_standard_catalog()
    if (json.dumps(catalog, sort_keys=True) != json.dumps(expected, sort_keys=True)
            or (source_sha256 is not None and source_sha256 != STAGE_SHA256)):
        raise Pilot1251Denied("Kun det eksakte lukkede 1251-katalog accepteres")
    approval_lock_1251()


def require_closed_standard_control(catalog: Mapping, control: Mapping, *, allow_predecessor: bool = False) -> str:
    validate_closed_standard_catalog(catalog)
    old_sha = approval_lock_1250()["approved_bundle_sha256"]
    new_sha = approval_lock_1251()["approved_bundle_sha256"]
    actual = (control.get("stable_release_id"), control.get("stable_bundle_sha256"), control.get("revision"))
    if type(control.get("revision")) is not int:
        raise Pilot1251Denied("Ugyldig revisionsbinding")
    if actual == (BASELINE_ID, old_sha, 2) and allow_predecessor:
        mode = "pending"
    elif actual == (SUCCESSOR_ID, new_sha, 3):
        mode = "bound"
    else:
        raise Pilot1251Denied("1251 kontrolbinding matcher ikke den lukkede overgang")
    # Reuse the exact existing independent environment and policy interlocks.
    require_closed_baseline(closed_baseline_catalog(), {
        **control, "stable_release_id": BASELINE_ID, "stable_bundle_sha256": old_sha, "revision": 2,
    }, 2)
    return mode


def baseline_snapshot() -> dict:
    a = approval_lock_1250()
    return dict(target_release_id=BASELINE_ID, target_version=BASELINE_VERSION,
                target_release_sequence=1250, bundle_sha256=a["approved_bundle_sha256"],
                bundle_size=a["approved_bundle_size"], release_approval_reference=a["approval_reference"],
                release_candidate_sha256=a["candidate_sha256"], source_commit=a["source_commit"])


def require_completed_successor(latest, predecessor, *, client_id: int) -> None:
    # Import locally to keep native RDP admission and this pure evidence
    # contract independent at module import time.
    from .native_rdp_admission import matches_completed_update
    if (not match_successor_order(latest, client_id=client_id)
            or not matches_completed_update(latest, client_id=client_id, artifact=successor_snapshot())
            or latest.observed_previous_release_id != BASELINE_ID
            or not matches_completed_update(predecessor, client_id=client_id, artifact=baseline_snapshot())
            or predecessor.allow_downgrade is not False
            or predecessor.observed_previous_release_id != "clientflow-1.3.47-seq-1248"):
        raise Pilot1251Denied("Eksakt gennemført 1250 → 1251-deployment mangler")
