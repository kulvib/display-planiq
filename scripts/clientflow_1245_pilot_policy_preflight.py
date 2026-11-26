#!/usr/bin/env python3
"""Read-only 1245 pilot catalog gate; runtime operator switches remain separate.

A successful result is NOT a release approval or permission to deploy.
"""
from __future__ import annotations

import argparse
import json

from clientflow_63d6_active_catalog_contract import (
    ActiveCatalogDenied, projected_stable_1245, verified_mode,
)
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_RELEASE = "clientflow-1.3.44-seq-1245"
EXPECTED_SOURCE = "06857104952ebb40bf1394c423c01332d28f8d5e"
EXPECTED_CANDIDATE = "ffe58332c8e3b263e00f299e363dc95ecb9ac7e0176fd51888be98fecad9bd97"
EXPECTED_INSTALLER = "fc843b6b37772996ecbfa67ff08a0e6f372443bf7d6104ca28d616855bc5737a"


def inspect(repo: Path) -> dict:
    checks: dict[str, bool] = {}

    def read(relative: str) -> str:
        try:
            return (repo / relative).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return ""

    def load(relative: str) -> dict:
        try:
            record = json.loads(read(relative))
        except ValueError:
            return {}
        return record if isinstance(record, dict) else {}

    try:
        catalog_mode = verified_mode(repo)
        cat = projected_stable_1245(repo)
    except ActiveCatalogDenied:
        catalog_mode = None
        cat = {}

    releases = cat.get("releases") or []
    lock = load("backend/service1/clientflow_pilot_1245_approval.json")
    source = load("client/release/release-input.json")
    # The 1245 approval is immutable; a separate unsigned 1246 source may
    # coexist without becoming the selected catalog or inheriting approval.
    checks["pinned_source_identity"] = (
        (read("client/VERSION").strip(), source.get("release_sequence"))
        in (("1.3.44", 1245), ("1.3.45", 1246), ("1.3.46", 1247), ("1.3.47", 1248), ("1.3.48", 1249), ("1.4.0", 1250))
    )
    checks["one_stable_1245_catalog"] = (
        catalog_mode in ("stable_1245_only", "update_only_1246_pilot_catalog", "update_only_1247_pilot_catalog", "update_only_1248_pilot_catalog")
        and cat.get("catalog_sequence") == 1245
        and cat.get("latest_stable") == cat.get("default_install_version") == "1.3.44"
        and isinstance(releases, list) and len(releases) == 1
        and releases[0].get("release_id") == EXPECTED_RELEASE
        and releases[0].get("status") == "stable"
        and releases[0].get("install_modes") == ["fresh_install", "in_place_update"]
        and releases[0].get("installable") is True
        and releases[0].get("update_allowed") is True
        and releases[0].get("rollback_allowed") is False
        and releases[0].get("min_current_version") == releases[0].get("max_current_version") == "1.3.43"
    )
    checks["exact_approval_but_separate_pilot_flags"] = (
        lock.get("schema_version") == 1
        and lock.get("approved") is True
        and lock.get("approved_bundle_sha256") == "28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5"
        and lock.get("approved_bundle_size") == 223610880
        and lock.get("approval_reference") == "CF-1.3.44-1245-20261114-0685710-ffe58332-R2"
    )
    checks["exact_candidate_and_source_locked"] = (
        lock.get("release_id") == EXPECTED_RELEASE
        and lock.get("source_commit") == EXPECTED_SOURCE
        and lock.get("candidate_sha256") == EXPECTED_CANDIDATE
        and lock.get("installer_sha256") == EXPECTED_INSTALLER
    )
    checks["old_rollback_trust_disabled"] = load("client/release/rollback-trust.json") == {
        "schema_version": 1, "enabled": False, "keys": [],
    }
    checks["all_three_old_pilot_flags_rejected"] = all(
        flag in read("backend/service1/clientflow_pilot_1245.py")
        for flag in (
            "CLIENTFLOW_1241_PILOT_CLIENT_ID", "CLIENTFLOW_1242_PILOT_CLIENT_ID",
            "CLIENTFLOW_1243_PILOT_CLIENT_ID",
        )
    )
    checks["new_stable_rollout_default_off"] = all(
        token in read("backend/service1/clientflow_stable_rollout.py")
        for token in (
            'os.environ.get(ENABLED_FLAG) != "1"',
            'MAX_WAVE_CLIENTS = 25',
            'CLIENTFLOW_STABLE_ROLLOUT_BUNDLE_SHA256',
            'CLIENTFLOW_STABLE_ROLLOUT_CLIENT_IDS',
        )
    )
    checks["both_operator_flags_required"] = all(token in read("backend/service1/clientflow_pilot_1245.py") for token in (
        "CLIENTFLOW_1245_PILOT_CLIENT_ID", "CLIENTFLOW_1245_PILOT_ARM_REFERENCE",
        "os.environ.get(PILOT_ARM_FLAG) != PILOT_ARM_REFERENCE",
    ))
    checks["deployment_rechecks_artifact_after_lock"] = all(
        token in read("backend/service1/routers/clientflow_deployments.py")
        for token in (
            "lock_system_client(session, int(client.id))",
            "artifact=artifact", "require_pilot_1245", "require_stable_rollout",
        )
    )
    return {
        "phase": "one_stable_1245_catalog_operator_disarmed",
        "approved": True,
        "deployed": False,
        "stable_promoted": True,
        "ready": all(checks.values()),
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    args = parser.parse_args()
    result = inspect(args.repo_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
