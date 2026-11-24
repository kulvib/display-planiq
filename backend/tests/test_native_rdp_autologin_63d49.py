"""63D-49 superadmin-only one-shot sealed GNOME RDP broker boundaries."""
import asyncio
import time
from types import SimpleNamespace

import pytest

from service1.routers import remote_desktop_v2 as broker

CLIENT = 3
SESSION = "c8e4a40e-a48c-48a1-9a2c-35035cb9e9bc"
CHALLENGE = "73a81005-99cc-4efa-9f7c-9e82e82f2fa9"
PUB = "A" * 87


def browser():
    return SimpleNamespace(
        client_id=CLIENT,
        session_id=SESSION,
        native_rdp_autologin_pending=None,
        native_rdp_autologin_expires_at=0.0,
    )


def envelope():
    return {
        "schema": 1,
        "session_id": SESSION,
        "request_id": CHALLENGE,
        "public_key": "A" * 87,
        "salt": "A" * 22,
        "nonce": "A" * 16,
        "ciphertext": "A" * 420,
        "expires_unix": int(time.time()) + 45,
    }


def setup_broker(monkeypatch, *, admin=True):
    item = browser()
    forwarded = []
    delivered = []

    async def find(sid, cid):
        return item if sid == SESSION and cid == CLIENT else None

    async def send_agent(_agent, payload):
        forwarded.append(payload)

    async def send_browser(_sid, _cid, payload):
        delivered.append(payload)

    monkeypatch.setitem(broker.CONTROL_AGENTS, CLIENT, SimpleNamespace())
    monkeypatch.setattr(broker, "_browser_for_session", find)
    monkeypatch.setattr(broker, "_send_agent", send_agent)
    monkeypatch.setattr(broker, "_send_browser", send_browser)
    monkeypatch.setattr(broker, "_remote_desktop_browser_auth_state",
                        lambda _browser: (SimpleNamespace(is_superadmin=True), "ok") if admin else (None, "login_session_invalid"))
    return item, forwarded, delivered


def test_only_live_superadmin_can_issue_sealed_request_and_reply_once(monkeypatch):
    item, forwarded, delivered = setup_broker(monkeypatch)
    request = {"type": "native_rdp_autologin_request", "request_id": CHALLENGE, "public_key": PUB}
    asyncio.run(broker._browser_control_message(CLIENT, SESSION, request))
    assert len(forwarded) == 1
    assert forwarded[0]["session_id"] == SESSION
    assert forwarded[0]["public_key"] == PUB
    assert item.native_rdp_autologin_pending == CHALLENGE

    reply = {
        "type": "native_rdp_autologin_envelope",
        "session_id": SESSION,
        "request_id": CHALLENGE,
        "envelope": envelope(),
    }
    asyncio.run(broker._handle_control_agent_message(CLIENT, "mock-agent-credential", reply))
    assert len(delivered) == 1
    assert delivered[0]["type"] == "native_rdp_autologin_envelope"
    assert delivered[0]["envelope"] == envelope()
    assert item.native_rdp_autologin_pending is None
    asyncio.run(broker._handle_control_agent_message(CLIENT, "mock-agent-credential", reply))
    assert len(delivered) == 1, "duplicate/replay must be ignored"


@pytest.mark.parametrize("attempt", [
    {"request_id": "wrong", "public_key": PUB},
    {"request_id": CHALLENGE, "public_key": "not-p256"},
    {"request_id": CHALLENGE, "public_key": PUB, "password": "SENSITIVE"},
])
def test_bad_requests_cannot_leak_raw_secrets(monkeypatch, attempt):
    item, forwarded, delivered = setup_broker(monkeypatch)
    asyncio.run(broker._browser_control_message(
        CLIENT, SESSION, {"type": "native_rdp_autologin_request", **attempt}
    ))
    # Extra fields are stripped before forwarding; valid fields only.
    assert all("password" not in payload for payload in forwarded)
    assert all("SENSITIVE" not in repr(payload) for payload in forwarded + delivered)
    assert not any("password" in payload for payload in delivered)


def test_revoked_superadmin_or_changed_session_blocks_request_and_response(monkeypatch):
    item, forwarded, delivered = setup_broker(monkeypatch, admin=False)
    asyncio.run(broker._browser_control_message(CLIENT, SESSION, {
        "type": "native_rdp_autologin_request", "request_id": CHALLENGE, "public_key": PUB,
    }))
    assert not forwarded
    assert delivered[-1]["type"] == "native_rdp_autologin_denied"

    item.native_rdp_autologin_pending = CHALLENGE
    item.native_rdp_autologin_expires_at = time.monotonic() + 10
    asyncio.run(broker._handle_control_agent_message(CLIENT, "mock-agent-credential", {
        "type": "native_rdp_autologin_envelope",
        "session_id": SESSION,
        "request_id": CHALLENGE, "envelope": envelope(),
    }))
    assert not any(payload["type"] == "native_rdp_autologin_envelope" for payload in delivered)


def test_expired_or_wrong_session_response_is_denied(monkeypatch):
    item, _, delivered = setup_broker(monkeypatch)
    item.native_rdp_autologin_pending = CHALLENGE
    item.native_rdp_autologin_expires_at = time.monotonic() - 1
    asyncio.run(broker._handle_control_agent_message(CLIENT, "agent", {
        "type": "native_rdp_autologin_envelope",
        "session_id": SESSION, "request_id": CHALLENGE,
        "envelope": envelope(),
    }))
    assert delivered == []
    item.native_rdp_autologin_expires_at = time.monotonic() + 10
    forged = envelope()
    forged["session_id"] = "c8e4a40e-a48c-48a1-9a2c-35035cb9e9bd"
    asyncio.run(broker._handle_control_agent_message(CLIENT, "agent", {
        "type": "native_rdp_autologin_envelope", "session_id": SESSION,
        "request_id": CHALLENGE, "envelope": forged,
    }))
    assert delivered == []
