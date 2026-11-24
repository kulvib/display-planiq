"""Loopback TLS proof of the actual agent request adapter; no external traffic."""
import asyncio
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import ssl
import sys
import threading
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "client" / "runtime"))
from clientflow_runtime.native_rdp_https_peer import (  # noqa: E402
    PeerError, make_agent_https_request,
)


def test_real_tls_agent_request_rejects_redirect_and_oversize(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(hours=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                          serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            calls.append((self.path, self.headers.get("Authorization")))
            if self.path.endswith("/redirect"):
                self.send_response(307)
                self.send_header("Location", "/api/remote-desktop/forbidden-target")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body = b"x" * 33 if self.path.endswith("/oversize") else b"\x00\xff\x03"
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-ClientFlow-Sequence", "0")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            calls.append((self.path, self.headers.get("Authorization")))
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.send_response(204 if body == b"\x00\xff" and not self.headers.get("Upgrade") else 400)
            self.send_header("X-ClientFlow-Sequence", "1")
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(cert_path, key_path)
    server.socket = server_ctx.wrap_socket(server.socket, server_side=True)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    context = ssl.create_default_context(cafile=str(cert_path))
    transport = SimpleNamespace(
        credential=SimpleNamespace(backend_url=f"https://localhost:{server.server_port}"),
        access_token=lambda: "synthetic-test-token",
    )
    request = make_agent_https_request(transport, context)

    async def exercise():
        prefix = "/api/remote-desktop/native-https/"
        result = await request("GET", prefix + "poll", None, 32, 3)
        assert result.body == b"\x00\xff\x03"
        assert result.headers["x-clientflow-sequence"] == "0"
        result = await request("POST", prefix + "send", b"\x00\xff", 0, 3)
        assert result.status_code == 204 and result.headers["x-clientflow-sequence"] == "1"
        with pytest.raises(PeerError):
            await request("GET", prefix + "redirect", None, 32, 3)
        with pytest.raises(PeerError):
            await request("GET", prefix + "oversize", None, 32, 3)
        wrong = SimpleNamespace(
            credential=SimpleNamespace(backend_url=f"https://127.0.0.1:{server.server_port}"),
            access_token=transport.access_token,
        )
        with pytest.raises(OSError):
            await make_agent_https_request(wrong, context)("GET", prefix + "poll", None, 32, 3)

    try:
        asyncio.run(exercise())
        assert len(calls) == 4
        assert all(token == "Bearer synthetic-test-token" for _, token in calls)
        assert not any(path.endswith("forbidden-target") for path, _ in calls)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
