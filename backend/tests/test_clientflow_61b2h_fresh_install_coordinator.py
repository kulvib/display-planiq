"""61B-2H: first-claim -> first healthy activation uses the same durable lock."""
from __future__ import annotations

from pathlib import Path
import json
import sys
from types import SimpleNamespace
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'client/release/lib'))
from clientflow_release import cli, install_coordinator, transaction
from clientflow_release.transaction import Layout

FIRST = '00000000-0000-4000-8000-000000001234'
SECOND = '00000000-0000-4000-8000-000000005678'


def _create_preclaim(layout: Layout, install_id: str = FIRST):
    root = cli._fresh_coordination_root(layout)
    install_coordinator.claim(owner='fresh_install', operation_id=install_id, root=root)
    layout.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = cli._install_state_path(layout)
    path.write_text(json.dumps({'install_id': install_id}), encoding='utf-8')
    path.chmod(0o600)
    etc = layout.path('/etc/clientflow/update')
    etc.mkdir(parents=True, exist_ok=True)
    (etc / 'private-key.pem').write_text('secret')
    return root


def test_definitive_4xx_cleanup_preserves_global_mutex_and_allows_new_code(tmp_path):
    layout = Layout(tmp_path)
    root = _create_preclaim(layout)
    cli._cleanup_new_install_preclaim_state(layout, install_id=FIRST)
    assert not cli._install_state_path(layout).exists()
    assert not layout.path('/etc/clientflow').exists()
    assert root.is_dir()
    assert install_coordinator.snapshot(root=root) is None
    assert cli._fresh_conflicts(layout) == []
    install_coordinator.claim(owner='fresh_install', operation_id=SECOND, root=root)
    with pytest.raises(install_coordinator.InstallCoordinationError, match='another_installation'):
        install_coordinator.claim(owner='update_os', operation_id=FIRST, root=root)


def test_no_cleanup_of_another_installation_or_extra_files(tmp_path):
    layout = Layout(tmp_path)
    root = _create_preclaim(layout)
    with pytest.raises(RuntimeError, match='anden transaction'):
        cli._cleanup_new_install_preclaim_state(layout, install_id=SECOND)
    assert install_coordinator.snapshot(root=root)['operation_id'] == FIRST
    unexpected = layout.path('/var/lib/clientflow/active-metadata.json')
    unexpected.write_text('unexpected')
    with pytest.raises(RuntimeError, match='uventede state-filer'):
        cli._cleanup_new_install_preclaim_state(layout, install_id=FIRST)
    assert unexpected.exists() and cli._install_state_path(layout).exists()
    assert install_coordinator.snapshot(root=root)['owner'] == 'fresh_install'


def test_incomplete_first_install_blocks_os_firmware_and_update(tmp_path):
    layout = Layout(tmp_path)
    root = _create_preclaim(layout)
    for owner in ('update_os', 'update_firmware', 'update_clientflow'):
        with pytest.raises(install_coordinator.InstallCoordinationError, match='another_installation'):
            install_coordinator.claim(owner=owner, operation_id=SECOND, root=root)
    assert '/var/lib/clientflow' in cli._fresh_conflicts(layout)


def test_first_activation_releases_after_durable_health_boundary(monkeypatch, tmp_path):
    layout = Layout(tmp_path)
    root = _create_preclaim(layout)
    state = {'active_release_id': None, 'activation_intent': None}
    release = 'clientflow-1.3.45-seq-1246'
    monkeypatch.setattr(transaction, 'TransactionLock', lambda _layout: __import__('contextlib').nullcontext())
    monkeypatch.setattr(transaction, 'load_state', lambda _layout: state.copy())
    monkeypatch.setattr(transaction, '_canonical_activation_approval', lambda *_a, **_kw: 'approval')
    monkeypatch.setattr(transaction, '_read_active_release_id', lambda _layout: state['active_release_id'])
    seen = []
    def activated(*_args):
        state['active_release_id'] = release
        seen.append('committed')
        return {'status': 'active', 'release_id': release}
    monkeypatch.setattr(transaction, '_activate_release', activated)
    result = transaction.activate_release(release,
        expected_release_approval_reference='approval', layout=layout,
        first_activation_authorizer=lambda _layout: seen.append('proof'))
    assert result['status'] == 'active'
    assert seen == ['proof', 'committed']
    assert install_coordinator.snapshot(root=root) is None


