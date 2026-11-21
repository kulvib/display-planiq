#!/usr/bin/env python3
"""63D-18: pin a *future* systemd-bound, single-use Viborg1/1248 controller.

No direct shell activation, no signed-file edit, no timer, no backend write
without an independently authorized deployment and the original controller's
DPoP-authenticated state machine. --check is strictly read-only. An actual
--execute is a DIFFERENT, independently approved physical operation.

Critical: the 1247 updater.service has OnSuccess=update-controller.service.
The reviewed, credential-preserving controller drop-in must be installed and
verified BEFORE a single manual start of the updater.service. Never enable its
periodic timer or start the unmodified controller.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import uuid

HOST = "viborg1-NUC14MNK-B2"
CLIENT_ID = 3
OLD = "clientflow-1.3.46-seq-1247"
NEW = "clientflow-1.3.47-seq-1248"
BUNDLE_SHA256 = "9ca8852ba29153f2ec40b58d18007c738a03f9569f14762486fc1953c59eb6ff"
BUNDLE_SIZE = 223692800
APPROVAL = "CF-1.3.47-1248-20261121-c0d5a092-f8240014"
SOURCE_COMMIT = "c0d5a092efe0c4e8638866ad98621481d6f5d0e8"
CANDIDATE_SHA256 = "f82400140eb49efecf697b099cb86c94cecfb3f29dfe069b4d96ecb3b611173b"
SHA256_FIXED_TRANSACTION = "459bf6d9821f87e461c6a73efae579606bf2b8acd26ad78b2b4339c1f006c4b8"
SIGNED_1247_FILES = {
    "transaction.py": "196b4e7b957e3de4aacc7978e95a87d62331ebf936d2c66e5ca6ef6cfeb24e5f",
    "update_controller.py": "af611f805a29a02b2e968b1fda2750a0a0bfa9a36736772f30ed3ff1f1da9edb",
    "updater_state.py": "a39a087d2001d800ba1fc76361c6a176e9e6ffeec7b6d0f491a7e29c0b5f1767",
    "updater_client.py": "6bd9cbe526e38dcf3ab6b9e13a43d5246eb90424e021a6bf8f6e24bd8ec686ce",
    "install_coordinator.py": "f236b9d9964c5c0fcf2b68ee8872a6af0cad8fcd14e2b78b6f00a9512955caeb",
}
RUN_DIRECTORY = Path("/var/lib/clientflow/63d18-1248")
ACTIVE_ROOT = Path("/opt/clientflow/releases") / OLD
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class Pilot1248Denied(RuntimeError):
    pass


def _canonical_uuid(value: str) -> str:
    try:
        canonical = str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise Pilot1248Denied("Invalid deployment UUID") from exc
    if canonical != value:
        raise Pilot1248Denied("Noncanonical deployment UUID")
    return canonical


def _read_trusted(path: Path, *, private: bool, expected_sha256: str | None = None,
                  max_bytes: int = 200_000) -> bytes:
    """No symlinks or TOCTOU through a second path-open; root-owned staging."""
    try:
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
                or before.st_size <= 0 or before.st_size > max_bytes
                or before.st_mode & (0o077 if private else 0o022)):
            raise Pilot1248Denied("Untrusted source file")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            after = os.fstat(descriptor)
            if (after.st_ino, after.st_dev, after.st_size) != (before.st_ino, before.st_dev, before.st_size):
                raise Pilot1248Denied("Source changed during verification")
            data = os.read(descriptor, max_bytes + 1)
        finally:
            os.close(descriptor)
        if len(data) != before.st_size:
            raise Pilot1248Denied("Incomplete source read")
        if expected_sha256 is not None and (
            _SHA.fullmatch(expected_sha256) is None
            or hashlib.sha256(data).hexdigest() != expected_sha256
        ):
            raise Pilot1248Denied("Source SHA256 does not match approval")
        return data
    except OSError as exc:
        raise Pilot1248Denied("Source file unavailable or unsafe") from exc


def _json(path: Path, *, private: bool) -> dict:
    try:
        obj = json.loads(_read_trusted(path, private=private, max_bytes=1_048_576))
    except (ValueError, UnicodeError, TypeError) as exc:
        raise Pilot1248Denied("Invalid trusted local journal") from exc
    if not isinstance(obj, dict):
        raise Pilot1248Denied("Unexpected local journal type")
    return obj


def _unit_state(unit: str, prop: str) -> str:
    p = subprocess.run(
        ["systemctl", "show", unit, "-p", prop, "--value", "--no-pager"],
        capture_output=True, text=True, timeout=10, check=False,
    )
    if p.returncode != 0:
        raise Pilot1248Denied("systemd status is unavailable")
    return p.stdout.strip()


def _service_checks(*, executing: bool) -> dict[str, bool]:
    return {
        "updater_timer_disabled": _unit_state("clientflow-updater.timer", "UnitFileState") == "disabled",
        "updater_timer_inactive": _unit_state("clientflow-updater.timer", "ActiveState") == "inactive",
        "updater_service_inactive": _unit_state("clientflow-updater.service", "ActiveState") == "inactive",
        "controller_safe_state": _unit_state("clientflow-update-controller.service", "ActiveState") == (
            "activating" if executing else "inactive"
        ),
        "status_agent_active": _unit_state("clientflow-status-agent.service", "ActiveState") == "active",
    }


def read_only_preflight(*, root: Path = Path("/"), run_directory: Path = RUN_DIRECTORY,
                        verify_services: bool = True, executing: bool = False) -> dict:
    """Read-only host and immutable source checks; not a deployment grant."""
    if os.geteuid() != 0:
        raise Pilot1248Denied("The host-bound gate requires root")
    if root == Path("/") and os.uname().nodename != HOST:
        raise Pilot1248Denied("Unexpected physical host")
    path = lambda suffix: root / suffix.lstrip("/")
    old = path(f"/opt/clientflow/releases/{OLD}")
    lib = old / "release/lib/clientflow_release"
    stage = run_directory if root == Path("/") else path("/var/lib/clientflow/63d18-1248")
    if not stage.is_dir() or stage.is_symlink():
        raise Pilot1248Denied("Private run directory missing")
    info = stage.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise Pilot1248Denied("Unsafe run directory")
    runner = stage / "phase63d18_viborg1_1248_one_shot.py"
    if root == Path("/") and Path(__file__).absolute() != runner:
        raise Pilot1248Denied("One-shot must run from the exact root-owned staging path")
    _read_trusted(runner, private=True)
    _read_trusted(stage / "transaction.py", private=True, expected_sha256=SHA256_FIXED_TRANSACTION)
    for name, digest in SIGNED_1247_FILES.items():
        _read_trusted(lib / name, private=False, expected_sha256=digest)
    identity = _json(path("/etc/clientflow/identity.json"), private=False)
    local = _json(path("/var/lib/clientflow/release/state.json"), private=True)
    controller_path = path("/var/lib/clientflow/update-controller/state.json")
    controller = _json(controller_path, private=True) if controller_path.exists() else {"phase": "idle", "deployment": None}
    coordinator_path = path("/var/lib/clientflow/install-coordinator/state.json")
    # A successful 1247 deployment must have relinquished its durable lock.
    # Any unresolved owner is a STOP, not a reason to remove the journal.
    coordinator = _json(coordinator_path, private=True) if coordinator_path.exists() else None
    installed = (local.get("installed") or {}).get(OLD)
    if not isinstance(installed, dict):
        raise Pilot1248Denied("Missing installed 1247 record")
    old_controller_deployment = controller.get("deployment")
    old_controller_ok = (
        controller.get("phase") == "idle" and old_controller_deployment is None
    ) or (
        controller.get("phase") == "activation_succeeded"
        and isinstance(old_controller_deployment, dict)
        and old_controller_deployment.get("target_release_id") == OLD
        and old_controller_deployment.get("bundle_sha256") == "3d6df5ec096a5713866943a67d9f88bba3fc6287458d0ea2f616bd41e42db150"
    )
    checks = {
        "client_id": type(identity.get("client_id")) is int and identity["client_id"] == CLIENT_ID,
        "active_source": path("/opt/clientflow/active").is_symlink()
        and old.is_dir()
        and path("/opt/clientflow/active").resolve() == old.resolve(),
        "journal_source": local.get("active_release_id") == OLD,
        "journal_bundle": installed.get("bundle_sha256") == "3d6df5ec096a5713866943a67d9f88bba3fc6287458d0ea2f616bd41e42db150",
        "no_activation_intent": local.get("activation_intent") is None,
        "no_other_coordinator": coordinator is None,
        "controller_clean_terminal": old_controller_ok,
    }
    if verify_services:
        checks.update(_service_checks(executing=executing))
    return {
        "mode": "read_only_source_bound_preflight",
        "expected_old_release": OLD, "approved_target_release": NEW,
        "checks": checks, "pass": all(checks.values()),
        "backend_authorized": False, "physical_activation_performed": False,
        "updater_timer_enabled": False,
    }


def _systemd_gate(env: dict[str, str], deployment_id: str) -> None:
    deployment_id = _canonical_uuid(deployment_id)
    if env.get("CLIENTFLOW_63D18_ONE_SHOT") != deployment_id:
        raise Pilot1248Denied("Exact operator one-shot grant absent")
    if not env.get("INVOCATION_ID") or not env.get("CREDENTIALS_DIRECTORY"):
        raise Pilot1248Denied("Only the systemd controller may execute")
    if env.get("CLIENTFLOW_UPDATE_SOURCE_STATE_DIR") != "/var/lib/clientflow/updater":
        raise Pilot1248Denied("Original updater source state is required")
    creds = Path(env["CREDENTIALS_DIRECTORY"])
    if not creds.is_dir() or creds.is_symlink():
        raise Pilot1248Denied("Untrusted credential directory")
    for name in ("update-credential.json", "update-private-key.pem"):
        if not (creds / name).is_file() or (creds / name).is_symlink():
            raise Pilot1248Denied("Original systemd credential is missing")


def _load_pinned_transaction(path: Path, installed_library: Path):
    """Same exception identity as original 1247 controller; no sealed edits."""
    if "clientflow_release.transaction" in sys.modules or "clientflow_release.update_controller" in sys.modules:
        raise Pilot1248Denied("Controller imported before approved fix")
    sys.path.insert(0, str(installed_library))
    importlib.import_module("clientflow_release")
    name = "clientflow_release.transaction"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise Pilot1248Denied("Fixed transaction cannot be imported")
    fixed = importlib.util.module_from_spec(spec)
    sys.modules[name] = fixed
    try:
        spec.loader.exec_module(fixed)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    controller = importlib.import_module("clientflow_release.update_controller")
    if controller.TransactionError is not fixed.TransactionError or controller.Layout is not fixed.Layout:
        raise Pilot1248Denied("Controller/transaction source identity mismatch")
    return fixed, controller


def _require_exact_snapshot(snapshot, deployment_id: str) -> None:
    expected = (
        deployment_id, NEW, "1.3.47", 1248, BUNDLE_SHA256,
        BUNDLE_SIZE, APPROVAL, CANDIDATE_SHA256, SOURCE_COMMIT,
    )
    actual = (
        snapshot.deployment_id, snapshot.target_release_id,
        snapshot.target_version, snapshot.target_release_sequence,
        snapshot.bundle_sha256, snapshot.bundle_size,
        snapshot.release_approval_reference, snapshot.release_candidate_sha256,
        snapshot.source_commit,
    )
    if actual != expected:
        raise Pilot1248Denied("Authenticated backend target differs from exact one-shot approval")


def _bind_exact_activation(fixed, deployment_id: str):
    def activated(release_id: str, *, expected_release_approval_reference: str, layout):
        if (release_id != NEW or expected_release_approval_reference != APPROVAL
                or layout.root != Path("/")):
            raise Pilot1248Denied("Unexpected activation target")
        return fixed.activate_release(
            release_id, expected_release_approval_reference=APPROVAL,
            layout=layout, expected_update_deployment_id=deployment_id,
        )
    return activated


def _run_exact_controller(fixed, controller, deployment_id: str):
    """Bound identity before *any* staging, activation or backend event."""
    from clientflow_release.updater_config import UpdaterConfig
    cfg = UpdaterConfig.from_environment()
    if cfg.client_id != CLIENT_ID or cfg.state_root not in {
        Path("/var/lib/clientflow/updater"), Path("/var/lib/clientflow/update-controller")
    }:
        raise Pilot1248Denied("Updater credential/client identity mismatch")

    class ExactController(controller.UpdateController):
        def _bind_deployment(self, deployment, *, expected_snapshot=None, expected_deployment_id=None):
            snapshot = super()._bind_deployment(
                deployment, expected_snapshot=expected_snapshot,
                expected_deployment_id=expected_deployment_id,
            )
            _require_exact_snapshot(snapshot, deployment_id)
            return snapshot

    original = ExactController(
        cfg, source_state_root=Path("/var/lib/clientflow/updater"),
        controller_state_root=Path("/var/lib/clientflow/update-controller"),
        activate_func=_bind_exact_activation(fixed, deployment_id),
    )
    result = original.run_once()
    if (result.get("deployment_id") != deployment_id
            or result.get("release_id") != NEW
            or result.get("status") not in {"succeeded", "rolled_back", "recovery_failed"}):
        raise Pilot1248Denied("One-shot ended without unambiguous terminal result")
    return result


def run(*, execute: bool = False, deployment_id: str | None = None):
    if execute:
        if deployment_id is None:
            raise Pilot1248Denied("Exact deployment ID missing")
        deployment_id = _canonical_uuid(deployment_id)
        _systemd_gate(os.environ, deployment_id)
    outcome = read_only_preflight(executing=execute)
    if not outcome["pass"]:
        raise Pilot1248Denied("Local signed-source or controller preflight failed")
    if not execute:
        return outcome
    # Only the existing original updater's successful verified handoff can
    # advance backend 'verified' to 'staged'; this wrapper does NOT download or
    # generate update credentials or synthesize any authorization.
    fixed, controller = _load_pinned_transaction(
        RUN_DIRECTORY / "transaction.py", ACTIVE_ROOT / "release/lib"
    )
    return _run_exact_controller(fixed, controller, deployment_id)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--execute", action="store_true")
    parser.add_argument("--deployment-id")
    args = parser.parse_args()
    try:
        if args.check and args.deployment_id:
            raise Pilot1248Denied("Read-only check must not bind an operator authorization")
        result = run(execute=args.execute, deployment_id=args.deployment_id)
    except Exception as exc:
        # No raw tokens, backend snapshots or systemd credentials in logs.
        print("PHASE_63D18=STOP (" + type(exc).__name__ + ")", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    if args.execute:
        # Only the verified backend-local succeeded transition is a candidate
        # for *later* human physical acceptance. Rollback/recovery are STOP.
        if result.get("status") != "succeeded":
            print("PHASE_63D18=STOP_REQUIRES_PHYSICAL_RECOVERY_REVIEW")
            return 2
        print("PHASE_63D18=BACKEND_SUCCESS_PENDING_PHYSICAL_ACCEPTANCE")
    else:
        print("PHASE_63D18=CHECK_ONLY_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
