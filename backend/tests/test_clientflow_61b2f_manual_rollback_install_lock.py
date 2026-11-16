"""61B-2F manual rollback is covered by the same durable installation lock.

Synthetic test layouts only: no systemd, Render, physical machines or production
credential changes.
"""
from __future__ import annotations

from pathlib import Path
import sys
import uuid
import pytest

ROOT = Path(__file__).resolve().parents[2]
for relative in ('client/release/lib', 'client/runtime', 'backend/tests'):
    path = str(ROOT / relative)
    if path not in sys.path:
        sys.path.insert(0, path)

from clientflow_release import install_coordinator, transaction  # noqa: E402
from test_clientflow_manual_rollback_1241 import (  # noqa: E402
    prepare, PREVIOUS, CURRENT, APPROVAL,
)

REASON = 'Physical development rollback exercise'
OS_OPERATION = '00000000-0000-4000-8000-000000004444'


def _root(layout):
    return layout.path('/var/lib/clientflow/install-coordinator')


def _run(layout):
    return transaction.rollback_release(
        release_id=PREVIOUS, expected_release_approval_reference=APPROVAL,
        reason=REASON, layout=layout,
    )


def test_manual_rollback_conflict_prevents_audit_consumption_and_activation(tmp_path, monkeypatch):
    layout, calls = prepare(tmp_path, monkeypatch)
    root = _root(layout)
    install_coordinator.claim(owner='update_os', operation_id=OS_OPERATION, root=root)
    original = transaction.load_state(layout)
    with pytest.raises(transaction.TransactionError, match='blokeret'):
        _run(layout)
    assert transaction.load_state(layout) == original
    assert calls == []
    assert install_coordinator.snapshot(root=root) == {
        'schema_version': 1, 'owner': 'update_os', 'operation_id': OS_OPERATION,
    }


def test_successful_rollback_releases_only_its_own_lock_after_durable_commit(tmp_path, monkeypatch):
    layout, calls = prepare(tmp_path, monkeypatch)
    original_save = transaction.save_state
    observed = []

    def observed_save(_layout, state):
        if any(isinstance(row, dict) and row.get('event') == 'manual_rollback'
               for row in state.get('history', [])):
            snapshot = install_coordinator.snapshot(root=_root(layout))
            observed.append(snapshot)
            assert snapshot and snapshot['owner'] == 'update_clientflow'
        return original_save(_layout, state)

    monkeypatch.setattr(transaction, 'save_state', observed_save)
    result = _run(layout)
    assert result['status'] == 'active'
    assert observed and observed[-1]['owner'] == 'update_clientflow'
    assert install_coordinator.snapshot(root=_root(layout)) is None
    assert 'health:' + PREVIOUS in calls


def test_failed_rollback_keeps_lock_for_audited_recovery(tmp_path, monkeypatch):
    layout, _ = prepare(tmp_path, monkeypatch, fail_target=True)
    with pytest.raises(transaction.TransactionError):
        _run(layout)
    retained = install_coordinator.snapshot(root=_root(layout))
    assert retained and retained['owner'] == 'update_clientflow'
    assert str(uuid.UUID(retained['operation_id'])) == retained['operation_id']
    with pytest.raises(install_coordinator.InstallCoordinationError, match='another_installation'):
        install_coordinator.claim(owner='update_firmware', operation_id=OS_OPERATION, root=_root(layout))


def test_invalid_approval_does_not_grab_a_durable_lock(tmp_path, monkeypatch):
    layout, calls = prepare(tmp_path, monkeypatch)
    with pytest.raises(transaction.TransactionError, match='Wrong approval'):
        transaction.rollback_release(
            release_id=PREVIOUS, expected_release_approval_reference='invalid',
            reason=REASON, layout=layout,
        )
    assert not _root(layout).exists()
    assert calls == []


def test_manual_recovery_key_is_deterministic_and_isolated(tmp_path):
    key = transaction._manual_rollback_coordination_id(
        permit_id='permit-signed-a', active=CURRENT, target=PREVIOUS,
        approval=APPROVAL, reason=REASON,
    )
    assert str(uuid.UUID(key)) == key
    assert key == transaction._manual_rollback_coordination_id(
        permit_id='permit-signed-a', active=CURRENT, target=PREVIOUS,
        approval=APPROVAL, reason=REASON,
    )
    assert key != transaction._manual_rollback_coordination_id(
        permit_id='permit-signed-b', active=CURRENT, target=PREVIOUS,
        approval=APPROVAL, reason=REASON,
    )
    legacy = transaction._manual_rollback_coordination_id(
        permit_id=None, active=CURRENT, target=PREVIOUS,
        approval=APPROVAL, reason=REASON,
    )
    assert legacy != key
