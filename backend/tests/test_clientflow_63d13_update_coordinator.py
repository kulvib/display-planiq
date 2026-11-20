"""Regression for physical 1246->1247 activation deadlock at Viborg1.

The controller owns a durable update_clientflow reservation.  The transaction
must accept *only* that backend-bound operation and preserve first-install gates.
"""
from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'client/release/lib'))
from clientflow_release import transaction, install_coordinator
from clientflow_release.transaction import Layout

DEPLOYMENT = 'f99607f6-f1b7-43e5-a489-d756246e1849'
OTHER = '00000000-0000-4000-8000-000000001234'
OLD = 'clientflow-1.3.45-seq-1246'
NEW = 'clientflow-1.3.46-seq-1247'


def _arrange(monkeypatch, tmp_path, *, old=OLD, staged=NEW):
    layout = Layout(tmp_path)
    root = tmp_path / 'var/lib/clientflow/install-coordinator'
    state = {
        'active_release_id': old, 'staged_release_id': staged,
        'activation_intent': None,
    }
    monkeypatch.setattr(transaction, 'TransactionLock', lambda _layout: nullcontext())
    monkeypatch.setattr(transaction, 'load_state', lambda _layout: dict(state))
    monkeypatch.setattr(transaction, '_canonical_activation_approval', lambda *_a, **_k: 'pinned-approval')
    monkeypatch.setattr(transaction, '_read_active_release_id', lambda _layout: old)
    calls = []
    def activate(*args):
        calls.append(args)
        return {'status': 'active', 'release_id': NEW}
    monkeypatch.setattr(transaction, '_activate_release', activate)
    return layout, root, calls


def _activate(layout, **kwargs):
    return transaction.activate_release(
        NEW, expected_release_approval_reference='pinned-approval',
        layout=layout, **kwargs,
    )


def test_exact_update_reservation_allows_already_authorized_deployment(monkeypatch, tmp_path):
    layout, root, calls = _arrange(monkeypatch, tmp_path)
    install_coordinator.claim(owner='update_clientflow', operation_id=DEPLOYMENT, root=root)
    result = _activate(layout, expected_update_deployment_id=DEPLOYMENT)
    assert result['status'] == 'active'
    assert len(calls) == 1
    # Retained until the update-controller verifies the backend terminal state.
    assert install_coordinator.snapshot(root=root)['operation_id'] == DEPLOYMENT


@pytest.mark.parametrize('owner,actual,provided', [
    ('update_os', DEPLOYMENT, DEPLOYMENT),
    ('fresh_install', DEPLOYMENT, DEPLOYMENT),
    ('update_clientflow', OTHER, DEPLOYMENT),
    ('update_clientflow', DEPLOYMENT, OTHER),
    ('update_clientflow', DEPLOYMENT, 'bad-id'),
])
def test_conflicting_or_forged_update_reservation_is_refused(
    monkeypatch, tmp_path, owner, actual, provided,
):
    layout, root, calls = _arrange(monkeypatch, tmp_path)
    install_coordinator.claim(owner=owner, operation_id=actual, root=root)
    with pytest.raises(transaction.TransactionError):
        _activate(layout, expected_update_deployment_id=provided)
    assert calls == []
    assert install_coordinator.snapshot(root=root)['owner'] == owner


def test_missing_lock_refused_even_with_exact_id(monkeypatch, tmp_path):
    layout, root, calls = _arrange(monkeypatch, tmp_path)
    with pytest.raises(transaction.TransactionError):
        _activate(layout, expected_update_deployment_id=DEPLOYMENT)
    assert calls == []
    assert not root.exists() or install_coordinator.snapshot(root=root) is None


@pytest.mark.parametrize('old,staged', [(None, NEW), (OLD, OLD)])
def test_update_auth_cannot_be_reused_for_first_install_or_unstaged_target(
    monkeypatch, tmp_path, old, staged,
):
    layout, root, calls = _arrange(monkeypatch, tmp_path, old=old, staged=staged)
    install_coordinator.claim(owner='update_clientflow', operation_id=DEPLOYMENT, root=root)
    with pytest.raises(transaction.TransactionError):
        _activate(layout, expected_update_deployment_id=DEPLOYMENT)
    assert calls == []


def test_existing_update_lock_still_rejected_without_controller_id(monkeypatch, tmp_path):
    layout, root, calls = _arrange(monkeypatch, tmp_path)
    install_coordinator.claim(owner='update_clientflow', operation_id=DEPLOYMENT, root=root)
    with pytest.raises(transaction.TransactionError, match='blokeret'):
        _activate(layout)
    assert calls == []


def test_source_controller_passes_backend_snapshot_id_to_transaction():
    source = (ROOT / 'client/release/lib/clientflow_release/update_controller.py').read_text()
    assert 'expected_update_deployment_id=snapshot.deployment_id' in source
