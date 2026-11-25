"""ASGI/native handler transport matrix; identity and DB boundaries stubbed."""
import asyncio
from contextlib import nullcontext
from types import SimpleNamespace

import json
from urllib.parse import urlsplit
import pytest
from fastapi import FastAPI
from starlette.datastructures import Headers

from service1.native_rdp_https_core import QueueBudget, encode_batch, decode_batch
from service1.routers import native_rdp_tunnel as native
from service1.routers import native_rdp_https_http as http
from service1.routers import remote_desktop_v2 as control

SESSION = "12345678-1234-4234-8234-123456789abc"
ORIGIN = "https://display.planiq.dk"


class ASGIClient:
    """In-process HTTP driver; no extra dependency or mocked routes."""

    def __init__(self, app):
        self.app = app

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass

    async def request(self, method, path, headers, content=b""):
        parsed = urlsplit(path)
        raw = [(key.lower().encode("ascii"), value.encode("ascii"))
               for key, value in headers.items()]
        raw += [(b"host", b"api.display.planiq.dk"),
                (b"content-length", str(len(content)).encode("ascii"))]
        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1", "method": method, "scheme": "https",
            "path": parsed.path, "raw_path": parsed.path.encode("ascii"),
            "root_path": "", "query_string": parsed.query.encode("ascii"),
            "headers": raw, "client": ("127.0.0.1", 12345),
            "server": ("api.display.planiq.dk", 443),
        }
        messages = []
        received = False

        async def receive():
            nonlocal received
            if received:
                await asyncio.Future()
            received = True
            return {"type": "http.request", "body": content, "more_body": False}

        async def send(message):
            messages.append(message)

        await self.app(scope, receive, send)
        start = next(message for message in messages if message["type"] == "http.response.start")
        body = b"".join(message.get("body", b"") for message in messages
                        if message["type"] == "http.response.body")
        return SimpleNamespace(status_code=start["status"], headers=Headers(raw=start["headers"]),
                               content=body, text=body.decode("utf-8", errors="replace"),
                               json=lambda: json.loads(body))

    async def post(self, path, *, headers, content=b""):
        return await self.request("POST", path, headers, content)

    async def get(self, path, *, headers):
        return await self.request("GET", path, headers)


class Socket:
    def __init__(self, headers):
        self.headers = headers
        self.cookies = {}
        self.query_params = {}
        self.client = None
        self.accepted = asyncio.Event()
        self.incoming = asyncio.Queue()
        self.outgoing = asyncio.Queue()
        self.closed = False

    async def accept(self, **kwargs):
        self.accepted.set()

    async def receive(self):
        return await self.incoming.get()

    async def send_bytes(self, body):
        await self.outgoing.put(body)

    async def close(self, **kwargs):
        if not self.closed:
            self.closed = True
            await self.incoming.put({"type": "websocket.disconnect", "code": 1000})


