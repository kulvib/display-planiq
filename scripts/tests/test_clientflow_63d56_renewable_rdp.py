"""Renewable local physical RDP lease regression, no physical services."""
import os
import time

import pytest

from scripts import clientflow_63d53_rdp_ipc as ipc
from scripts import clientflow_63d53_rdp_lifecycle as life
from scripts import clientflow_63d53_rdp_proof as proof

SESSION = "c8e4a40e-a48c-48a1-9a2c-35035cb9e9bc"
REQUEST = "c8e4a40e-a48c-48a1-9a2c-35035cb9e9bd"


def test_renewal_message_exact_generation_and_monotonic_sequence():
    request = {"session_id": SESSION, "request_id": REQUEST}
    packet = {"type": "renew", **request, "sequence": 1}
    assert ipc.validate_renewal(packet, request, 0) == 1
    for mutation in ({"sequence": 2}, {"sequence": True}, {"request_id": SESSION},
                     {"session_id": REQUEST}, {"type": "start"}, {"extra": 1}):
        with pytest.raises(ipc.IpcDenied):
            ipc.validate_renewal({**packet, **mutation}, request, 0)
    with pytest.raises(ipc.IpcDenied):
        ipc.validate_renewal(packet, request, 1)


def test_atomic_state_refresh_is_root_owned_and_preserves_modes(tmp_path, monkeypatch):
    monkeypatch.setattr(life, "safe_directory", lambda _: None)
    state = tmp_path / "state.json"
    state.write_text("{}")
    life.replace_root_json(state, {"deadline": 90}, 0o600)
    assert state.read_text() == '{"deadline":90}'
    assert state.stat().st_mode & 0o777 == 0o600
    assert list(tmp_path.iterdir()) == [state]


def test_expired_physical_lease_cannot_be_resurrected(monkeypatch, tmp_path):
    from types import SimpleNamespace

    lock = tmp_path / "watchdog.lock"
    lock.touch(mode=0o600)
    monkeypatch.setattr(life, "WATCHDOG_LOCK", lock)
    monkeypatch.setattr(life, "safe_directory", lambda _: None)
    original = os.fstat

    def root_owned(fd):
        return SimpleNamespace(st_mode=original(fd).st_mode, st_uid=0)

    monkeypatch.setattr(life.os, "fstat", root_owned)
    monkeypatch.setattr(proof, "BOOT", SimpleNamespace(read_text=lambda: "boot"))
    monkeypatch.setattr(proof, "process_start", lambda _: "start")
    owner = {"session_id": SESSION, "pid": os.getpid(), "process_start": "start", "boot_id": "boot"}
    state = {"phase": "63D-30", "boot_id": "boot",
             "deadline_wall": time.time() - 1, "deadline_mono": time.monotonic() - 1}
    grant = {"schema": 1, "client_id": 3, "hostname": proof.HOST, "boot_id": "boot",
             "expires_wall": time.time() + 60, "expires_mono": time.monotonic() + 60}
    records = {proof.PROOF: owner, proof.STATE: state, proof.APPROVAL: grant}
    monkeypatch.setattr(proof, "root_json", lambda path, _: records[path])
    ops = life.PhysicalOperations()
    monkeypatch.setattr(ops, "run", lambda *a, **k: "\n".join([
        "PILOT_STATE_EXISTS= True", "GUARD_KERNEL_VERIFIED= True",
        "ROOT_WATCHDOG_VERIFIED= True", "GNOME_RDP_SETTING= true",
        "RDP_LISTENERS_3389_3398= [3389]", "PILOT_EXPIRED= False"]))
    writes = []
    monkeypatch.setattr(life, "replace_root_json", lambda *a: writes.append(a))
    with pytest.raises(life.LifecycleDenied, match="RENEWAL_EXPIRED"):
        ops.renew(SESSION)
    assert writes == []
    state.update(deadline_wall=time.time() + 60, deadline_mono=time.monotonic() + 60)
    ops.renew(SESSION)
    assert len(writes) == 2
    assert writes[0][0] == proof.STATE and writes[1][0] == proof.APPROVAL
    assert 85 < state["deadline_mono"] - time.monotonic() <= 90
    assert state["deadline_mono"] == grant["expires_mono"]
