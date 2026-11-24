"""63D-49 sealed autologin proof: root-only credentials never reach backend."""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import time
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[2]
BROKER = ROOT / "scripts" / "clientflow_63d49_autologin_broker.py"
SESSION = "c8e4a40e-a48c-48a1-9a2c-35035cb9e9bc"
CHALLENGE = "73a81005-99cc-4efa-9f7c-9e82e82f2fa9"


def module():
    spec = importlib.util.spec_from_file_location("rdp63d49_broker", BROKER)
    obj = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = obj
    spec.loader.exec_module(obj)
    return obj


def browser_pair():
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    pair = ec.generate_private_key(ec.SECP256R1())
    pub = pair.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return pair, pub


def b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def un64(raw):
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


def test_root_broker_uses_ecdh_hkdf_aes_gcm_and_seals_to_requesting_browser(tmp_path, monkeypatch):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    m = module()
    cert = tmp_path / "tls.crt"
    cert.write_text(
        "-----BEGIN CERTIFICATE-----\n"
        + base64.b64encode(b"test-public-gnome-cert").decode("ascii")
        + "\n-----END CERTIFICATE-----\n"
    )
    monkeypatch.setattr(m, "_safe_grant", lambda: int(time.time()) + 45)
    monkeypatch.setattr(m, "_verify_physical_firewall", lambda: None)
    secret = "s" * 45
    monkeypatch.setattr(m, "_root_private", lambda *_a, **_kw: ("cfpilotabcdef12\n" + secret + "\n").encode())
    monkeypatch.setattr(m, "_cert_path", lambda _uid: cert)
    monkeypatch.setattr(m.pwd, "getpwnam", lambda _user: SimpleNamespace(pw_uid=1000))

    private, public = browser_pair()
    request = {
        "schema": 1, "session_id": SESSION, "request_id": CHALLENGE,
        "public_key": b64(public),
    }
    packet = m._seal(request)
    as_json = json.dumps(packet)
    assert secret not in as_json
    assert "cfpilotabcdef12" not in as_json
    assert "tls.crt" not in as_json
    assert set(packet) == {
        "schema", "session_id", "request_id", "public_key",
        "salt", "nonce", "ciphertext", "expires_unix",
    }

    server = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), un64(packet["public_key"]))
    shared = private.exchange(ec.ECDH(), server)
    info = f"{m.MAGIC}|{SESSION}|{CHALLENGE}".encode()
    aad = f"{m.MAGIC}|3|{SESSION}|{CHALLENGE}".encode()
    key = HKDF(hashes.SHA256(), 32, un64(packet["salt"]), info).derive(shared)
    plaintext = AESGCM(key).decrypt(un64(packet["nonce"]), un64(packet["ciphertext"]), aad)
    payload = json.loads(plaintext)
    assert payload["username"] == "cfpilotabcdef12"
    assert payload["password"] == secret
    assert payload["fingerprint"] == hashlib.sha256(b"test-public-gnome-cert").hexdigest()
    assert payload["expires_unix"] == packet["expires_unix"]
    with pytest.raises(Exception):
        AESGCM(key).decrypt(un64(packet["nonce"]), un64(packet["ciphertext"]),
                           f"{m.MAGIC}|3|{SESSION}|{uuid.uuid4()}".encode())


@pytest.mark.parametrize("mutator", [
    lambda req: req.update(schema=True),
    lambda req: req.update(session_id="other"),
    lambda req: req.update(request_id="other"),
    lambda req: req.update(public_key="invalid"),
    lambda req: req.update(password="plain"),
    lambda req: req.pop("public_key"),
])
def test_root_broker_rejects_unbound_or_plaintext_requests(mutator, monkeypatch):
    m = module()
    browser, pub = browser_pair()
    del browser
    request = {
        "schema": 1, "session_id": SESSION, "request_id": CHALLENGE,
        "public_key": b64(pub),
    }
    mutator(request)
    with pytest.raises(m.BrokerDenied):
        m._seal(request)


def test_root_broker_cannot_serve_without_physical_root_guard(monkeypatch):
    m = module()
    monkeypatch.setattr(m.os, "geteuid", lambda: 1000)
    with pytest.raises(m.BrokerDenied, match="WRONG_MACHINE_OR_PRIVILEGE"):
        m._safe_grant()


def test_root_broker_must_be_unprivileged_peer_only_and_never_print_secrets():
    source = BROKER.read_text()
    assert "socket.SO_PEERCRED" in source
    assert "peer_uid" not in source or "uid != agent.pw_uid" in source
    assert "stat.S_ISSOCK" in source
    assert "os.chmod(SOCKET_PATH, 0o660)" in source
    assert "GNOME_RUNNER_SHA256" in source
    assert "_verify_physical_firewall()" in source
    assert "SESSION_ALREADY_ISSUED" in source
    assert "MAX_REQUEST = 1024" in source
    assert 'print("RDP_AUTOLOGIN_BROKER=READY"' in source
    assert "print(username)" not in source
    assert "print(password)" not in source
    assert "ENCRYPTION_FALLBACK" not in source


def test_socket_activated_root_service_is_offline_and_independently_bounded():
    root = ROOT / "experiments" / "63d49-autologin"
    sock = (root / "clientflow-rdp-autologin.socket").read_text()
    service = (root / "clientflow-rdp-autologin.service").read_text()
    assert "ListenStream=/run/clientflow/rdp-autologin-v1.sock" in sock
    assert "SocketGroup=clientflow-remote-desktop-agent" in sock
    assert "SocketMode=0660" in sock
    assert "RemoveOnStop=yes" in sock
    assert "Accept=no" in sock
    assert "Backlog=4" in sock
    assert "RuntimeMaxSec=360" in service
    assert "User=root" in service
    assert "NoNewPrivileges=yes" in service
    assert "ProtectSystem=strict" in service
    assert "ProtectHome=yes" in service
    assert "RestrictAddressFamilies=AF_UNIX" in service
    assert "ConditionPathExists=/var/lib/clientflow/rdp-pilot-63d30/state.json" in service
    assert "CapabilityBoundingSet=" in service
    assert not any(
        marker in sock + service
        for marker in ("0.0.0.0", "ListenDatagram=", "ListenStream=3389", "ListenStream=4822")
    )
    broker = BROKER.read_text()
    assert "LISTEN_FDS" in broker and "LISTEN_PID" in broker
    assert "socket.fromfd(3, socket.AF_UNIX, socket.SOCK_STREAM)" in broker
    assert "UNTRUSTED_SYSTEMD_SOCKET_OWNER" in broker
    assert "_verify_physical_firewall()" in broker
