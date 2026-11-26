"""Host-free tests of the deployment-bound post-activation reboot gate."""
from pathlib import Path
import sys
from types import SimpleNamespace
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client/release/lib"))
from clientflow_release import update_controller as module


def fixture(monkeypatch, tmp_path):
    boot = [str(uuid.uuid4())]
    events = []
    state = SimpleNamespace(_state={}, _save=lambda: events.append("durable"))
    controller = object.__new__(module.UpdateController)
    controller.controller_state = state
    controller.controller_state_root = tmp_path / "controller"
    controller.layout = module.Layout(tmp_path)
    controller._boot_id = lambda: boot[0]
    controller._request_reboot = lambda: events.append("reboot")
    snapshot = SimpleNamespace(target_version="1.4.0", target_release_sequence=1250,
        deployment_id=str(uuid.uuid4()), target_release_id="clientflow-1.4.0-seq-1250")
    monkeypatch.setattr(module.release_public_status, "publish", lambda **kw: events.append(kw["phase"]))
    monkeypatch.setattr(module, "_assert_no_temporary_media_override", lambda layout: events.append("no_pilots"))
    monkeypatch.setattr(module, "_health_check", lambda *a, **k: events.append("healthy"))
    return controller, snapshot, boot, events


def test_reboot_request_is_durable_and_not_repeated(monkeypatch, tmp_path):
    c, s, boot, events = fixture(monkeypatch, tmp_path)
    assert c._await_post_activation_boot(s) is False
    assert events == ["rebooting", "durable", "reboot"]
    assert c._await_post_activation_boot(s) is False
    assert events.count("reboot") == 1
    boot[0] = str(uuid.uuid4())
    assert c._await_post_activation_boot(s) is True
    assert events[-4:] == ["post_boot_check", "no_pilots", "healthy", "durable"]
    assert c.controller_state._state["reboot_boundary"]["observed_boot_id"] == boot[0]


def test_health_failure_and_wrong_deployment_never_succeed(monkeypatch, tmp_path):
    c, s, boot, events = fixture(monkeypatch, tmp_path)
    assert c._await_post_activation_boot(s) is False
    boot[0] = str(uuid.uuid4())
    def unhealthy(*args, **kwargs):
        raise module.TransactionError("unhealthy")
    monkeypatch.setattr(module, "_health_check", unhealthy)
    with pytest.raises(module.TransactionError):
        c._await_post_activation_boot(s)
    assert events[-1] == "recovery_required"
    assert c.controller_state._state["reboot_boundary"]["observed_boot_id"] is None
    s.deployment_id = str(uuid.uuid4())
    with pytest.raises(module.UpdateControllerError):
        c._await_post_activation_boot(s)
    assert events.count("reboot") == 1


def test_failed_reboot_request_is_not_replayed(monkeypatch, tmp_path):
    c, s, boot, events = fixture(monkeypatch, tmp_path)
    def failed():
        events.append("reboot")
        raise OSError("test")
    c._request_reboot = failed
    with pytest.raises(module.UpdateControllerError):
        c._await_post_activation_boot(s)
    assert events[-1] == "recovery_required"
    assert c._await_post_activation_boot(s) is False
    assert events.count("reboot") == 1


def test_legacy_update_is_not_retroactively_changed(monkeypatch, tmp_path):
    c, s, boot, events = fixture(monkeypatch, tmp_path)
    s.target_version = "1.3.47"
    s.target_release_sequence = 1248
    assert c._await_post_activation_boot(s) is True
    assert not events