def test_first_activation_failure_keeps_lock_for_recovery(monkeypatch, tmp_path):
    layout = Layout(tmp_path)
    root = _create_preclaim(layout)
    state = {'active_release_id': None, 'activation_intent': None}
    release = 'clientflow-1.3.45-seq-1246'
    monkeypatch.setattr(transaction, 'TransactionLock', lambda _layout: __import__('contextlib').nullcontext())
    monkeypatch.setattr(transaction, 'load_state', lambda _layout: state)
    monkeypatch.setattr(transaction, '_canonical_activation_approval', lambda *_a, **_kw: 'approval')
    monkeypatch.setattr(transaction, '_activate_release', lambda *_a, **_kw: (_ for _ in ()).throw(transaction.TransactionError('health failure')))
    with pytest.raises(transaction.TransactionError, match='health failure'):
        transaction.activate_release(release,
            expected_release_approval_reference='approval', layout=layout,
            first_activation_authorizer=lambda _layout: None)
    assert install_coordinator.snapshot(root=root)['operation_id'] == FIRST


def test_activation_refuses_foreign_os_lock_before_any_mutation(monkeypatch, tmp_path):
    layout = Layout(tmp_path)
    root = cli._fresh_coordination_root(layout)
    install_coordinator.claim(owner='update_os', operation_id=FIRST, root=root)
    state = {'active_release_id': None, 'activation_intent': None}
    release = 'clientflow-1.3.45-seq-1246'
    monkeypatch.setattr(transaction, 'TransactionLock', lambda _layout: __import__('contextlib').nullcontext())
    monkeypatch.setattr(transaction, 'load_state', lambda _layout: state)
    monkeypatch.setattr(transaction, '_canonical_activation_approval', lambda *_a, **_kw: 'approval')
    monkeypatch.setattr(transaction, '_activate_release', lambda *_a, **_kw: pytest.fail('activation not allowed'))
    with pytest.raises(transaction.TransactionError, match='blokeret'):
        transaction.activate_release(release,
            expected_release_approval_reference='approval', layout=layout,
            first_activation_authorizer=lambda _layout: pytest.fail('proof must not run'))
    assert install_coordinator.snapshot(root=root)['owner'] == 'update_os'


def test_coordinator_rejects_wrong_install_id_before_activation(monkeypatch, tmp_path):
    layout = Layout(tmp_path)
    root = _create_preclaim(layout)
    cli._install_state_path(layout).write_text(json.dumps({'install_id': SECOND}))
    monkeypatch.setattr(transaction, 'TransactionLock', lambda _layout: __import__('contextlib').nullcontext())
    monkeypatch.setattr(transaction, 'load_state', lambda _layout: {'active_release_id': None, 'activation_intent': None})
    monkeypatch.setattr(transaction, '_canonical_activation_approval', lambda *_a, **_kw: 'approval')
    with pytest.raises(transaction.TransactionError, match='matcher ikke install-state'):
        transaction.activate_release('clientflow-1.3.45-seq-1246',
            expected_release_approval_reference='approval', layout=layout,
            first_activation_authorizer=lambda _layout: pytest.fail('must not run'))
    assert install_coordinator.snapshot(root=root)['operation_id'] == FIRST


def test_repeated_activation_can_release_post_commit_crash_lock(monkeypatch, tmp_path):
    layout = Layout(tmp_path)
    root = _create_preclaim(layout)
    release = 'clientflow-1.3.45-seq-1246'
    state = {'active_release_id': release, 'activation_intent': None}
    monkeypatch.setattr(transaction, 'TransactionLock', lambda _layout: __import__('contextlib').nullcontext())
    monkeypatch.setattr(transaction, 'load_state', lambda _layout: state)
    monkeypatch.setattr(transaction, '_canonical_activation_approval', lambda *_a, **_kw: 'approval')
    monkeypatch.setattr(transaction, '_read_active_release_id', lambda _layout: release)
    monkeypatch.setattr(transaction, '_activate_release', lambda *_a, **_kw: {'status': 'already_active', 'release_id': release})
    result = transaction.activate_release(release, expected_release_approval_reference='approval', layout=layout)
    assert result['status'] == 'already_active'
    assert install_coordinator.snapshot(root=root) is None


