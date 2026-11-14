#!/usr/bin/env python3
"""Read-only source-stage gate for 1245 pilot and stable-default policy.

A successful result is NOT a release approval or permission to deploy.
"""
from __future__ import annotations

import argparse
import json
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

    cat = load("backend/service1/clientflow_release_catalog.json")
    releases = cat.get("releases") or []
    lock = load("backend/service1/clientflow_pilot_1245_approval.json")
    source = load("client/release/release-input.json")
    checks["pinned_source_identity"] = (
        read("client/VERSION").strip() == "1.3.44"
        and source.get("release_sequence") == 1245
    )
    checks["unpromoted_1244_catalog"] = (
        cat.get("catalog_sequence") == 1244
        and cat.get("latest_stable") == cat.get("default_install_version") == "1.3.43"
        and isinstance(releases, list)
        and len(releases) == 1
        and isinstance(releases[0], dict)
        and releases[0].get("release_id") == "clientflow-1.3.43-seq-1244"
        and releases[0].get("status") == "stable"
        and releases[0].get("install_modes") == ["fresh_install"]
        and releases[0].get("update_allowed") is False
    )
    checks["no_1245_deployment_while_unapproved"] = (
        lock.get("schema_version") == 1
        and lock.get("approved") is False
        and lock.get("approved_bundle_sha256") is None
        and lock.get("approved_bundle_size") is None
        and lock.get("approval_reference") is None
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
    checks["source_gate_still_requires_no_release_promotion"] = (
        "explicit_no_1245_catalog_promotion" in read("scripts/clientflow_1245_source_preflight.py")
    )
    checks["deployment_rechecks_artifact_after_lock"] = all(
        token in read("backend/service1/routers/clientflow_deployments.py")
        for token in (
            "lock_system_client(session, int(client.id))",
            "artifact=artifact", "require_pilot_1245", "require_stable_rollout",
        )
    )
    return {
        "phase": "source_only",
        "approved": False,
        "deployed": False,
        "stable_promoted": False,
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