@pytest.mark.parametrize("browser_https,agent_https", [
    (False, False), (True, False), (False, True), (True, True),
])
def test_native_binary_mixed_transport_matrix(monkeypatch, browser_https, agent_https):
    async def exercise():
        monkeypatch.setenv("CLIENTFLOW_NATIVE_BINARY_HTTPS_ENABLED", "true")
        user = SimpleNamespace(id=42, token_version=7, is_active=True, is_superadmin=True)
        credential = SimpleNamespace(id="credential", token_version=5)
        channel = SimpleNamespace(credential_id="credential", token_version=5)
        active = SimpleNamespace(client_id=3, user_id=42, user_token_version=7,
                                 auth_session_binding="login", native_rdp_managed_request_id="managed",
                                 native_rdp_managed_ready=True, native_rdp_managed_renewable=True,
                                 native_rdp_managed_channel=channel)
        opened = asyncio.Queue()
        valid = [True]
        browsers, agents = {SESSION: active}, {3: channel}
        for module in (native, control):
            monkeypatch.setattr(module, "BROWSERS", browsers)
            monkeypatch.setattr(module, "CONTROL_AGENTS", agents)
            monkeypatch.setattr(module, "_platform_client_accessible", lambda *_: True)
            monkeypatch.setattr(module, "_remote_desktop_browser_auth_state",
                                lambda _: (user, "ok") if valid[0] else (None, "idle_timeout"))
            monkeypatch.setattr(module, "_remote_desktop_agent_channel_valid", lambda _: True)
            monkeypatch.setattr(module, "_ws_origin_allowed", lambda ws: ws.headers.get("origin") == ORIGIN)
        monkeypatch.setattr(native, "_TUNNELS", {})
        monkeypatch.setattr(native, "_CLIENT_TUNNELS", {})
        monkeypatch.setattr(native, "_LOCK", asyncio.Lock())
        monkeypatch.setattr(http, "_PEERS", {})
        monkeypatch.setattr(http, "_BUDGET", QueueBudget())
        monkeypatch.setattr(native, "Session", lambda *_: nullcontext(None))
        monkeypatch.setattr(http, "Session", lambda *_: nullcontext(None))
        monkeypatch.setattr(native, "authenticate_browser_websocket_with_context",
                            lambda *_a, **_k: (user, "planiq-ws-ticket", "login"))
        monkeypatch.setattr(control, "_get_http_user", lambda request: user)
        monkeypatch.setattr(control, "_require_superadmin", lambda principal: principal)
        monkeypatch.setattr(control, "_http_browser_session_binding", lambda *_: "login")
        monkeypatch.setattr(native, "verify_remote_desktop_agent_token", lambda *_a, **_k: credential)
        monkeypatch.setattr(http, "verify_remote_desktop_agent_token", lambda *_a, **_k: credential)
        async def send_agent(_channel, packet):
            await opened.put(packet)
        monkeypatch.setattr(native, "_send_agent", send_agent)
        status = []
        async def send_browser(session, client_id, payload):
            assert session == SESSION and client_id == 3
            status.append(payload)
        monkeypatch.setattr(native, "_send_browser", send_browser)
        app = FastAPI()
        app.include_router(http.router, prefix="/api")
        bh = {"origin": ORIGIN, "authorization": "Bearer test", "x-clientflow-ticket": "A" * 43}
        ah = {"authorization": "Bearer test-agent"}
        tasks = []
        async with ASGIClient(app) as client:
            async def open_http(path, headers, role):
                result = await client.post(path, headers=headers)
                assert result.status_code == 200, result.text
                peer_id = result.json()["peer_id"]
                tasks.append(http._PEERS[peer_id].task)
                return "/api/remote-desktop/native-https/" + role + "/3/" + peer_id

            if browser_https:
                browser = await open_http("/api/remote-desktop/browser/3/native-https/" + SESSION + "/open",
                                          bh, "browser")
            else:
                browser = Socket(bh)
                tasks.append(asyncio.create_task(native.native_rdp_browser_ws(browser, 3, SESSION)))
                await browser.accepted.wait()
            packet = await opened.get()
            tunnel_id = packet["tunnel_id"]
            assert packet["managed_request_id"] == "managed"
            if agent_https:
                agent = await open_http("/api/remote-desktop-agent/clients/3/native-https/" + SESSION
                                        + "/" + tunnel_id + "/open", ah, "agent")
            else:
                agent = Socket(ah)
                tasks.append(asyncio.create_task(native.native_rdp_agent_ws(agent, 3, SESSION, tunnel_id)))
                await agent.accepted.wait()

            download_sequences = {}

            async def transfer(source, target, sh, th, frames):
                if isinstance(source, str):
                    stable = "/browser/" in source
                    path = source + ("/send" if stable else "/send/0")
                    headers = {**sh, "content-type": "application/octet-stream"}
                    if stable:
                        headers["x-clientflow-sequence"] = "0"
                    result = await client.post(path, content=encode_batch(frames), headers=headers)
                    assert result.status_code == 204 and result.headers["x-clientflow-sequence"] == "1"
                else:
                    for frame in frames:
                        await source.incoming.put({"type": "websocket.receive", "bytes": frame})
                actual = []
                seq = download_sequences.get(target, 0) if isinstance(target, str) else 0
                while len(actual) < len(frames):
                    if isinstance(target, str):
                        stable = "/browser/" in target
                        path = target + ("/poll" if stable else "/poll/" + str(seq))
                        headers = {**th, "x-clientflow-sequence": str(seq)} if stable else th
                        result = await client.get(path, headers=headers)
                        assert result.status_code == 200, result.text
                        assert result.headers["x-clientflow-sequence"] == str(seq)
                        if result.content:
                            actual.extend(decode_batch(result.content))
                            seq += 1
                            download_sequences[target] = seq
                    else:
                        actual.append(await target.outgoing.get())
                assert actual == frames

            try:
                await transfer(browser, agent, bh, ah, [b"\x00\xff", bytes(range(256)) * 256, b"end"])
                await transfer(agent, browser, ah, bh, [b"\x03\x00", b"reply"])
                assert status == [{"type": "native_rdp_transport", "session_id": SESSION,
                                   "tunnel_id": tunnel_id, "phase": "ready",
                                   "browser": "https" if browser_https else "wss",
                                   "agent": "https" if agent_https else "wss"}]
                if browser_https:
                    denied = await client.post(browser + "/send", content=encode_batch([b"denied"]),
                                               headers={**bh, "x-clientflow-sequence": "1", "origin": "https://other.invalid",
                                                        "content-type": "application/octet-stream"})
                    assert denied.status_code == 403
                    assert not native._TUNNELS[tunnel_id].closed.is_set()
                valid[0] = False
                # Make the revoked poll immediately runnable, without relying on
                # the 15-second independent native tunnel watchdog.
                for entry in http._PEERS.values():
                    await entry.peer.send_bytes(b"must-not-be-delivered")
                if browser_https:
                    denied = await client.get(browser + "/poll", headers={**bh,
                        "x-clientflow-sequence": str(download_sequences[browser])})
                    assert denied.status_code == 403
                    assert denied.json()["detail"] == "ClientFlow-session ikke godkendt"
                    assert b"must-not-be-delivered" not in denied.content
                elif agent_https:
                    denied = await client.get(agent + "/poll/" + str(download_sequences[agent]), headers=ah)
                    assert denied.status_code == 403
                    assert denied.json()["detail"] == "ClientFlow-session ikke godkendt"
                    assert b"must-not-be-delivered" not in denied.content
            finally:
                await native.close_native_rdp_session(3, SESSION)
                await asyncio.gather(*tasks)
            assert status[-1] == {"type": "native_rdp_transport", "session_id": SESSION,
                                  "tunnel_id": tunnel_id, "phase": "closed"}
            assert len(status) == 2
            assert native._TUNNELS == {} and native._CLIENT_TUNNELS == {}
            assert http._PEERS == {} and http._BUDGET.used == 0

    async def bounded():
        await asyncio.wait_for(exercise(), timeout=10)
    asyncio.run(bounded())
