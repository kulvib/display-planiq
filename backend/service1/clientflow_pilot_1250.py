"""Source-reviewed approval pin and exact closed pre-cutover 1250 pilot policy.

A successful build is not approval. The pin remains None until a separate
reviewed post-build commit records the real approved archive metadata.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from collections.abc import Mapping

from .clientflow_pilot_1248_db_authorization import CONFLICTING_FLAGS
from .clientflow_standard_release import BASELINE_ID, BASELINE_VERSION, BASELINE_SEQUENCE

APPROVAL_PATH = Path(__file__).with_name("clientflow_pilot_1250_approval.json")
EXPECTED_APPROVAL_SHA256 = None
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_COMMIT = re.compile(r"[a-f0-9]{40}\Z")
_OLD_ID = "clientflow-1.3.44-seq-1245"
_OLD_SHA = "28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5"


class Pilot1250Denied(ValueError):
    pass


def approval_lock_1250() -> dict:
    try:
        if not isinstance(EXPECTED_APPROVAL_SHA256, str) or not _SHA.fullmatch(EXPECTED_APPROVAL_SHA256):
            raise ValueError("unapproved_source")
        if APPROVAL_PATH.is_symlink() or not APPROVAL_PATH.is_file() or APPROVAL_PATH.stat().st_size > 4096:
            raise ValueError("unsafe_approval_source")
        raw = APPROVAL_PATH.read_bytes()
        if hashlib.sha256(raw).hexdigest() != EXPECTED_APPROVAL_SHA256:
            raise ValueError("approval_pin_mismatch")
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) != {
            "schema_version", "approved", "release_id", "source_commit", "candidate_sha256",
            "installer_sha256", "approved_bundle_sha256", "approved_bundle_size",
            "approval_reference", "approval_run_id", "github_release_tag",
        }:
            raise ValueError("approval_schema")
        if (type(data["schema_version"]) is not int or data["schema_version"] != 1
                or data["approved"] is not True or data["release_id"] != BASELINE_ID
                or not isinstance(data["source_commit"], str) or not _COMMIT.fullmatch(data["source_commit"])
                or any(not isinstance(data[key], str) or not _SHA.fullmatch(data[key])
                       for key in ("candidate_sha256", "installer_sha256", "approved_bundle_sha256"))
                or type(data["approved_bundle_size"]) is not int or data["approved_bundle_size"] <= 0
                or type(data["approval_run_id"]) is not int or data["approval_run_id"] <= 0
                or not isinstance(data["approval_reference"], str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._:/@+-]{0,199}", data["approval_reference"])
                or data["github_release_tag"] != "clientflow-1.4.0-1250-approved-transport"):
            raise ValueError("invalid_approval")
        return data
    except (OSError, ValueError, TypeError, UnicodeError) as exc:
        raise Pilot1250Denied("1250 mangler eksakt Git-reviewet godkendelseslås") from exc


def pilot_release() -> dict:
    return {"release_id": BASELINE_ID, "revision": BASELINE_ID, "version": BASELINE_VERSION,
            "release_sequence": BASELINE_SEQUENCE, "status": "supported", "installable": False,
            "update_allowed": True, "rollback_allowed": False, "requires_reboot": True,
            "requires_explicit_downgrade": False, "install_modes": ["in_place_update"],
            "artifact_type": "runtime_release", "min_current_version": "1.3.47", "max_current_version": "1.3.47",
            "ubuntu_compatibility": {"policy": "ubuntu-desktop-lts-minimum",
                "minimum_lts_version": "26.04", "maximum_certified_version": "26.04",
                "certified_versions": ["26.04"], "architecture": "amd64", "desktop": "gnome",
                "display_stack": "wayland", "requires_platform_preflight": True}}


def require_pilot_holds(catalog: Mapping, control: Mapping, revision: int) -> None:
    # _bound_control separately validates the exact immutable historical catalog.
    if (catalog.get("catalog_sequence") != 1248
            or catalog.get("latest_stable") != "1.3.44"
            or catalog.get("default_install_version") != "1.3.44"
            or control.get("stable_release_id") != _OLD_ID
            or control.get("stable_bundle_sha256") != _OLD_SHA
            or type(revision) is not int or revision < 1 or control.get("revision") != revision
            or any(control.get(flag) is not False for flag in ("cutover_enabled", "fleet_open", "fresh_install_open"))
            or os.environ.get("CLIENTFLOW_FRESH_INSTALL_SUSPENDED") != "1"
            or any(os.environ.get(flag) for flag in CONFLICTING_FLAGS)):
        raise Pilot1250Denied("Historisk katalog eller lukkede releaseporte er ændret")


def match_approved_artifact(approval: Mapping, artifact: Mapping) -> None:
    expected = {
        "target_release_id": BASELINE_ID,
        "bundle_sha256": approval.get("approved_bundle_sha256"),
        "bundle_size": approval.get("approved_bundle_size"),
        "release_approval_reference": approval.get("approval_reference"),
        "release_candidate_sha256": approval.get("candidate_sha256"),
        "source_commit": approval.get("source_commit"),
    }
    if any(value is None or type(artifact.get(key)) is not type(value)
           or artifact.get(key) != value for key, value in expected.items()):
        raise Pilot1250Denied("Publiceret 1250 artifact matcher ikke godkendt proveniens")
