"""63D-8: bounded delivery and native-geometry SQL budget.

No production DB or client is used; the real broker is driven with an
in-memory channel and its existing authentication boundary remains intact.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

pytest.importorskip("sqlmodel")
from service1.routers import remote_desktop_v2 as remote


def browser():
    return remote.BrowserSession(
        session_id="63d8-test-session", client_id=3, websocket=object(),
        user_id=1, username="operator", user_token_version=1,
        auth_session_binding="test-binding", expires_at=datetime.now(timezone.utc),
    )


def test_native_geometry_skips_all_per_frame_database_resolution(monkeypatch):
    async def scenario():
        session = browser()
        monkeypatch.setitem(remote.BROWSERS, session.session_id, session)
        def unexpected_resolution(_client_id):
            raise AssertionError("A valid JPEG must not open a SQLModel resolution session")
        monkeypatch.setattr(remote, "_configured_resolution", unexpected_resolution)
        async def fake_send(_session_id, _client_id, _payload):
            return None
        monkeypatch.setattr(remote, "_send_browser", fake_send)
        try:
            for n in range(120):
                await remote._handle_control_agent_message(3, "credential", {
                    "type": "frame", "session_id": session.session_id,
                    "screen_width": 1920, "screen_height": 1080,
                    "data": str(n),
                })
            assert (session.screen_width, session.screen_height) == (1920, 1080)
        finally:
            remote.BROWSERS.pop(session.session_id, None)
    asyncio.run(scenario())


def test_missing_geometry_has_single_bounded_fallback(monkeypatch):
    async def scenario():
        session = browser()
        monkeypatch.setitem(remote.BROWSERS, session.session_id, session)
        calls = []
        monkeypatch.setattr(remote, "_configured_resolution", lambda client_id: (calls.append(client_id) or (1440, 900)))
        sent = []
        async def capture(_session_id, _client_id, payload):
            sent.append(payload)
        monkeypatch.setattr(remote, "_send_browser", capture)
        try:
            for _ in range(20):
                await remote._handle_control_agent_message(3, "credential", {
                    "type": "frame", "session_id": session.session_id,
                    "data": "snapshot", "screen_width": "invalid", "screen_height": "invalid",
                })
            assert calls == [3]
            assert all(item["screen_width"] == 1440 and item["screen_height"] == 900 for item in sent)
        finally:
            remote.BROWSERS.pop(session.session_id, None)
    asyncio.run(scenario())



def test_invalid_frame_geometry_after_native_update_reuses_valid_session_values(monkeypatch):
    async def scenario():
        session = browser()
        monkeypatch.setitem(remote.BROWSERS, session.session_id, session)
        def unexpected_resolution(_client_id):
            raise AssertionError("Known native geometry must never require a DB lookup")
        monkeypatch.setattr(remote, "_configured_resolution", unexpected_resolution)
        sent = []
        async def capture(_session_id, _client_id, payload):
            sent.append(payload)
        monkeypatch.setattr(remote, "_send_browser", capture)
        try:
            await remote._handle_control_agent_message(3, "credential", {
                "type": "frame", "session_id": session.session_id,
                "screen_width": "1600", "screen_height": "900", "data": "first",
            })
            await remote._handle_control_agent_message(3, "credential", {
                "type": "frame", "session_id": session.session_id,
                "screen_width": "invalid", "screen_height": "invalid", "data": "second",
            })
            assert [(frame["screen_width"], frame["screen_height"]) for frame in sent] == [
                (1600, 900), (1600, 900),
            ]
        finally:
            remote.BROWSERS.pop(session.session_id, None)
    asyncio.run(scenario())


def test_stalled_browser_keeps_only_newest_waiting_jpeg_and_all_control_events(monkeypatch):
    async def scenario():
        session = browser()
        monkeypatch.setitem(remote.BROWSERS, session.session_id, session)
        hold = asyncio.Event()
        sending = asyncio.Event()
        delivered = []
        async def fake_send(_socket, payload):
            if payload.get("type") == "frame" and not sending.is_set():
                sending.set()
                await hold.wait()
            delivered.append(payload)
        monkeypatch.setattr(remote, "_send_json", fake_send)
        try:
            await remote._send_browser(session.session_id, 3, {"type": "frame", "data": "first"})
            await sending.wait()
            for n in range(100):
                await remote._send_browser(session.session_id, 3, {"type": "frame", "data": str(n)})
            control = asyncio.create_task(remote._send_browser(
                session.session_id, 3, {"type": "error", "message": "input_failure"},
            ))
            await asyncio.sleep(0)
            hold.set()
            await control
            if session.frame_sender:
                await session.frame_sender
            frames = [item["data"] for item in delivered if item["type"] == "frame"]
            assert frames == ["first", "99"]
            assert len([x for x in delivered if x["type"] == "error"]) == 1
            assert session.pending_frame is None
        finally:
            if session.frame_sender:
                session.frame_sender.cancel()
            remote.BROWSERS.pop(session.session_id, None)
    asyncio.run(scenario())


def test_reject_unknown_session_before_any_frame_delivery(monkeypatch):
    async def scenario():
        delivered = []
        async def fake_send(*args): delivered.append(args)
        monkeypatch.setattr(remote, "_send_json", fake_send)
        await remote._handle_control_agent_message(3, "credential", {
            "type": "frame", "session_id": "unknown", "data": "should-never-deliver",
            "screen_width": 1920, "screen_height": 1080,
        })
        assert not delivered
    asyncio.run(scenario())
