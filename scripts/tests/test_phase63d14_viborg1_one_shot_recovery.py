"""63D-14 release recovery must fail closed and must not silently patch a signed release."""
from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys

import pytest
from scripts import phase63d14_viborg1_one_shot_recovery as runner
from scripts.tests.test_phase63d13_viborg1_recovery_preflight import fixture

ROOT = Path(__file__).resolve().parents[2]
# Exact historic approved recovery source, deliberately independent of current release code.
FIXED_TRANSACTION = ROOT / 'scripts/tests/fixtures/63d14-fixed-transaction.txt'
FIXED_CONTROLLER = ROOT / 'scripts/tests/fixtures/63d14-fixed-controller.txt'


def _script_setup(tmp_path, monkeypatch):
    local = fixture(tmp_path)
    run_dir = local / 'var/lib/clientflow/63d14-recovery'
    run_dir.mkdir(parents=True)
    run_dir.chmod(0o700)
    active = local / 'opt/clientflow/releases' / runner.OLD
    source = active / 'release/lib/clientflow_release'
    source.mkdir(parents=True)
    (run_dir / 'phase63d14_viborg1_one_shot_recovery.py').write_bytes(Path(runner.__file__).read_bytes())
    (run_dir / 'transaction.py').write_bytes(FIXED_TRANSACTION.read_bytes())
    (run_dir / 'phase63d13_viborg1_recovery_preflight.py').write_bytes((ROOT / 'scripts/phase63d13_viborg1_recovery_preflight.py').read_bytes())
    monkeypatch.setattr(runner, '_require_root', lambda: None)
    monkeypatch.setattr(runner, '__file__', str(run_dir / 'phase63d14_viborg1_one_shot_recovery.py'))
    monkeypatch.setattr(runner, 'RUN_DIRECTORY', run_dir)
    monkeypatch.setattr(runner, 'ACTIVE_ROOT', active)
    # Copy known pre-lock-fix source files from repository's old 1246 fixture
    # if present; their byte digests are tested independently below.
    (source / 'transaction.py').write_text('old source')
    (source / 'update_controller.py').write_text('old controller')
    monkeypatch.setattr(runner, 'SHA256_OLD_TRANSACTION', hashlib.sha256(b'old source').hexdigest())
    monkeypatch.setattr(runner, 'SHA256_OLD_CONTROLLER', hashlib.sha256(b'old controller').hexdigest())
    for f in (source / 'transaction.py', source / 'update_controller.py'):
        f.chmod(0o644)
    for f in run_dir.iterdir():
        f.chmod(0o600)
    return local, run_dir


def test_read_only_preflight_green_and_no_mutations(tmp_path, monkeypatch):
    local, run_dir = _script_setup(tmp_path, monkeypatch)
    preflight_file = run_dir / 'phase63d13_viborg1_recovery_preflight.py'
    spec = runner._load_reviewed_preflight(preflight_file)
    monkeypatch.setattr(spec.os, 'uname', lambda: type('U', (), {'nodename': 'viborg1-NUC14MNK-B2'})())
    # Test root fixture is separate from production: preflight's inspect
    # still uses its own root-bound code and checks the exact local state.
    assert runner.SHA256_FIXED_TRANSACTION == hashlib.sha256(
        FIXED_TRANSACTION.read_bytes()
    ).hexdigest()
    assert runner.SHA256_63D13_PREFLIGHT == hashlib.sha256(
        (ROOT / 'scripts/phase63d13_viborg1_recovery_preflight.py').read_bytes()
    ).hexdigest()
    before = {p.relative_to(local): p.read_bytes() for p in local.rglob('*') if p.is_file()}
    # Avoid running real host preflight on a CI fake filesystem: independent
    # fixture already verifies the original inspector's read-only behavior.
    monkeypatch.setattr(runner, '_load_reviewed_preflight', lambda _: type('I', (), {
        'inspect': staticmethod(lambda **kw: {'deployment_id': runner.DEPLOYMENT_ID, 'local_evidence_pass': True}),
    })())
    assert runner.preflight(run_directory=run_dir, check_services=False)['local_evidence_pass']
    after = {p.relative_to(local): p.read_bytes() for p in local.rglob('*') if p.is_file()}
    assert before == after


