"""Agent adapter protocol tests with deterministic in-memory responses."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "client" / "runtime"))
from clientflow_runtime.native_rdp_https_peer import (  # noqa: E402
    NativeHttpsAgentPeer, PeerError, encode, decode,
)
from service1.native_rdp_https_core import encode_batch, decode_batch  # noqa: E402

SESSION = "12345678-1234-4234-8234-123456789abc"
TUNNEL = "22345678-1234-4234-8234-123456789abc"
PEER = "a" * 32


def reply(status, body=b"", **headers):
    return SimpleNamespace(status_code=status, body=body, headers=headers)


def test_agent_codec_matches_backend():
    frames = [b"\x00\xff", bytes(range(256)) * 256]
    assert encode(frames) == encode_batch(frames)
    assert decode(encode_batch(frames)) == frames
    assert decode_batch(encode(frames)) == frames


def test_agent_full_duplex_and_terminal_failure_no_replay():
    async def exercise():
        calls = []
        async def request(method, path, body, cap, timeout):
            calls.append((method, path))
            if path.endswith("/open"):
                return reply(200, json.dumps({"peer_id": PEER, "upload_sequence": 0,
                                              "download_sequence": 0}).encode())
            if path.endswith("/send/0"):
                assert decode_batch(body) == [b"input"]
                return reply(204, **{"x-clientflow-sequence": "1"})
            if path.endswith("/send/1"):
                raise OSError("ambiguous delivery")
            if path.endswith("/poll/0"):
                return reply(200, encode_batch([b"a", b"b"]),
                             **{"x-clientflow-sequence": "0", "content-type": "application/octet-stream"})
            if method == "DELETE":
                return reply(204)
            raise AssertionError("unexpected request")
        peer = NativeHttpsAgentPeer(request, client_id=3, session_id=SESSION,
                                    tunnel_id=TUNNEL, approved=True)
        async with peer:
            await peer.send(b"input")
            assert await anext(peer) == b"a"
            assert await anext(peer) == b"b"
            with pytest.raises(OSError):
                await peer.send(b"ambiguous")
            with pytest.raises(StopAsyncIteration):
                await anext(peer)
        assert sum(path.endswith("/send/1") for _, path in calls) == 1
        assert sum(method == "DELETE" for method, _ in calls) == 1
    asyncio.run(exercise())


def test_agent_requires_explicit_approval_and_exact_generation():
    async def request(*args):
        raise AssertionError("must not connect")
    with pytest.raises(PeerError):
        NativeHttpsAgentPeer(request, client_id=3, session_id=SESSION, tunnel_id=TUNNEL)
    with pytest.raises(PeerError):
        NativeHttpsAgentPeer(request, client_id=4, session_id=SESSION, tunnel_id=TUNNEL, approved=True)
    with pytest.raises(PeerError):
        NativeHttpsAgentPeer(request, client_id=3, session_id="../bad", tunnel_id=TUNNEL, approved=True)


def test_agent_read_ahead_batches_in_order_without_replaying():
    from clientflow_runtime.native_rdp_https_peer import upload_stream

    async def exercise():
        first_ack = asyncio.Event()
        frames = [bytes([i]) * 16384 for i in range(20)]
        sent = []
        batches = []
        class Reader:
            async def read(self, size):
                assert size == 16384
                return frames.pop(0) if frames else b""
        class Peer:
            async def send_many(self, batch):
                assert 0 < len(batch) <= 15
                assert len(encode(batch)) <= 262144
                batches.append(list(batch))
                if len(batches) == 1:
                    await first_ack.wait()
        async def release():
            while not batches:
                await asyncio.sleep(0)
            await asyncio.sleep(0)
            first_ack.set()
        expected = list(frames)
        await asyncio.wait_for(asyncio.gather(
            upload_stream(Reader(), Peer(), lambda: None, sent.append), release()), 2)
        assert sent == expected
        assert [frame for batch in batches for frame in batch] == expected
        assert len(batches) < len(expected)
    asyncio.run(exercise())
