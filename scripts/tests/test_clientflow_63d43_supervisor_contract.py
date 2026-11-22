"""63D-43: rootless, negative tests of *inert* supervisor policy only."""
from __future__ import annotations

from dataclasses import replace
import math
from pathlib import Path

import pytest

from client.runtime.clientflow_runtime import native_rfb_local_gate as gate
from client.runtime.clientflow_runtime import native_rfb_supervisor_contract as policy

SESSION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
STREAM = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
OTHER = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


def approve_only_in_test(monkeypatch):
    monkeypatch.setattr(gate, "PRODUCER_APPROVED", True)
    monkeypatch.setattr(policy, "CVE_CLEARANCE_APPROVED", True)
    monkeypatch.setattr(policy, "ROOT_CLEANUP_WATCHDOG_APPROVED", True)
    monkeypatch.setattr(policy, "PHYSICAL_CLIENT_ACTIVATION_APPROVED", True)


def verified() -> gate.VerifiedSocket:
    return gate.VerifiedSocket(
        path=gate.socket_path(SESSION),
        directory_device=1, directory_inode=11, directory_mtime_ns=5,
        socket_device=1, socket_inode=15, socket_ctime_ns=7, owner_uid=1000,
    )


def active(monkeypatch):
    approve_only_in_test(monkeypatch)
    ctrl = policy.SupervisorContract()
    spec = ctrl.request(
        client_id=3, owner_uid=1000, session_id=SESSION, stream_id=STREAM,
        now=10.0, requested_seconds=360,
    )
    ctrl.socket_ready(verified(), now=12.0)
    return ctrl, spec


def test_production_security_flags_all_stay_off():
    assert gate.PRODUCER_APPROVED is False
    assert policy.CVE_CLEARANCE_APPROVED is False
    assert policy.ROOT_CLEANUP_WATCHDOG_APPROVED is False
    assert policy.PHYSICAL_CLIENT_ACTIVATION_APPROVED is False
    assert policy.approvals_present() is False
    with pytest.raises(policy.NativeRfbSupervisorDenied, match="not approved"):
        policy.SupervisorContract().request(
            client_id=3, owner_uid=1000, session_id=SESSION, stream_id=STREAM,
            now=10.0, requested_seconds=360,
        )


@pytest.mark.parametrize("flag", [
    "CVE_CLEARANCE_APPROVED",
    "ROOT_CLEANUP_WATCHDOG_APPROVED",
    "PHYSICAL_CLIENT_ACTIVATION_APPROVED",
])
def test_each_source_approval_independently_required(monkeypatch, flag):
    approve_only_in_test(monkeypatch)
    monkeypatch.setattr(policy, flag, False)
    with pytest.raises(policy.NativeRfbSupervisorDenied):
        policy.SupervisorContract().request(
            client_id=3, owner_uid=1000, session_id=SESSION, stream_id=STREAM,
            now=10.0, requested_seconds=360,
        )


@pytest.mark.parametrize("overrides", [
    {"client_id": 0}, {"client_id": True}, {"owner_uid": 0},
    {"owner_uid": True}, {"requested_seconds": 361},
    {"requested_seconds": 0}, {"requested_seconds": True},
    {"session_id": "not-a-uuid"}, {"stream_id": SESSION},
    {"now": float("nan")}, {"now": float("inf")}, {"now": -1.0},
])
def test_invalid_request_fails_closed(monkeypatch, overrides):
    approve_only_in_test(monkeypatch)
    args = dict(
        client_id=3, owner_uid=1000, session_id=SESSION, stream_id=STREAM,
        now=10.0, requested_seconds=360,
    )
    args.update(overrides)
    with pytest.raises((policy.NativeRfbSupervisorDenied, gate.NativeRfbLocalGateError)):
        policy.SupervisorContract().request(**args)


def test_valid_contract_has_absolute_deadline_and_no_extension(monkeypatch):
    ctrl, spec = active(monkeypatch)
    assert spec.deadline == 370
    assert spec.startup_deadline == 25
    ctrl.authorise_stream(
        session_id=SESSION, stream_id=STREAM, client_id=3,
        owner_uid=1000, current_socket=verified(), now=369.999,
    )
    assert ctrl.tick(now=369.999, owner_still_authorised=True)
    assert not ctrl.tick(now=370, owner_still_authorised=True)
    assert ctrl.mode == "closed"
    assert ctrl.lease is None
    with pytest.raises(policy.NativeRfbSupervisorDenied):
        ctrl.request(
            client_id=3, owner_uid=1000, session_id=SESSION,
            stream_id=OTHER, now=371, requested_seconds=360,
        )


