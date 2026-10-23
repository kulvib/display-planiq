"""Only the explicitly audited rollback operation may downgrade an installed client.

The synthetic transaction fixture exercises the public activation gate without
changing systemd, a running client, or the immutable release artifact store.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "client" / "release" / "lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

from clientflow_release import transaction  # noqa: E402

OLDER = "clientflow-1.3.38-seq-1239"
NEWER = "clientflow-1.3.40-seq-1241"
APPROVAL = "approved-test-reference"


def _fixture(tmp_path, monkeypatch, *, active=NEWER, target=OLDER, intent=None):
    layout = transaction.Layout(tmp_path / "clientflow")
    layout.releases.mkdir(parents=True)
    transaction.save_state(layout, {
        "schema_version": transaction.STATE_SCHEMA,
        "highest_release_sequence": 1241,
        "active_release_id": active,
        "previous_release_id": target,
        "staged_release_id": None,
        "activation_intent": intent,
        "installed": {
            OLDER: {"release_sequence": 1239},
            NEWER: {"release_sequence": 1241},
            "clientflow-1.3.39-seq-1241": {"release_sequence": 1241},
        },
        "history": [],
    })
    calls = []

    def approval(_layout, _state, _target, *, expected_approval_reference):
        calls.append(("provenance", _target))
        assert expected_approval_reference == APPROVAL
        return APPROVAL

    def activation(_layout, _state, _target, _approval):
        calls.append(("mutation", _target))
        return {"status": "synthetic_active", "release_id": _target}

    monkeypatch.setattr(transaction, "_canonical_activation_approval", approval)
    monkeypatch.setattr(transaction, "_activate_release", activation)
    return layout, calls


def test_older_installed_release_cannot_be_activated_without_rollback(tmp_path, monkeypatch):
    layout, calls = _fixture(tmp_path, monkeypatch)
    with pytest.raises(transaction.TransactionError, match="eksplicit rollback"):
        transaction.activate_release(
            OLDER,
            expected_release_approval_reference=APPROVAL,
            layout=layout,
        )
    assert calls == []
    state = transaction.load_state(layout)
    assert state["active_release_id"] == NEWER
    assert state["highest_release_sequence"] == 1241
    assert state["activation_intent"] is None
    assert state["history"] == []


def test_equal_sequence_cannot_be_used_to_switch_release_identity(tmp_path, monkeypatch):
    target = "clientflow-1.3.39-seq-1241"
    layout, calls = _fixture(tmp_path, monkeypatch, target=target)
    with pytest.raises(transaction.TransactionError, match="ikke-stigende"):
        transaction.activate_release(
            target, expected_release_approval_reference=APPROVAL, layout=layout,
        )
    assert calls == []


def test_existing_rollback_intent_cannot_resume_through_activate(tmp_path, monkeypatch):
    intent = {
        "release_id": OLDER,
        "previous_release_id": NEWER,
        "release_approval_reference": APPROVAL,
    }
    layout, calls = _fixture(tmp_path, monkeypatch, intent=intent)
    with pytest.raises(transaction.TransactionError, match="eksplicit rollback"):
        transaction.activate_release(
            OLDER, expected_release_approval_reference=APPROVAL, layout=layout,
        )
    assert calls == []
    assert transaction.load_state(layout)["activation_intent"] == intent


def test_forward_reactivation_remains_possible(tmp_path, monkeypatch):
    layout, calls = _fixture(tmp_path, monkeypatch, active=OLDER, target=NEWER)
    result = transaction.activate_release(
        NEWER, expected_release_approval_reference=APPROVAL, layout=layout,
    )
    assert result["release_id"] == NEWER
    assert calls == [("provenance", NEWER), ("mutation", NEWER)]


def test_same_release_activation_remains_idempotent(tmp_path, monkeypatch):
    layout, calls = _fixture(tmp_path, monkeypatch, active=NEWER, target=NEWER)
    result = transaction.activate_release(
        NEWER, expected_release_approval_reference=APPROVAL, layout=layout,
    )
    assert result["release_id"] == NEWER
    assert calls == [("provenance", NEWER), ("mutation", NEWER)]


def test_first_activation_still_requires_separate_backend_proof(tmp_path, monkeypatch):
    layout, calls = _fixture(tmp_path, monkeypatch, active=None, target=NEWER)
    with pytest.raises(transaction.TransactionError, match="backend-approved"):
        transaction.activate_release(
            NEWER, expected_release_approval_reference=APPROVAL, layout=layout,
        )
    assert calls == [("provenance", NEWER)]
    calls.clear()

    result = transaction.activate_release(
        NEWER, expected_release_approval_reference=APPROVAL, layout=layout,
        first_activation_authorizer=lambda _layout: calls.append(("approved", NEWER)),
    )
    assert result["release_id"] == NEWER
    assert calls == [
        ("provenance", NEWER), ("approved", NEWER), ("mutation", NEWER),
    ]
