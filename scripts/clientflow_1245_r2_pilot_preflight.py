#!/usr/bin/env python3
"""Read-only, fail-closed ClientFlow 1245 R2 *staging* guard.

Not an approval, Render mutation, pilot enablement or authorization to deploy.
"""
from __future__ import annotations

import argparse
import json

from clientflow_63d6_active_catalog_contract import (
    ActiveCatalogDenied, projected_stable_1245, verified_mode,
)
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

    try:
        catalog_mode = verified_mode(repo)
        active = projected_stable_1245(repo)
    except ActiveCatalogDenied:
        catalog_mode = None
        active = {}

    historic = load("scripts/tests/fixtures/clientflow_1244_pre_1245_pilot_catalog.json")
    staged = load("backend/service1/clientflow_release_catalog_1245_pilot.stage.json")
    stable_stage = load("backend/service1/clientflow_release_catalog_1245_stable.stage.json")
    lock = load("backend/service1/clientflow_pilot_1245_approval.json")
    active_releases = active.get("releases")
    historic_releases = historic.get("releases")
    staged_releases = staged.get("releases")
    baseline = historic_releases[0] if isinstance(historic_releases, list) and len(historic_releases) == 1 and isinstance(historic_releases[0], dict) else {}
    proposal = staged_releases[1] if isinstance(staged_releases, list) and len(staged_releases) == 2 and isinstance(staged_releases[1], dict) else {}

    checks["historic_1244_baseline_preserved"] = (
        historic.get("catalog_sequence") == 1244
        and historic.get("latest_stable") == historic.get("default_install_version") == "1.3.43"
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
    checks["single_pilot_sequence_and_default"] = (
        staged.get("catalog_sequence") == 1245
        and staged.get("manifest_schema") == historic.get("manifest_schema") == 4
        and staged.get("channel") == historic.get("channel") == "canonical-release-catalog"
        and staged.get("retention_policy") == historic.get("retention_policy") == {
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
    checks["approval_lock_r2_exact_ready"] = (
        lock == {
            "schema_version": 1, "approved": True,
            "release_id": PILOT_RELEASE, "source_commit": SOURCE,
            "candidate_sha256": CANDIDATE_SHA,
            "installer_sha256": INSTALLER_SHA,
            "approved_bundle_sha256": APPROVED_SHA,
            "approved_bundle_size": APPROVED_SIZE,
            "approval_reference": APPROVAL_REF,
        }
    )
    stable_rows = stable_stage.get("releases") or []
    checks["live_catalog_exact_one_stable_1245"] = (
        catalog_mode in ("stable_1245_only", "update_only_1246_pilot_catalog", "update_only_1247_pilot_catalog")
        and active.get("catalog_sequence") == stable_stage.get("catalog_sequence") == 1245
        and active.get("latest_stable") == active.get("default_install_version") == "1.3.44"
        and isinstance(active_releases, list) and len(active_releases) == 1
        and isinstance(stable_rows, list) and len(stable_rows) == 1
        and active_releases[0].get("release_id") == PILOT_RELEASE
        and active_releases[0].get("status") == "stable"
        and active_releases[0].get("install_modes") == ["fresh_install", "in_place_update"]
        and active_releases[0].get("installable") is True
        and active_releases[0].get("update_allowed") is True
        and all(proof in " ".join(str(n) for n in active_releases[0].get("notes", []))
                for proof in (APPROVED_SHA, SOURCE, APPROVAL_REF))
        and {key: value for key, value in active_releases[0].items() if key != "notes"}
        == {key: value for key, value in stable_rows[0].items() if key != "notes"}
    )
    # Frozen approval is about the ORIGINAL 1245 artifact; source can now
    # advance to a separate *unsigned* exact 1246 candidate, never the catalog.
    checks["original_client_source_untouched"] = (
        ((repo / "client/VERSION").read_text(encoding="utf-8").strip(),
         load("client/release/release-input.json").get("release_sequence"))
        in (("1.3.44", 1245), ("1.3.45", 1246), ("1.3.46", 1247))
    ) if (repo / "client/VERSION").is_file() else False
    checks["rollback_authority_disabled"] = (
        load("client/release/rollback-trust.json") == {
            "schema_version": 1, "enabled": False, "keys": [],
        }
    )
    guard = repo / "backend/service1/clientflow_pilot_1245.py"
    checks["two_separate_operator_flags_required"] = (
        guard.is_file()
        and 'os.environ.get(PILOT_FLAG) != str(PILOT_CLIENT_ID)' in guard.read_text(encoding="utf-8")
        and 'if approval.get("approved") is not True' in guard.read_text(encoding="utf-8")
        and 'os.environ.get(PILOT_ARM_FLAG) != PILOT_ARM_REFERENCE' in guard.read_text(encoding="utf-8")
    )
    return {
        "stage": "R2_one_stable_catalog_active_but_environment_disarmed",
        "ready": all(checks.values()),
        "pilot_authorized": False,
        "catalog_promoted": True,
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
