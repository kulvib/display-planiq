"""63D-49 agent cannot read GNOME credentials or bypass the root socket."""
from __future__ import annotations

import asyncio
from pathlib import Path
import stat
import sys
import time
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client" / "runtime"))

from clientflow_runtime import native_rdp_autologin as autologin  # noqa: E402

SESSION = "c8e4a40e-a48c-48a1-9a2c-35035cb9e9bc"
REQUEST = "73a81005-99cc-4efa-9f7c-9e82e82f2fa9"
PUBLIC = "A" * 87


def test_envelope_rejects_wrong_session_and_expired_lease():
    frame = {
        "schema": 1, "session_id": SESSION, "request_id": REQUEST,
        "public_key": "A" * 87, "salt": "A" * 22,
        "nonce": "A" * 16, "ciphertext": "A" * 200,
        "expires_unix": int(time.time()) + 40,
    }
    autologin._validate_envelope(frame, session_id=SESSION, request_id=REQUEST)
    with pytest.raises(autologin.AutologinUnavailable):
        autologin._validate_envelope(frame, session_id=REQUEST, request_id=REQUEST)
    frame["expires_unix"] = int(time.time()) - 1
    with pytest.raises(autologin.AutologinUnavailable):
        autologin._validate_envelope(frame, session_id=SESSION, request_id=REQUEST)
    frame["expires_unix"] = int(time.time()) + 40
    frame["password"] = "plaintext-never-forward"
    with pytest.raises(autologin.AutologinUnavailable):
        autologin._validate_envelope(frame, session_id=SESSION, request_id=REQUEST)


def test_agent_checks_root_owned_unix_socket_before_connect(monkeypatch):
    class SocketFile:
        def lstat(self):
            return SimpleNamespace(st_mode=stat.S_IFREG | 0o666, st_uid=1000)

    class ParentFile:
        def lstat(self):
            return SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0)

    class FakePath:
        parent = ParentFile()

        def lstat(self):
            return SocketFile().lstat()

    monkeypatch.setattr(autologin, "SOCKET", FakePath())
    with pytest.raises(autologin.AutologinUnavailable, match="UNTRUSTED"):
        autologin._verify_local_socket()


def test_agent_must_require_live_physical_root_guard_before_sealed_login(monkeypatch):
    def reject(**_kwargs):
        raise autologin.AutologinUnavailable("ROOT_GUARD_MISSING")

    monkeypatch.setattr(autologin, "ensure_native_rdp_guard", reject)
    with pytest.raises(autologin.AutologinUnavailable, match="ROOT_GUARD_MISSING"):
        asyncio.run(autologin.request_sealed_native_rdp_login(
            client_id=3, session_id=SESSION,
            request_id=REQUEST, public_key=PUBLIC,
        ))


def test_agent_never_reads_root_password_file_or_logs_unsealed_values():
    source = (ROOT / "client" / "runtime" / "clientflow_runtime" /
              "native_rdp_autologin.py").read_text()
    assert "ensure_native_rdp_guard(client_id=client_id)" in source
    assert "open_unix_connection" in source
    assert "request_id" in source and "session_id" in source
    assert "readline()" in source
    assert "MAX_REPLY = 2048" in source
    assert '"/run/clientflow-rdp-63d30/credentials"' not in source
    assert "print(" not in source
    assert "logger." not in source
    assert "localStorage" not in source
