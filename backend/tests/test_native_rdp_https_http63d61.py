"""HTTP boundary proofs with no live network or physical device."""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from service1.native_rdp_https_core import MAX_BATCH, encode_batch
from service1.routers import native_rdp_https_http as http


def test_default_gate_and_exact_pilot(monkeypatch):
    monkeypatch.delenv("CLIENTFLOW_NATIVE_BINARY_HTTPS_ENABLED", raising=False)
    with pytest.raises(HTTPException) as denied:
        http._gate(3)
    assert denied.value.status_code == 404
    monkeypatch.setenv("CLIENTFLOW_NATIVE_BINARY_HTTPS_ENABLED", "true")
    http._gate(3)
    with pytest.raises(HTTPException):
        http._gate(4)


def test_owner_identity_includes_role_client_version_login_and_principal(monkeypatch):
    owner = http.Owner("browser", 3, "42", 1, "login")
    entry = SimpleNamespace(owner=owner)
    monkeypatch.setitem(http._PEERS, "peer", entry)
    assert http._entry(owner, "peer") is entry
    for other in (
        http.Owner("agent", 3, "42", 1, "login"),
        http.Owner("browser", 4, "42", 1, "login"),
        http.Owner("browser", 3, "43", 1, "login"),
        http.Owner("browser", 3, "42", 2, "login"),
        http.Owner("browser", 3, "42", 1, "other"),
    ):
        with pytest.raises(HTTPException) as denied:
            http._entry(other, "peer")
        assert denied.value.status_code == 404


def _request(chunks, content_length=None, content_type="application/octet-stream"):
    queue = iter(chunks)
    async def receive():
        data = next(queue, None)
        if data is None:
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.request", "body": data, "more_body": True}
    headers = [(b"content-type", content_type.encode())]
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode()))
    return Request({"type": "http", "headers": headers}, receive)


def test_streamed_body_is_bounded_before_push():
    async def exercise():
        frame = encode_batch([b"abc"])
        assert await http._body(_request([frame[:2], frame[2:]], len(frame))) == frame
        with pytest.raises(HTTPException) as oversized:
            await http._body(_request([b"x" * MAX_BATCH, b"y"]))
        assert oversized.value.status_code == 413
        with pytest.raises(HTTPException):
            await http._body(_request([b"x"], MAX_BATCH + 1))
        with pytest.raises(HTTPException):
            await http._body(_request([b"x"], 2))
        with pytest.raises(HTTPException):
            await http._body(_request([b"x"], content_type="application/json"))
    asyncio.run(exercise())


def test_send_and_poll_lanes_held_through_asgi_delivery(monkeypatch):
    async def exercise():
        async def live(_entry, **_kwargs):
            pass
        monkeypatch.setattr(http, "_live", live)
        owner = http.Owner("browser", 3, "42", 1, "login")
        peer = http.HttpPeer({}, None)
        entry = http.Entry("peer", owner, "session", "request", object(), object(), peer)
        response = await http._send(_request([encode_batch([b"abc"])]), entry, "0")
        assert entry.uploading and response.status_code == 204
        assert response.headers["x-clientflow-sequence"] == "1"
        assert (await peer.receive())["bytes"] == b"abc"
        async def deliver(_message):
            assert entry.uploading
        await response({"type": "http"}, None, deliver)
        assert not entry.uploading
        await peer.send_bytes(b"out")
        response = await http._poll(entry, "0")
        assert entry.polling and response.body == encode_batch([b"out"])
        async def lost(_message):
            raise OSError("response lost")
        with pytest.raises(OSError):
            await response({"type": "http"}, None, lost)
        assert not entry.polling and peer.closed.is_set() and peer.queued_bytes == 0
    asyncio.run(exercise())


def test_concurrent_upload_fails_closed(monkeypatch):
    async def exercise():
        async def live(_entry, **_kwargs):
            pass
        monkeypatch.setattr(http, "_live", live)
        peer = http.HttpPeer({}, None)
        entry = http.Entry("peer", http.Owner("agent", 3, "credential", 1),
                           "session", "request", object(), object(), peer)
        entry.uploading = True
        with pytest.raises(HTTPException) as conflict:
            await http._send(_request([encode_batch([b"abc"])]), entry, "0")
        assert conflict.value.status_code == 409 and peer.closed.is_set()
    asyncio.run(exercise())


def test_handshake_removes_secrets_and_bad_sequence_rejected():
    async def exercise():
        peer = http.HttpPeer({"authorization": "test-secret"}, None)
        await peer.accept()
        assert peer.headers == {} and peer.accepted.is_set()
        await peer.close()
        assert peer.closed.is_set()
    asyncio.run(exercise())
    for value in ("-1", "01", "1.0", "9007199254740991", "a"):
        with pytest.raises(HTTPException):
            http._sequence(value)


def test_https_counters_count_accepted_work_without_secrets(monkeypatch, caplog):
    import logging

    async def exercise():
        async def live(_entry, **_kwargs):
            pass
        monkeypatch.setattr(http, "_live", live)
        peer = http.HttpPeer({}, None)
        entry = http.Entry("secret-peer", http.Owner("agent", 3, "secret-owner", 1),
                           "secret-session", "secret-request", object(), object(), peer)
        body = encode_batch([b"secret-payload"])
        response = await http._send(_request([body]), entry, "0")
        async def deliver(_message):
            pass
        await response({"type": "http"}, None, deliver)
        assert entry.counters.uploads == 1
        assert entry.counters.upload_bytes == len(body)
        await peer.receive()

        original_poll = peer.poll
        async def fast_poll(sequence):
            return await original_poll(sequence, timeout=0.001)
        monkeypatch.setattr(peer, "poll", fast_poll)
        response = await http._poll(entry, "0")
        assert response.body == b""
        await response({"type": "http"}, None, deliver)
        assert entry.counters.empty_polls == 1

        await peer.send_bytes(b"output")
        response = await http._poll(entry, "0")
        assert entry.counters.nonempty_polls == 1
        assert entry.counters.download_bytes == len(encode_batch([b"output"]))
        async def lost(_message):
            raise OSError("secret-error")
        with pytest.raises(OSError):
            await response({"type": "http"}, None, lost)
        assert entry.counters.delivery_errors == 1
        assert peer.closed.is_set()

        with caplog.at_level(logging.INFO, logger=http.logger.name):
            entry.counters.report(entry.owner.role)
        assert "uploads=1" in caplog.text
        assert "nonempty_polls=1 empty_polls=1" in caplog.text
        assert "response_delivery_errors_observed=1" in caplog.text
        assert "secret-" not in caplog.text

    asyncio.run(exercise())


def test_https_counters_are_per_peer():
    first = http.TransportCounters()
    second = http.TransportCounters()
    first.uploads += 1
    assert second.uploads == 0


def test_stable_browser_sequence_header_requires_one_canonical_value():
    from starlette.requests import Request

    def request(values):
        return Request({"type": "http", "headers": [
            (b"x-clientflow-sequence", value) for value in values
        ]})

    assert http._header_sequence(request([b"0"])) == "0"
    assert http._sequence(http._header_sequence(request([b"17"]))) == 17
    for values in ([], [b"0", b"1"], [b"0, 1"], [b"01"], [b"-1"], [b"9007199254740991"]):
        with pytest.raises(HTTPException):
            http._sequence(http._header_sequence(request(values)))
