"""63D-18 physical one-shot MUST be inert without exact external approval."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts import phase63d18_viborg1_1248_one_shot as runner

ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENT = "a35da2f0-ec43-4c61-a269-2da37ea6d8c9"


def fixture(root: Path, monkeypatch):
    run = root / "var/lib/clientflow/63d18-1248"
    run.mkdir(parents=True)
    run.chmod(0o700)
    files = root / "opt/clientflow/releases" / runner.OLD / "release/lib/clientflow_release"
    files.mkdir(parents=True)
    checksums = {}
    for filename in runner.SIGNED_1247_FILES:
        source = ROOT / "client/release/lib/clientflow_release" / filename
        raw = source.read_bytes()
        (files / filename).write_bytes(raw)
        (files / filename).chmod(0o644)
        checksums[filename] = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(runner, "SIGNED_1247_FILES", checksums)
    runner_copy = run / "phase63d18_viborg1_1248_one_shot.py"
    runner_copy.write_bytes(Path(runner.__file__).read_bytes())
    runner_copy.chmod(0o600)
    fixed = run / "transaction.py"
    fixed.write_bytes((ROOT / "client/release/lib/clientflow_release/transaction.py").read_bytes())
    fixed.chmod(0o600)
    (root / "etc/clientflow").mkdir(parents=True)
    identity = root / "etc/clientflow/identity.json"
    identity.write_text(json.dumps({"schema_version": 1, "client_id": 3}))
    identity.chmod(0o600)
    release = root / "var/lib/clientflow/release"
    release.mkdir(parents=True)
    journal = release / "state.json"
    journal.write_text(json.dumps({
        "active_release_id": runner.OLD,
        "activation_intent": None,
        "installed": {runner.OLD: {"bundle_sha256": "3d6df5ec096a5713866943a67d9f88bba3fc6287458d0ea2f616bd41e42db150"}},
    }))
    journal.chmod(0o600)
    link = root / "opt/clientflow/active"
    link.symlink_to(root / "opt/clientflow/releases" / runner.OLD)
    return run, files, journal


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    run, files, journal = fixture(tmp_path, monkeypatch)
    # These fixtures are stored in the sandbox under the current user. The
    # test-runner does not grant extra privilege; bypass only a simulated UID.
    monkeypatch.setattr(runner.os, "geteuid", lambda: run.stat().st_uid)
    return tmp_path, run, files, journal


def check(prepared):
    root, run, _, _ = prepared
    return runner.read_only_preflight(root=root, run_directory=run, verify_services=False)


def test_source_preflight_is_read_only_and_does_not_authorize(prepared):
    result = check(prepared)
    assert result["pass"] is True
    assert result["backend_authorized"] is False
    assert result["physical_activation_performed"] is False


def test_exact_controller_bundle_identity_is_verified(prepared):
    _, _, files, _ = prepared
    assert set(runner.SIGNED_1247_FILES) == {
        "transaction.py", "update_controller.py", "updater_state.py",
        "updater_client.py", "install_coordinator.py",
    }
    for name, expected in runner.SIGNED_1247_FILES.items():
        assert hashlib.sha256((files / name).read_bytes()).hexdigest() == expected


@pytest.mark.parametrize("filename", [
    "transaction.py", "update_controller.py", "updater_state.py",
    "updater_client.py", "install_coordinator.py",
])
def test_installed_source_mutation_denied(prepared, filename):
    _, _, files, _ = prepared
    (files / filename).write_text("tampered")
    with pytest.raises(runner.Pilot1248Denied, match="SHA256"):
        check(prepared)


def test_fixed_source_mutation_and_symlink_denied(prepared):
    _, run, _, _ = prepared
    p = run / "transaction.py"
    p.write_text("tampered")
    with pytest.raises(runner.Pilot1248Denied):
        check(prepared)
    p.unlink()
    p.symlink_to(run / "phase63d18_viborg1_1248_one_shot.py")
    with pytest.raises(runner.Pilot1248Denied):
        check(prepared)


def test_wrong_client_or_active_release_denied(prepared):
    root, _, _, _ = prepared
    identity = root / "etc/clientflow/identity.json"
    identity.write_text(json.dumps({"client_id": 4}))
    assert check(prepared)["pass"] is False
    identity.write_text(json.dumps({"client_id": 3}))
    (root / "opt/clientflow/active").unlink()
    assert check(prepared)["pass"] is False


def test_activation_intent_denied(prepared):
    _, _, _, journal = prepared
    data = json.loads(journal.read_text())
    data["activation_intent"] = {"some": "unknown in flight"}
    journal.write_text(json.dumps(data))
    assert check(prepared)["pass"] is False


def test_existing_install_coordinator_binding_denied(prepared):
    root, _, _, _ = prepared
    path = root / "var/lib/clientflow/install-coordinator/state.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schema_version": 1, "owner": "update_clientflow", "operation_id": DEPLOYMENT}))
    path.chmod(0o600)
    assert check(prepared)["pass"] is False


def test_previous_controller_failed_state_denied(prepared):
    root, _, _, _ = prepared
    state = root / "var/lib/clientflow/update-controller/state.json"
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({"phase": "recovery_failed", "deployment": None}))
    state.chmod(0o600)
    assert check(prepared)["pass"] is False


def test_successful_old_controller_terminal_accepted(prepared):
    root, _, _, _ = prepared
    state = root / "var/lib/clientflow/update-controller/state.json"
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({"phase": "activation_succeeded", "deployment": {
        "target_release_id": runner.OLD,
        "bundle_sha256": "3d6df5ec096a5713866943a67d9f88bba3fc6287458d0ea2f616bd41e42db150",
    }}))
    state.chmod(0o600)
    assert check(prepared)["pass"] is True


def test_exact_backend_signed_snapshot_is_required():
    expected = SimpleNamespace(
        deployment_id=DEPLOYMENT, target_release_id=runner.NEW,
        target_version="1.3.47", target_release_sequence=1248,
        bundle_sha256=runner.BUNDLE_SHA256, bundle_size=runner.BUNDLE_SIZE,
        release_approval_reference=runner.APPROVAL,
        release_candidate_sha256=runner.CANDIDATE_SHA256,
        source_commit=runner.SOURCE_COMMIT,
    )
    runner._require_exact_snapshot(expected, DEPLOYMENT)
    for value in ("different", "clientflow-1.3.44-seq-1245"):
        tampered = SimpleNamespace(**vars(expected))
        tampered.target_release_id = value
        with pytest.raises(runner.Pilot1248Denied):
            runner._require_exact_snapshot(tampered, DEPLOYMENT)
    tampered = SimpleNamespace(**vars(expected))
    tampered.bundle_sha256 = "0" * 64
    with pytest.raises(runner.Pilot1248Denied):
        runner._require_exact_snapshot(tampered, DEPLOYMENT)


def test_exact_activation_bound_to_backend_deployment_id():
    calls = []
    fixed = SimpleNamespace(activate_release=lambda *args, **kwargs: calls.append((args, kwargs)) or {"ok": True})
    callback = runner._bind_exact_activation(fixed, DEPLOYMENT)
    assert callback(runner.NEW, expected_release_approval_reference=runner.APPROVAL,
                    layout=SimpleNamespace(root=Path("/"))) == {"ok": True}
    assert calls[0][1]["expected_update_deployment_id"] == DEPLOYMENT
    with pytest.raises(runner.Pilot1248Denied):
        callback(runner.OLD, expected_release_approval_reference=runner.APPROVAL,
                 layout=SimpleNamespace(root=Path("/")))
    with pytest.raises(runner.Pilot1248Denied):
        callback(runner.NEW, expected_release_approval_reference=runner.APPROVAL,
                 layout=SimpleNamespace(root=Path("/tmp")))
    assert len(calls) == 1


@pytest.mark.parametrize("data", [
    {}, {"INVOCATION_ID": "fake"},
    {"CLIENTFLOW_63D18_ONE_SHOT": DEPLOYMENT},
    {"CLIENTFLOW_63D18_ONE_SHOT": "other", "INVOCATION_ID": "some"},
])
def test_execute_absent_one_shot_gate_denied(data):
    with pytest.raises(runner.Pilot1248Denied):
        runner._systemd_gate(data, DEPLOYMENT)


def test_invalid_operator_uuid_denied():
    for value in ("bad", DEPLOYMENT.upper(), ""):
        with pytest.raises(runner.Pilot1248Denied):
            runner._canonical_uuid(value)


def test_signed_controller_and_fixed_transaction_can_share_exception_identity():
    code = '''
import sys
from pathlib import Path
root=Path(sys.argv[1])
sys.path.insert(0,str(root/"backend"))
from scripts.phase63d18_viborg1_1248_one_shot import _load_pinned_transaction
fixed,controller=_load_pinned_transaction(root/'client/release/lib/clientflow_release/transaction.py', root/'client/release/lib')
assert controller.TransactionError is fixed.TransactionError
assert controller.Layout is fixed.Layout
print('OVERLAY_IMPORT=PASS')
'''
    out = subprocess.run([sys.executable, "-c", code, str(ROOT)], cwd=ROOT,
                         text=True, capture_output=True)
    assert out.returncode == 0, out.stderr
    assert "OVERLAY_IMPORT=PASS" in out.stdout


def test_original_updater_is_oneshot_with_controller_onsuccess():
    service = (ROOT / "client/systemd/clientflow-updater.service").read_text()
    controller = (ROOT / "client/systemd/clientflow-update-controller.service").read_text()
    assert "OnSuccess=clientflow-update-controller.service" in service
    assert "Type=oneshot" in service
    assert "LoadCredential=update-credential.json:" in service
    assert "LoadCredential=update-private-key.pem:" in controller
    script = (ROOT / "scripts/phase63d18_viborg1_1248_one_shot.py").read_text()
    assert "original.run_once()" in script
    assert "expected_update_deployment_id=deployment_id" in script
    assert "install_coordinator.release(" not in script
    assert "systemctl start" not in script
    assert "os.unlink(" not in script
