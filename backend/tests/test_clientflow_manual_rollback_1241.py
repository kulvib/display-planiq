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
        "installed": {
            PREVIOUS: {"release_sequence": 1239},
            CURRENT: {"release_sequence": 1241},
        },
        "history": [],
    })
    calls = []
    def exact_approval(_layout, state, target, *, expected_approval_reference):
        assert state["installed"][target] == {"release_sequence": 1239}
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
    assert [row["event"] for row in state["history"] if row["event"].startswith("manual_rollback")] == [
        "manual_rollback_requested", "manual_rollback",
    ]
    requested = next(row for row in state["history"] if row["event"] == "manual_rollback_requested")
    assert requested["reason"] == "Physical development rollback exercise"
    assert requested["to_release_id"] == PREVIOUS
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
    assert any(row["event"] == "manual_rollback_requested" for row in state["history"])
    assert not any(row["event"] == "manual_rollback" for row in state["history"])
    assert "health:" + CURRENT in calls


@pytest.mark.parametrize("scenario", [
    "not_previous", "forward", "equal_sequence", "corrupt_current_sequence",
    "corrupt_previous_sequence", "highwater_regression", "missing_current",
    "other_activation_inflight", "wrong_active_symlink",
])
def test_manual_rollback_preflight_rejects_unsafe_transition_before_mutation(
    tmp_path, monkeypatch, scenario
):
    layout, calls = prepare(tmp_path, monkeypatch)
    state = transaction.load_state(layout)
    target = PREVIOUS
    if scenario == "not_previous":
        target = "clientflow-1.3.37-seq-1238"
        state["installed"][target] = {"release_sequence": 1238}
    elif scenario == "forward":
        state["active_release_id"] = PREVIOUS
        state["previous_release_id"] = CURRENT
        layout.active.unlink()
        layout.active.symlink_to("releases/" + PREVIOUS)
        target = CURRENT
    elif scenario == "equal_sequence":
        target = "clientflow-1.3.37-seq-1241"
        state["installed"][target] = {"release_sequence": 1241}
        state["previous_release_id"] = target
    elif scenario == "corrupt_current_sequence":
        state["installed"][CURRENT]["release_sequence"] = 1240
    elif scenario == "corrupt_previous_sequence":
        state["installed"][PREVIOUS]["release_sequence"] = 1240
    elif scenario == "highwater_regression":
        state["highest_release_sequence"] = 1239
    elif scenario == "missing_current":
        state["installed"].pop(CURRENT)
    elif scenario == "other_activation_inflight":
        state["activation_intent"] = {
            "release_id": "clientflow-1.3.37-seq-1238",
            "previous_release_id": CURRENT,
        }
    elif scenario == "wrong_active_symlink":
        layout.active.unlink()
        layout.active.symlink_to("releases/" + PREVIOUS)
    transaction.save_state(layout, state)

    with pytest.raises(transaction.TransactionError):
        transaction.rollback_release(
            release_id=target,
            expected_release_approval_reference=APPROVAL,
            reason="Approved development rollback",
            layout=layout,
        )
    assert not calls
    assert not any(
        row["event"].startswith("manual_rollback")
        for row in transaction.load_state(layout)["history"]
    )


def test_manual_rollback_rejects_invalid_reason_without_state_change(tmp_path, monkeypatch):
    layout, calls = prepare(tmp_path, monkeypatch)
    with pytest.raises(transaction.TransactionError, match="begrundelsen"):
        transaction.rollback_release(
            release_id=PREVIOUS,
            expected_release_approval_reference=APPROVAL,
            reason=" ",
            layout=layout,
        )
    assert not calls
    assert transaction.load_state(layout)["history"] == []


def test_manual_rollback_target_selection_defaults_to_exact_previous(tmp_path, monkeypatch):
    layout, calls = prepare(tmp_path, monkeypatch)
    result = transaction.rollback_release(
        expected_release_approval_reference=APPROVAL,
        reason="Approved development rollback",
        layout=layout,
    )
    assert result["release_id"] == PREVIOUS
    assert transaction.load_state(layout)["highest_release_sequence"] == 1241
    assert any(row["event"] == "manual_rollback_requested" for row in transaction.load_state(layout)["history"])


