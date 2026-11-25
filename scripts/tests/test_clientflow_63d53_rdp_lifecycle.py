"""63D-53 source-level lifecycle ordering and attestation regression."""
from __future__ import annotations

import os
import time

import pytest

from scripts import clientflow_63d53_rdp_lifecycle as lifecycle
from scripts import clientflow_63d53_rdp_proof as proof

SESSION = "c8e4a40e-a48c-48a1-9a2c-35035cb9e9bc"
OTHER = "c8e4a40e-a48c-48a1-9a2c-35035cb9e9bd"
FINGERPRINT = "ab" * 32


class Operations:
    def __init__(self, failure=None):
        self.calls = []
        self.failure = failure

    def step(self, name):
        self.calls.append(name)
        if self.failure == name:
            raise RuntimeError(name)

    def preflight(self):
        self.step("preflight")

    def stage(self):
        self.step("stage")

    def start(self):
        self.step("start")

    def arm(self):
        self.step("arm")
        return FINGERPRINT

    def publish(self, session, fingerprint):
        assert session == SESSION and fingerprint == FINGERPRINT
        self.step("publish")

    def revoke(self):
        self.step("revoke")

    def stop(self):
        self.step("stop")


def configure_lock(monkeypatch, tmp_path):
    # CI can run without root: patch only owner checking on the synthetic lock.
    monkeypatch.setattr(lifecycle, "LOCK", tmp_path / "lease.lock")
    monkeypatch.setattr(lifecycle, "safe_directory", lambda _: None)
    original = os.fstat

    def root_owned(fd):
        from types import SimpleNamespace
        meta = original(fd)
        return SimpleNamespace(st_mode=meta.st_mode, st_uid=0)

    monkeypatch.setattr(lifecycle.os, "fstat", root_owned)


@pytest.mark.parametrize("failure", [None, "stage", "start", "arm", "publish", "hold", "revoke"])
def test_owned_session_always_attempts_gnome_cleanup(monkeypatch, tmp_path, failure):
    configure_lock(monkeypatch, tmp_path)
    ops = Operations(failure)
    def invoke():
        lifecycle.run_owned_session(SESSION, lambda: ops.step("hold"), operations=ops)
    if failure:
        with pytest.raises(RuntimeError, match=failure):
            invoke()
    else:
        invoke()
        assert ops.calls == ["preflight", "stage", "start", "arm",
                             "publish", "hold", "revoke", "stop"]
    assert ops.calls[-2:] == ["revoke", "stop"]


def test_foreign_existing_state_never_stopped(monkeypatch, tmp_path):
    configure_lock(monkeypatch, tmp_path)
    ops = Operations("preflight")
    with pytest.raises(RuntimeError, match="preflight"):
        lifecycle.run_owned_session(SESSION, lambda: pytest.fail("hold"), operations=ops)
    assert ops.calls == ["preflight"]


def test_exclusive_session_rejects_second_owner(monkeypatch, tmp_path):
    configure_lock(monkeypatch, tmp_path)
    ops, other = Operations(), Operations()

    def hold():
        with pytest.raises(lifecycle.LifecycleDenied, match="BUSY"):
            lifecycle.run_owned_session(OTHER, lambda: pytest.fail("hold"), operations=other)

    lifecycle.run_owned_session(SESSION, hold, operations=ops)
    assert other.calls == []


def proof_data(monkeypatch):
    now, mono = time.time(), time.monotonic()
    boot = "test-boot"
    packet = {
        "schema": 1, "client_id": 3, "boot_id": boot, "session_id": SESSION,
        "pid": 123, "process_start": "456", "expires_wall": now + 20,
        "expires_mono": mono + 20, "fingerprint": FINGERPRINT,
    }
    grant = {"schema": 1, "client_id": 3, "hostname": proof.HOST, "boot_id": boot,
             "expires_wall": now + 80, "expires_mono": mono + 80}
    state = {"phase": "63D-30", "boot_id": boot,
             "deadline_wall": now + 80, "deadline_mono": mono + 80}
    records = {proof.PROOF: packet, proof.APPROVAL: grant, proof.STATE: state}
    monkeypatch.setattr(proof, "root_json", lambda path, _mode: records[path])
    monkeypatch.setattr(proof, "process_start", lambda _pid: "456")
    from types import SimpleNamespace
    monkeypatch.setattr(proof, "BOOT", SimpleNamespace(read_text=lambda: boot))
    return packet, grant, state


def test_proof_is_bound_to_live_owner_boot_and_physical_deadlines(monkeypatch):
    packet, grant, state = proof_data(monkeypatch)
    expires, fingerprint = proof.authorize(SESSION)
    assert 0 < expires - int(time.time()) <= 30
    assert fingerprint == FINGERPRINT
    with pytest.raises(proof.ProofDenied):
        proof.authorize(OTHER)
    packet["process_start"] = "different"
    with pytest.raises(proof.ProofDenied):
        proof.authorize(SESSION)
    packet["process_start"] = "456"
    grant["expires_mono"] = time.monotonic() - 1
    with pytest.raises(proof.ProofDenied):
        proof.authorize(SESSION)
    grant["expires_mono"] = time.monotonic() + 80
    state["boot_id"] = "foreign-boot"
    with pytest.raises(proof.ProofDenied):
        proof.authorize(SESSION)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "30"])
def test_invalid_deadline_is_rejected(value):
    with pytest.raises(proof.ProofDenied):
        proof.remaining(value, time.monotonic() + 20)


def test_pinned_operations_reject_arbitrary_command():
    with pytest.raises(lifecycle.LifecycleDenied, match="UNSUPPORTED"):
        lifecycle.PhysicalOperations().run(lifecycle.RUNNER, "shell")


def test_sealer_can_use_attestation_without_privileged_probe(monkeypatch):
    import base64
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from scripts import clientflow_63d49_autologin_broker as broker

    pair = ec.generate_private_key(ec.SECP256R1())
    raw = pair.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    public = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    request = {"schema": 1, "session_id": SESSION, "request_id": OTHER, "public_key": public}
    monkeypatch.setattr(broker, "_safe_grant", lambda: pytest.fail("legacy grant"))
    monkeypatch.setattr(broker, "_verify_physical_firewall", lambda: pytest.fail("privileged probe"))
    monkeypatch.setattr(broker, "_cert_path", lambda _: pytest.fail("kiosk certificate"))
    monkeypatch.setattr(broker, "_root_private", lambda *_a, **_kw:
                        ("cfpilotabcdef12\n" + "s" * 45 + "\n").encode())
    deadline = int(time.time()) + 20

    def authorize(session):
        assert session == SESSION
        return deadline, FINGERPRINT

    packet = broker._seal(request, authorize=authorize)
    assert packet["expires_unix"] == deadline
    assert "fingerprint" not in packet and "password" not in packet
    results = iter([(deadline, FINGERPRINT), (deadline, "cd" * 32)])
    with pytest.raises(broker.BrokerDenied, match="AUTHORIZATION_CHANGED"):
        broker._seal(request, authorize=lambda _: next(results))
