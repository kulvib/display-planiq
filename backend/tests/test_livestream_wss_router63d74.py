"""ASGI wire/route tests with authorization boundary test doubles."""
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from service1.routers import livestream_wss as wss
from service1.livestream_wss_core import INIT, FRAGMENT, encode_frame

ORIGIN = "https://display.planiq.dk"
GEN = "62b641a3-bdad-4454-a5fd-cfb8e6774582"
SUB = f"/livestream-wss/clients/3/generations/{GEN}/subscribe"
PUB = f"/livestream-agent/clients/3/generations/{GEN}/media/ws"
TICKET = f"/livestream-wss/clients/3/generations/{GEN}/ticket"


@pytest.fixture
def api(monkeypatch):
    app = FastAPI()
    user = SimpleNamespace(id=7, token_version=2)
    app.dependency_overrides[wss.get_current_user] = lambda: user
    app.dependency_overrides[wss.oauth2_scheme] = lambda: "browser-test"
    monkeypatch.setattr(wss, "Session", lambda *_: nullcontext(None))
    monkeypatch.setattr(wss, "require_active_browser_auth_session_binding", lambda *a, **kw: "binding")
    monkeypatch.setattr(wss, "enforce_request_rate_limit", lambda *a, **kw: None)
    monkeypatch.setattr(wss, "_handshake_limit", lambda *_: None)

    def publisher(cid, generation, auth):
        if (cid, generation, auth) != (3, GEN, "Bearer agent-test"):
            raise HTTPException(403)

    def viewer(binding):
        if (binding.client_id, binding.generation_id, binding.user_id, binding.viewer_id) != (
                3, GEN, 7, "viewer-test"):
            raise HTTPException(403)

    monkeypatch.setattr(wss, "_check_publisher", publisher)
    monkeypatch.setattr(wss, "_check_viewer", viewer)
    app.include_router(wss.create_livestream_wss_router(allowed_origins=[ORIGIN]))
    with TestClient(app) as client:
        yield client


def ticket(api):
    response = api.post(TICKET, json={"viewer_id": "viewer-test"}, headers={"origin": ORIGIN})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    return [data["subprotocol"], data["ticket"]]


def test_ticket_origin_and_viewer(api):
    assert api.post(TICKET, json={"viewer_id": "viewer-test"}).status_code == 403
    assert api.post(TICKET, json={"viewer_id": "other"}, headers={"origin": ORIGIN}).status_code == 403
    with pytest.raises(ValueError):
        wss.create_livestream_wss_router(allowed_origins=["*"])


def test_no_auth_or_wrong_origin(api):
    with pytest.raises(WebSocketDisconnect):
        with api.websocket_connect(PUB):
            pytest.fail("unauthenticated publisher accepted")
    with pytest.raises(WebSocketDisconnect):
        with api.websocket_connect(PUB, headers={"authorization": "Bearer wrong"}):
            pytest.fail("wrong publisher accepted")
    with pytest.raises(WebSocketDisconnect):
        with api.websocket_connect(SUB, subprotocols=ticket(api), headers={"origin": "https://wrong.example"}):
            pytest.fail("cross-origin subscriber accepted")


def test_media_and_replay(api):
    first = encode_frame(INIT, 0, 0, b"init")
    fragment = encode_frame(FRAGMENT, 1, 1000000, b"fragment")
    with api.websocket_connect(PUB, headers={"authorization": "Bearer agent-test"}) as publisher:
        publisher.send_bytes(first)
        publisher.send_bytes(fragment)
        protocols = ticket(api)
        with api.websocket_connect(SUB, subprotocols=protocols, headers={"origin": ORIGIN}) as viewer:
            assert viewer.accepted_subprotocol == protocols[0]
            assert viewer.receive_bytes() == first
            assert viewer.receive_bytes() == fragment
            next_frame = encode_frame(FRAGMENT, 2, 2000000, b"next")
            publisher.send_bytes(next_frame)
            assert viewer.receive_bytes() == next_frame
        with pytest.raises(WebSocketDisconnect):
            with api.websocket_connect(SUB, subprotocols=protocols, headers={"origin": ORIGIN}):
                pytest.fail("replay accepted")


def test_malformed_publisher_clears_channel(api):
    with api.websocket_connect(PUB, headers={"authorization": "Bearer agent-test"}) as publisher:
        publisher.send_bytes(b"not-a-frame")
        with pytest.raises(WebSocketDisconnect):
            publisher.receive_bytes()
    with pytest.raises(WebSocketDisconnect):
        with api.websocket_connect(SUB, subprotocols=ticket(api), headers={"origin": ORIGIN}):
            pytest.fail("stale channel accepted")
