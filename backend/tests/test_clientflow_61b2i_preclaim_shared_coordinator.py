"""61B-2I preclaim apt/update mutual exclusion; deliberately no host mutation."""
from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client/release/lib"))
from clientflow_release import cli, install_coordinator as coordination  # noqa: E402
from clientflow_release.transaction import Layout  # noqa: E402

APPROVED_BUNDLE_SHA = "d" * 64
OTHER_BUNDLE_SHA = "e" * 64
FIRST_INSTALL = "00000000-0000-4000-8000-000000000abc"
SECOND_INSTALL = "00000000-0000-4000-8000-000000000def"


def test_new_preclaim_blocks_every_update_plane_until_verified_success(tmp_path):
    root = tmp_path / "var/lib/clientflow/install-coordinator"
    with coordination.preclaim_host_guard(expected_bundle_sha256=APPROVED_BUNDLE_SHA, root=root):
        lock = coordination.snapshot(root=root)
        assert lock["owner"] == "preclaim_host"
        assert lock["operation_id"] == coordination._preclaim_operation_id(APPROVED_BUNDLE_SHA)
        for owner in ("update_os", "update_firmware", "update_clientflow", "fresh_install"):
            with pytest.raises(coordination.InstallCoordinationError, match="another_installation"):
                coordination.claim(owner=owner, operation_id=SECOND_INSTALL, root=root)
        assert (root / "preclaim-run.lock").stat().st_mode & 0o777 == 0o600
        assert (root / "state.json").stat().st_mode & 0o777 == 0o600
    assert coordination.snapshot(root=root) is None
    assert cli._fresh_conflicts(Layout(tmp_path)) == []
    coordination.claim(owner="fresh_install", operation_id=FIRST_INSTALL, root=root)
    assert coordination.snapshot(root=root)["operation_id"] == FIRST_INSTALL


def test_preclaim_raises_on_simultaneous_same_source_before_host_work(tmp_path):
    root = tmp_path / "var/lib/clientflow/install-coordinator"
    ran = []
    with coordination.preclaim_host_guard(expected_bundle_sha256=APPROVED_BUNDLE_SHA, root=root):
        with pytest.raises(coordination.InstallCoordinationError, match="already_running"):
            with coordination.preclaim_host_guard(expected_bundle_sha256=APPROVED_BUNDLE_SHA, root=root):
                ran.append("apt upgrade")
        assert ran == []
        assert coordination.snapshot(root=root)["owner"] == "preclaim_host"
    assert coordination.snapshot(root=root) is None


def test_crashed_preclaim_remains_reserved_and_only_exact_bundle_can_recover(tmp_path):
    root = tmp_path / "locks"
    with pytest.raises(RuntimeError, match="apt_partial_failure"):
        with coordination.preclaim_host_guard(expected_bundle_sha256=APPROVED_BUNDLE_SHA, root=root):
            raise RuntimeError("apt_partial_failure")
    prior = coordination.snapshot(root=root)
    assert prior["owner"] == "preclaim_host"
    with pytest.raises(coordination.InstallCoordinationError, match="another_installation"):
        with coordination.preclaim_host_guard(expected_bundle_sha256=OTHER_BUNDLE_SHA, root=root):
            pytest.fail("untrusted source cannot resume")
    assert coordination.snapshot(root=root) == prior
    with coordination.preclaim_host_guard(expected_bundle_sha256=APPROVED_BUNDLE_SHA, root=root):
        assert coordination.snapshot(root=root) == prior
    assert coordination.snapshot(root=root) is None


def test_preclaim_interrupt_does_not_release_lock(tmp_path):
    root = tmp_path / "locks"
    with pytest.raises(KeyboardInterrupt):
        with coordination.preclaim_host_guard(expected_bundle_sha256=APPROVED_BUNDLE_SHA, root=root):
            raise KeyboardInterrupt
    assert coordination.snapshot(root=root)["owner"] == "preclaim_host"


def test_pending_fresh_install_preserves_its_original_claim_during_preclaim(tmp_path):
    root = tmp_path / "locks"
    coordination.claim(owner="fresh_install", operation_id=FIRST_INSTALL, root=root)
    with coordination.preclaim_host_guard(
        expected_bundle_sha256=APPROVED_BUNDLE_SHA, existing_install_id=FIRST_INSTALL, root=root
    ):
        assert coordination.snapshot(root=root)["operation_id"] == FIRST_INSTALL
        with pytest.raises(coordination.InstallCoordinationError, match="another_installation"):
            coordination.claim(owner="update_os", operation_id=SECOND_INSTALL, root=root)
    assert coordination.snapshot(root=root)["owner"] == "fresh_install"  # until healthy first activation


def test_resume_rejects_foreign_lock_and_wrong_install_id(tmp_path):
    root = tmp_path / "locks"
    coordination.claim(owner="fresh_install", operation_id=FIRST_INSTALL, root=root)
    with pytest.raises(coordination.InstallCoordinationError, match="another_installation"):
        with coordination.preclaim_host_guard(
            expected_bundle_sha256=APPROVED_BUNDLE_SHA, existing_install_id=SECOND_INSTALL, root=root
        ):
            pytest.fail("bad resume must not perform apt upgrade")
    assert coordination.snapshot(root=root)["operation_id"] == FIRST_INSTALL


