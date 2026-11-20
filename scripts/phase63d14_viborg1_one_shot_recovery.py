#!/usr/bin/env python3
"""63D-14: exact one-shot 1247 recovery, never mutates signed 1246/1247 files.

A DIFFERENT script (63D-13) audits the local evidence. This guarded runner
loads exactly the reviewed 63D-13 fixed transaction source outside the sealed
release, but runs the installed 1246 update controller's ORIGINAL backend-
authenticated deployment and rollback machinery. The only injected behavior
passes the exact 1247 deployment UUID to the corrected transaction.

Do not use from an interactive terminal to execute activation: systemd owns the
operation across the ClientFlow runtime quiesce. Run only from the existing
clientflow-update-controller.service with an operator-reviewed, temporary
runtime-only ExecStart override, with original systemd LoadCredential/sandbox.
Default CLI --check is read-only. --execute requires independent explicit
operator authorization and systemd credentials. No auto retries or unlocks.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys

DEPLOYMENT_ID = "f99607f6-f1b7-43e5-a489-d756246e1849"
OLD = "clientflow-1.3.45-seq-1246"
NEW = "clientflow-1.3.46-seq-1247"
APPROVAL = "CF-1.3.46-1247-20261119-22a8a873-d60d63ba"
SHA256_OLD_TRANSACTION = "196b4e7b957e3de4aacc7978e95a87d62331ebf936d2c66e5ca6ef6cfeb24e5f"
SHA256_OLD_CONTROLLER = "af611f805a29a02b2e968b1fda2750a0a0bfa9a36736772f30ed3ff1f1da9edb"
SHA256_FIXED_TRANSACTION = "459bf6d9821f87e461c6a73efae579606bf2b8acd26ad78b2b4339c1f006c4b8"
SHA256_63D13_PREFLIGHT = "a30265c533500104a845bae18d18585a260947bd3c300ba30f20d1982a5e6c3d"
RUN_DIRECTORY = Path("/var/lib/clientflow/63d14-recovery")
ACTIVE_ROOT = Path("/opt/clientflow/releases") / OLD


class RecoveryDenied(RuntimeError):
    pass


def _secure_source(path: Path, expected_sha: str | None, *, private: bool) -> None:
    """Root-owned ordinary bytes only; never follow symlinks or oversized files."""
    try:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_size <= 0 or info.st_size > 200_000
                or info.st_mode & (0o077 if private else 0o022)):
            raise RecoveryDenied("Untrusted recovery source")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            actual = os.fstat(descriptor)
            if (actual.st_ino != info.st_ino or actual.st_dev != info.st_dev
                    or actual.st_size != info.st_size):
                raise RecoveryDenied("Recovery source changed during open")
            data = os.read(descriptor, 200_001)
        finally:
            os.close(descriptor)
        if expected_sha is not None and hashlib.sha256(data).hexdigest() != expected_sha:
            raise RecoveryDenied("Recovery source hash mismatch")
    except (OSError, ValueError) as exc:
        raise RecoveryDenied("Recovery source unavailable or unsafe") from exc


def _assert_source_root(run_directory: Path) -> None:
    if run_directory != RUN_DIRECTORY or run_directory.is_symlink():
        raise RecoveryDenied("Recovery path must be the fixed root-owned directory")
    info = run_directory.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o077):
        raise RecoveryDenied("Recovery directory must be private and root-owned")


def _load_reviewed_preflight(path: Path):
    spec = importlib.util.spec_from_file_location("_phase63d14_local_read_only_evidence", path)
    if spec is None or spec.loader is None:
        raise RecoveryDenied("Read-only preflight cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _require_root() -> None:
    if os.geteuid() != 0:
        raise RecoveryDenied("Recovery requires root")


def preflight(*, run_directory: Path = RUN_DIRECTORY, check_services: bool = True) -> dict:
    _require_root()
    _assert_source_root(run_directory)
    runner = run_directory / "phase63d14_viborg1_one_shot_recovery.py"
    if Path(__file__).absolute() != runner:
        raise RecoveryDenied("Runner is not executing from the fixed staging path")
    _secure_source(runner, None, private=True)
    fixed = run_directory / "transaction.py"
    old = ACTIVE_ROOT / "release/lib/clientflow_release"
    _secure_source(fixed, SHA256_FIXED_TRANSACTION, private=True)
    _secure_source(run_directory / "phase63d13_viborg1_recovery_preflight.py", SHA256_63D13_PREFLIGHT, private=True)
    _secure_source(old / "transaction.py", SHA256_OLD_TRANSACTION, private=False)
    _secure_source(old / "update_controller.py", SHA256_OLD_CONTROLLER, private=False)
    source_preflight = _load_reviewed_preflight(run_directory / "phase63d13_viborg1_recovery_preflight.py")
    local = source_preflight.inspect(check_services=check_services)
    if local.get("deployment_id") != DEPLOYMENT_ID or local.get("local_evidence_pass") is not True:
        raise RecoveryDenied("Local 63D-13 preflight not green")
    return local


def _require_systemd_operator_gate(env: dict[str, str]) -> None:
    if env.get("CLIENTFLOW_63D14_ONE_SHOT") != DEPLOYMENT_ID:
        raise RecoveryDenied("Missing exact single-use operator authorization")
    if not env.get("INVOCATION_ID") or not env.get("CREDENTIALS_DIRECTORY"):
        raise RecoveryDenied("Recovery must be launched with systemd service credentials")
    credentials = Path(env["CREDENTIALS_DIRECTORY"])
    if not credentials.is_dir() or credentials.is_symlink():
        raise RecoveryDenied("No trusted systemd credential directory")
    if not (credentials / "update-credential.json").is_file() or not (credentials / "update-private-key.pem").is_file():
        raise RecoveryDenied("Required update credentials missing")
    if env.get("CLIENTFLOW_UPDATE_SOURCE_STATE_DIR") != "/var/lib/clientflow/updater":
        raise RecoveryDenied("Original updater source state not configured")


def load_fixed_transaction(fixed_path: Path, installed_library: Path):
    """Install reviewed transaction module before old controller is imported.

    This guarantees ONE TransactionError type, so the original controller's
    health/rollback/error reconciliation continues to work unchanged.
    """
    if "clientflow_release.transaction" in sys.modules or "clientflow_release.update_controller" in sys.modules:
        raise RecoveryDenied("Transaction/controller already imported before verified override")
    sys.path.insert(0, str(installed_library))
    importlib.import_module("clientflow_release")
    name = "clientflow_release.transaction"
    spec = importlib.util.spec_from_file_location(name, fixed_path)
    if spec is None or spec.loader is None:
        raise RecoveryDenied("Verified transaction source could not be loaded")
    transaction = importlib.util.module_from_spec(spec)
    sys.modules[name] = transaction
    try:
        spec.loader.exec_module(transaction)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    controller = importlib.import_module("clientflow_release.update_controller")
    if controller.TransactionError is not transaction.TransactionError:
        raise RecoveryDenied("Controller and reviewed transaction exception types differ")
    if controller.Layout is not transaction.Layout:
        raise RecoveryDenied("Controller and reviewed transaction layouts differ")
    return transaction, controller


def _bind_exact_activation(transaction):
    def execute_release(release_id: str, *, expected_release_approval_reference: str, layout):
        if (release_id != NEW or expected_release_approval_reference != APPROVAL
                or layout.root != Path("/")):
            raise RecoveryDenied("Controller requested a different activation")
        return transaction.activate_release(
            release_id,
            expected_release_approval_reference=expected_release_approval_reference,
            layout=layout,
            expected_update_deployment_id=DEPLOYMENT_ID,
        )
    return execute_release


def run(*, execute: bool = False) -> dict:
    local = preflight()
    if not execute:
        return {
            "mode": "read_only_63d14_preflight",
            "deployment_id": DEPLOYMENT_ID,
            "local_evidence_pass": local["local_evidence_pass"],
            "backend_state_independently_verified": False,
            "recovery_performed": False,
        }

    _require_systemd_operator_gate(os.environ)
    active_lib = ACTIVE_ROOT / "release/lib"
    fixed, controller_mod = load_fixed_transaction(RUN_DIRECTORY / "transaction.py", active_lib)
    from clientflow_release.updater_config import UpdaterConfig
    config = UpdaterConfig.from_environment()
    if config.client_id != 3 or config.state_root not in {
        Path("/var/lib/clientflow/updater"), Path("/var/lib/clientflow/update-controller")
    }:
        raise RecoveryDenied("Update credential client or state identity changed")
    original = controller_mod.UpdateController(
        config,
        source_state_root=Path("/var/lib/clientflow/updater"),
        controller_state_root=Path("/var/lib/clientflow/update-controller"),
        activate_func=_bind_exact_activation(fixed),
    )
    # The ORIGINAL 1246 controller obtains a fresh DPoP-authenticated backend
    # deployment and validates immutable identity before any activation.
    # It performs staging reconciliation, health, automatic rollback and audit
    # reporting through its normal real transaction machinery.
    outcome = original.run_once()
    if outcome.get("deployment_id") != DEPLOYMENT_ID or outcome.get("release_id") != NEW:
        raise RecoveryDenied("Unexpected controller reconciliation result")
    return outcome


def main() -> int:
    parser = argparse.ArgumentParser(description="Viborg1/1247 one-shot recovery, default read-only")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="read-only local check")
    group.add_argument("--execute", action="store_true", help="one explicit systemd-bound recovery")
    args = parser.parse_args()
    try:
        result = run(execute=args.execute)
    except Exception as exc:
        # Never print secrets, snapshots or raw exceptions. Keep local forensic
        # journals untouched and report only a stable error class.
        print(f"PHASE_63D14=STOP ({type(exc).__name__})", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    print("PHASE_63D14=" + ("EXECUTED" if args.execute else "CHECK_ONLY_PASS"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
