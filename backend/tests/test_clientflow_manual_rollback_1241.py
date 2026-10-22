"""Synthetic proof: an already-installed approved previous release can be restored.

No Render, clients or systemd are touched. The actual field test remains pending.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "client/release/lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

from clientflow_release import transaction  # noqa: E402

PREVIOUS = "clientflow-1.3.38-seq-1239"
CURRENT = "clientflow-1.3.40-seq-1241"
APPROVAL = "approved-1338-test-provenance"


def prepare(tmp_path: Path, monkeypatch, *, fail_target: bool = False):
    layout = transaction.Layout(tmp_path / "clientflow")
    layout.releases.mkdir(parents=True)
    for release_id in (PREVIOUS, CURRENT):
        root = layout.releases / release_id
        root.mkdir()
        (root / "release-manifest.json").write_text(json.dumps({
            "release_id": release_id,
            "activation": {"health_timeout_seconds": 120},
        }))
    layout.active.symlink_to("releases/" + CURRENT)
    transaction.save_state(layout, {
        "schema_version": transaction.STATE_SCHEMA,
        "highest_release_sequence": 1241,
        "active_release_id": CURRENT,
        "previous_release_id": PREVIOUS,
        "staged_release_id": None,
        "activation_intent": None,
        "installed": {PREVIOUS: {}, CURRENT: {}},
        "history": [],
    })
    calls = []
    def exact_approval(_layout, state, target, *, expected_approval_reference):
        assert state["installed"][target] == {}
        if target != PREVIOUS or expected_approval_reference != APPROVAL:
            raise transaction.TransactionError("Wrong approval or target")
        return APPROVAL
    monkeypatch.setattr(transaction, "_canonical_activation_approval", exact_approval)
    for name in (
        "_disable_target", "_quiesce_runtime", "_disable_power_lifecycle_reporters",
        "_retire_preserved_first_activation_gui_before_update", "_apply_definitions",
        "_systemd_prepare", "_start_target", "_enable_power_lifecycle_reporters",
        "_enable_target",
    ):
        monkeypatch.setattr(transaction, name, lambda *_args, _name=name: calls.append(_name))
    def switch(_layout, release_id):
        calls.append("switch:" + release_id)
        transaction.atomic_symlink("releases/" + release_id, layout.active)
    monkeypatch.setattr(transaction, "_switch_active", switch)
    def health(_layout, release_id, *, timeout):
        calls.append("health:" + release_id)
        if fail_target and release_id == PREVIOUS:
            raise transaction.TransactionError("Synthetic unhealthy 1.3.38")
    monkeypatch.setattr(transaction, "_health_check", health)
    return layout, calls


def test_manual_rollback_after_successful_update_preserves_high_water_mark(tmp_path, monkeypatch):
    layout, calls = prepare(tmp_path, monkeypatch)
    result = transaction.rollback_release(
        release_id=PREVIOUS, expected_release_approval_reference=APPROVAL,
        reason="Physical development rollback exercise", layout=layout,
    )
    state = transaction.load_state(layout)
    assert result["status"] == "active"
    assert state["active_release_id"] == PREVIOUS
    assert state["highest_release_sequence"] == 1241
    assert state["activation_intent"] is None
    assert state["previous_release_id"] == CURRENT
    assert state["history"][-1]["event"] == "manual_rollback"
    assert calls.index("health:" + PREVIOUS) < calls.index("_enable_target")


def test_manual_rollback_rejects_incorrect_approval_before_mutation(tmp_path, monkeypatch):
    layout, calls = prepare(tmp_path, monkeypatch)
    with pytest.raises(transaction.TransactionError, match="Wrong approval"):
        transaction.rollback_release(
            release_id=PREVIOUS, expected_release_approval_reference="wrong",
            reason="Physical development rollback exercise", layout=layout,
        )
    assert calls == []
    assert transaction.load_state(layout)["active_release_id"] == CURRENT


def test_manual_rollback_failure_restores_current_version_and_retains_high_water(tmp_path, monkeypatch):
    layout, calls = prepare(tmp_path, monkeypatch, fail_target=True)
    with pytest.raises(transaction.TransactionError, match="tidligere release blev automatisk gendannet"):
        transaction.rollback_release(
            release_id=PREVIOUS, expected_release_approval_reference=APPROVAL,
            reason="Physical development rollback exercise", layout=layout,
        )
    state = transaction.load_state(layout)
    assert state["active_release_id"] == CURRENT
    assert state["highest_release_sequence"] == 1241
    assert state["activation_intent"] is None
    assert state["history"][-1]["event"] == "automatic_rollback_completed"
    assert "health:" + CURRENT in calls
