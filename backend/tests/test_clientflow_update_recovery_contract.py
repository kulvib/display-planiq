"""Regressions for the 1.3.39/1240 physical in-place-update recovery failure."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
RELEASE_LIB = ROOT / "client/release/lib"
if str(RELEASE_LIB) not in sys.path:
    sys.path.insert(0, str(RELEASE_LIB))

from clientflow_release import transaction  # noqa: E402
from clientflow_release.transaction import Layout, TransactionError  # noqa: E402

FAILED = "clientflow-1.3.39-seq-1240"
PREVIOUS = "clientflow-1.3.38-seq-1239"
APPROVAL = "1240-test-approval"


def _recovery_layout(tmp_path: Path, *, failure_recorded: bool = True) -> Layout:
    layout = Layout(tmp_path / "client")
    layout.releases.mkdir(parents=True)
    for release in (PREVIOUS, FAILED):
        root = layout.releases / release
        root.mkdir()
        manifest = {"release_id": release, "activation": {"health_timeout_seconds": 120}}
        (root / "release-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    layout.active.symlink_to(f"releases/{PREVIOUS}")
    state = {
        "schema_version": transaction.STATE_SCHEMA,
        "highest_release_sequence": 1240,
        "active_release_id": PREVIOUS,
        "previous_release_id": None,
        "staged_release_id": FAILED,
        "activation_intent": {
            "release_id": FAILED,
            "previous_release_id": PREVIOUS,
            "release_approval_reference": APPROVAL,
            "started_at": "2026-10-18T13:58:13Z",
        },
        "installed": {
            release: {
                "manifest_sha256": transaction._manifest_digest(json.loads(
                    (layout.releases / release / "release-manifest.json").read_text()
                )),
            }
            for release in (PREVIOUS, FAILED)
        },
        "history": [
            {
                "event": "activation_intent_committed",
                "release_id": FAILED,
                "previous_release_id": PREVIOUS,
                "release_approval_reference": APPROVAL,
            },
        ],
    }
    if failure_recorded:
        state["history"].append({
            "event": "automatic_rollback_failed",
            "release_id": FAILED,
            "previous_release_id": PREVIOUS,
            "error": "TransactionError",
        })
    transaction.save_state(layout, state)
    return layout


def _mock_runtime(monkeypatch, *, health_failure: bool = False) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(transaction, "_validate_prepared_release_tree", lambda *_args: calls.append("verify-tree"))
    for name, label in (
        ("_disable_target", "disable"),
        ("_quiesce_runtime", "quiesce"),
        ("_disable_power_lifecycle_reporters", "disable-reporters"),
        ("_apply_definitions", "definitions"),
        ("_switch_active", "switch"),
        ("_systemd_prepare", "prepare"),
        ("_start_target", "start"),
        ("_enable_power_lifecycle_reporters", "enable-reporters"),
        ("_enable_target", "enable"),
    ):
        monkeypatch.setattr(transaction, name, lambda *_args, _label=label: calls.append(_label))

    def check(*_args, **_kwargs):
        calls.append("health")
        if health_failure:
            raise TransactionError("private-key.pem MUST_NOT_PERSIST_IN_HISTORY")

    monkeypatch.setattr(transaction, "_health_check", check)
    return calls


def _recover(layout: Layout, *, previous: str = PREVIOUS):
    return transaction.recover_failed_update(
        expected_failed_release_id=FAILED,
        expected_previous_release_id=previous,
        expected_release_approval_reference=APPROVAL,
        layout=layout,
    )


def test_recovery_preserves_intent_until_health_is_durable_and_boot_enablement(tmp_path, monkeypatch):
    layout = _recovery_layout(tmp_path)
    calls = _mock_runtime(monkeypatch)
    saved: list[dict] = []
    original_save = transaction.save_state

    def record_save(the_layout, the_state):
        saved.append(json.loads(json.dumps(the_state)))
        original_save(the_layout, the_state)

    monkeypatch.setattr(transaction, "save_state", record_save)
    result = _recover(layout)
    assert result["status"] == "rolled_back"
    assert result["restored_release_id"] == PREVIOUS
    assert calls == [
        "verify-tree", "disable", "quiesce", "disable-reporters", "definitions",
        "switch", "prepare", "start", "health", "enable-reporters", "enable",
    ]
    assert saved[-2]["activation_intent"]["release_id"] == FAILED
    assert any(e["event"] == "rollback_health_verified" for e in saved[-2]["history"])
    assert saved[-1]["activation_intent"] is None
    assert saved[-1]["highest_release_sequence"] == 1240
    assert any(e["event"] == "automatic_rollback_completed" and e.get("resumed_after_recovery_failure")
               for e in saved[-1]["history"])


def test_failed_resume_keeps_intent_and_target_disabled(tmp_path, monkeypatch):
    layout = _recovery_layout(tmp_path)
    calls = _mock_runtime(monkeypatch, health_failure=True)
    with pytest.raises(TransactionError, match="activation-intent er bevaret"):
        _recover(layout)
    state = transaction.load_state(layout)
    assert state["activation_intent"]["release_id"] == FAILED
    assert state["active_release_id"] == PREVIOUS
    assert state["highest_release_sequence"] == 1240
    assert "enable" not in calls
    assert calls.count("disable") == 2
    event = state["history"][-1]
    assert event["event"] == "automatic_rollback_failed"
    assert event["rollback_failure"]["step"] == "health_check"
    assert "MUST_NOT_PERSIST" not in json.dumps(event)


@pytest.mark.parametrize("corruption", ["no_failure_event", "wrong_previous", "wrong_approval"])
def test_recovery_refuses_mismatched_or_unproven_state_before_mutation(tmp_path, monkeypatch, corruption):
    layout = _recovery_layout(tmp_path, failure_recorded=corruption != "no_failure_event")
    if corruption != "no_failure_event":
        state = transaction.load_state(layout)
        if corruption == "wrong_previous":
            state["activation_intent"]["previous_release_id"] = "clientflow-1.3.37-seq-1238"
        elif corruption == "wrong_approval":
            state["activation_intent"]["release_approval_reference"] = "unknown-approval"
        transaction.save_state(layout, state)
    calls = _mock_runtime(monkeypatch)
    with pytest.raises(TransactionError):
        _recover(layout)
    assert calls == []
    assert transaction.load_state(layout)["activation_intent"] is not None


def test_recovery_allowed_after_target_health_but_failed_boot_wiring(tmp_path, monkeypatch):
    layout = _recovery_layout(tmp_path)
    state = transaction.load_state(layout)
    state["activation_intent"]["health_verified_at"] = "2026-10-18T13:58:14Z"
    transaction.save_state(layout, state)
    _mock_runtime(monkeypatch)
    assert _recover(layout)["status"] == "rolled_back"
    assert transaction.load_state(layout)["activation_intent"] is None


def test_credential_free_failure_metadata_includes_original_and_rollback_steps(tmp_path, monkeypatch):
    layout = _recovery_layout(tmp_path)
    state = transaction.load_state(layout)
    state["activation_intent"] = None
    transaction.save_state(layout, state)
    calls = []
    monkeypatch.setattr(transaction, "_read_active_release_id", lambda _layout: PREVIOUS)
    monkeypatch.setattr(transaction, "_disable_target", lambda *_: None)
    monkeypatch.setattr(transaction, "_quiesce_runtime", lambda *_: None)
    monkeypatch.setattr(transaction, "_disable_power_lifecycle_reporters", lambda *_: None)
    monkeypatch.setattr(transaction, "_retire_preserved_first_activation_gui_before_update", lambda *_: None)

    def break_definitions(_layout, release_root):
        calls.append(release_root.name)
        raise transaction.CommandExecutionError(
            ["/usr/bin/setfacl", "-m", "credential-secret-raw"],
            13,
            "credential-secret-raw private-key.pem",
        )

    monkeypatch.setattr(transaction, "_apply_definitions", break_definitions)
    with pytest.raises(TransactionError, match="rollback fejlede"):
        transaction._activate_release(layout, state, FAILED, APPROVAL)
    failed_event = transaction.load_state(layout)["history"][-1]
    assert failed_event["event"] == "automatic_rollback_failed"
    assert failed_event["activation_failure"] == {
        "step": "apply_definitions", "error_type": "CommandExecutionError",
        "program": "setfacl", "exit_code": 13,
    }
    assert failed_event["rollback_failure"]["step"] == "apply_definitions"
    assert "credential-secret" not in json.dumps(failed_event)
    assert calls == [FAILED, PREVIOUS]


def test_canonical_controller_has_only_kiosk_home_bind_access():
    service = (ROOT / "client/systemd/clientflow-update-controller.service").read_text()
    directives = dict(line.split("=", 1) for line in service.splitlines()
                      if line and not line.startswith("#") and "=" in line)
    assert directives["User"] == "root"
    assert directives["ProtectHome"] == "tmpfs"
    assert directives["BindPaths"] == "/home/clientflow-kiosk"
    assert "BindReadOnlyPaths" not in directives
    assert directives["NoNewPrivileges"] == "yes"
    assert directives["PrivateDevices"] == "yes"
    assert "ProtectHome=yes" not in [line.strip() for line in service.splitlines()]


def test_recovery_cli_requires_explicit_three_way_binding(monkeypatch, capsys):
    from clientflow_release import cli

    bound = []

    def recover(**kwargs):
        bound.append(kwargs)
        return {"status": "rolled_back", "release_id": kwargs["expected_failed_release_id"]}

    monkeypatch.setattr(cli, "recover_failed_update", recover)
    with pytest.raises(SystemExit):
        cli.transaction_main(["recover-failed-update", "--expected-failed-release-id", FAILED])
    assert bound == []

    result = cli.transaction_main([
        "recover-failed-update",
        "--expected-failed-release-id", FAILED,
        "--expected-previous-release-id", PREVIOUS,
        "--expected-release-approval-reference", APPROVAL,
    ])
    assert result == 0
    assert bound == [{
        "expected_failed_release_id": FAILED,
        "expected_previous_release_id": PREVIOUS,
        "expected_release_approval_reference": APPROVAL,
    }]
    assert json.loads(capsys.readouterr().out)["status"] == "rolled_back"


def test_legacy_1338_bridge_is_explicit_opt_in_and_does_not_mutate_release_state():
    bridge = (ROOT / "scripts/clientflow_1338_controller_bridge.sh").read_text()
    assert "--apply" in bridge and "--confirm-clientflow-1338" in bridge
    assert "BRIDGE_DRY_RUN_ONLY=PASS" in bridge
    assert "CONTROLLER_DEFINITION_DRIFT" in bridge
    assert "systemctl daemon-reload" in bridge
    assert "BindPaths=/home/clientflow-kiosk" in bridge
    assert "ProtectHome=tmpfs" in bridge
    assert '"/opt/clientflow/active"' not in bridge
    assert "activation_intent') is None" in bridge
    assert "clientflow-1.3.38-seq-1239" in bridge
