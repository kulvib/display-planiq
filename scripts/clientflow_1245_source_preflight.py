#!/usr/bin/env python3
"""Read-only historical-source and active pilot-catalog guard for ClientFlow 1.3.44/1245.

This guard does not build, authorize a deployment, or install a release.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_INPUT = {
    "schema_version": 1,
    "release_sequence": 1245,
    "minimum_ubuntu_lts": "26.04",
    "architecture": "amd64",
    "runtime_python": "3.13.14",
}
PINNED_1244_SHA256 = "d3fdae8fb2a93f74431780f4aadde21625d10917e99cfbe6095ff2394e1e856b"


def inspect_source(repo: Path) -> dict:
    checks: list[dict] = []

    def check(name: str, passed: bool) -> None:
        checks.append({"check": name, "passed": bool(passed)})

    def read(path: str) -> str:
        try:
            return (repo / path).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return ""

    def policy_bytes_without_pilot_prose(catalog: dict) -> dict:
        """Compare full catalog and historic 1244 notes; newest pilot prose may evolve."""
        if not isinstance(catalog, dict):
            return {}
        copy = dict(catalog)
        rows = copy.get("releases")
        if not isinstance(rows, list) or len(rows) != 1 or not all(isinstance(x, dict) for x in rows):
            return copy
        cloned = [dict(row) for row in rows]
        cloned[0].pop("notes", None)
        copy["releases"] = cloned
        return copy

    def load(path: str) -> dict:
        try:
            value = json.loads(read(path))
            return value if isinstance(value, dict) else {}
        except ValueError:
            return {}

    check("exact_1245_source_identity", read("client/VERSION").strip() == "1.3.44"
          and load("client/release/release-input.json") == EXPECTED_INPUT)
    catalog = load("scripts/tests/fixtures/clientflow_1244_pre_1245_pilot_catalog.json")
    releases = catalog.get("releases")
    release = releases[0] if isinstance(releases, list) and len(releases) == 1 and isinstance(releases[0], dict) else {}
    notes = release.get("notes")
    check("1244_sole_immutable_published_selector", catalog.get("catalog_sequence") == 1244
          and catalog.get("latest_stable") == "1.3.43"
          and catalog.get("default_install_version") == "1.3.43"
          and release.get("release_id") == "clientflow-1.3.43-seq-1244"
          and release.get("version") == "1.3.43"
          and release.get("release_sequence") == 1244
          and release.get("status") == "stable"
          and release.get("install_modes") == ["fresh_install"]
          and release.get("installable") is True
          and release.get("update_allowed") is False
          and release.get("rollback_allowed") is False
          and isinstance(notes, list)
          and PINNED_1244_SHA256 in " ".join(str(n) for n in notes))
    check("three_version_retention_not_escalated", catalog.get("retention_policy") == {
        "max_selectable_versions": 3,
        "max_installable_versions": 1,
        "keep_blocked_metadata": False,
    })
    active = load("backend/service1/clientflow_release_catalog.json")
    stable_stage = load("backend/service1/clientflow_release_catalog_1245_stable.stage.json")
    stage_rows = stable_stage.get("releases") or []
    active_rows = active.get("releases") or []
    # Preserve the historical frozen two-entry pilot design as evidence, but
    # require one common stable 1245 as the *current* selectable catalog.
    check("historical_1244_immutable_and_current_1245_stable",
          not any(isinstance(item, dict) and item.get("release_sequence") == 1245
                  for item in (releases if isinstance(releases, list) else []))
          and active.get("catalog_sequence") == stable_stage.get("catalog_sequence") == 1245
          and active.get("latest_stable") == active.get("default_install_version") == "1.3.44"
          and len(active_rows) == len(stage_rows) == 1
          and isinstance(active_rows[0], dict)
          and policy_bytes_without_pilot_prose(active) == policy_bytes_without_pilot_prose(stable_stage)
          and active_rows[0].get("status") == "stable"
          and active_rows[0].get("install_modes") == ["fresh_install", "in_place_update"]
          and all(proof in " ".join(str(n) for n in active_rows[0].get("notes", []))
                  for proof in (
                      "28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5",
                      "CF-1.3.44-1245-20261114-0685710-ffe58332-R2",
                  )))
    check("manual_rollback_trust_disabled", load("client/release/rollback-trust.json") == {
        "schema_version": 1, "enabled": False, "keys": [],
    })
    check("central_security_policy_unchanged", load("backend/service1/clientflow_release_security_policy.json") == {
        "schema_version": 1,
        "revision": 1,
        "minimum_safe_release_sequence": 1239,
        "revoked_release_ids": [],
    })
    runtime = load("client/release/runtime-platform-inputs.lock.json")
    artifacts = runtime.get("artifacts") or []
    check("runtime_locked_and_patched", runtime.get("runtime_python") == "3.13.14"
          and runtime.get("architecture") == "amd64"
          and any(isinstance(a, dict) and a.get("file") == "pyjwt-2.15.1-py3-none-any.whl"
                  for a in artifacts))
    workflow = read(".github/workflows/release-build.yml")
    approval = read(".github/workflows/release-approve.yml")
    check("reproducible_keyless_approval_unchanged", all(token in workflow for token in (
        "expected_source_sha", "replica: [a, b]", "verify_github_ci_run.py",
        "Ubuntu 26.04 executable candidate gate",
    )) and all(token in approval for token in (
        "expected_candidate_sha256", "expected_installer_sha256", "approve_release",
    )))
    check("historical_1244_preflight_retained", all(read(path) for path in (
        "scripts/clientflow_1244_source_preflight.py",
        "scripts/tests/test_clientflow_1244_source_stage.py",
        "scripts/tests/fixtures/clientflow_1243_pre_reset_catalog.json",
    )))
    return {
        "target": "clientflow-1.3.44-seq-1245",
        "stage": "source_approved_single_stable_catalog_ready",
        "source_stage_ready": all(item["passed"] for item in checks),
        "approved": True,
        "published": True,
        "catalog_promoted": True,
        "install_authorized": False,
        "in_place_update_authorized": False,
        "physical_pilot_complete": False,
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
