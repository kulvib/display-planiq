"""Byte preservation and safe launch-gate tests; no physical GNOME claim."""
import asyncio
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client" / "runtime"))

from clientflow_runtime import native_rdp_forwarder as forwarder  # noqa: E402
from service1.routers import native_rdp_tunnel as relay  # noqa: E402


class SocketStub:
    def __init__(self):
        self.rx = asyncio.Queue()
        self.sent = []

    async def receive(self):
        return await self.rx.get()

    async def send_bytes(self, packet):
        self.sent.append(packet)


async def _exercise(packets):
    browser, agent = SocketStub(), SocketStub()
    instance = relay.NativeRdpTunnel(
        client_id=3, session_id="bd29ed7a-ad54-4f15-8028-5728fffe2156",
        tunnel_id="8457d398-2e89-4292-995b-54a67983623a",
        user_id=42, browser=browser, agent=agent,
    )
    instance.authorized_browser = lambda: True
    instance.authorized_agent = lambda: True
    task = asyncio.create_task(relay._pump(instance, browser, browser_side=True))
    for message in packets:
        await browser.rx.put(message)
    await asyncio.wait_for(task, 2)
    return agent.sent


def test_binary_chunks_preserve_order_and_data():
    result = asyncio.run(_exercise([
        {"type": "websocket.receive", "bytes": b"\x00\xffRDP"},
        {"type": "websocket.receive", "bytes": b"\x7f" * 512},
        {"type": "websocket.disconnect"},
    ]))
    assert result == [b"\x00\xffRDP", b"\x7f" * 512]


def test_text_or_oversized_messages_never_cross_agent_boundary():
    assert asyncio.run(_exercise([{"type": "websocket.receive", "text": "RDP"}])) == []
    assert asyncio.run(_exercise([
        {"type": "websocket.receive", "bytes": b"R" * (relay.MAX_BINARY_PACKET + 1)},
    ])) == []


def test_disconnect_does_not_replay_old_rdp_data():
    assert asyncio.run(_exercise([{"type": "websocket.disconnect"}])) == []


def test_root_owned_approval_marker_is_required(tmp_path, monkeypatch):
    marker = tmp_path / "approval"
    monkeypatch.setattr(forwarder, "GUARD_MARKER", marker)
    with pytest.raises(forwarder.NativeRdpNotApproved):
        forwarder.ensure_native_rdp_guard(client_id=3)
    marker.write_text("example-host:3\n", encoding="ascii")
    marker.chmod(0o644)
    with pytest.raises(forwarder.NativeRdpNotApproved):
        forwarder.ensure_native_rdp_guard(client_id=3)


def test_native_rdp_tcp_destination_is_fixed_loopback():
    assert forwarder.GNOME_RDP_HOST == "127.0.0.1"
    assert forwarder.GNOME_RDP_PORT == 3389
    assert forwarder.GUARD_MARKER.is_absolute()


def test_agent_socket_is_bound_to_live_control_credential_not_old_jwt(monkeypatch):
    from types import SimpleNamespace

    browser = SocketStub()
    tunnel = relay.NativeRdpTunnel(
        client_id=3, session_id="bd29ed7a-ad54-4f15-8028-5728fffe2156",
        tunnel_id="8457d398-2e89-4292-995b-54a67983623a",
        user_id=42, browser=browser,
    )
    tunnel.agent_credential_id = "rdp-credential"
    tunnel.agent_token_version = 7
    control = SimpleNamespace(credential_id="rdp-credential", token_version=7)
    monkeypatch.setitem(relay.CONTROL_AGENTS, 3, control)
    monkeypatch.setattr(relay, "_remote_desktop_agent_channel_valid", lambda _: True)
    assert tunnel.authorized_agent()
    # A renewed handshake JWT is not needed while the same credential remains
    # approved. Changing its persisted version must still revoke immediately.
    control.token_version = 8
    assert not tunnel.authorized_agent()