def test_activation_does_not_release_on_false_success(monkeypatch, tmp_path):
    layout = Layout(tmp_path)
    root = _create_preclaim(layout)
    release = 'clientflow-1.3.45-seq-1246'
    state = {'active_release_id': None, 'activation_intent': None}
    monkeypatch.setattr(transaction, 'TransactionLock', lambda _layout: __import__('contextlib').nullcontext())
    monkeypatch.setattr(transaction, 'load_state', lambda _layout: state)
    monkeypatch.setattr(transaction, '_canonical_activation_approval', lambda *_a, **_kw: 'approval')
    monkeypatch.setattr(transaction, '_activate_release', lambda *_a, **_kw: {'status': 'active', 'release_id': release})
    with pytest.raises(transaction.TransactionError, match='health-verificeret'):
        transaction.activate_release(release, expected_release_approval_reference='approval',
            layout=layout, first_activation_authorizer=lambda _layout: None)
    assert install_coordinator.snapshot(root=root)['owner'] == 'fresh_install'


def test_legacy_uncoordinated_first_activation_does_not_gain_release_authority(monkeypatch, tmp_path):
    layout = Layout(tmp_path)
    release = 'clientflow-1.3.44-seq-1245'
    state = {'active_release_id': None, 'activation_intent': None}
    monkeypatch.setattr(transaction, 'TransactionLock', lambda _layout: __import__('contextlib').nullcontext())
    monkeypatch.setattr(transaction, 'load_state', lambda _layout: state)
    monkeypatch.setattr(transaction, '_canonical_activation_approval', lambda *_a, **_kw: 'approval')
    def activated(*_a):
        state['active_release_id'] = release
        return {'status': 'active', 'release_id': release}
    monkeypatch.setattr(transaction, '_activate_release', activated)
    with pytest.raises(transaction.TransactionError, match='backend-approved client proof'):
        transaction.activate_release(release, expected_release_approval_reference='approval', layout=layout)
    assert state['active_release_id'] is None
    assert transaction.activate_release(release, expected_release_approval_reference='approval',
                                        layout=layout, first_activation_authorizer=lambda _layout: None)['status'] == 'active'


def test_fresh_install_wrong_state_or_symlink_not_accepted_by_activation(monkeypatch, tmp_path):
    layout = Layout(tmp_path)
    root = _create_preclaim(layout)
    state = {'active_release_id': None, 'activation_intent': None}
    monkeypatch.setattr(transaction, 'TransactionLock', lambda _layout: __import__('contextlib').nullcontext())
    monkeypatch.setattr(transaction, 'load_state', lambda _layout: state)
    monkeypatch.setattr(transaction, '_canonical_activation_approval', lambda *_a, **_kw: 'approval')
    path = cli._install_state_path(layout)
    path.unlink()
    path.symlink_to(tmp_path / 'outside')
    with pytest.raises(transaction.TransactionError, match='mangler original install-state'):
        transaction.activate_release('clientflow-1.3.45-seq-1246', expected_release_approval_reference='approval',
            layout=layout, first_activation_authorizer=lambda _layout: pytest.fail('must not run'))
    assert install_coordinator.snapshot(root=root)['owner'] == 'fresh_install'


def test_canonical_release_build_blocks_reused_identity():
    workflow = (ROOT / '.github/workflows/release-build.yml').read_text()
    gate = 'python scripts/clientflow_61b2g_release_source_gate.py --repo-root "$GITHUB_WORKSPACE"'
    assert gate in workflow
    assert workflow.index('Require successful canonical CI') < workflow.index(gate)
    assert workflow.index(gate) < workflow.index('Fetch exact runtime-input transport')
    assert gate + ' --source-only' not in workflow
