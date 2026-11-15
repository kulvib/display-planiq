#!/usr/bin/env python3
"""Read-only two-phase contract: guarded 1245 pilot, then ONE stable target.

Never writes the live release catalog, authorizes pilot, changes Render flags,
or grants fresh-install permission. Promotion is a separate code review AFTER
physical pilot and recovery acceptance. The same immutable R2 TAR is used for
both installation modes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "backend/service1/"
RELEASE_ID = "clientflow-1.3.44-seq-1245"
SHA256 = "28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5"
SIZE = 223610880
SOURCE = "06857104952ebb40bf1394c423c01332d28f8d5e"
CANDIDATE = "ffe58332c8e3b263e00f299e363dc95ecb9ac7e0176fd51888be98fecad9bd97"
INSTALLER = "fc843b6b37772996ecbfa67ff08a0e6f372443bf7d6104ca28d616855bc5737a"
REFERENCE = "CF-1.3.44-1245-20261114-0685710-ffe58332-R2"


def inspect(repo: Path) -> dict:
    checks: dict[str, bool] = {}

    def read(path: str) -> str:
        try:
            return (repo / path).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return ""

    def load(path: str) -> dict:
        try:
            value = json.loads(read(path))
            return value if isinstance(value, dict) else {}
        except ValueError:
            return {}

    active = load(BASE + "clientflow_release_catalog.json")
    stage = load(BASE + "clientflow_release_catalog_1245_stable.stage.json")
    lock = load(BASE + "clientflow_pilot_1245_approval.json")
    runtime = load("client/release/release-input.json")
    rows = active.get("releases") or []
    future = stage.get("releases") or []
    stable = future[0] if len(future) == 1 else {}
    notes = " ".join(stable.get("notes") or []) if isinstance(stable, dict) else ""

    checks["unchanged_approved_client_source"] = (
        read("client/VERSION").strip() == "1.3.44"
        and runtime.get("release_sequence") == 1245
    )
    checks["active_one_stable_1245"] = (
        active.get("catalog_sequence") == 1245
        and active.get("latest_stable") == active.get("default_install_version") == "1.3.44"
        and len(rows) == 1
        and rows[0].get("release_id") == RELEASE_ID
        and rows[0].get("status") == "stable"
        and rows[0].get("install_modes") == ["fresh_install", "in_place_update"]
        and rows[0].get("installable") is True
        and rows[0].get("update_allowed") is True
    )
    checks["stage_matches_active_release_policy"] = (
        stage.get("catalog_sequence") == 1245
        and stage.get("latest_stable") == stage.get("default_install_version") == "1.3.44"
        and len(rows) == len(future) == 1
        and {k: v for k, v in rows[0].items() if k != "notes"}
            == {k: v for k, v in future[0].items() if k != "notes"}
    )
    checks["one_common_stable_release_for_both_paths"] = (
        len(future) == 1
        and stable.get("version") == "1.3.44"
        and stable.get("client_version") == "1.3.44"
        and stable.get("release_id") == RELEASE_ID
        and stable.get("revision") == RELEASE_ID
        and stable.get("release_sequence") == 1245
        and stable.get("status") == "stable"
        and stable.get("installable") is True
        and stable.get("update_allowed") is True
        and stable.get("install_modes") == ["fresh_install", "in_place_update"]
        and stable.get("min_current_version") == "1.3.43"
        and stable.get("max_current_version") == "1.3.43"
    )
    checks["no_rollback_or_downgrade"] = (
        all(
            row.get("rollback_allowed") is False
            and row.get("requires_explicit_downgrade") is False
            for row in rows + future
        )
    )
    checks["one_installable_target_in_both_catalogs"] = all(
        sum(row.get("installable") is True for row in records) == 1
        for records in (rows, future)
    )
    checks["same_approved_r2_bytes_in_record"] = (
        lock.get("schema_version") == 1
        and lock.get("approved") is True
        and lock.get("release_id") == RELEASE_ID
        and lock.get("source_commit") == SOURCE
        and lock.get("candidate_sha256") == CANDIDATE
        and lock.get("installer_sha256") == INSTALLER
        and lock.get("approved_bundle_sha256") == SHA256
        and lock.get("approved_bundle_size") == SIZE
        and lock.get("approval_reference") == REFERENCE
    )
    checks["stable_template_same_approved_binary"] = all(
        value in notes for value in (SHA256, str(SIZE), SOURCE, CANDIDATE, INSTALLER, REFERENCE)
    )
    checks["separate_pilot_and_stable_operator_gates"] = all(
        key in read(BASE + "clientflow_pilot_1245.py")
        for key in ("CLIENTFLOW_1245_PILOT_CLIENT_ID", "CLIENTFLOW_1245_PILOT_ARM_REFERENCE")
    ) and all(
        key in read(BASE + "clientflow_stable_rollout.py")
        for key in ("CLIENTFLOW_STABLE_ROLLOUT_ENABLED", "CLIENTFLOW_STABLE_ROLLOUT_CLIENT_IDS",
                    "CLIENTFLOW_STABLE_ROLLOUT_BUNDLE_SHA256", "os.environ.get(ENABLED_FLAG) != \"1\"")
    )
    checks["fresh_install_separate_maintenance_hold"] = (
        "CLIENTFLOW_FRESH_INSTALL_SUSPENDED" in read(BASE + "clientflow_fresh_install_maintenance.py")
    )
    checks["rollback_trust_disabled"] = load("client/release/rollback-trust.json") == {
        "schema_version": 1, "enabled": False, "keys": []
    }
    fleet = load(BASE + "clientflow_1245_fleet_acceptance.json")
    checks["fleet_remains_unaccepted_pending_physical_pilot"] = (
        fleet == {
            "schema_version": 1, "release_id": RELEASE_ID,
            "physical_pilot_accepted": False,
            "approved_bundle_sha256": SHA256,
            "approval_reference": REFERENCE,
            "source_commit": SOURCE,
        }
        and "FLEET_ACCEPTANCE_PATH" in read(BASE + "clientflow_stable_rollout.py")
    )
    checks["stage_does_not_modify_client_or_installer"] = (
        stable.get("artifact_type") == "runtime_release"
        and stable.get("ubuntu_compatibility", {}).get("minimum_lts_version") == "26.04"
        and stable.get("requires_reboot") is True
    )
    return {
        "phase": "1245_one_stable_catalog_pilot_rollout_separately_gated",
        "ready": all(checks.values()),
        "pilot_enabled_by_this_preflight": False,
        "stable_promotion_applied": True,
        "fresh_install_hold_changed": False,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    args = parser.parse_args()
    result = inspect(args.repo_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("CLIENTFLOW_1245_UNIFIED_VERSION_PREFLIGHT=" + ("PASS" if result["ready"] else "FAIL"))
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
