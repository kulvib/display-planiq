"""Render TLS-termination regression tests: no wildcard proxy-header trust."""
from pathlib import Path

import pytest
from fastapi import FastAPI, Request, WebSocket
from fastapi.testclient import TestClient

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


def test_render_http_hop_appears_https_to_app_and_dpop():
    with TestClient(_app(), base_url=f"http://{PUBLIC_HOST}") as client:
        result = client.post("/api/clientflow-update/token?unused=1")
        assert result.status_code == 200
        assert result.json() == {"htu": f"https://{PUBLIC_HOST}/api/clientflow-update/token"}
        result = client.get("/health")
        assert result.json()["scheme"] == "https"


def test_https_trailing_slash_redirect_stays_https():
    with TestClient(_app(), base_url=f"http://{PUBLIC_HOST}", follow_redirects=False) as client:
        result = client.get("/health/")
        assert result.status_code == 307
        assert result.headers["location"] == f"https://{PUBLIC_HOST}/health"


@pytest.mark.parametrize("host", ["evil.example", "api.display.planiq.dk.evil.example", "api.display.planiq.dk:10000"])
def test_other_hosts_do_not_get_pinned_https(host):
    with TestClient(_app(), base_url=f"http://{host}") as client:
        result = client.get("/health")
        assert result.json()["scheme"] == "http"


def test_render_websocket_scheme_is_wss():
    with TestClient(_app(), base_url=f"http://{PUBLIC_HOST}") as client:
        with client.websocket_connect("/probe/ws", headers={"host": PUBLIC_HOST}) as ws:
            assert ws.receive_json() == {"scheme": "wss"}


def test_forwarded_headers_cannot_influence_scheme():
    headers = {
        "X-Forwarded-Proto": "http",
        "X-Forwarded-Host": "evil.example",
        "X-Forwarded-For": "203.0.113.2",
    }
    with TestClient(_app(), base_url=f"http://{PUBLIC_HOST}", headers=headers) as client:
        result = client.get("/health")
        assert result.json() == {"url": f"https://{PUBLIC_HOST}/health", "scheme": "https"}
    with TestClient(_app(), base_url="http://evil.example", headers={**headers, "X-Forwarded-Proto": "https"}) as client:
        result = client.get("/health")
        assert result.json()["scheme"] == "http"


def test_duplicate_host_does_not_get_scheme_upgrade():
    scope = {"type": "http", "scheme": "http", "headers": [(b"host", PUBLIC_HOST.encode()), (b"host", b"evil.example")]}
    async def recorder(s, receive, send):
        assert s["scheme"] == "http"
    async def run_test():
        await PinnedPublicHttpsScheme(recorder, public_hostname=PUBLIC_HOST)(scope, None, None)
    import asyncio
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
