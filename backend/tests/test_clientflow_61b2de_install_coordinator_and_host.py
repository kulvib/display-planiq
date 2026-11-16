"""61B-2D/E: durable exclusive ownership and independent host maintenance."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import stat
import sys
from types import SimpleNamespace
import uuid
import importlib.util

import pytest

ROOT = Path(__file__).resolve().parents[2]
for relative in ('client/release/lib', 'client/runtime'):
    candidate = str(ROOT / relative)
    if candidate not in sys.path:
        sys.path.insert(0, candidate)
from clientflow_release import install_coordinator as release_coord
from clientflow_runtime import install_coordinator as system_coord
from clientflow_release import update_controller
from clientflow_runtime import system_broker, display_runtime

FIRST = '00000000-0000-4000-8000-000000001234'
SECOND = '00000000-0000-4000-8000-000000005678'


def test_two_privilege_planes_use_identical_security_code():
    paths = (ROOT / 'client/release/lib/clientflow_release/install_coordinator.py',
             ROOT / 'client/runtime/clientflow_runtime/install_coordinator.py')
    assert paths[0].read_bytes() == paths[1].read_bytes()


def test_durable_claim_conflict_idempotence_and_recovery(tmp_path):
    root = tmp_path / 'private'
    system_coord.claim(owner='update_os', operation_id=FIRST, root=root)
    assert (root / 'state.json').stat().st_mode & 0o777 == 0o600
    assert root.stat().st_mode & 0o777 == 0o700
    assert release_coord.snapshot(root=root) == {'schema_version': 1, 'owner': 'update_os', 'operation_id': FIRST}
    release_coord.claim(owner='update_os', operation_id=FIRST, root=root)  # after process restart
    for owner, operation in [('update_firmware', SECOND), ('update_clientflow', FIRST), ('update_os', SECOND)]:
        with pytest.raises(release_coord.InstallCoordinationError, match='another_installation'):
            release_coord.claim(owner=owner, operation_id=operation, root=root)
    with pytest.raises(system_coord.InstallCoordinationError, match='binding_mismatch'):
        system_coord.release(owner='update_firmware', operation_id=FIRST, root=root)
    release_coord.release(owner='update_os', operation_id=FIRST, root=root)
    release_coord.release(owner='update_os', operation_id=FIRST, root=root)  # idempotent
    release_coord.claim(owner='update_clientflow', operation_id=SECOND, root=root)
    assert system_coord.snapshot(root=root)['operation_id'] == SECOND


def test_two_simultaneous_distinct_claims_cannot_both_win(tmp_path):
    root = tmp_path / 'lock'
    def try_claim(kind, identifier):
        try:
            system_coord.claim(owner=kind, operation_id=identifier, root=root)
            return True
        except system_coord.InstallCoordinationError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda pair: try_claim(*pair), [('update_os', FIRST), ('update_clientflow', SECOND)]))
    assert sorted(results) == [False, True]
    assert system_coord.snapshot(root=root)['owner'] in {'update_os', 'update_clientflow'}


def test_untrusted_state_and_missing_file_never_overrides_existing_lock(tmp_path):
    root = tmp_path / 'state'
    release_coord.claim(owner='update_firmware', operation_id=FIRST, root=root)
    path = root / 'state.json'
    path.chmod(0o666)
    with pytest.raises(release_coord.InstallCoordinationError, match='untrusted'):
        release_coord.claim(owner='update_firmware', operation_id=FIRST, root=root)
    path.chmod(0o600)
    path.write_text('{broken')
    with pytest.raises(release_coord.InstallCoordinationError, match='corrupt'):
        release_coord.release(owner='update_firmware', operation_id=FIRST, root=root)
    path.unlink()
    path.symlink_to(tmp_path / 'outside')
    with pytest.raises(release_coord.InstallCoordinationError, match='unreadable'):
        release_coord.snapshot(root=root)


def test_binding_is_canonical_and_cannot_be_stolen(tmp_path):
    root = tmp_path / 'locks'
    for bad in ['../bad', str(uuid.uuid4()).upper(), '', '0' * 36]:
        with pytest.raises(release_coord.InstallCoordinationError):
            release_coord.claim(owner='update_clientflow', operation_id=bad, root=root)
    assert not root.exists()


def test_release_controller_claim_precedes_transaction_and_terminal_proof_controls_release(monkeypatch, tmp_path):
    controller = update_controller.UpdateController.__new__(update_controller.UpdateController)
    controller.layout = SimpleNamespace(root=tmp_path)
    controller.controller_state_root = tmp_path / 'controller'
    class State:
        phase = 'activation_succeeded'
        _state = {'deployment': {'deployment_id': FIRST}}
        def reload(self):
            pass
    controller.controller_state = State()
    controller._run_locked = lambda: {'status': 'succeeded', 'deployment_id': FIRST, 'release_id': 'clientflow-1.3.45-seq-1246'}
    controller._complete_advisory_release_status = lambda result: None
    seen = []
    monkeypatch.setattr(update_controller.install_coordinator, 'release', lambda **kw: seen.append(kw))
    controller.run_once()
    assert seen == [{'owner': 'update_clientflow', 'operation_id': FIRST, 'root': tmp_path / 'var/lib/clientflow/install-coordinator'}]
    seen.clear()
    controller.controller_state.phase = 'activation_authorized'
    controller.run_once()
    assert seen == []
    source = (ROOT / 'client/release/lib/clientflow_release/update_controller.py').read_text()
    assert source.index('install_coordinator.claim(owner="update_clientflow"') < source.index('self._stage_verified(snapshot)', source.index('if state == "verified":'))


def test_system_broker_claim_precedes_browser_stop_and_release_after_journal():
    source = (ROOT / 'client/runtime/clientflow_runtime/system_broker.py').read_text()
    claim = source.index('install_coordinator.claim(owner=action, operation_id=command_id,')
    browser_stop = source.index('_enter_update_maintenance(', claim)
    journal_success = source.index('    _journal_finish(\n        lock_fd, client_id=client_id, command_id=command_id, action=action, result=result, error=None')
    release = source.index('install_coordinator.release(owner=action, operation_id=command_id,', journal_success)
    assert claim < browser_stop < journal_success < release
    assert 'recovered_after_boot_change' in source


def test_independent_screen_is_not_part_of_quiesced_clientflow_target():
    unit = ROOT / 'client/stable-systemd/planiq-display-maintenance.service'
    text = unit.read_text()
    assert 'WantedBy=multi-user.target' in text
    assert 'clientflow.target' not in text
    assert 'User=@CLIENTFLOW_KIOSK_USER@' in text
    assert '/usr/lib/clientflow/maintenance/host-screen' in text
    assert 'NoNewPrivileges=yes' in text
    assert 'ProtectSystem=strict' in text
    from clientflow_release.transaction import Layout, _runtime_unit_names, _managed_unit_paths
    layout = Layout(root=Path('/'))  # use source contract, not service side effects
    assert unit.name.startswith('planiq-') and not unit.name.startswith('clientflow')
    source = (ROOT / 'client/release/lib/clientflow_release/transaction.py').read_text()
    assert 'planiq-display-maintenance.service' in source
    assert 'enable", "--now", maintenance_unit' in source
    assert 'stable_screen' in source


def test_host_screen_source_is_read_only_and_handles_release_overlay():
    source = (ROOT / 'client/libexec/update-maintenance-screen').read_text()
    assert '--supervisor' in source
    assert '_trusted_release_snapshot' in source
    assert 'window.set_visible(False)' in source
    assert 'RELEASE_PHASES' in source
    for forbidden in ('http://', 'https://', 'subprocess.', 'os.system('):
        assert forbidden not in source
    assert 'self._sync_maintenance_screen()' in (ROOT / 'client/runtime/clientflow_runtime/display_runtime.py').read_text()


def test_host_screen_separates_release_from_os_and_rejects_untrusted_markers(monkeypatch, tmp_path):
    import runpy
    import time
    src = ROOT / 'client/libexec/update-maintenance-screen'
    ns = runpy.run_path(str(src))
    release_reader = ns['_trusted_release_snapshot']
    screen = ns['_visible_state']
    glob = release_reader.__globals__
    directory = tmp_path / 'release-status'
    directory.mkdir(mode=0o755)
    marker = directory / 'state.json'
    class RootDirectory:
        def lstat(self):
            info = directory.lstat()
            return SimpleNamespace(st_uid=0, st_mode=info.st_mode)
    class RootOS:
        def __getattr__(self, name):
            return getattr(os, name)
        def fstat(self, fd):
            info = os.fstat(fd)
            return SimpleNamespace(st_uid=0, st_mode=info.st_mode, st_size=info.st_size)
    monkeypatch.setitem(glob, 'RELEASE_DIR', RootDirectory())
    monkeypatch.setitem(glob, 'RELEASE_PATH', marker)
    monkeypatch.setitem(glob, 'os', RootOS())
    # No OS maintenance file in the isolated test root.
    monkeypatch.setitem(glob, 'STATE_DIR', SimpleNamespace(lstat=lambda: (_ for _ in ()).throw(FileNotFoundError())))
    assert screen() is None
    def record(phase, age=0):
        marker.write_text(json.dumps({
            'schema_version': 1, 'action': 'update_clientflow', 'deployment_id': FIRST,
            'target_release_id': 'clientflow-1.3.45-seq-1246',
            'phase': phase, 'updated_at': time.time() - age,
        }))
        marker.chmod(0o644)
    record('staging')
    assert screen() is None  # do not cover the browser during preactivation
    record('activating')
    assert screen() == {'action': 'ClientFlow', 'phase': 'activating'}
    record('rolling_back')
    assert screen()['phase'] == 'rolling_back'
    record('post_activation_check', age=1900)
    assert screen()['phase'] == 'recovery_required'  # NEVER stale green health
    record('completed')
    assert screen() is None
    marker.write_text('not json')
    assert screen()['phase'] == 'recovery_required'
    marker.chmod(0o666)
    assert screen()['phase'] == 'recovery_required'
    marker.unlink()
    marker.symlink_to(tmp_path / 'outside.json')
    assert screen()['phase'] == 'recovery_required'


def test_real_controller_cannot_stage_while_os_install_is_held(tmp_path):
    import importlib.util
    source = ROOT / 'backend/tests/test_clientflow_update_controller.py'
    spec = importlib.util.spec_from_file_location('isolated_existing_controller_fixture', source)
    tests = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tests)
    controller, transport, snapshot, actions, _local_state = tests._controller_fixture(tmp_path)
    root = controller._installation_lock_root()
    system_coord.claim(owner='update_os', operation_id=FIRST, root=root)
    with pytest.raises(release_coord.InstallCoordinationError, match='another_installation'):
        controller.run_once()
    assert 'local_stage' not in actions and 'local_activate' not in actions
    system_coord.release(owner='update_os', operation_id=FIRST, root=root)
    outcome = controller.run_once()
    assert outcome['status'] == 'succeeded'
    assert 'local_stage' in actions and 'local_activate' in actions
    assert system_coord.snapshot(root=root) is None
