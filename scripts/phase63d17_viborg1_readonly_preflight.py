#!/usr/bin/env python3
"""63D-17 read-only physical Viborg1 readiness evidence for a future 1248 pilot.

Never stages bytes, invokes the update controller, writes journals, changes
systemd, authorizes backend deployments, or enables the updater timer.
Activation remains separately approved after exact 1247-controller code review.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

CLIENT_ID = 3
HOST = "viborg1-NUC14MNK-B2"
CURRENT_RELEASE = "clientflow-1.3.46-seq-1247"
EXPECTED_SHA = "3d6df5ec096a5713866943a67d9f88bba3fc6287458d0ea2f616bd41e42db150"
TARGET = "clientflow-1.3.47-seq-1248"
TARGET_SIZE = 223692800
RESERVE = 128 * 1024 * 1024


def _systemd_status(unit: str, action: str) -> str:
    result = subprocess.run(
        ["systemctl", action, unit], capture_output=True, text=True,
        timeout=10, check=False,
    )
    return result.stdout.strip() if result.returncode in (0, 1, 3) else "unknown"


def _bounded_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 1024 * 1024:
        raise ValueError("Untrusted local evidence path")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Unexpected evidence structure")
    return data


def inspect(*, root: Path = Path("/"), services: dict | None = None, hostname: str | None = None) -> dict:
    """Read only; dry-run test roots are for unit tests, never execution."""
    local = lambda suffix: root / suffix.lstrip("/")
    active = local("/opt/clientflow/active")
    expected = local("/opt/clientflow/releases") / CURRENT_RELEASE
    identity = _bounded_json(local("/etc/clientflow/identity.json"))
    installed = _bounded_json(local("/var/lib/clientflow/release/state.json"))
    installed_release = (installed.get("installed") or {}).get(CURRENT_RELEASE) or {}
    if not isinstance(installed_release, dict):
        raise ValueError("Installed record is not a dictionary")
    states = services if services is not None else {
        "updater_active": _systemd_status("clientflow-updater.timer", "is-active"),
        "updater_enabled": _systemd_status("clientflow-updater.timer", "is-enabled"),
        "controller_active": _systemd_status("clientflow-update-controller.service", "is-active"),
        "status_active": _systemd_status("clientflow-status-agent.service", "is-active"),
    }
    vfs = os.statvfs(local("/opt/clientflow"))
    free_bytes = vfs.f_bavail * vfs.f_frsize
    observed_id = identity.get("client_id", identity.get("CLIENT_ID"))
    checks = {
        "host_exact": (hostname if hostname is not None else os.uname().nodename) == HOST,
        "identity_exact": type(observed_id) is int and observed_id == CLIENT_ID,
        "active_symlink_exact": active.is_symlink() and expected.is_dir()
        and active.resolve() == expected.resolve(),
        "release_journal_exact": installed.get("active_release_id") == CURRENT_RELEASE,
        "signed_1247_installed": installed_release.get("bundle_sha256") == EXPECTED_SHA,
        "updater_disabled": states.get("updater_enabled") == "disabled",
        "updater_inactive": states.get("updater_active") == "inactive",
        "controller_inactive": states.get("controller_active") == "inactive",
        "status_agent_active": states.get("status_active") == "active",
        "disk_sufficient": free_bytes >= TARGET_SIZE + RESERVE,
    }
    return {
        "mode": "read_only_no_deployment_grant",
        "target_release_id": TARGET,
        "client_id": CLIENT_ID,
        "checks": checks,
        "local_preflight_pass": all(checks.values()),
        "backend_deployment_independently_verified": False,
        "one_shot_controller_authorized": False,
        "physical_acceptance": False,
        "deployment_performed": False,
    }


def main() -> int:
    if os.geteuid() != 0:
        print("PHASE_63D17_LOCAL_PREFLIGHT=STOP (root_required)")
        return 2
    try:
        outcome = inspect()
    except (OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired):
        print("PHASE_63D17_LOCAL_PREFLIGHT=STOP (unverified_evidence)")
        return 2
    print(json.dumps(outcome, ensure_ascii=False, sort_keys=True, indent=2))
    print("PHASE_63D17_LOCAL_PREFLIGHT=" + ("PASS" if outcome["local_preflight_pass"] else "STOP"))
    print("CLIENTFLOW_1248_INSTALLATION=NOT_AUTHORIZED")
    return 0 if outcome["local_preflight_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