def test_manual_rollback_pending_intent_must_target_previous(tmp_path, monkeypatch):
    layout, calls = prepare(tmp_path, monkeypatch)
    state = transaction.load_state(layout)
    state["activation_intent"] = {
        "release_id": PREVIOUS,
        "previous_release_id": CURRENT,
        "release_approval_reference": APPROVAL,
    }
    state["history"].extend([
        {"event": "manual_rollback_requested", "from_release_id": CURRENT,
         "to_release_id": PREVIOUS, "release_approval_reference": APPROVAL,
         "reason": "Resume previous rollback after unexpected power loss"},
        {"event": "activation_intent_committed", "release_id": PREVIOUS,
         "previous_release_id": CURRENT, "release_approval_reference": APPROVAL},
    ])
    transaction.save_state(layout, state)
    result = transaction.rollback_release(
        release_id=PREVIOUS,
        expected_release_approval_reference=APPROVAL,
        reason="Resume previous rollback after unexpected power loss",
        layout=layout,
    )
    assert result["release_id"] == PREVIOUS
    assert transaction.load_state(layout)["activation_intent"] is None


def test_manual_rollback_resumes_after_symlink_switched_before_commit(tmp_path, monkeypatch):
    layout, calls = prepare(tmp_path, monkeypatch)
    state = transaction.load_state(layout)
    reason = "Resume previous rollback after unexpected power loss"
    state["activation_intent"] = {
        "release_id": PREVIOUS, "previous_release_id": CURRENT,
        "release_approval_reference": APPROVAL,
    }
    state["history"].extend([
        {"event": "manual_rollback_requested", "from_release_id": CURRENT,
         "to_release_id": PREVIOUS, "release_approval_reference": APPROVAL,
         "reason": reason},
        {"event": "activation_intent_committed", "release_id": PREVIOUS,
         "previous_release_id": CURRENT, "release_approval_reference": APPROVAL},
    ])
    transaction.save_state(layout, state)
    layout.active.unlink()
    layout.active.symlink_to("releases/" + PREVIOUS)
    result = transaction.rollback_release(
        release_id=PREVIOUS, expected_release_approval_reference=APPROVAL,
        reason=reason, layout=layout,
    )
    assert result["status"] == "active"
    assert transaction.load_state(layout)["active_release_id"] == PREVIOUS
    assert [event["event"] for event in transaction.load_state(layout)["history"]
            if event["event"] == "manual_rollback_requested"] == ["manual_rollback_requested"]
    assert "health:" + PREVIOUS in calls


@pytest.mark.parametrize("scenario", ["missing_audit", "reason_changed", "unrelated_activation"])
def test_manual_rollback_resume_rejects_unaudited_or_changed_intent(tmp_path, monkeypatch, scenario):
    layout, calls = prepare(tmp_path, monkeypatch)
    state = transaction.load_state(layout)
    reason = "Approved recovery operation"
    state["activation_intent"] = {
        "release_id": PREVIOUS, "previous_release_id": CURRENT,
        "release_approval_reference": APPROVAL,
    }
    if scenario != "missing_audit":
        state["history"].append({
            "event": "manual_rollback_requested", "from_release_id": CURRENT,
            "to_release_id": PREVIOUS, "release_approval_reference": APPROVAL,
            "reason": reason,
        })
    state["history"].append({
        "event": "activation_intent_committed", "release_id": PREVIOUS,
        "previous_release_id": CURRENT, "release_approval_reference": APPROVAL,
    })
    if scenario == "unrelated_activation":
        state["history"].insert(-1, {"event": "automatic_rollback_failed"})
    transaction.save_state(layout, state)
    with pytest.raises(transaction.TransactionError):
        transaction.rollback_release(
            release_id=PREVIOUS, expected_release_approval_reference=APPROVAL,
            reason="Changed reason" if scenario == "reason_changed" else reason,
            layout=layout,
        )
    assert not calls
    assert transaction.load_state(layout)["active_release_id"] == CURRENT
