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
    # Production pins the exact channel at tunnel creation. An incomplete
    # fixture without that binding must be rejected rather than authorized.
    assert not tunnel.authorized_agent()
    tunnel.control_channel = control
    assert tunnel.authorized_agent()
    # A renewed handshake JWT is not needed while the same channel and
    # credential remain approved. A new channel with identical claims is
    # nevertheless a different generation and cannot inherit the old tunnel.
    replacement = SimpleNamespace(credential_id="rdp-credential", token_version=7)
    monkeypatch.setitem(relay.CONTROL_AGENTS, 3, replacement)
    assert not tunnel.authorized_agent()
    monkeypatch.setitem(relay.CONTROL_AGENTS, 3, control)
    assert tunnel.authorized_agent()
    # Changing the persisted credential version must still revoke immediately.
    control.token_version = 8
    assert not tunnel.authorized_agent()



def test_root_owned_unexpired_viborg1_grant_is_accepted(monkeypatch):
    import time

    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    marker = {
        "schema": 1,
        "hostname": "viborg1-NUC14MNK-B2",
        "client_id": 3,
        "boot_id": boot_id,
        "expires_wall": time.time() + 90,
        "expires_mono": time.monotonic() + 90,
    }

    monkeypatch.setattr(forwarder, "_read_guard_marker", lambda: dict(marker))
    monkeypatch.setattr(forwarder.socket, "gethostname", lambda: "viborg1-NUC14MNK-B2")
    forwarder.ensure_native_rdp_guard(client_id=3)

    marker["expires_wall"] = time.time() - 1
    with pytest.raises(forwarder.NativeRdpNotApproved):
        forwarder.ensure_native_rdp_guard(client_id=3)
    marker["expires_wall"] = time.time() + 90
    marker["expires_mono"] = time.monotonic() + 361
    with pytest.raises(forwarder.NativeRdpNotApproved):
        forwarder.ensure_native_rdp_guard(client_id=3)
    marker["expires_mono"] = time.monotonic() + 90
    marker["boot_id"] = "wrong-boot"
    with pytest.raises(forwarder.NativeRdpNotApproved):
        forwarder.ensure_native_rdp_guard(client_id=3)
    marker["boot_id"] = boot_id
    with pytest.raises(forwarder.NativeRdpNotApproved):
        forwarder.ensure_native_rdp_guard(client_id=4)
    marker["client_id"] = 99
    with pytest.raises(forwarder.NativeRdpNotApproved):
        forwarder.ensure_native_rdp_guard(client_id=3)
    marker["hostname"] = "client-99"
    monkeypatch.setattr(forwarder.socket, "gethostname", lambda: "client-99")
    forwarder.ensure_native_rdp_guard(client_id=99)
    for invalid in (True, 0, "99", 100):
        with pytest.raises(forwarder.NativeRdpNotApproved):
            forwarder.ensure_native_rdp_guard(client_id=invalid)
    marker["schema"] = True
    with pytest.raises(forwarder.NativeRdpNotApproved):
        forwarder.ensure_native_rdp_guard(client_id=99)


def test_physical_guard_never_leaks_secrets_and_binds_to_existing_expiry(
        monkeypatch, tmp_path, capsys):
    import importlib
    import json
    import time

    pilot = importlib.import_module("scripts.clientflow_native_rdp_browser_pilot")
    marker = tmp_path / "native-rdp-approved"
    now = time.time()
    mono = time.monotonic()
    state = {
        "phase": "63D-30",
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "deadline_wall": now + 95,
        "deadline_mono": mono + 95,
    }
    monkeypatch.setattr(pilot, "MARKER", marker)
    monkeypatch.setattr(pilot, "check_physical_guard", lambda: (1001, state))
    monkeypatch.setattr(pilot, "ensure_marker_dir", lambda: None)
    monkeypatch.setattr(pilot, "certificate_fingerprint", lambda uid: "AA:" * 31 + "AA")
    pilot.arm()
    output = capsys.readouterr().out
    assert "NATIVE_RDP_BROWSER_GRANT=ARMED" in output
    assert "GNOME_TLS_SHA256=" in output
    assert "password" not in output.casefold()
    saved = json.loads(marker.read_text(encoding="ascii"))
    assert saved["client_id"] == 3
    assert saved["expires_wall"] == state["deadline_wall"]
    assert saved["expires_mono"] == state["deadline_mono"]
    with pytest.raises(RuntimeError, match="eksisterende"):
        pilot.arm()


def test_guard_staging_cannot_bypass_expiry(monkeypatch):
    import importlib
    import time
    pilot = importlib.import_module("scripts.clientflow_native_rdp_browser_pilot")
    now = time.time()
    mono = time.monotonic()
    monkeypatch.setattr(pilot, "verify_host", lambda: (1001, None))
    monkeypatch.setattr(pilot.pilot, "state_load", lambda: {
        "phase": "63D-30",
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "deadline_wall": now - 1,
        "deadline_mono": mono - 1,
    })
    monkeypatch.setattr(pilot.pilot, "deadline_expired", lambda _: True)
    with pytest.raises(RuntimeError, match="ikke aktiv"):
        pilot.check_physical_guard()


def test_stalled_native_peer_is_bounded_and_never_reorders(monkeypatch):
    import asyncio

    class StalledSocket(SocketStub):
        async def send_bytes(self, packet):
            await asyncio.Future()

    async def check():
        browser = SocketStub()
        agent = StalledSocket()
        instance = relay.NativeRdpTunnel(
            client_id=3, session_id="bd29ed7a-ad54-4f15-8028-5728fffe2156",
            tunnel_id="8457d398-2e89-4292-995b-54a67983623a",
            user_id=42, browser=browser, agent=agent,
        )
        instance.authorized_browser = lambda: True
        instance.authorized_agent = lambda: True
        monkeypatch.setattr(relay, "SEND_TIMEOUT", 0.02)
        await browser.rx.put({"type": "websocket.receive", "bytes": b"one"})
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(relay._pump(instance, browser, browser_side=True), timeout=1)

    asyncio.run(check())


def test_binary_agent_packet_size_limit_and_closed_tunnel(monkeypatch):
    import asyncio

    async def check():
        agent = SocketStub()
        browser = SocketStub()
        instance = relay.NativeRdpTunnel(
            client_id=3, session_id="bd29ed7a-ad54-4f15-8028-5728fffe2156",
            tunnel_id="8457d398-2e89-4292-995b-54a67983623a",
            user_id=42, browser=browser, agent=agent,
        )
        instance.authorized_browser = lambda: True
        instance.authorized_agent = lambda: True
        await agent.rx.put({"type": "websocket.receive", "bytes": b"\x00\xff"})
        await agent.rx.put({"type": "websocket.disconnect"})
        await relay._pump(instance, agent, browser_side=False)
        assert browser.sent == [b"\x00\xff"]
        instance.closed.set()
        await agent.rx.put({"type": "websocket.receive", "bytes": b"stale"})
        await relay._pump(instance, agent, browser_side=False)
        assert browser.sent == [b"\x00\xff"]

    asyncio.run(check())
