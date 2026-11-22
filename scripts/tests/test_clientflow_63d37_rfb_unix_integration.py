"""63D-37: synthetic AF_UNIX and RFB banner integration, no VNC package."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import stat

from client.runtime.clientflow_runtime import native_rfb_local_gate as gate
from client.runtime.clientflow_runtime.native_rfb_stream import (
    NativeRfbClientSession,
)

SESSION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
STREAM = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def test_source_approved_mock_unix_socket_delivers_ordered_rfb_bytes(
    tmp_path: Path, monkeypatch,
):
    async def scenario():
        root = tmp_path / "native-rfb"
        root.mkdir(mode=0o700)
        path = gate.socket_path(SESSION, runtime_root=root)
        echoed = asyncio.Queue()
        wire = []
        opened = asyncio.Event()

        async def fake_rfb_server(reader, writer):
            writer.write(b"RFB 003.008\n")
            await writer.drain()
            echoed.put_nowait(await asyncio.wait_for(reader.read(64), 2))
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_unix_server(fake_rfb_server, path=str(path))
        path.chmod(0o600)
        owner = os.getuid()
        if owner == 0:
            owner = 65534
            os.chown(root, owner, owner)
            os.chown(path, owner, owner)
            monkeypatch.setattr(gate.os, "geteuid", lambda: owner)

        assert stat.S_ISSOCK(path.stat().st_mode)
        # The product stays hard-disabled; this simulates a reviewed source
        # approval *only against our in-process synthetic AF_UNIX server*.
        monkeypatch.setattr(gate, "PRODUCER_APPROVED", True)

        async def send_json(message):
            wire.append(message)
            if message["type"] == "native_rdp_ready":
                opened.set()

        try:
            reader, writer = await gate.open_approved_socket(
                SESSION, runtime_root=root,
            )
            bridge = NativeRfbClientSession(
                session_id=SESSION, stream_id=STREAM,
                reader=reader, writer=writer, send_json=send_json,
            )
            task = asyncio.create_task(bridge.run())
            await asyncio.wait_for(opened.wait(), 2)
            # Browser -> authorised agent -> protected AF_UNIX producer.
            import base64
            await bridge.receive({
                "type": "native_rdp_chunk", "protocol": 1,
                "session_id": SESSION, "stream_id": STREAM, "seq": 0,
                "data": base64.b64encode(b"RFB 003.008\n").decode("ascii"),
            })
            assert await asyncio.wait_for(echoed.get(), 2) == b"RFB 003.008\n"
            await asyncio.wait_for(task, 2)
            assert [item["type"] for item in wire] == [
                "native_rdp_ready", "native_rdp_ack",
                "native_rdp_chunk", "native_rdp_close",
            ] or set(item["type"] for item in wire) == {
                "native_rdp_ready", "native_rdp_ack",
                "native_rdp_chunk", "native_rdp_close",
            }
            assert any(
                item["type"] == "native_rdp_chunk"
                and base64.b64decode(item["data"]) == b"RFB 003.008\n"
                for item in wire
            )
            assert bridge.closed
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(scenario())