def test_post_boot_recovery_preparation_and_restore_preserve_high_water(monkeypatch, tmp_path):
    import json
    from clientflow_release import transaction as txn
    from clientflow_release import install_coordinator
    layout = txn.Layout(tmp_path)
    failed = "clientflow-1.4.1-seq-1251"
    previous = "clientflow-1.4.0-seq-1250"
    operation, before, after = (str(uuid.uuid4()) for _ in range(3))
    layout.releases.mkdir(parents=True)
    layout.state_root.mkdir(parents=True)
    boot = layout.path("/proc/sys/kernel/random/boot_id")
    boot.parent.mkdir(parents=True)
    boot.write_text(after)
    installed = {}
    for release_id in (failed, previous):
        folder = layout.releases / release_id
        folder.mkdir()
        manifest = {"release_id": release_id, "release_approval": {"reference": "approval", "candidate_sha256": "b"*64},
                    "source": {"commit": "c"*40}}
        (folder / "release-manifest.json").write_text(json.dumps(manifest))
        installed[release_id] = {"manifest_sha256": txn._manifest_digest(manifest), "bundle_size": 100,
                                 "bundle_sha256": "a"*64, "release_approval_reference": "approval",
                                 "release_candidate_sha256": "b"*64, "source_commit": "c"*40}
    layout.active.symlink_to(layout.releases / failed)
    state = txn._initial_state()
    state.update(active_release_id=failed, previous_release_id=previous, highest_release_sequence=1251,
                 installed=installed)
    txn._append_history(state, "activated", release_id=failed, previous_release_id=previous,
                        release_approval_reference="approval")
    txn.save_state(layout, state)
    calls = []
    monkeypatch.setattr(txn, "_validate_prepared_release_tree", lambda *a: None)
    for name in ("_disable_target", "_quiesce_runtime", "_disable_power_lifecycle_reporters",
                 "_apply_definitions", "_systemd_prepare", "_start_target", "_enable_power_lifecycle_reporters",
                 "_enable_target"):
        monkeypatch.setattr(txn, name, lambda *a, name=name: calls.append(name))
    monkeypatch.setattr(txn, "_health_check", lambda layout, release_id, **kw: calls.append(release_id))
    args = dict(expected_failed_release_id=failed, expected_previous_release_id=previous,
                expected_release_approval_reference="approval", expected_bundle_sha256="a"*64,
                deployment_id=operation, requested_boot_id=before, failed_boot_id=after, layout=layout)
    with pytest.raises(txn.TransactionError, match="installationslåsen"):
        txn.prepare_post_boot_recovery(**args)
    assert txn.load_state(layout)["activation_intent"] is None and not calls
    install_coordinator.claim(owner="update_clientflow", operation_id=operation,
                             root=layout.path("/var/lib/clientflow/install-coordinator"))
    with pytest.raises(txn.TransactionError):
        txn.prepare_post_boot_recovery(**dict(args, requested_boot_id=after))
    txn.prepare_post_boot_recovery(**args)
    first = txn.load_state(layout)
    assert first["active_release_id"] == failed and first["activation_intent"]["post_boot_deployment_id"] == operation
    txn.prepare_post_boot_recovery(**args)
    assert txn.load_state(layout) == first and not calls
    result = txn.recover_failed_update(expected_failed_release_id=failed,
                                       expected_previous_release_id=previous,
                                       expected_release_approval_reference="approval", layout=layout)
    final = txn.status(layout)
    assert result["restored_release_id"] == previous
    assert final["active_release_id"] == final["active_symlink_release_id"] == previous
    assert final["highest_release_sequence"] == 1251 and final["activation_intent"] is None
    assert previous in calls
    assert install_coordinator.snapshot(root=layout.path("/var/lib/clientflow/install-coordinator"))["operation_id"] == operation


@pytest.mark.parametrize("restore", [True, False])
def test_post_boot_controller_reports_only_durable_restoration(monkeypatch, tmp_path, restore):
    c, s, boot, events = fixture(monkeypatch, tmp_path)
    s.target_release_id = "clientflow-1.4.1-seq-1251"
    s.target_version = "1.4.1"
    s.target_release_sequence = 1251
    s.release_approval_reference = "approval"
    s.bundle_sha256 = "a"*64
    prior = "clientflow-1.4.0-seq-1250"
    c._await_post_activation_boot(s)
    boot[0] = str(uuid.uuid4())
    monkeypatch.setattr(module, "_health_check", lambda *a, **k: (_ for _ in ()).throw(module.TransactionError("unhealthy")))
    c._fresh_active = lambda s: ("token", {"state": "health_check"})
    c._publish_advisory_release_status = lambda s, phase: events.append(phase)
    c.controller_state.mark_outcome = lambda outcome: events.append(outcome.state)
    c._report_rollback = lambda s, outcome: {"status": "rolled_back"}
    c._report_recovery_failed = lambda s: {"status": "recovery_failed"}
    restored = [False]
    c._post_boot_restored = lambda s, previous: restored[0]
    monkeypatch.setattr(module, "prepare_post_boot_recovery", lambda **kw: events.append("prepare"))
    def recover(**kwargs):
        events.append("restore")
        if not restore:
            raise module.TransactionError("cannot restore")
        restored[0] = True
    c.recovery_func = recover
    outcome = module.LocalActivationOutcome("succeeded", prior)
    expected = "rolled_back" if restore else "recovery_failed"
    assert c._report_success(s, outcome)["status"] == expected
    assert c._recover_post_boot(s)["status"] == expected
    assert events.count("restore") == 1 and events.count("reboot") == 1
    assert "succeeded" not in events
