#!/usr/bin/env python3
"""Read-only 1.3.42/1243 catalog-pilot gate; NEVER a physical rollout.

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
    "clientflow-1.3.42-seq-1243",
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
        pilot = releases[-1] if isinstance(releases, list) and releases else {}
        catalog_ok = (
            catalog.get("catalog_sequence") == 1243
            and catalog.get("latest_stable") == "1.3.38"
            and catalog.get("default_install_version") == "1.3.38"
            and catalog.get("retention_policy") == {
                "max_installable_versions": 1,
                "keep_blocked_metadata": False,
            }
            and isinstance(releases, list)
            and tuple(row.get("release_id") for row in releases if isinstance(row, dict)) == PUBLISHED_IDS
            and len(releases) == 4
            and releases[0].get("install_modes") == ["fresh_install"]
            and releases[0].get("installable") is True
            and releases[0].get("update_allowed") is False
            and releases[0].get("rollback_allowed") is False
            and all(row.get("rollback_allowed") is False for row in releases)
            and all(row.get("installable") is False for row in releases[1:])
            and all(row.get("install_modes") == ["in_place_update"] for row in releases[1:])
            and pilot.get("version") == "1.3.42"
            and pilot.get("release_sequence") == 1243
            and pilot.get("status") == "supported"
            and pilot.get("installable") is False
            and pilot.get("update_allowed") is True
            and pilot.get("rollback_allowed") is False
            and pilot.get("requires_explicit_downgrade") is False
            and pilot.get("requires_reboot") is True
            and pilot.get("min_current_version") == "1.3.38"
            and pilot.get("max_current_version") == "1.3.38"
        )
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
        catalog_ok = False
    check("approved_catalog_exact_1243_pilot_only", catalog_ok)

    # The exact-byte 1243 guard is now prepared following explicit approval.
    # Catalog promotion is not live client authorization: disabled-by-default
    # exact guard still prevents any automatic or broader rollout.
    # Requiring the exact guard prevents a future
    # source refreeze from quietly substituting a generic client allowlist.
    try:
        router = read("backend/service1/routers/clientflow_deployments.py")
        pilot = read("backend/service1/clientflow_pilot_1243.py")
        bridge = read("scripts/clientflow_1338_controller_bridge.sh")
        probe = read("scripts/clientflow_controller_sandbox_probe.sh")
        controller = read("client/systemd/clientflow-update-controller.service")
        transaction = read("client/release/lib/clientflow_release/transaction.py")
        approve = read(".github/workflows/release-approve.yml")
        build = read(".github/workflows/release-build.yml")
    except (OSError, UnicodeError):
        router = pilot = bridge = probe = controller = transaction = approve = build = ""
    check(
        "exact_1243_guard_staged_for_disabled_pilot",
        router.count('if release.get("release_id") == "clientflow-1.3.42-seq-1243"') == 1
        and "def _require_exact_scoped_pilot(" in router
        and "require_pilot_1243(release=release, **kwargs)" in router
        and "raise ClientFlowPilot1242Denied" in router
        and 'PILOT_CLIENT_ID = 2' in pilot
        and 'PILOT_RELEASE_ID = "clientflow-1.3.42-seq-1243"' in pilot
        and 'PILOT_APPROVED_BUNDLE_SHA256 = "ee35cc6caa9304bbc7ee4b1c763ecdeaf03d9d58a6c73cee943805251d8d6914"' in pilot
        and 'if os.environ.get(PILOT_FLAG) != str(PILOT_CLIENT_ID):' in pilot
        and "if any(os.environ.get(flag) for flag in CONFLICTING_PILOT_FLAGS):" in pilot,
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
        "phase": "catalog_pilot_stage_only",
        "catalog_pilot_ready": ready,
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
