"""Source-level tests; never start GNOME or install systemd services."""
import socket

import pytest

from scripts import clientflow_63d53_rdp_ipc as ipc


def test_bounded_frame_and_peer_disconnect():
    left, right = socket.socketpair()
    with left, right:
        ipc.send_frame(left, {"schema": 1}, ipc.MAX_REQUEST)
        assert ipc.read_frame(right, ipc.MAX_REQUEST) == {"schema": 1}
        ipc.require_open(right)
        left.close()
        with pytest.raises(ipc.IpcDenied, match="AGENT_CLOSED"):
            ipc.require_open(right)


@pytest.mark.parametrize("payload", [b"[]\n", b"{}\n{}\n", b"x" * 1025])
def test_invalid_frame(payload):
    left, right = socket.socketpair()
    with left, right:
        left.sendall(payload)
        with pytest.raises((ipc.IpcDenied, ValueError)):
            ipc.read_frame(right, ipc.MAX_REQUEST)


def test_sealer_refuses_nonroot_peer(monkeypatch):
    monkeypatch.setattr(ipc, "peer_uid", lambda _: 1000)
    with pytest.raises(ipc.IpcDenied, match="UNAUTHORIZED_LIFECYCLE"):
        ipc.serve_sealer(None)


def test_lifecycle_refuses_unrelated_peer(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(ipc.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=123))
    monkeypatch.setattr(ipc, "peer_uid", lambda _: 456)
    with pytest.raises(ipc.IpcDenied, match="UNAUTHORIZED_AGENT"):
        ipc.serve_lifecycle(None)
