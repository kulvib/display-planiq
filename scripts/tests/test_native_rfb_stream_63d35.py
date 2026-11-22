"""Native RFB relay tests, no localhost access and no GNOME activation."""
import asyncio
import base64

import pytest

from client.runtime.clientflow_runtime.native_rfb_stream import (
    MAX_CHUNK, MAX_UNACKED, NativeRfbClientSession, NativeRfbStreamError,
)

SESSION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
STREAM = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
OTHER = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


class FakeReader:
    def __init__(self):
        self.queue = asyncio.Queue()
    async def read(self, _size):
        return await self.queue.get()


class FakeWriter:
    def __init__(self):
        self.writes = []
        self.closed = False
    def write(self, payload):
        self.writes.append(payload)
    async def drain(self):
        pass
    def close(self):
        self.closed = True
    async def wait_closed(self):
        return


def fixtures():
    reader, writer = FakeReader(), FakeWriter()
    wire = []
    async def send(payload):
        wire.append(payload)
    session = NativeRfbClientSession(
        session_id=SESSION, stream_id=STREAM,
        reader=reader, writer=writer, send_json=send,
    )
    return session, reader, writer, wire


def state(t):
    return {"type":t, "protocol":1, "session_id":SESSION, "stream_id":STREAM}


def frame(seq, payload=b"rfb\x00"):
    return {**state("native_rdp_chunk"), "seq":seq,
            "data":base64.b64encode(payload).decode()}


def ack(seq):
    return {**state("native_rdp_ack"), "seq":seq}


def test_connected_stream_forwards_and_acknowledges_each_direction():
    async def run():
        session, reader, writer, wire = fixtures()
        task = asyncio.create_task(session.run())
        await reader.queue.put(b"RFB 003.008\n")
        await reader.queue.put(b"")
        await asyncio.wait_for(task, 2)
        assert wire[0] == state("native_rdp_ready")
        assert wire[1] == frame(0, b"RFB 003.008\n")
        assert wire[-1] == state("native_rdp_close")
        assert writer.closed
    asyncio.run(run())


def test_received_chunks_are_written_once_and_acknowledged_after_drain():
    async def run():
        session, _, writer, wire = fixtures()
        await session.receive(frame(0, b"key-down"))
        await session.receive(frame(1, b"key-up"))
        assert writer.writes == [b"key-down", b"key-up"]
        assert wire == [ack(0), ack(1)]
        with pytest.raises(NativeRfbStreamError):
            await session.receive(frame(1))
        assert writer.closed and session.closed
    asyncio.run(run())


@pytest.mark.parametrize("mutate", [
    lambda v: {**v, "session_id": OTHER},
    lambda v: {**v, "stream_id": OTHER},
    lambda v: {**v, "protocol": True},
    lambda v: {**v, "data": "YR=="},
    lambda v: {**v, "data": "!!"},
    lambda v: {**v, "data": base64.b64encode(b"x"*(MAX_CHUNK+1)).decode()},
    lambda v: {**v, "extra": "credential"},
    lambda v: {**v, "seq": True},
])
def test_tampering_never_writes_to_local_display(mutate):
    async def run():
        session, _, writer, wire = fixtures()
        with pytest.raises(NativeRfbStreamError):
            await session.receive(mutate(frame(0)))
        assert writer.writes == []
        assert wire == [] and writer.closed
    asyncio.run(run())


def test_credit_window_waits_for_ack_no_discarding_bytes():
    async def run():
        session, reader, writer, wire = fixtures()
        task = asyncio.create_task(session.run())
        for i in range(MAX_UNACKED + 1):
            await reader.queue.put(bytes([i]))
        for _ in range(30):
            await asyncio.sleep(0)
            if len(wire) >= MAX_UNACKED + 1:
                break
        assert len([v for v in wire if v["type"] == "native_rdp_chunk"]) == MAX_UNACKED
        await session.receive(ack(0))
        for _ in range(30):
            await asyncio.sleep(0)
            if len([v for v in wire if v["type"] == "native_rdp_chunk"]) > MAX_UNACKED:
                break
        assert len([v for v in wire if v["type"] == "native_rdp_chunk"]) == MAX_UNACKED + 1
        assert [v["seq"] for v in wire if v["type"] == "native_rdp_chunk"] == list(range(MAX_UNACKED+1))
        # RFB is an ordered byte stream; acknowledge outstanding packets
        # before expecting the source EOF, rather than silently dropping.
        for seq in range(1, MAX_UNACKED + 1):
            await session.receive(ack(seq))
        await reader.queue.put(b"")
        await asyncio.wait_for(task, 2)
        assert writer.closed
    asyncio.run(run())


def test_close_aborts_stream_without_replaying_buttons():
    async def run():
        session, _, writer, wire = fixtures()
        await session.receive(state("native_rdp_close"))
        assert session.closed and writer.closed
        with pytest.raises(NativeRfbStreamError):
            await session.receive(frame(0))
        assert wire == []
    asyncio.run(run())


def test_no_implicit_server_start_or_loopback_connection():
    import inspect
    from client.runtime.clientflow_runtime import native_rfb_stream
    src = inspect.getsource(native_rfb_stream)
    assert "open_connection(" not in src
    assert "subprocess" not in src
    assert "listen(" not in src
    assert "Xvfb" in src  # Documentation only; not an implicit invocation.
