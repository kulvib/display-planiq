"""68N-B2 draft candidate: fault injection against actual transaction code.

All host actions are replaced with recording fakes. The filesystem is a
temporary test root, never the active ClientFlow host.
"""
from pathlib import Path
import sys
import json

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client/release/lib"))
from clientflow_release import transaction as txn

OLDER = "clientflow-1.4.0-seq-1250"
PREVIOUS = "clientflow-1.4.1-seq-1251"
TARGET = "clientflow-1.4.2-seq-1252"
APPROVAL = "synthetic-1252-candidate"


@pytest.fixture
def host(tmp_path, monkeypatch):
    layout = txn.Layout(tmp_path)
    for rid in (OLDER, PREVIOUS, TARGET):
        path = layout.releases / rid
        path.mkdir(parents=True)
        manifest = {"release_id": rid, "activation": {"health_timeout_seconds": 1}}
        (path / "release-manifest.json").write_text(json.dumps(manifest))
    txn._switch_active(layout, PREVIOUS)
    state = txn._initial_state()
    state.update(active_release_id=PREVIOUS, previous_release_id=OLDER,
                 staged_release_id=TARGET, highest_release_sequence=1252,
                 installed={rid: {"manifest_sha256": txn._manifest_digest(
                     json.loads((layout.releases / rid / "release-manifest.json").read_text()))}
                     for rid in (OLDER, PREVIOUS, TARGET)})
    txn.save_state(layout, state)
    identity = layout.path("/etc/clientflow/identity.json")
    identity.parent.mkdir(parents=True)
    identity.write_text('{"CLIENT_ID":3}')
    calls = []
    for name in ("_assert_no_temporary_media_override", "_disable_target", "_quiesce_runtime",
                 "_disable_power_lifecycle_reporters", "_retire_preserved_first_activation_gui_before_update",
                 "_systemd_prepare", "_start_target", "_enable_power_lifecycle_reporters", "_enable_target"):
        monkeypatch.setattr(txn, name, lambda *args, n=name, **kw: calls.append(n))
    monkeypatch.setattr(txn, "_apply_definitions", lambda l, path: calls.append("apply:" + path.name))
    monkeypatch.setattr(txn, "_health_check", lambda l, rid, **kw: calls.append("health:" + rid))
    monkeypatch.setattr(txn, "_validate_prepared_release_tree", lambda *args: None)
    return layout, state, identity, calls


def assert_identity(identity):
    assert identity.read_text() == '{"CLIENT_ID":3}'


@pytest.mark.parametrize("after_replace", [False, True])
def test_final_activation_write_failure_and_failed_rollback_retains_intent(
        host, monkeypatch, after_replace):
    layout, state, identity, calls = host
    real_save = txn.save_state
    failed_once = False
    def fail_commit(l, candidate):
        nonlocal failed_once
        if not failed_once and candidate.get("active_release_id") == TARGET and candidate.get("activation_intent") is None:
            failed_once = True
            if after_replace:
                real_save(l, candidate)  # model rename succeeded, fsync failed
            raise OSError("injected final commit failure")
        real_save(l, candidate)
    monkeypatch.setattr(txn, "save_state", fail_commit)
    def apply(l, path):
        if path.name == PREVIOUS:
            raise OSError("injected rollback definition failure")
    monkeypatch.setattr(txn, "_apply_definitions", apply)
    with pytest.raises(txn.TransactionError, match="automatisk rollback fejlede"):
        txn._activate_release(layout, state, TARGET, APPROVAL)
    observed = txn.load_state(layout)
    assert failed_once
    assert observed["active_release_id"] == PREVIOUS
    assert observed["staged_release_id"] == TARGET
    assert observed["previous_release_id"] == OLDER
    assert observed["activation_intent"]["release_id"] == TARGET
    assert observed["history"][-1]["event"] == "automatic_rollback_failed"
    assert calls[-3:] == ["_disable_target", "_quiesce_runtime", "_disable_power_lifecycle_reporters"]
    assert_identity(identity)
    # Subsequent exact recovery must accept the legitimate older predecessor.
    monkeypatch.setattr(txn, "_apply_definitions", lambda *args: None)
    result = txn.recover_failed_update(expected_failed_release_id=TARGET,
        expected_release_approval_reference=APPROVAL, expected_previous_release_id=PREVIOUS, layout=layout)
    assert result["restored_release_id"] == PREVIOUS
    observed = txn.load_state(layout)
    assert observed["active_release_id"] == txn._read_active_release_id(layout) == PREVIOUS
    assert observed["activation_intent"] is None
    assert observed["highest_release_sequence"] == 1252
    assert_identity(identity)