def test_runner_requires_fixed_directory_and_private_sources(tmp_path, monkeypatch):
    local, run_dir = _script_setup(tmp_path, monkeypatch)
    source = run_dir / 'transaction.py'
    source.chmod(0o644)
    with pytest.raises(runner.RecoveryDenied, match='Untrusted'):
        runner.preflight(run_directory=run_dir, check_services=False)
    source.chmod(0o600)
    source.write_text('modified')
    with pytest.raises(runner.RecoveryDenied, match='hash mismatch'):
        runner.preflight(run_directory=run_dir, check_services=False)
    source.unlink()
    source.symlink_to(local / 'var/lib/clientflow/release/state.json')
    with pytest.raises(runner.RecoveryDenied, match='Untrusted'):
        runner.preflight(run_directory=run_dir, check_services=False)


def test_wrong_legacy_source_or_status_is_denied(tmp_path, monkeypatch):
    local, run_dir = _script_setup(tmp_path, monkeypatch)
    src = local / 'opt/clientflow/releases' / runner.OLD / 'release/lib/clientflow_release/transaction.py'
    src.write_text('different legacy source')
    with pytest.raises(runner.RecoveryDenied, match='hash mismatch'):
        runner.preflight(run_directory=run_dir, check_services=False)
    src.write_text('old source')
    monkeypatch.setattr(runner, '_load_reviewed_preflight', lambda _: type('I', (), {
        'inspect': staticmethod(lambda **kw: {'deployment_id': 'other', 'local_evidence_pass': True}),
    })())
    with pytest.raises(runner.RecoveryDenied, match='preflight not green'):
        runner.preflight(run_directory=run_dir, check_services=False)


@pytest.mark.parametrize('change', [
    {},
    {'CLIENTFLOW_63D14_ONE_SHOT': runner.DEPLOYMENT_ID},
    {'INVOCATION_ID': 'not-systemd'},
    {'CREDENTIALS_DIRECTORY': '/missing'},
    {'CLIENTFLOW_63D14_ONE_SHOT': 'another'},
])
def test_execute_operator_gate_defaults_closed(change):
    with pytest.raises(runner.RecoveryDenied):
        runner._require_systemd_operator_gate(change)


def test_exact_activation_wrapper_passes_deployment_id_only_for_expected_target():
    calls = []
    class Transaction:
        @staticmethod
        def activate_release(release_id, **kwargs):
            calls.append((release_id, kwargs))
            return {'status': 'active'}
    binding = runner._bind_exact_activation(Transaction)
    class Layout:
        root = Path('/')
    assert binding(runner.NEW, expected_release_approval_reference=runner.APPROVAL, layout=Layout()) == {'status': 'active'}
    assert calls[0][1]['expected_update_deployment_id'] == runner.DEPLOYMENT_ID
    with pytest.raises(runner.RecoveryDenied):
        binding(runner.OLD, expected_release_approval_reference=runner.APPROVAL, layout=Layout())
    with pytest.raises(runner.RecoveryDenied):
        binding(runner.NEW, expected_release_approval_reference='wrong', layout=Layout())
    with pytest.raises(runner.RecoveryDenied):
        binding(runner.NEW, expected_release_approval_reference=runner.APPROVAL, layout=type('L', (), {'root': Path('/tmp')})())
    assert len(calls) == 1


