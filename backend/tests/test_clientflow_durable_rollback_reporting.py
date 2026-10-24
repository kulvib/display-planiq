"""Durable signed rollback reporting across an older active ClientFlow release."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import uuid
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "client/release/lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

from clientflow_release import rollback_outbox, transaction  # noqa: E402
from clientflow_release.builder import _create_updater_pyz  # noqa: E402
from clientflow_release.rollback_outbox import RollbackOutboxError, RollbackReceiptQueue  # noqa: E402
from clientflow_release.updater_client import StableUpdaterClient  # noqa: E402
from clientflow_release.updater_transport import UpdaterHTTPError  # noqa: E402


PERMIT = "11111111-1111-4111-8111-111111111111"
TARGET = "clientflow-1.3.40-seq-1241"


def receipt():
    return {
        "permit_id": PERMIT,
        "event_id": str(uuid.uuid5(uuid.NAMESPACE_URL, "planiq-clientflow-rollback-succeeded:" + PERMIT)),
        "outcome": "succeeded",
        "occurred_at": "2026-10-23T12:34:00Z",
        "to_release_id": TARGET,
    }


def test_durable_receipt_is_minimal_and_deterministic():
    result = rollback_outbox._receipt(receipt())
    assert result == receipt()
    assert "reason" not in result and "credential" not in result
    for mutate in (lambda x: x.update(event_id=str(uuid.uuid4())),
                   lambda x: x.update(to_release_id="../../etc/passwd"),
                   lambda x: x.update(outcome="unknown"),
                   lambda x: x.update(permit_id="not a uuid"),
                   lambda x: x.update(occurred_at="bad date"),
                   lambda x: x.update(secret="unsafe")):
        invalid = receipt()
        mutate(invalid)
        with pytest.raises(RollbackOutboxError):
            rollback_outbox._receipt(invalid)




def failed_receipt():
    value = receipt()
    value["outcome"] = "failed"
    value["event_id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, "planiq-clientflow-rollback-failed:" + PERMIT))
    return value


def test_failed_receipt_is_exactly_bound_and_exportable(tmp_path, monkeypatch):
    result = failed_receipt()
    assert rollback_outbox._receipt(result) == result
    with pytest.raises(RollbackOutboxError, match="event-ID"):
        rollback_outbox._receipt({**result, "event_id": receipt()["event_id"]})
    state = {"schema_version": 2, "used_rollback_permits": {PERMIT: TARGET},
             "rollback_reports": {PERMIT: result}}
    published = []
    monkeypatch.setattr(rollback_outbox.os, "geteuid", lambda: 0)
    monkeypatch.setattr(rollback_outbox, "_read_root_state", lambda path: state)
    monkeypatch.setattr(rollback_outbox, "_root_outbox_directory", lambda *a, **k: None)
    monkeypatch.setattr(rollback_outbox, "_write_receipt", lambda path, value, **kw: published.append(value) or True)
    assert rollback_outbox.export_completed_rollbacks(
        state_path=tmp_path / "root", outbox_root=tmp_path / "outbox", updater_gid=1234
    ) == {"published": 1, "total": 1}
    assert published == [result]


def test_failed_signed_rollback_records_terminal_outcome_after_automatic_restore(tmp_path, monkeypatch):
    from test_clientflow_signed_rollback_permit_contract import setup, REASON, PREVIOUS, APPROVAL, CURRENT
    layout, _calls, permit, sign = setup(tmp_path, monkeypatch)
    original_health_check = transaction._health_check

    def fail_rollback_target(layout_arg, release_id, **kwargs):
        if release_id == PREVIOUS:
            raise transaction.TransactionError("synthetic target health failure")
        return original_health_check(layout_arg, release_id, **kwargs)

    monkeypatch.setattr(transaction, "_health_check", fail_rollback_target)
    with pytest.raises(transaction.TransactionError, match="Aktivering fejlede"):
        transaction.rollback_release(
            release_id=PREVIOUS, expected_release_approval_reference=APPROVAL,
            reason=REASON, permit_file=sign(), layout=layout,
        )
    state = transaction.load_state(layout)
    assert state["active_release_id"] == CURRENT
    assert state["activation_intent"] is None
    assert state["used_rollback_permits"][permit["permit_id"]] == PREVIOUS
    assert state["rollback_reports"][permit["permit_id"]]["outcome"] == "failed"
    assert state["rollback_reports"][permit["permit_id"]]["to_release_id"] == PREVIOUS


def test_transport_accepts_exact_failed_receipt_only():
    from clientflow_release.updater_transport import UpdaterTransport, UpdaterTransportError
    transport = UpdaterTransport.__new__(UpdaterTransport)
    transport._json_request = lambda **kwargs: {"status": "failed", "replayed": True}
    assert transport.report_rollback_result("token", failed_receipt()) == {"status": "failed", "replayed": True}
    with pytest.raises(UpdaterTransportError, match="eksakte rollback-resultat"):
        transport.report_rollback_result("token", receipt())

def test_root_export_from_atomic_state_is_idempotent_and_does_not_publish_secrets(tmp_path, monkeypatch):
    state = {"schema_version": 2, "used_rollback_permits": {PERMIT: TARGET},
             "rollback_reports": {PERMIT: receipt()}}
    monkeypatch.setattr(rollback_outbox.os, "geteuid", lambda: 0)
    monkeypatch.setattr(rollback_outbox, "_read_root_state", lambda path: state)
    # No filesystem credential details leak into the public receipt.
    output = []
    monkeypatch.setattr(rollback_outbox, "_root_outbox_directory", lambda *a, **k: None)
    monkeypatch.setattr(rollback_outbox, "_write_receipt", lambda path, value, **kw: output.append((path, value)) or True)
    result = rollback_outbox.export_completed_rollbacks(state_path=tmp_path / "secret", outbox_root=tmp_path / "public", updater_gid=1000)
    assert result == {"published": 1, "total": 1}
    assert output[0][1] == receipt()
    assert output[0][0].name == receipt()["event_id"] + ".json"
    state["used_rollback_permits"][PERMIT] = "clientflow-1.3.38-seq-1239"
    with pytest.raises(RollbackOutboxError, match="forbrugsjournal"):
        rollback_outbox.export_completed_rollbacks(state_path=tmp_path / "secret", outbox_root=tmp_path / "public", updater_gid=1000)


@pytest.mark.skipif(os.geteuid() != 0, reason="root-owned outbox requires root for full filesystem test")
def test_outbox_rejects_replacement_of_committed_receipt(tmp_path):
    location = tmp_path / "event.json"
    location.write_text(json.dumps(receipt()))
    location.chmod(0o640)
    assert rollback_outbox._write_receipt(location, receipt(), gid=os.getgid()) is False or os.geteuid() != 0
    changed = receipt()
    changed["occurred_at"] = "2026-10-23T12:35:00Z"
    with pytest.raises(RollbackOutboxError):
        rollback_outbox._write_receipt(location, changed, gid=os.getgid())


def test_ack_is_durable_and_does_not_relax_private_directory(tmp_path):
    path = tmp_path / "private"
    path.mkdir(mode=0o700)
    queue = RollbackReceiptQueue(path, outbox_root=tmp_path / "no-outbox")
    queue.acknowledge(receipt())
    assert stat.S_IMODE(path.stat().st_mode) == 0o700
    assert stat.S_IMODE(queue.ack_path.stat().st_mode) == 0o600
    assert queue._acknowledged() == {receipt()["event_id"]: PERMIT}
    queue.acknowledge(receipt())
    assert len(queue._acknowledged()) == 1
    queue.ack_path.unlink()
    queue.ack_path.symlink_to(tmp_path / "sensitive")
    with pytest.raises((RollbackOutboxError, OSError)):
        queue.acknowledge(receipt())


def test_signed_rollback_writes_receipt_in_same_success_commit(tmp_path, monkeypatch):
    # Exactly the same state write that durably marks the rollback target active.
    # Inject a crash after commit but before manual_rollback history could save.
    from test_clientflow_signed_rollback_permit_contract import setup, REASON, PREVIOUS, APPROVAL
    layout, _calls, permit, sign = setup(tmp_path, monkeypatch)
    original = transaction._append_history

    def crash_after_success(state, event, **details):
        if event == "manual_rollback":
            raise RuntimeError("simulated power loss after committed activation")
        return original(state, event, **details)

    monkeypatch.setattr(transaction, "_append_history", crash_after_success)
    with pytest.raises(RuntimeError, match="simulated power loss"):
        transaction.rollback_release(release_id=PREVIOUS,
                                     expected_release_approval_reference=APPROVAL,
                                     reason=REASON, permit_file=sign(), layout=layout)
    committed = transaction.load_state(layout)
    assert committed["active_release_id"] == PREVIOUS
    assert committed["activation_intent"] is None
    assert committed["rollback_reports"][permit["permit_id"]]["outcome"] == "succeeded"
    assert committed["rollback_reports"][permit["permit_id"]]["to_release_id"] == PREVIOUS
    assert not any(e["event"] == "manual_rollback" for e in committed["history"])


def test_old_unsigned_rollback_never_gets_false_central_receipt(tmp_path, monkeypatch):
    from test_clientflow_manual_rollback_1241 import prepare, PREVIOUS, APPROVAL
    layout, _ = prepare(tmp_path, monkeypatch)
    transaction.rollback_release(release_id=PREVIOUS,
                                 expected_release_approval_reference=APPROVAL,
                                 reason="Manuel ældre nødrulning", layout=layout)
    assert transaction.load_state(layout).get("rollback_reports", {}) == {}


def test_zipapp_keeps_root_journal_and_transaction_code_out_of_nonroot_runtime(tmp_path):
    pyz = tmp_path / "updater.pyz"
    _create_updater_pyz(ROOT, pyz, epoch=1_700_000_000)
    with zipfile.ZipFile(pyz) as zf:
        names = set(zf.namelist())
    assert "clientflow_release/rollback_outbox.py" in names
    assert "clientflow_release/transaction.py" not in names
    assert "clientflow_release/cli.py" not in names
    assert "clientflow_release/rollback_verifier.py" not in names


def test_updater_retries_pending_409_and_acks_only_real_success(tmp_path, monkeypatch):
    from clientflow_release import updater_client
    class FakeQueue:
        def __init__(self, *a, **k):
            pass
        def pending(self):
            return [receipt()]
        def acknowledge(self, value):
            acknowledgements.append(value)
    acknowledgements = []
    monkeypatch.setattr(updater_client, "RollbackReceiptQueue", FakeQueue)
    class FakeTransport:
        def __init__(self):
            self.status = 409
        def report_rollback_result(self, token, data):
            assert token == "token"
            assert data == receipt()
            if self.status:
                raise UpdaterHTTPError(self.status, "pending")
            return {"status": "succeeded", "replayed": True}
    transport = FakeTransport()
    client = StableUpdaterClient.__new__(StableUpdaterClient)
    client.config = type("Config", (), {"state_root": tmp_path})()
    client.transport = transport
    client._report_rollback_receipts("token")
    assert not acknowledgements
    transport.status = 0
    client._report_rollback_receipts("token")
    assert acknowledgements == [receipt()]
    transport.status = 403
    with pytest.raises(UpdaterHTTPError):
        client._report_rollback_receipts("token")
    assert len(acknowledgements) == 1


def test_stable_root_exporter_survives_old_release_and_isolated_from_network():
    transaction_code = (ROOT / "client/release/lib/clientflow_release/transaction.py").read_text()
    assert "planiq-rollback-outbox-export.service" in transaction_code
    assert "SIGNED_ROLLBACK_MIN_SOURCE_SEQUENCE" in transaction_code
    assert "promote_durable_rollback_host" in transaction_code
    assert "rollback-promotion.json" in transaction_code
    assert 'value["release_sequence"] > seq' in transaction_code
    assert "_remove_managed_units(layout)" in transaction_code
    service = (ROOT / "client/stable-systemd/planiq-rollback-outbox-export.service").read_text()
    timer = (ROOT / "client/stable-systemd/planiq-rollback-outbox-export.timer").read_text()
    assert "User=root" in service
    assert "RestrictAddressFamilies=AF_UNIX" in service
    assert "ReadWritePaths=/var/lib/planiq-rollback-outbox" in service
    assert "ProtectSystem=strict" in service
    assert "export-rollback-reports" in service
    assert "OnUnitActiveSec=1min" in timer
    promoter = (ROOT / "client/systemd/clientflow-stable-rollback-promote.service").read_text()
    assert "ConditionPathExists=" not in promoter  # A missing immutable unit must FAIL, not silently skip.
    assert "StateDirectory=planiq-rollback-outbox" in promoter
    target = (ROOT / "client/systemd/clientflow.target").read_text()
    assert "Requires=clientflow-platform-prepare.service clientflow-stable-rollback-promote.service" in target
    assert "After=clientflow-platform-prepare.service clientflow-stable-rollback-promote.service" in target
    updater_service = (ROOT / "client/systemd/clientflow-updater.service").read_text()
    assert "User=clientflow-updater" in updater_service
    assert "CapabilityBoundingSet=\n" in updater_service


def _fake_future_release(layout, *, release_id="clientflow-1.3.41-seq-1242"):
    target = layout.releases / release_id
    (target / "release/stable-systemd").mkdir(parents=True)
    for name in transaction._STABLE_ROLLBACK_UNITS:
        (target / "release/stable-systemd" / name).write_bytes(
            (ROOT / "client/stable-systemd" / name).read_bytes()
        )
    pyz = target / "release/updater/clientflow-updater.pyz"
    pyz.parent.mkdir(parents=True)
    pyz.write_bytes(b"#!/usr/bin/python3\nimmutable updater\n")
    pyz.chmod(0o555)
    (target / "release-manifest.json").write_text('{"release_id": "' + release_id + '"}')
    layout.active.parent.mkdir(parents=True, exist_ok=True)
    layout.active.unlink(missing_ok=True)
    layout.active.symlink_to("releases/" + release_id)
    return target


def test_new_release_host_promotion_is_stable_and_cannot_downgrade(tmp_path, monkeypatch):
    layout = transaction.Layout(tmp_path)
    _fake_future_release(layout)
    monkeypatch.setattr(transaction, "_validate_prepared_release_tree", lambda *args: None)
    result = transaction.promote_durable_rollback_host(layout=layout)
    assert result["status"] == "stable_rollback_reporter_ready"
    installed = layout.stable_updater_pyz
    assert installed.is_file()
    assert stat.S_IMODE(installed.stat().st_mode) == 0o555
    assert (layout.unit_root / transaction._STABLE_ROLLBACK_UNITS[0]).is_file()
    assert (layout.unit_root / transaction._STABLE_ROLLBACK_UNITS[1]).is_file()
    assert (layout.stable_updater_root / "rollback-promotion.json").is_file()
    assert result["updater_sha256"] == hashlib.sha256(installed.read_bytes()).hexdigest()

    # The current active release can roll back, but its stable outbox exporter
    # and verified updater remain installed independently of managed units.
    client_unit = layout.unit_root / "clientflow-status-agent.service"
    client_unit.write_text("[Service]\nExecStart=/bin/true\n")
    transaction._remove_managed_units(layout)
    assert not client_unit.exists()
    assert (layout.unit_root / transaction._STABLE_ROLLBACK_UNITS[0]).exists()
    assert installed.read_bytes().endswith(b"immutable updater\n")

    newer = {"schema_version": 1, "release_sequence": 1243}
    (layout.stable_updater_root / "rollback-promotion.json").write_text(json.dumps(newer))
    outcome = transaction.promote_durable_rollback_host(layout=layout)
    assert outcome["status"] == "newer_stable_updater_preserved"
    assert installed.read_bytes().endswith(b"immutable updater\n")


def test_stable_host_promotion_fails_before_changes_on_missing_unit(tmp_path, monkeypatch):
    layout = transaction.Layout(tmp_path)
    target = _fake_future_release(layout)
    (target / "release/stable-systemd" / transaction._STABLE_ROLLBACK_UNITS[0]).unlink()
    monkeypatch.setattr(transaction, "_validate_prepared_release_tree", lambda *args: None)
    with pytest.raises(FileNotFoundError):
        transaction.promote_durable_rollback_host(layout=layout)
    assert not layout.stable_updater_pyz.exists()


@pytest.mark.skipif(os.geteuid() != 0, reason="root-owned outbox filesystem integration requires root")
def test_root_export_and_reboot_retries_and_ack(tmp_path):
    state_root = tmp_path / "release"
    state_root.mkdir(mode=0o700)
    state_file = state_root / "state.json"
    data = {"schema_version": 2, "history": [],
            "used_rollback_permits": {PERMIT: TARGET},
            "rollback_reports": {PERMIT: receipt()}}
    state_file.write_text(json.dumps(data))
    state_file.chmod(0o600)
    dest = tmp_path / "public-outbox"
    first = rollback_outbox.export_completed_rollbacks(
        state_path=state_file, outbox_root=dest, updater_gid=os.getgid(),
    )
    assert first == {"published": 1, "total": 1}
    second = rollback_outbox.export_completed_rollbacks(
        state_path=state_file, outbox_root=dest, updater_gid=os.getgid(),
    )
    assert second == {"published": 0, "total": 1}
    assert stat.S_IMODE(dest.stat().st_mode) == 0o750
    file = dest / (receipt()["event_id"] + ".json")
    assert stat.S_IMODE(file.stat().st_mode) == 0o640
    assert json.loads(file.read_text()) == receipt()
    private = tmp_path / "unprivileged-state"
    private.mkdir(mode=0o700)
    pending = RollbackReceiptQueue(private, outbox_root=dest)
    assert pending.pending() == [receipt()]
    pending.acknowledge(receipt())
    assert pending.pending() == []
    # Reboot/recreate an updater state store: receipt stays acknowledged.
    assert RollbackReceiptQueue(private, outbox_root=dest).pending() == []


def test_backend_reporting_uses_bound_dpop_path_and_never_acks_invalid_response():
    from clientflow_release.updater_transport import UpdaterTransport, UpdaterTransportError
    transport = UpdaterTransport.__new__(UpdaterTransport)
    observed = []
    transport._json_request = lambda **params: observed.append(params) or {"status": "succeeded", "replayed": True}
    response = transport.report_rollback_result("token", receipt())
    assert response["replayed"] is True
    assert observed[0]["path"] == "/api/clientflow-update/rollback-permits/" + PERMIT + "/events"
    assert observed[0]["payload"] == {
        "event_id": receipt()["event_id"], "outcome": "succeeded",
        "occurred_at": receipt()["occurred_at"],
    }
    transport._json_request = lambda **params: {"status": "issued"}
    with pytest.raises(UpdaterTransportError, match="eksakte rollback-resultat"):
        transport.report_rollback_result("token", receipt())


def test_root_export_dispatch_is_not_available_to_unprivileged_updater(monkeypatch, capsys):
    from clientflow_release import updater_entrypoint
    monkeypatch.setattr(updater_entrypoint.os if hasattr(updater_entrypoint, "os") else os, "geteuid", lambda: 1000)
    result = updater_entrypoint.main(["export-rollback-reports"])
    assert result == 1
    assert "outbox export" in capsys.readouterr().err