def test_invalid_bundle_hash_or_install_id_has_no_filesystem_side_effect(tmp_path):
    root = tmp_path / "locks"
    for invalid in ("f" * 63, "F" * 64, "../outside", "z" * 64, ""):
        with pytest.raises(coordination.InstallCoordinationError, match="exact_bundle_sha256"):
            with coordination.preclaim_host_guard(expected_bundle_sha256=invalid, root=root):
                pytest.fail("never run")
        assert not root.exists()
    with pytest.raises(coordination.InstallCoordinationError, match="invalid_binding"):
        with coordination.preclaim_host_guard(
            expected_bundle_sha256=APPROVED_BUNDLE_SHA, existing_install_id="not-an-uuid", root=root
        ):
            pytest.fail("never run")
    assert not root.exists()


def test_existing_os_lock_blocks_preclaim_without_replacement(tmp_path):
    root = tmp_path / "locks"
    coordination.claim(owner="update_os", operation_id=FIRST_INSTALL, root=root)
    with pytest.raises(coordination.InstallCoordinationError, match="another_installation"):
        with coordination.preclaim_host_guard(expected_bundle_sha256=APPROVED_BUNDLE_SHA, root=root):
            pytest.fail("apt must not start")
    assert coordination.snapshot(root=root) == {
        "schema_version": 1, "owner": "update_os", "operation_id": FIRST_INSTALL
    }


def test_corrupt_or_symlinked_preclaim_run_guard_fails_closed(tmp_path):
    root = tmp_path / "locks"
    root.mkdir(mode=0o700)
    guard = root / "preclaim-run.lock"
    guard.write_text("corrupt")
    guard.chmod(0o644)
    with pytest.raises(coordination.InstallCoordinationError, match="file_untrusted"):
        with coordination.preclaim_host_guard(expected_bundle_sha256=APPROVED_BUNDLE_SHA, root=root):
            pytest.fail("invalid lock")
    assert coordination.snapshot(root=root) is None
    guard.unlink()
    guard.symlink_to(tmp_path / "outside")
    with pytest.raises(OSError):
        with coordination.preclaim_host_guard(expected_bundle_sha256=APPROVED_BUNDLE_SHA, root=root):
            pytest.fail("symlink cannot win")
    assert coordination.snapshot(root=root) is None


def test_claimed_failed_preclaim_is_not_treated_as_clean_fresh_installer(tmp_path):
    root = tmp_path / "var/lib/clientflow/install-coordinator"
    with pytest.raises(RuntimeError):
        with coordination.preclaim_host_guard(expected_bundle_sha256=APPROVED_BUNDLE_SHA, root=root):
            raise RuntimeError("partial upgrade")
    assert "/var/lib/clientflow" in cli._fresh_conflicts(Layout(tmp_path))
    # An exact approved-bundle retry proves health and releases the reservation.
    with coordination.preclaim_host_guard(expected_bundle_sha256=APPROVED_BUNDLE_SHA, root=root):
        pass
    assert cli._fresh_conflicts(Layout(tmp_path)) == []


def test_preclaim_guard_present_before_apt_and_before_consuming_enrollment():
    src = (ROOT / "client/release/lib/clientflow_release/cli.py").read_text()
    start = src.index("def install_fresh(")
    end = src.index("def _common_transaction_parser", start)
    body = src[start:end]
    assert body.index("with install_coordinator.preclaim_host_guard(") < body.index("ensure_preclaim_host_readiness(")
    assert body.index("ensure_preclaim_host_readiness(") < body.index("_fresh_install_authorities(args)")
    assert body.index("_fresh_install_authorities(args)") < body.index("response = claim(")
    assert "existing_install_id=(str(install_state['install_id']) if not new_install else None)" in body
    assert "{'coordinate.lock', 'preclaim-run.lock'}" in src


def test_preclaim_schema_identical_in_host_and_runtime_and_readonly_release_gate():
    host = (ROOT / "client/release/lib/clientflow_release/install_coordinator.py").read_bytes()
    runtime = (ROOT / "client/runtime/clientflow_runtime/install_coordinator.py").read_bytes()
    assert host == runtime
    gate = (ROOT / "scripts/clientflow_61b2g_release_source_gate.py").read_text()
    assert "missing_preclaim_shared_install_lock_contract" in gate
    assert "LOCK_EX | fcntl.LOCK_NB" in host.decode()


def test_definite_4xx_clean_machine_check_rejects_untrusted_preclaim_execution_file(tmp_path):
    layout = Layout(tmp_path)
    root = cli._fresh_coordination_root(layout)
    with coordination.preclaim_host_guard(expected_bundle_sha256=APPROVED_BUNDLE_SHA, root=root):
        pass
    assert cli._fresh_conflicts(layout) == []
    guard = root / 'preclaim-run.lock'
    guard.chmod(0o644)
    assert '/var/lib/clientflow' in cli._fresh_conflicts(layout)
    guard.chmod(0o600)
    guard.unlink()
    guard.symlink_to(tmp_path / 'outside')
    assert '/var/lib/clientflow' in cli._fresh_conflicts(layout)


def test_existing_activation_is_readonly_rejected_before_apt_preclaim():
    src = (ROOT / 'client/release/lib/clientflow_release/cli.py').read_text()
    body = src[src.index('def install_fresh('):src.index('def _common_transaction_parser')]
    assert body.index('early_release_state = status(layout)') < body.index('with install_coordinator.preclaim_host_guard(')
    assert body.index('early_release_state = status(layout)') < body.index('install_coordinator.claim(')
