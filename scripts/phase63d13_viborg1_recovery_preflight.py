#!/usr/bin/env python3
"""63D-13: read-only, host-bound 1246->1247 recovery evidence.

This NEVER calls the updater, unlocks coordination, changes state or activates a
release. The backend's active deployment must be independently rechecked before
any later, separately reviewed physical recovery operation.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess

DEPLOYMENT_ID = "f99607f6-f1b7-43e5-a489-d756246e1849"
OLD = "clientflow-1.3.45-seq-1246"
NEW = "clientflow-1.3.46-seq-1247"
APPROVAL = "CF-1.3.46-1247-20261119-22a8a873-d60d63ba"
SHA = "3d6df5ec096a5713866943a67d9f88bba3fc6287458d0ea2f616bd41e42db150"
SOURCE = "22a8a873899fe736018e8238f4b2ec4bb896f6a2"
EXPECTED_HOSTNAME = "viborg1-NUC14MNK-B2"


def _safe_object(path: Path, *, private: bool = True) -> dict:
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_size > 1024 * 1024 or info.st_size <= 0
            or info.st_mode & (0o077 if private else 0o022)):
        raise ValueError(f"Untrusted journal: {path.name}")
    with path.open("rb") as handle:
        value = json.loads(handle.read(1024 * 1024 + 1))
    if not isinstance(value, dict):
        raise ValueError(f"Invalid journal: {path.name}")
    return value


def _service_status(unit: str) -> str:
    result = subprocess.run(
        ["systemctl", "is-active", unit], capture_output=True,
        text=True, timeout=10, check=False,
    )
    return result.stdout.strip()


def inspect(root: Path = Path("/"), *, check_services: bool = True) -> dict:
    # Test roots are only supplied by internal unit tests; the CLI always checks /.
    p = lambda suffix: root / suffix.lstrip("/")
    active = p("/opt/clientflow/active")
    if not active.is_symlink():
        raise ValueError("Active release link missing")
    expected_old = p(f"/opt/clientflow/releases/{OLD}")
    active_ok = active.resolve() == expected_old.resolve() and expected_old.is_dir()

    coordinator = _safe_object(p("/var/lib/clientflow/install-coordinator/state.json"))
    controller = _safe_object(p("/var/lib/clientflow/update-controller/state.json"))
    release = _safe_object(p("/var/lib/clientflow/release/state.json"))
    display = _safe_object(p("/var/lib/clientflow/release-status/state.json"), private=False)
    stage_root = p(f"/opt/clientflow/releases/{NEW}")
    if stage_root.is_symlink() or not stage_root.is_dir():
        raise ValueError("Staged release directory missing/unsafe")
    manifest = _safe_object(stage_root / "release-manifest.json", private=False)

    owned = coordinator == {
        "schema_version": 1,
        "owner": "update_clientflow",
        "operation_id": DEPLOYMENT_ID,
    }
    controller_snapshot = controller.get("deployment") or {}
    ctrl_ok = bool(
        controller.get("phase") == "activation_authorized"
        and isinstance(controller_snapshot, dict)
        and controller_snapshot.get("deployment_id") == DEPLOYMENT_ID
        and controller_snapshot.get("target_release_id") == NEW
        and controller_snapshot.get("bundle_sha256") == SHA
        and controller_snapshot.get("release_approval_reference") == APPROVAL
    )
    installed = (release.get("installed") or {}).get(NEW) or {}
    txn_ok = bool(
        release.get("active_release_id") == OLD
        and release.get("staged_release_id") == NEW
        and release.get("activation_intent") is None
        and isinstance(installed, dict)
        and installed.get("bundle_sha256") == SHA
        and installed.get("release_approval_reference") == APPROVAL
        and installed.get("source_commit") == SOURCE
    )
    approval = manifest.get("release_approval") or {}
    origin = manifest.get("source") or {}
    manifest_ok = bool(
        manifest.get("release_id") == NEW
        and manifest.get("version") == "1.3.46"
        and manifest.get("release_sequence") == 1247
        and isinstance(approval, dict) and approval.get("reference") == APPROVAL
        and isinstance(origin, dict) and origin.get("commit") == SOURCE
    )
    display_ok = bool(
        display.get("deployment_id") == DEPLOYMENT_ID
        and display.get("target_release_id") == NEW
        and display.get("phase") == "activating"
    )
    host_ok = os.uname().nodename == EXPECTED_HOSTNAME if root == Path("/") else True
    results = {
        "mode": "read_only_no_recovery_authorization",
        "deployment_id": DEPLOYMENT_ID,
        "old_release_active": active_ok,
        "host_identity": host_ok,
        "coordinator_exact": owned,
        "controller_authorized": ctrl_ok,
        "transaction_staged_without_intent": txn_ok,
        "signed_stage_metadata_matches": manifest_ok,
        "display_status_matches": display_ok,
    }
    if check_services:
        services = {
            "updater_timer": _service_status("clientflow-updater.timer"),
            "updater_service": _service_status("clientflow-updater.service"),
            "update_controller": _service_status("clientflow-update-controller.service"),
            "status_agent": _service_status("clientflow-status-agent.service"),
        }
        results["services"] = services
        results["services_safely_paused"] = bool(
            services["updater_timer"] == "inactive"
            and services["updater_service"] == "inactive"
            and services["update_controller"] != "active"
            and services["status_agent"] == "active"
        )
    results["local_evidence_pass"] = all(
        value for key, value in results.items() if isinstance(value, bool)
    )
    results["backend_state_independently_verified"] = False
    results["recovery_approved"] = False
    results["recovery_performed"] = False
    return results


def main() -> int:
    if os.geteuid() != 0:
        raise SystemExit("Read-only recovery preflight requires root on Viborg1")
    try:
        result = inspect()
    except (OSError, ValueError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        print(f"READ_ONLY_PREFLIGHT=STOP ({type(exc).__name__})")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    print("READ_ONLY_PREFLIGHT=" + ("PASS" if result["local_evidence_pass"] else "STOP"))
    print("RECOVERY_ACTION=NONE")
    return 0 if result["local_evidence_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
