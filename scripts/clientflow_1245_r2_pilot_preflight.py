#!/usr/bin/env python3
"""Read-only, fail-closed ClientFlow 1245 R2 *staging* guard.

Not an approval, Render mutation, pilot enablement or authorization to deploy.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "06857104952ebb40bf1394c423c01332d28f8d5e"
CANDIDATE_SHA = "ffe58332c8e3b263e00f299e363dc95ecb9ac7e0176fd51888be98fecad9bd97"
INSTALLER_SHA = "fc843b6b37772996ecbfa67ff08a0e6f372443bf7d6104ca28d616855bc5737a"
APPROVED_SHA = "28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5"
APPROVED_SIZE = 223610880
APPROVAL_REF = "CF-1.3.44-1245-20261114-0685710-ffe58332-R2"
PILOT_RELEASE = "clientflow-1.3.44-seq-1245"
BASELINE_RELEASE = "clientflow-1.3.43-seq-1244"
BASELINE_SHA = "d3fdae8fb2a93f74431780f4aadde21625d10917e99cfbe6095ff2394e1e856b"


def inspect(repo: Path) -> dict:
    checks: dict[str, bool] = {}

    def load(path: str) -> dict:
        try:
            data = json.loads((repo / path).read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, UnicodeError, ValueError):
            return {}

    active = load("backend/service1/clientflow_release_catalog.json")
    staged = load("backend/service1/clientflow_release_catalog_1245_pilot.stage.json")
    lock = load("backend/service1/clientflow_pilot_1245_approval.json")
    active_releases = active.get("releases")
    staged_releases = staged.get("releases")
    baseline = active_releases[0] if isinstance(active_releases, list) and len(active_releases) == 1 and isinstance(active_releases[0], dict) else {}
    proposal = staged_releases[1] if isinstance(staged_releases, list) and len(staged_releases) == 2 and isinstance(staged_releases[1], dict) else {}

    checks["active_catalog_still_1244_only"] = (
        active.get("catalog_sequence") == 1244
        and active.get("latest_stable") == active.get("default_install_version") == "1.3.43"
        and baseline.get("release_id") == BASELINE_RELEASE
        and baseline.get("status") == "stable"
        and baseline.get("installable") is True
        and baseline.get("update_allowed") is False
        and baseline.get("rollback_allowed") is False
        and baseline.get("install_modes") == ["fresh_install"]
        and BASELINE_SHA in " ".join(str(x) for x in baseline.get("notes", []))
    )
    checks["unmodified_1244_baseline_in_stage"] = (
        isinstance(staged_releases, list) and len(staged_releases) == 2
        and staged_releases[0] == baseline
    )
    checks["single_future_sequence_and_default"] = (
        staged.get("catalog_sequence") == 1245
        and staged.get("manifest_schema") == active.get("manifest_schema") == 4
        and staged.get("channel") == active.get("channel") == "canonical-release-catalog"
        and staged.get("retention_policy") == active.get("retention_policy") == {
            "max_selectable_versions": 3, "max_installable_versions": 1,
            "keep_blocked_metadata": False,
        }
        and staged.get("latest_stable") == staged.get("default_install_version") == "1.3.43"
    )
    checks["pilot_catalog_exact_update_only"] = (
        proposal.get("version") == proposal.get("client_version") == "1.3.44"
        and proposal.get("release_id") == proposal.get("revision") == PILOT_RELEASE
        and type(proposal.get("release_sequence")) is int
        and proposal["release_sequence"] == 1245
        and proposal.get("status") == "supported"
        and proposal.get("artifact_type") == "runtime_release"
        and proposal.get("installable") is False
        and proposal.get("update_allowed") is True
        and proposal.get("rollback_allowed") is False
        and proposal.get("requires_explicit_downgrade") is False
        and proposal.get("requires_reboot") is True
        and proposal.get("install_modes") == ["in_place_update"]
        and proposal.get("min_current_version") == proposal.get("max_current_version") == "1.3.43"
        and proposal.get("ubuntu_compatibility") == baseline.get("ubuntu_compatibility")
    )
    checks["approval_lock_r2_exact_but_disabled"] = (
        lock == {
            "schema_version": 1, "approved": False,
            "release_id": PILOT_RELEASE, "source_commit": SOURCE,
            "candidate_sha256": CANDIDATE_SHA,
            "installer_sha256": INSTALLER_SHA,
            "approved_bundle_sha256": APPROVED_SHA,
            "approved_bundle_size": APPROVED_SIZE,
            "approval_reference": APPROVAL_REF,
        }
    )
    checks["no_live_pilot_promotion"] = (
        all(isinstance(x, dict) and x.get("release_id") != PILOT_RELEASE for x in active_releases)
        if isinstance(active_releases, list) else False
    )
    checks["original_client_source_untouched"] = (
        (repo / "client/VERSION").read_text(encoding="utf-8").strip() == "1.3.44"
        and load("client/release/release-input.json").get("release_sequence") == 1245
    ) if (repo / "client/VERSION").is_file() else False
    checks["rollback_authority_disabled"] = (
        load("client/release/rollback-trust.json") == {
            "schema_version": 1, "enabled": False, "keys": [],
        }
    )
    guard = repo / "backend/service1/clientflow_pilot_1245.py"
    checks["separate_operator_flag_required"] = (
        guard.is_file()
        and 'os.environ.get(PILOT_FLAG) != str(PILOT_CLIENT_ID)' in guard.read_text(encoding="utf-8")
        and 'if approval.get("approved") is not True' in guard.read_text(encoding="utf-8")
    )
    return {
        "stage": "R2_exact_bytes_staged_only",
        "ready": all(checks.values()),
        "pilot_authorized": False,
        "catalog_promoted": False,
        "physical_recovery_verified": False,
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    result = inspect(parser.parse_args(argv).repo_root)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
