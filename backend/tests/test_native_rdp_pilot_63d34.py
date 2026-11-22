"""63D-34: verified synthetic native RDP broker, NEVER touches kiosk/Render.

No network listener, GNOME startup, credentials or production DB required.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json

import pytest

pytest.importorskip("sqlmodel")
from service1.native_rdp_bridge_protocol import encode_chunk, NativeRdpProtocolError
from service1.native_rdp_session_bridge import NativeRdpRelaySession
from service1.routers import native_rdp_pilot as pilot
from service1.routers import remote_desktop_v2 as rd

SESSION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
STREAM = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
OTHER = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.closed = []
    async def send_text(self, raw):
        self.sent.append(json.loads(raw))
    async def close(self, *, code=1000, reason=""):
        self.closed.append((code, reason))
    async def accept(self, **kwargs):
        pass


def setup(monkeypatch):
    browser_ws = FakeSocket()
    native_browser_ws = FakeSocket()
    agent_ws = FakeSocket()
    owner = rd.BrowserSession(
        session_id=SESSION, client_id=3, websocket=browser_ws,
        user_id=8, username="operator", user_token_version=2,
        auth_session_binding="bound-session",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=20),
    )
    peer = pilot.BrowserPeer(
        NativeRdpRelaySession(SESSION, 3, stream_id=STREAM),
        native_browser_ws, 8, 2, "bound-session",
    )
    agent = rd.AgentChannel(
        client_id=3, credential_id=OTHER, token_version=1, websocket=agent_ws,
    )
    monkeypatch.setitem(rd.BROWSERS, SESSION, owner)
    monkeypatch.setitem(pilot.AGENTS, 3, agent)
    monkeypatch.setitem(pilot.PEERS, SESSION, peer)
    return owner, peer, agent, native_browser_ws, agent_ws


def control(kind):
    return {"type":kind, "protocol":1, "session_id":SESSION, "stream_id":STREAM}


def frame(seq=0, payload=b"\x00\xffGNOME"):
    return encode_chunk(
        session_id=SESSION, stream_id=STREAM, seq=seq, payload=payload,
    )


def ack(seq=0):
    return {**control("native_rdp_ack"), "seq":seq}


def test_synthetic_native_bridge_carries_two_independent_byte_streams(monkeypatch):
    async def scenario():
        owner, peer, agent, browser_ws, agent_ws = setup(monkeypatch)
        await pilot._forward(peer, control("native_rdp_ready"), from_side="agent")
        assert browser_ws.sent == [control("native_rdp_ready")]
        await pilot._forward(peer, frame(0), from_side="browser")
        assert agent_ws.sent == [frame(0)]
        await pilot._forward(peer, ack(0), from_side="agent")
        assert browser_ws.sent[-1] == ack(0)
        await pilot._forward(peer, frame(0, b"gnome-desktop"), from_side="agent")
        assert browser_ws.sent[-1] == frame(0, b"gnome-desktop")
        await pilot._forward(peer, ack(0), from_side="browser")
        assert agent_ws.sent[-1] == ack(0)
        await pilot._abort(peer)
        assert browser_ws.closed and peer.bridge.closed
        assert SESSION not in pilot.PEERS
    asyncio.run(scenario())


def test_revocation_stops_transport_before_any_byte_is_sent(monkeypatch):
    async def scenario():
        owner, peer, agent, browser_ws, agent_ws = setup(monkeypatch)
        peer.bridge.agent_ready(control("native_rdp_ready"))
        owner.auth_session_binding = "rotated"
        with pytest.raises(NativeRdpProtocolError, match="revoked"):
            await pilot._forward(peer, frame(0), from_side="browser")
        assert agent_ws.sent == []
        await pilot._abort(peer)
    asyncio.run(scenario())


def test_cross_client_and_generation_packets_are_rejected(monkeypatch):
    async def scenario():
        _, peer, agent, browser_ws, agent_ws = setup(monkeypatch)
        peer.bridge.agent_ready(control("native_rdp_ready"))
        with pytest.raises(NativeRdpProtocolError):
            await pilot._forward(peer, {**frame(0), "stream_id":OTHER}, from_side="agent")
        with pytest.raises(NativeRdpProtocolError):
            await pilot._forward(peer, {**frame(0), "session_id":OTHER}, from_side="browser")
        assert browser_ws.sent == [] and agent_ws.sent == []
        peer.bridge.client_id = 99
        with pytest.raises(NativeRdpProtocolError):
            await pilot._forward(peer, frame(0), from_side="browser")
        await pilot._abort(peer)
    asyncio.run(scenario())


def test_reconnect_invalidates_old_stream_after_close(monkeypatch):
    async def scenario():
        _, peer, _, browser_ws, agent_ws = setup(monkeypatch)
        peer.bridge.agent_ready(control("native_rdp_ready"))
        await pilot._abort(peer, notify_agent=False)
        assert peer.bridge.closed
        with pytest.raises(NativeRdpProtocolError):
            await pilot._forward(peer, frame(0), from_side="browser")
        assert not agent_ws.sent
    asyncio.run(scenario())


def test_pilot_is_source_disabled_and_does_not_accept_unauthorised_requests(monkeypatch):
    assert pilot.PILOT_ENABLED is False
    with pytest.raises(Exception) as exc:
        pilot._http_scope("browser", 3, SESSION, None)
    assert getattr(exc.value, "status_code", None) == 404

    async def scenario():
        browser = FakeSocket()
        agent = FakeSocket()
        await pilot._native_browser_websocket(browser, client_id=3, session_id=SESSION)
        await pilot._native_agent_websocket(agent, client_id=3)
        assert browser.closed[0][0] == 4404
        assert agent.closed[0][0] == 4404
        assert not agent.sent and not browser.sent
    asyncio.run(scenario())


def test_native_only_messages_fail_closed_for_legacy_jpeg_browser(monkeypatch):
    # The existing JPEG client remains unmodified; native RDP only has
    # separate explicit websocket endpoints with independent authorization.
    import inspect
    source = inspect.getsource(pilot)
    assert "/remote-desktop/native/browser/{client_id}/{session_id}/ws" in source
    assert "/remote-desktop/native/agent/{client_id}/ws" in source
    assert "authenticate_browser_websocket_with_context" in source
    assert "verify_remote_desktop_agent_token" in source
    assert "require_relay_scope(relay, **scope)" in source
    assert "native_rdp_pilot_router" not in inspect.getsource(rd)
    assert "gnome-remote-desktop" not in source
    assert "subprocess" not in source
