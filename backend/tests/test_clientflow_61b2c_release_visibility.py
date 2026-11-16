"""61B-2C: offline, read-only release visibility; no real deployment/Chrome."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
import time
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
for relative in ('client/release/lib', 'client/runtime'):
    path = str(ROOT / relative)
    if path not in sys.path:
        sys.path.insert(0, path)

from clientflow_release import release_public_status as writer  # noqa: E402
from clientflow_release.update_controller import UpdateController  # noqa: E402
from clientflow_runtime import release_public_status as reader  # noqa: E402
from clientflow_runtime import status_agent  # noqa: E402

DEPLOYMENT = '00000000-0000-4000-8000-000000008888'
RELEASE = 'clientflow-1.3.45-seq-1246'


class RootView:
    """Simulate ONLY ownership metadata; retain actual nofollow/mode/data checks."""
    def __init__(self, actual, uid=0):
        self.actual = actual
        self.uid = uid

    def lstat(self):
        real = self.actual.lstat()
        return SimpleNamespace(st_uid=self.uid, st_mode=real.st_mode, st_size=real.st_size)


class SafeOS:
    def __init__(self, uid=0):
        self.uid = uid

    def __getattr__(self, attr):
        return getattr(os, attr)

    def fstat(self, fd):
        real = os.fstat(fd)
        return SimpleNamespace(st_uid=self.uid, st_mode=real.st_mode, st_size=real.st_size)


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    folder = tmp_path / 'release-status'
    path = folder / 'state.json'
    monkeypatch.setattr(reader, 'STATUS_DIR', RootView(folder))
    monkeypatch.setattr(reader, 'STATUS_PATH', path)
    monkeypatch.setattr(reader, 'os', SafeOS())
    return folder, path


def publish(path, phase='activating', *, operation=DEPLOYMENT, release=RELEASE):
    writer.publish(path=path, deployment_id=operation, release_id=release, phase=phase)


def test_status_publication_is_atomic_sanitized_and_idempotent(isolated):
    folder, path = isolated
    assert reader.public_snapshot() is None
    publish(path)
    value = json.loads(path.read_text())
    assert folder.stat().st_mode & 0o777 == 0o755
    assert path.stat().st_mode & 0o777 == 0o644
    assert set(value) == {
        'schema_version', 'action', 'deployment_id', 'target_release_id',
        'phase', 'revision', 'updated_at',
    }
    assert 'approval' not in json.dumps(value).lower()
    first_snapshot = reader.public_snapshot()
    assert first_snapshot['action'] == 'update_clientflow'
    assert first_snapshot['phase'] == 'activating'
    assert first_snapshot['operation_id'] == DEPLOYMENT
    assert first_snapshot['target_release_id'] == RELEASE
    assert first_snapshot['active'] is True
    first_bytes = path.read_bytes()
    publish(path)  # no heartbeat-driven DB writes / artificial phase revision
    assert path.read_bytes() == first_bytes
    publish(path, 'post_activation_check')
    assert reader.public_snapshot()['revision'] == 2
    publish(path, 'completed')
    assert reader.public_snapshot()['active'] is False
    writer.clear(path=path)
    assert reader.public_snapshot() is None


def test_status_does_not_allow_untrusted_file_or_invent_success(isolated, tmp_path):
    folder, path = isolated
    publish(path)
    path.chmod(0o666)
    assert reader.public_snapshot()['phase'] == 'recovery_required'
    with pytest.raises(writer.ReleasePublicStatusError, match='Ubetroet'):
        publish(path)
    path.unlink()
    outside = tmp_path / 'outside.json'
    outside.write_text(json.dumps({'phase': 'completed'}))
    path.symlink_to(outside)
    assert reader.public_snapshot()['phase'] == 'recovery_required'
    with pytest.raises(writer.ReleasePublicStatusError, match='Ubetroet'):
        publish(path)
    path.unlink()
    path.write_text('{broken')
    assert reader.public_snapshot()['phase'] == 'recovery_required'
    with pytest.raises(writer.ReleasePublicStatusError, match='eksisterende'):
        publish(path)


def test_rejects_non_root_marker_even_when_permissions_seem_safe(isolated, monkeypatch):
    folder, path = isolated
    publish(path)
    monkeypatch.setattr(reader, 'STATUS_DIR', RootView(folder, uid=1234))
    assert reader.public_snapshot()['phase'] == 'recovery_required'
    monkeypatch.setattr(reader, 'STATUS_DIR', RootView(folder))
    monkeypatch.setattr(reader, 'os', SafeOS(uid=1234))
    assert reader.public_snapshot()['phase'] == 'recovery_required'


def test_stale_and_invalid_release_statuses_are_not_false_success(isolated):
    _folder, path = isolated
    publish(path)
    value = json.loads(path.read_text())
    value['updated_at'] = time.time() - reader.STALE_SECONDS - 10
    path.write_text(json.dumps(value))
    assert reader.public_snapshot()['phase'] == 'recovery_required'
    assert 'forældet' in reader.public_snapshot()['message']
    value['target_release_id'] = 'not-a-release-unsafe'
    path.write_text(json.dumps(value))
    assert reader.public_snapshot()['phase'] == 'recovery_required'
    path.write_text(json.dumps({'schema_version': 1, 'phase': 'completed'}))
    assert reader.public_snapshot()['phase'] == 'recovery_required'
    with pytest.raises(writer.ReleasePublicStatusError):
        publish(path, phase='unauthorized')
    with pytest.raises(writer.ReleasePublicStatusError):
        publish(path, release='../../danger')


def test_controller_display_failure_cannot_override_activation_outcome(tmp_path):
    controller = UpdateController.__new__(UpdateController)
    controller.layout = SimpleNamespace(root=tmp_path)
    controller.controller_state_root = tmp_path / 'controller-state'
    controller.controller_state = SimpleNamespace(reload=lambda: None, phase='idle')
    controller._run_locked = lambda: {'status': 'succeeded', 'deployment_id': DEPLOYMENT, 'release_id': RELEASE}

    def broken_presentation(_result):
        raise RuntimeError('GTK or public file failure')

    controller._complete_advisory_release_status = broken_presentation
    result = controller.run_once()
    assert result['status'] == 'succeeded'  # same outcome, no rollback or mutation


def test_status_agent_uses_same_existing_heartbeat(monkeypatch):
    # The status agent already collects update_maintenance in collect_host_status;
    # its new source is a local reader, never a transport or backend query.
    source = (ROOT / 'client/runtime/clientflow_runtime/status_agent.py').read_text()
    assert 'release_maintenance = clientflow_release_snapshot()' in source
    assert 'payload["update_maintenance"] = release_maintenance or os_maintenance' in source
    assert 'Samtidige system- og ClientFlow-opdateringsstatusser' in source
    assert 'clientflow_release_snapshot' in source
    # No new heartbeat loop, separate network request or database column.
    assert 'payload["clientflow_release_maintenance"]' not in source


def test_controller_publishes_only_after_durable_activation_authorization():
    source = (ROOT / 'client/release/lib/clientflow_release/update_controller.py').read_text()
    method = source[source.index('def _activate_or_reconcile'):source.index('def _complete_advisory_release_status')]
    assert method.index('_assert_local_staged(self.layout, snapshot, local_state)\n        # Read-only') < method.index('self.activate_func(')
    assert method.index('self._publish_advisory_release_status(snapshot, "activating")') < method.index('self.activate_func(')
    assert 'mark_activation_authorized(local_state)' in source
    assert 'snapshot.target_release_id' in source


def test_terminal_presentation_requires_local_controller_outcome(isolated, tmp_path):
    from clientflow_release.updater_state import DeploymentSnapshot

    _folder, path = isolated
    controller = UpdateController.__new__(UpdateController)
    controller.controller_state_root = tmp_path / 'controller-state'
    snapshot = DeploymentSnapshot(
        deployment_id=DEPLOYMENT, target_release_id=RELEASE,
        target_version='1.3.45', target_release_sequence=1246,
        bundle_sha256='a' * 64, bundle_size=100,
        release_approval_reference='test-approval',
        release_candidate_sha256=None, source_commit=None,
    )
    controller.controller_state = SimpleNamespace(
        phase='activation_authorized', _state={'deployment': snapshot.to_dict()},
    )
    result = {'status': 'succeeded', 'deployment_id': DEPLOYMENT, 'release_id': RELEASE}
    controller._complete_advisory_release_status(result)
    assert reader.public_snapshot()['phase'] == 'post_activation_check'
    controller.controller_state.phase = 'activation_succeeded'
    controller._complete_advisory_release_status(result)
    assert reader.public_snapshot()['phase'] == 'completed'
    controller.controller_state.phase = 'rolled_back'
    controller._complete_advisory_release_status({**result, 'status': 'rolled_back'})
    assert reader.public_snapshot()['phase'] == 'rolled_back'
    assert reader.public_snapshot()['active'] is False


def test_status_agent_prioritizes_system_maintenance_and_flags_conflict(monkeypatch):
    monkeypatch.setattr(status_agent, '_network_status', lambda: {})
    monkeypatch.setattr(status_agent, '_time_status', lambda: {})
    monkeypatch.setattr(status_agent, '_service_status', lambda: {})
    monkeypatch.setattr(status_agent, '_meminfo', lambda: {})
    monkeypatch.setattr(status_agent, '_uptime', lambda: 1.0)
    monkeypatch.setattr(status_agent, '_ubuntu_version', lambda: 'Ubuntu 26.04')
    monkeypatch.setattr(status_agent, 'collect_completed_local_power_event', lambda: None)
    system = {
        'schema_version': 1, 'action': 'update_os', 'phase': 'installing',
        'active': True, 'message': 'Ubuntu opdatering',
    }
    release = {
        'schema_version': 1, 'action': 'update_clientflow',
        'phase': 'activating', 'active': True, 'message': 'ClientFlow opdatering',
    }
    monkeypatch.setattr(status_agent, 'update_maintenance_snapshot', lambda: None)
    monkeypatch.setattr(status_agent, 'clientflow_release_snapshot', lambda: release)
    assert status_agent.collect_host_status()['update_maintenance'] == release
    monkeypatch.setattr(status_agent, 'update_maintenance_snapshot', lambda: system)
    conflict = status_agent.collect_host_status()['update_maintenance']
    assert conflict['phase'] == 'recovery_required'
    assert conflict['active'] is True
    monkeypatch.setattr(status_agent, 'clientflow_release_snapshot', lambda: None)
    assert status_agent.collect_host_status()['update_maintenance'] == system
    monkeypatch.setattr(status_agent, 'update_maintenance_snapshot', lambda: None)
    assert status_agent.collect_host_status()['update_maintenance'] is None


def test_revision_stable_for_repeated_controller_status_poll(isolated):
    _folder, path = isolated
    controller = UpdateController.__new__(UpdateController)
    controller.controller_state_root = path.parent.parent / 'controller-state'
    snapshot = SimpleNamespace(deployment_id=DEPLOYMENT, target_release_id=RELEASE)
    controller._publish_advisory_release_status(snapshot, 'staging')
    original = path.read_bytes()
    controller._publish_advisory_release_status(snapshot, 'staging')
    assert path.read_bytes() == original
    controller._publish_advisory_release_status(snapshot, 'activating')
    assert reader.public_snapshot()['revision'] == 2