def test_failed_initial_quiesce_enters_bounded_recovery(host, monkeypatch):
    layout, state, identity, calls = host
    seen = 0
    def quiesce(l):
        nonlocal seen
        seen += 1
        if seen == 1:
            raise OSError("injected first quiesce failure")
    monkeypatch.setattr(txn, "_quiesce_runtime", quiesce)
    with pytest.raises(txn.TransactionError, match="tidligere release blev automatisk gendannet"):
        txn._activate_release(layout, state, TARGET, APPROVAL)
    observed = txn.load_state(layout)
    assert observed["active_release_id"] == txn._read_active_release_id(layout) == PREVIOUS
    assert observed["activation_intent"] is None
    assert observed["history"][-1]["event"] == "automatic_rollback_completed"
    assert "apply:" + TARGET not in calls
    assert_identity(identity)


def test_success_does_not_change_identity(host):
    layout, state, identity, calls = host
    result = txn._activate_release(layout, state, TARGET, APPROVAL)
    observed = txn.load_state(layout)
    assert result["status"] == "active"
    assert observed["active_release_id"] == txn._read_active_release_id(layout) == TARGET
    assert observed["previous_release_id"] == PREVIOUS
    assert observed["activation_intent"] is None
    assert state == observed  # caller sees the exact durable commit
    assert_identity(identity)


def test_initial_disable_failure_preserves_running_predecessor_and_intent(host, monkeypatch):
    layout, state, identity, calls = host
    def fail_disable(l):
        raise txn.TransactionError("disable failed")
    monkeypatch.setattr(txn, "_disable_target", fail_disable)
    with pytest.raises(txn.TransactionError, match="disable failed"):
        txn._activate_release(layout, state, TARGET, APPROVAL)
    observed = txn.load_state(layout)
    assert observed["activation_intent"]["release_id"] == TARGET
    assert observed["active_release_id"] == txn._read_active_release_id(layout) == PREVIOUS
    assert observed["staged_release_id"] == TARGET
    assert calls == []
    assert_identity(identity)


@pytest.mark.parametrize("after_replace", [False, True])
def test_failed_rollback_final_write_preserves_intent(host, monkeypatch, after_replace):
    layout, state, identity, calls = host
    real_save = txn.save_state
    def health(l, rid, **kw):
        if rid == TARGET:
            raise OSError("injected activation health failure")
    monkeypatch.setattr(txn, "_health_check", health)
    def fail_restore_commit(l, candidate):
        if candidate["activation_intent"] is None and candidate["history"][-1]["event"] == "automatic_rollback_completed":
            if after_replace:
                real_save(l, candidate)
            raise OSError("injected rollback outcome write failure")
        real_save(l, candidate)
    monkeypatch.setattr(txn, "save_state", fail_restore_commit)
    with pytest.raises(txn.TransactionError, match="Rollback journal"):
        txn._activate_release(layout, state, TARGET, APPROVAL)
    observed = txn.load_state(layout)
    assert observed["active_release_id"] == txn._read_active_release_id(layout) == PREVIOUS
    assert observed["staged_release_id"] == TARGET
    assert observed["activation_intent"]["release_id"] == TARGET
    assert observed["history"][-1]["event"] == "automatic_rollback_failed"
    assert observed["history"][-1]["rollback_failure"]["step"] == "commit_rollback_outcome"
    assert state == observed
    assert calls[-3:] == ["_disable_target", "_quiesce_runtime", "_disable_power_lifecycle_reporters"]
    assert_identity(identity)