def test_startup_timeout_destroys_generation(monkeypatch):
    approve_only_in_test(monkeypatch)
    ctrl = policy.SupervisorContract()
    ctrl.request(client_id=3, owner_uid=1000, session_id=SESSION,
                 stream_id=STREAM, now=10, requested_seconds=360)
    assert not ctrl.tick(now=25, owner_still_authorised=True)
    assert ctrl.closed_reason == "startup_timeout"
    with pytest.raises(policy.NativeRfbSupervisorDenied):
        ctrl.socket_ready(verified(), now=25)


@pytest.mark.parametrize("replace_field,value", [
    ("path", Path("/tmp/attacker.sock")),
    ("socket_inode", 999),
    ("socket_device", 9),
    ("owner_uid", 1001),
])
def test_substituted_socket_generation_denied(monkeypatch, replace_field, value):
    ctrl, _ = active(monkeypatch)
    changed = replace(verified(), **{replace_field: value})
    with pytest.raises(policy.NativeRfbSupervisorDenied, match="generation changed"):
        ctrl.authorise_stream(
            session_id=SESSION, stream_id=STREAM, client_id=3,
            owner_uid=1000, current_socket=changed, now=13,
        )
    assert ctrl.mode == "closed" and ctrl.lease is None


@pytest.mark.parametrize("identities", [
    {"session_id": OTHER}, {"stream_id": OTHER},
    {"client_id": 4}, {"owner_uid": 1001},
    {"client_id": True}, {"owner_uid": True},
])
def test_wrong_session_stream_owner_client_denied(monkeypatch, identities):
    ctrl, _ = active(monkeypatch)
    args = dict(
        session_id=SESSION, stream_id=STREAM, client_id=3,
        owner_uid=1000, current_socket=verified(), now=13.0,
    )
    args.update(identities)
    with pytest.raises(policy.NativeRfbSupervisorDenied):
        ctrl.authorise_stream(**args)
    assert ctrl.mode == "closed"


def test_revoked_owner_and_revoked_source_are_immediate_stop(monkeypatch):
    ctrl, _ = active(monkeypatch)
    assert not ctrl.tick(now=14, owner_still_authorised=False)
    assert ctrl.closed_reason == "owner_revoked"
    ctrl, _ = active(monkeypatch)
    monkeypatch.setattr(policy, "CVE_CLEARANCE_APPROVED", False)
    assert not ctrl.tick(now=14, owner_still_authorised=True)
    assert ctrl.closed_reason == "source_approval_revoked"


def test_duplicate_ready_and_generation_replay_denied(monkeypatch):
    ctrl, _ = active(monkeypatch)
    with pytest.raises(policy.NativeRfbSupervisorDenied):
        ctrl.socket_ready(verified(), now=14)
    assert ctrl.mode == "closed"
    with pytest.raises(policy.NativeRfbSupervisorDenied):
        ctrl.authorise_stream(
            session_id=SESSION, stream_id=STREAM, client_id=3,
            owner_uid=1000, now=15, current_socket=verified(),
        )


def test_bad_socket_ready_cannot_approve(monkeypatch):
    approve_only_in_test(monkeypatch)
    ctrl = policy.SupervisorContract()
    ctrl.request(client_id=3, owner_uid=1000, session_id=SESSION,
                 stream_id=STREAM, now=1, requested_seconds=30)
    with pytest.raises(policy.NativeRfbSupervisorDenied):
        ctrl.socket_ready(replace(verified(), owner_uid=0), now=2)
    assert ctrl.closed_reason == "socket_identity_rejected"


def test_lease_is_pure_source_contract_not_a_service():
    from pathlib import Path
    source = Path(policy.__file__).read_text()
    assert "subprocess." not in source
    assert "os.system(" not in source
    assert "systemctl " not in source
    assert "socket.socket(" not in source
    assert "Popen(" not in source
    assert "killpg(" not in source
    assert "def tick(" in source
    assert "This pure contract cannot perform or assert cleanup itself." in source
