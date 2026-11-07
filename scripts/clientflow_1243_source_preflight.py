#!/usr/bin/env python3
"""Read-only 1.3.42/1243 source-stage check; NEVER an approval or rollout.

This gate examines only public source/approval metadata. It neither builds nor
publishes artifacts, reads signing secrets, changes backend policy, or touches a
ClientFlow device. Publication and one-client authority are separate gates.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_INPUT = {
    "schema_version": 1,
    "release_sequence": 1243,
    "minimum_ubuntu_lts": "26.04",
    "architecture": "amd64",
    "runtime_python": "3.13.14",
}
PUBLISHED_IDS = (
    "clientflow-1.3.38-seq-1239",
    "clientflow-1.3.40-seq-1241",
    "clientflow-1.3.41-seq-1242",
)


def inspect_source(repo: Path) -> dict:
    repo = repo.resolve()
    checks: list[dict[str, object]] = []

    def check(name: str, ok: bool) -> None:
        checks.append({"name": name, "passed": bool(ok)})

    def read(relative: str) -> str:
        return (repo / relative).read_text(encoding="utf-8")

    def parse(relative: str) -> dict:
        obj = json.loads(read(relative))
        if not isinstance(obj, dict):
            raise ValueError("expected JSON object")
        return obj

    try:
        version = read("client/VERSION").strip()
    except (OSError, UnicodeError):
        version = None
    check("exact_source_version", version == "1.3.42")

    try:
        identity = parse("client/release/release-input.json")
    except (OSError, UnicodeError, ValueError):
        identity = {}
    check("exact_source_sequence_and_platform", identity == EXPECTED_INPUT)

    try:
        catalog = parse("backend/service1/clientflow_release_catalog.json")
        releases = catalog.get("releases")
        catalog_ok = (
            catalog.get("catalog_sequence") == 1242
            and catalog.get("latest_stable") == "1.3.38"
            and catalog.get("default_install_version") == "1.3.38"
            and catalog.get("retention_policy") == {
                "max_installable_versions": 1,
                "keep_blocked_metadata": False,
            }
            and isinstance(releases, list)
            and tuple(row.get("release_id") for row in releases if isinstance(row, dict)) == PUBLISHED_IDS
            and len(releases) == 3
            and releases[0].get("install_modes") == ["fresh_install"]
            and releases[0].get("update_allowed") is False
            and releases[0].get("rollback_allowed") is False
            and all(row.get("release_sequence") != 1243 for row in releases)
        )
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
        catalog_ok = False
    check("published_catalog_unchanged_1243_not_authorized", catalog_ok)

    # This script cannot independently grant remote deployment authority: the
    # backend has no 1243 guard or artifact hash before exact-source approval.
    try:
        router = read("backend/service1/routers/clientflow_deployments.py")
        bridge = read("scripts/clientflow_1338_controller_bridge.sh")
        probe = read("scripts/clientflow_controller_sandbox_probe.sh")
        controller = read("client/systemd/clientflow-update-controller.service")
        transaction = read("client/release/lib/clientflow_release/transaction.py")
        approve = read(".github/workflows/release-approve.yml")
        build = read(".github/workflows/release-build.yml")
    except (OSError, UnicodeError):
        router = bridge = probe = controller = transaction = approve = build = ""
    check(
        "no_1243_remote_pilot_authority",
        'if release.get("release_id") == "clientflow-1.3.42-seq-1243"' not in router
        and "def _require_exact_scoped_pilot(" in router
        and "raise ClientFlowPilot1242Denied" in router,
    )
    check(
        "original_1338_bridge_and_sandbox_proof_retained",
        all(token in bridge for token in (
            "--confirm-clientflow-1338", "--confirm-backend-idle",
            "BRIDGE_IMMUTABLE_SOURCE_MATCH=PASS", "BRIDGE_PRECONDITIONS=PASS",
        ))
        and "CONTROLLER_KIOSK_ACL_DRY_RUN=PASS" in probe
        and "ProtectHome=tmpfs" in controller
        and "BindPaths=/home/clientflow-kiosk" in controller
        and "ProtectHome=yes" not in controller.splitlines(),
    )
    check(
        "durable_recovery_and_manual_approval_retained",
        "def recover_failed_update(" in transaction
        and "automatic_rollback_failed" in transaction
        and "automatic_rollback_completed" in transaction
        and "expected_candidate_sha256" in approve
        and "expected_installer_sha256" in approve
        and "approve_release" in approve
        and "replica: [a, b]" in build
        and "verify_github_ci_run.py" in build,
    )

    mode = "invalid"
    try:
        # Same public validator as the canonical release builder. Absolutely no
        # signer key is fetched, printed, loaded, created or inferred here.
        for directory in (ROOT / "backend", ROOT / "client/release/lib"):
            if str(directory) not in sys.path:
                sys.path.insert(0, str(directory))
        from clientflow_release.rollback_trust_build import validate_release_rollback_trust
        validate_release_rollback_trust(repo, 1243)
        trust = parse("client/release/rollback-trust.json")
        mode = "signed" if trust.get("enabled") is True else "disabled"
        trust_ok = trust == {"schema_version": 1, "enabled": False, "keys": []}
    except (ImportError, OSError, UnicodeError, ValueError, TypeError, KeyError):
        trust_ok = False
    check("explicit_keyless_manual_rollback_disabled", trust_ok)

    ready = all(bool(row["passed"]) for row in checks)
    return {
        "target": "clientflow-1.3.42-seq-1243",
        "phase": "source_stage_only",
        "source_stage_ready": ready,
        "publish_authorized": False,
        "activation_authorized": False,
        "pilot_enabled": False,
        "manual_rollback_mode": mode,
        "requires_physical_pilot": True,
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT, help="Repository root; read-only")
    args = parser.parse_args(argv)
    result = inspect_source(args.repo_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["source_stage_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
