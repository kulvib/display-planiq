"""Closed 1250 predecessor / exact 1251 successor policy (68K-E3).

Staging this source never promotes a catalog or authorizes a client.
No new environment authority. The historical 1248 catalog remains unchanged.
"""
from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path

from .clientflow_pilot_1250 import (
    approval_lock_1250, match_approved_artifact, pilot_release, CONFLICTING_FLAGS,
)
from .clientflow_standard_release import (
    BASELINE_ID, BASELINE_VERSION, BASELINE_SEQUENCE, validate_baseline_catalog,
)

SUCCESSOR_ID = "clientflow-1.4.1-seq-1251"
SUCCESSOR_VERSION = "1.4.1"
SUCCESSOR_SEQUENCE = 1251
PILOT_CLIENT_ID = 3
APPROVAL_PATH = Path(__file__).with_name("clientflow_pilot_1251_approval.json")
APPROVAL_SHA256 = "2926a9d1bdb1d364616f11c44ef1aba43664e6107379eaa97562b31002cb6038"
STAGE_PATH = Path(__file__).with_name("clientflow_release_catalog_1250_closed.stage.json")
STAGE_SHA256 = "27b14ddd7f692ec37d2e5e372cfb3470d5af84bacd9662d7a7e4aabbc21848f4"
INVENTORY_PATH = Path(__file__).with_name("clientflow_1251_archive_inventory.json")
INVENTORY_SHA256 = "521b32f00437fcc880fa9b05647b841ac33aee85786548bdb0311a59756d3cbc"
RETAINED_IDS = frozenset({"clientflow-1.3.47-seq-1248", BASELINE_ID, SUCCESSOR_ID})


class Pilot1251Denied(ValueError):
    pass


def _pinned_json(path: Path, expected: str) -> dict:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 32768:
            raise ValueError("unsafe pinned source")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("pin mismatch")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("invalid pinned object")
        return data
    except (OSError, ValueError, UnicodeError) as exc:
        raise Pilot1251Denied("Eksakt 1251-kildebevis mangler") from exc


def approval_lock_1251() -> dict:
    return _pinned_json(APPROVAL_PATH, APPROVAL_SHA256)


def closed_baseline_catalog() -> dict:
    catalog = _pinned_json(STAGE_PATH, STAGE_SHA256)
    validate_baseline_catalog(catalog)
    return catalog


def archive_inventory() -> dict:
    return _pinned_json(INVENTORY_PATH, INVENTORY_SHA256)["releases"]


def require_closed_baseline(catalog: Mapping, control: Mapping, revision: int) -> None:
    approval = approval_lock_1250()
    if (catalog != closed_baseline_catalog()
            or control.get("stable_release_id") != BASELINE_ID
            or control.get("stable_bundle_sha256") != approval["approved_bundle_sha256"]
            or type(revision) is not int or revision < 1 or control.get("revision") != revision
            or any(control.get(flag) is not False for flag in ("cutover_enabled", "fleet_open", "fresh_install_open"))
            or os.environ.get("CLIENTFLOW_FRESH_INSTALL_SUSPENDED") != "1"
            or os.environ.get("CLIENTFLOW_SIGNED_ROLLBACK_ENABLED", "false").strip().lower() != "false"
            or any(os.environ.get(flag) for flag in CONFLICTING_FLAGS)):
        raise Pilot1251Denied("Lukket 1250-reference og releasepolitik er ikke verificeret")


def successor_release() -> dict:
    return {**pilot_release(), "release_id": SUCCESSOR_ID, "revision": SUCCESSOR_ID,
            "version": SUCCESSOR_VERSION, "release_sequence": SUCCESSOR_SEQUENCE,
            "min_current_version": BASELINE_VERSION, "max_current_version": BASELINE_VERSION}


def successor_snapshot() -> dict:
    data = approval_lock_1251()
    return {"target_release_id": SUCCESSOR_ID, "target_version": SUCCESSOR_VERSION,
            "target_release_sequence": SUCCESSOR_SEQUENCE,
            "bundle_sha256": data["approved_bundle_sha256"],
            "bundle_size": data["approved_bundle_size"],
            "release_approval_reference": data["approval_reference"],
            "release_candidate_sha256": data["candidate_sha256"],
            "source_commit": data["source_commit"]}


def match_successor_artifact(artifact: Mapping) -> None:
    expected = successor_snapshot()
    if any(type(artifact.get(key)) is not type(value) or artifact.get(key) != value
           for key, value in expected.items()):
        raise Pilot1251Denied("1251 artifact matcher ikke eksakt godkendelse")


def match_successor_order(row, *, client_id: int) -> bool:
    expected = successor_snapshot()
    return bool(row is not None and type(client_id) is int and client_id == PILOT_CLIENT_ID
                and row.client_id == client_id and row.allow_downgrade is False
                and all(getattr(row, key, None) == value for key, value in expected.items()))


def require_retained_store() -> dict:
    """Explicit admin order only: verify all three exact stored TARs, no hot-path hashing."""
    from .clientflow_release_artifacts import _artifact_root
    from .clientflow_releases import deployment_release_snapshot
    root = _artifact_root()
    names = {path.name for path in root.iterdir()
             if path.name.startswith("clientflow-") and path.name.endswith(".tar")}
    if names != {identifier + ".tar" for identifier in RETAINED_IDS}:
        raise Pilot1251Denied("Render skal indeholde præcis 1248, 1250 og 1251")
    inventory = archive_inventory()
    for identifier in sorted(RETAINED_IDS):
        row = inventory[identifier]
        artifact = deployment_release_snapshot({"release_id": identifier, "version": row["version"],
                                               "release_sequence": row["sequence"]})
        if (artifact["bundle_size"], artifact["bundle_sha256"]) != (row["size"], row["sha256"]):
            raise Pilot1251Denied("Release-lagerets bytes matcher ikke arkivbevis")
        if identifier == BASELINE_ID:
            match_approved_artifact(approval_lock_1250(), artifact)
        if identifier == SUCCESSOR_ID:
            match_successor_artifact({**artifact, "target_version": SUCCESSOR_VERSION,
                                      "target_release_sequence": SUCCESSOR_SEQUENCE})
    return successor_snapshot()
