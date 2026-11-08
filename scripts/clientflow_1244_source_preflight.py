#!/usr/bin/env python3
"""Read-only 1.3.43/1244 source identity gate. NOT release authorization.

Do not edit the 1243 approved catalog, store, clients or production flags here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_INPUT = {
    "schema_version": 1,
    "release_sequence": 1244,
    "minimum_ubuntu_lts": "26.04",
    "architecture": "amd64",
    "runtime_python": "3.13.14",
}
OLD_CATALOG_RELEASES = [
    "clientflow-1.3.38-seq-1239",
    "clientflow-1.3.40-seq-1241",
    "clientflow-1.3.41-seq-1242",
    "clientflow-1.3.42-seq-1243",
]


def inspect_source(repo: Path) -> dict:
    """Validate exact staged source; all output intentionally contains no secrets."""
    checks = []

    def check(label: str, passed: bool) -> None:
        checks.append({"check": label, "passed": bool(passed)})

    def source(path: str) -> str:
        try:
            return (repo / path).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return ""

    def obj(path: str) -> dict:
        try:
            value = json.loads(source(path))
            return value if isinstance(value, dict) else {}
        except ValueError:
            return {}

    check("exact_new_source_version", source("client/VERSION").strip() == "1.3.43")
    check("exact_1244_platform_input", obj("client/release/release-input.json") == EXPECTED_INPUT)
    catalog = obj("backend/service1/clientflow_release_catalog.json")
    rows = catalog.get("releases") or []
    check("old_1243_catalog_unchanged_until_approved_publication", (
        catalog.get("catalog_sequence") == 1243
        and catalog.get("latest_stable") == "1.3.38"
        and catalog.get("default_install_version") == "1.3.38"
        and isinstance(rows, list)
        and [item.get("release_id") for item in rows if isinstance(item, dict)] == OLD_CATALOG_RELEASES
        and not any(isinstance(item, dict) and item.get("release_sequence") == 1244 for item in rows)
    ))
    check("manual_rollback_still_disabled", obj("client/release/rollback-trust.json") == {
        "schema_version": 1, "enabled": False, "keys": [],
    })
    catalog_code = source("backend/service1/clientflow_releases.py")
    check("new_policy_only_after_1244_catalog_promotion", all(token in catalog_code for token in (
        'if data["catalog_sequence"] >= 1244:',
        'policy.get("max_selectable_versions") != 3',
        'not 1 <= len(releases) <= 3',
        'sequences[-1] != data["catalog_sequence"]',
        'data.get("default_install_version") != newest.get("version")',
    )))
    system = source("client/systemd/clientflow-system-broker.service")
    platform = source("client/systemd/clientflow-platform-prepare.service")
    agent = source("client/systemd/clientflow-system-agent.service")
    check("apt_dracut_host_and_agent_isolation_retained", all(
        'ProtectKernelModules=no' in block
        and 'CapabilityBoundingSet=~CAP_SYS_MODULE' in block
        and 'SystemCallFilter=~@module' in block
        for block in (system, platform)
    ) and 'ProtectKernelModules=yes' in agent)
    release_build = source(".github/workflows/release-build.yml")
    release_approve = source(".github/workflows/release-approve.yml")
    check("exact_source_reproducible_build_and_approval_gates_preserved", all(token in release_build for token in (
        'expected_source_sha', 'replica: [a, b]', 'verify_github_ci_run.py',
        'Ubuntu 26.04 executable candidate gate',
    )) and all(token in release_approve for token in (
        'expected_candidate_sha256', 'expected_installer_sha256', 'approve_release',
    )))
    return {
        "target": "clientflow-1.3.43-seq-1244",
        "stage": "source_stage_only",
        "source_stage_ready": all(row["passed"] for row in checks),
        "published": False,
        "approved": False,
        "catalog_promoted": False,
        "install_authorized": False,
        "cleanup_authorized": False,
        "requires_physical_fresh_install": True,
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    result = inspect_source(args.repo_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["source_stage_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