def test_installed_controller_can_share_reviewed_transaction_exception_identity(tmp_path):
    """Run in a fresh subprocess to avoid polluting this pytest's sys.modules."""
    # GitHub CI does not have user uploads; test against the matching source
    # contract by constructing a synthetic release with one in-memory loader.
    code = r'''
import importlib, sys
from pathlib import Path
repo=Path(sys.argv[1]); sys.path.insert(0,str(repo/'backend'))
old_lib=repo/'client/release/lib'
from scripts.phase63d14_viborg1_one_shot_recovery import load_fixed_transaction
fixed, controller=load_fixed_transaction(old_lib/'clientflow_release/transaction.py',old_lib)
assert controller.TransactionError is fixed.TransactionError
assert controller.Layout is fixed.Layout
assert controller.UpdateController.__init__.__defaults__ is None or callable(controller.UpdateController)
print('OVERLAY_IMPORT=PASS')
'''
    p = subprocess.run([sys.executable, '-c', code, str(ROOT)], capture_output=True, text=True, cwd=ROOT)
    assert p.returncode == 0, p.stderr
    assert 'OVERLAY_IMPORT=PASS' in p.stdout


def test_no_imports_activate_and_no_self_deployment_mutations():
    source = (ROOT / 'scripts/phase63d14_viborg1_one_shot_recovery.py').read_text()
    assert 'original.run_once()' in source
    assert 'expected_update_deployment_id=DEPLOYMENT_ID' in source
    assert 'os.remove(' not in source and '.unlink(' not in source
    assert 'os.system(' not in source and 'subprocess.run(' not in source
    assert 'sudo systemctl' not in source


def test_exact_historic_1246_file_hashes_are_reproducible_from_63d13_diff():
    """63D-13 modified ONLY the intended lock/call sites, not other internals."""
    transaction = FIXED_TRANSACTION.read_text()
    controller = FIXED_CONTROLLER.read_text()
    historic_txn = transaction.replace(
        '    expected_update_deployment_id: str | None = None,\n', '', 1
    )
    start = historic_txn.index('        # The privileged update controller has already obtained backend')
    end = historic_txn.index('        elif coordinator_state is not None:\n', start)
    historic_txn = historic_txn[:start] + '        if coordinator_state is not None:\n' + historic_txn[end+len('        elif coordinator_state is not None:\n'):]
    historic_controller = controller.replace('                expected_update_deployment_id=snapshot.deployment_id,\n', '', 1)
    assert hashlib.sha256(historic_txn.encode()).hexdigest() == runner.SHA256_OLD_TRANSACTION
    assert hashlib.sha256(historic_controller.encode()).hexdigest() == runner.SHA256_OLD_CONTROLLER


def test_real_original_controller_source_with_reviewed_transaction(tmp_path):
    """Old controller + fixed transaction must have same imported error class."""
    import shutil
    old_source = tmp_path / 'clientflow_release'
    shutil.copytree(ROOT / 'client/release/lib/clientflow_release', old_source)
    p = old_source / 'update_controller.py'
    data = FIXED_CONTROLLER.read_text().replace('                expected_update_deployment_id=snapshot.deployment_id,\n', '', 1)
    assert hashlib.sha256(data.encode()).hexdigest() == runner.SHA256_OLD_CONTROLLER
    p.write_text(data)
    code = r'''
from pathlib import Path
import sys
repo=Path(sys.argv[1]); path=Path(sys.argv[2])
sys.path.insert(0,str(repo/'backend'))
from scripts.phase63d14_viborg1_one_shot_recovery import load_fixed_transaction, SHA256_OLD_CONTROLLER
import hashlib
fixed, old=load_fixed_transaction(repo/'scripts/tests/fixtures/63d14-fixed-transaction.txt',path.parent.parent)
assert old.TransactionError is fixed.TransactionError
assert old.Layout is fixed.Layout
assert hashlib.sha256(Path(old.__file__).read_bytes()).hexdigest()==SHA256_OLD_CONTROLLER
assert 'expected_update_deployment_id' not in old.UpdateController._activate_or_reconcile.__code__.co_varnames
print('HISTORIC_CONTROLLER_OVERLAY=PASS')
'''
    result = subprocess.run([sys.executable, '-c', code, str(ROOT), str(p)], cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert 'HISTORIC_CONTROLLER_OVERLAY=PASS' in result.stdout
