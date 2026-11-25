"""Exercise real ASGI routing without adding TestClient/httpx2 dependencies.

Authorization calls use test doubles here; actual DB authorization is separate.
"""
import asyncio
from contextlib import nullcontext
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException

from service1.routers import livestream_wss as wss
from service1.livestream_wss_core import INIT, FRAGMENT, encode_frame

ORIGIN = "https://display.planiq.dk"
GEN = "62b641a3-bdad-4454-a5fd-cfb8e6774582"
SUB = f"/livestream-wss/clients/3/generations/{GEN}/subscribe"
PUB = f"/livestream-agent/clients/3/generations/{GEN}/media/ws"
TICKET = f"/livestream-wss/clients/3/generations/{GEN}/ticket"


@pytest.fixture
def app(monkeypatch):
    api = FastAPI()
    user = SimpleNamespace(id=7, token_version=2)
    api.dependency_overrides[wss.get_current_user] = lambda: user
    api.dependency_overrides[wss.oauth2_scheme] = lambda: "browser-test"
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
    api.include_router(wss.create_livestream_wss_router(allowed_origins=[ORIGIN]))
    return api


def scope(path, headers, *, socket=False, protocols=()):
    return {
        "type": "websocket" if socket else "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1", "scheme": "wss" if socket else "https",
        "path": path, "raw_path": path.encode(), "root_path": "",
        "query_string": b"", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": ("127.0.0.1", 1234), "server": ("test", 443),
        **({"subprotocols": list(protocols)} if socket else {"method": "POST"}),
    }


async def issue(app, viewer="viewer-test", origin=ORIGIN):
    headers = {"content-type": "application/json"}
    if origin is not None:
        headers["origin"] = origin
    messages = []

    async def receive():
        return {"type": "http.request", "body": json.dumps({"viewer_id": viewer}).encode(),
                "more_body": False}

    async def send(message):
        messages.append(message)

    await asyncio.wait_for(app(scope(TICKET, headers), receive, send), 5)
    start = messages[0]
    body = json.loads(b"".join(m.get("body", b"") for m in messages[1:]))
    return start["status"], dict(start["headers"]), body


async def ticket(app):
    code, headers, body = await issue(app)
    assert code == 200 and headers[b"cache-control"] == b"no-store"
    return [body["subprotocol"], body["ticket"]]


class Socket:
    def __init__(self, app, path, headers=None, protocols=()):
        headers = dict(headers or {})
        if protocols:
            headers["sec-websocket-protocol"] = ", ".join(protocols)
        self.incoming = asyncio.Queue(maxsize=8)
        self.outgoing = asyncio.Queue(maxsize=8)
        self.incoming.put_nowait({"type": "websocket.connect"})
        self.task = asyncio.create_task(app(
            scope(path, headers, socket=True, protocols=protocols),
            self.incoming.get, self.outgoing.put,
        ))

    async def next(self):
        return await asyncio.wait_for(self.outgoing.get(), 5)

    async def send(self, payload):
        await asyncio.wait_for(self.incoming.put({"type": "websocket.receive", "bytes": payload}), 5)

    async def close(self):
        if not self.task.done():
            await self.incoming.put({"type": "websocket.disconnect", "code": 1000})
        try:
            await asyncio.wait_for(self.task, 5)
        finally:
            if not self.task.done():
                self.task.cancel()
                await asyncio.gather(self.task, return_exceptions=True)


def test_ticket_origin_and_viewer(app):
    async def scenario():
        assert (await issue(app, origin=None))[0] == 403
        assert (await issue(app, viewer="other"))[0] == 403
        with pytest.raises(ValueError):
            wss.create_livestream_wss_router(allowed_origins=["*"])
    asyncio.run(scenario())


def test_no_auth_or_wrong_origin(app):
    async def scenario():
        for path, headers, protocols in [
            (PUB, {}, ()), (PUB, {"authorization": "Bearer wrong"}, ()),
            (SUB, {"origin": "https://wrong.example"}, await ticket(app)),
        ]:
            sock = Socket(app, path, headers, protocols)
            try:
                assert (await sock.next())["type"] == "websocket.close"
            finally:
                await sock.close()
    asyncio.run(scenario())


def test_media_and_replay(app):
    async def scenario():
        first = encode_frame(INIT, 0, 0, b"init")
        frag = encode_frame(FRAGMENT, 1, 1000000, b"fragment")
        publisher = Socket(app, PUB, {"authorization": "Bearer agent-test"})
        try:
            assert (await publisher.next())["type"] == "websocket.accept"
            await publisher.send(first)
            await publisher.send(frag)
            protocols = await ticket(app)
            viewer = Socket(app, SUB, {"origin": ORIGIN}, protocols)
            try:
                accepted = await viewer.next()
                assert accepted["type"] == "websocket.accept"
                assert accepted["subprotocol"] == protocols[0]
                assert (await viewer.next())["bytes"] == first
                assert (await viewer.next())["bytes"] == frag
                nxt = encode_frame(FRAGMENT, 2, 2000000, b"next")
                await publisher.send(nxt)
                assert (await viewer.next())["bytes"] == nxt
            finally:
                await viewer.close()
            replay = Socket(app, SUB, {"origin": ORIGIN}, protocols)
            try:
                assert (await replay.next())["type"] == "websocket.close"
            finally:
                await replay.close()
        finally:
            await publisher.close()
    asyncio.run(scenario())


def test_malformed_publisher_clears_channel(app):
    async def scenario():
        publisher = Socket(app, PUB, {"authorization": "Bearer agent-test"})
        try:
            assert (await publisher.next())["type"] == "websocket.accept"
            await publisher.send(b"not-a-frame")
            assert (await publisher.next())["type"] == "websocket.close"
        finally:
            await publisher.close()
        viewer = Socket(app, SUB, {"origin": ORIGIN}, await ticket(app))
        try:
            assert (await viewer.next())["type"] == "websocket.close"
        finally:
            await viewer.close()
    asyncio.run(scenario())
