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
