"""Render TLS-termination regression tests without optional HTTP test clients.

The CI dependency lock intentionally has no Starlette ``httpx2`` extra.
Invoke the ASGI application directly, as other repository integration tests do,
so these tests exercise real FastAPI routes/redirects without test-only packages.
"""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, Request, WebSocket

from service1.public_https_scheme import PinnedPublicHttpsScheme


PUBLIC_HOST = "api.display.planiq.dk"
ROOT = Path(__file__).resolve().parents[2]


def _app():
    app = FastAPI()

    @app.get("/health")
    def health(request: Request):
        return {"url": str(request.url), "scheme": request.scope["scheme"]}

    @app.post("/api/clientflow-update/token")
    def token(request: Request):
        # The real DPoP verifier compares its signed htu against request.url.
        return {"htu": str(request.url.replace(query="", fragment=""))}

    @app.websocket("/probe/ws")
    async def websocket_probe(ws: WebSocket):
        await ws.accept()
        await ws.send_json({"scheme": ws.scope["scheme"]})
        await ws.close()

    app.add_middleware(PinnedPublicHttpsScheme, public_hostname=PUBLIC_HOST)
    return app


def _scope(kind: str, path: str, host: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    raw_headers = [(b"host", host.encode("latin-1"))]
    if headers:
        raw_headers.extend(
            (key.lower().encode("latin-1"), value.encode("latin-1"))
            for key, value in headers.items()
        )
    return {
        "type": kind,
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "scheme": "http" if kind == "http" else "ws",
        "path": path,
        "raw_path": path.encode("ascii"),
        "root_path": "",
        "query_string": b"",
        "headers": raw_headers,
        "client": ("127.0.0.1", 50000),
        "server": (host, 80),
        **({"http_version": "1.1", "method": "GET"} if kind == "http" else {"subprotocols": []}),
    }


def _request(
    app: FastAPI,
    path: str,
    *,
    method: str = "GET",
    host: str = PUBLIC_HOST,
    query: bytes = b"",
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], Any]:
    async def run() -> tuple[int, dict[str, str], Any]:
        messages: list[dict[str, Any]] = []
        request_sent = False

        async def receive() -> dict[str, Any]:
            nonlocal request_sent
            if not request_sent:
                request_sent = True
                return {"type": "http.request", "body": b"", "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            messages.append(message)

        scope = _scope("http", path, host, headers)
        scope["method"] = method
        scope["query_string"] = query
        await app(scope, receive, send)
        starts = [m for m in messages if m["type"] == "http.response.start"]
        assert len(starts) == 1, messages
        response_headers = {
            name.decode("latin-1").lower(): value.decode("latin-1")
            for name, value in starts[0]["headers"]
        }
        body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
        return starts[0]["status"], response_headers, json.loads(body) if body else None

    return asyncio.run(run())


def _websocket_messages(app: FastAPI, *, host: str = PUBLIC_HOST) -> list[dict[str, Any]]:
    async def run() -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        connected = False

        async def receive() -> dict[str, Any]:
            nonlocal connected
            if not connected:
                connected = True
                return {"type": "websocket.connect"}
            return {"type": "websocket.disconnect", "code": 1000}

        async def send(message: dict[str, Any]) -> None:
            messages.append(message)

        await app(_scope("websocket", "/probe/ws", host), receive, send)
        return messages

    return asyncio.run(run())


def test_render_http_hop_appears_https_to_app_and_dpop():
    app = _app()
    status, _, data = _request(app, "/api/clientflow-update/token", method="POST", query=b"unused=1")
    assert status == 200
    assert data == {"htu": f"https://{PUBLIC_HOST}/api/clientflow-update/token"}
    status, _, data = _request(app, "/health")
    assert status == 200
    assert data["scheme"] == "https"


def test_https_trailing_slash_redirect_stays_https():
    status, headers, _ = _request(_app(), "/health/")
    assert status == 307
    assert headers["location"] == f"https://{PUBLIC_HOST}/health"


@pytest.mark.parametrize("host", ["evil.example", "api.display.planiq.dk.evil.example", "api.display.planiq.dk:10000"])
def test_other_hosts_do_not_get_pinned_https(host):
    status, _, data = _request(_app(), "/health", host=host)
    assert status == 200
    assert data["scheme"] == "http"


def test_render_websocket_scheme_is_wss():
    messages = _websocket_messages(_app())
    assert [message["type"] for message in messages] == [
        "websocket.accept", "websocket.send", "websocket.close"
    ]
    assert json.loads(messages[1]["text"]) == {"scheme": "wss"}


def test_forwarded_headers_cannot_influence_scheme():
    headers = {
        "X-Forwarded-Proto": "http",
        "X-Forwarded-Host": "evil.example",
        "X-Forwarded-For": "203.0.113.2",
    }
    status, _, data = _request(_app(), "/health", headers=headers)
    assert status == 200
    assert data == {"url": f"https://{PUBLIC_HOST}/health", "scheme": "https"}
    status, _, data = _request(
        _app(), "/health", host="evil.example", headers={**headers, "X-Forwarded-Proto": "https"}
    )
    assert status == 200
    assert data["scheme"] == "http"


def test_duplicate_host_does_not_get_scheme_upgrade():
    scope = {
        "type": "http",
        "scheme": "http",
        "headers": [(b"host", PUBLIC_HOST.encode()), (b"host", b"evil.example")],
    }

    async def recorder(inner_scope, receive, send):
        assert inner_scope["scheme"] == "http"

    async def run_test():
        await PinnedPublicHttpsScheme(recorder, public_hostname=PUBLIC_HOST)(scope, None, None)

    asyncio.run(run_test())


@pytest.mark.parametrize("host", ["", "https://api.display.planiq.dk", "api.display.planiq.dk:443", "*.example.org", "evil..org"])
def test_configuration_rejects_non_host_values(host):
    with pytest.raises(ValueError):
        PinnedPublicHttpsScheme(lambda *_args: None, public_hostname=host)


def test_startup_enables_pinning_without_wildcard_proxy_trust():
    start = (ROOT / "backend/scripts/start_single_node.sh").read_text()
    main = (ROOT / "backend/service1/main.py").read_text()
    assert 'export DISPLAY_PUBLIC_HTTPS_HOST="${DISPLAY_PUBLIC_HTTPS_HOST:-api.display.planiq.dk}"' in start
    assert 'app.add_middleware(PinnedPublicHttpsScheme, public_hostname=_public_https_host)' in main
    assert '--forwarded-allow-ips="*"' not in start
    assert "--forwarded-allow-ips '*'" not in start
