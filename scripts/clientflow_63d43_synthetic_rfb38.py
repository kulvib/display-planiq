#!/usr/bin/env python3
"""63D-43: real AF_UNIX + *synthetic* RFB 3.8 end-to-end protocol proof.

Runs only as an unprivileged, ephemeral Ubuntu 26.04 GitHub CI job.
All RFB bytes originate in THIS Python process; no x11vnc, TigerVNC,
Xvfb, GNOME, TCP, public socket, real framebuffer or real credentials.
Exercises: strict private socket identity -> agent RFB byte stream ->
authenticated-broker sequence model -> synthetic browser RFB handshake,
framebuffer raw pixels, key-down/up and mouse-down/up -> cleanup.

NEVER overrides any product source activation flag.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
import socket
import stat
import struct
import tempfile

from backend.service1.native_rdp_bridge_protocol import (
    decode_chunk, encode_chunk,
)
from backend.service1.native_rdp_session_bridge import NativeRdpRelaySession
from client.runtime.clientflow_runtime import native_rfb_local_gate as local_gate
from client.runtime.clientflow_runtime.native_rfb_stream import NativeRfbClientSession
from scripts import clientflow_63d41_rfb_source_gate as ci_gate

SESSION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
STREAM = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
BANNER = b"RFB 003.008\n"
PIXELS = b"\x00\x00\xff\x00\x00\xff\x00\x00"  # two synthetic RGB pixels
PIXEL_FORMAT = struct.pack(">BBBBHHHBBBxxx", 32, 24, 0, 1, 255, 255, 255, 16, 8, 0)
SERVER_INIT = struct.pack(">HH", 2, 1) + PIXEL_FORMAT + struct.pack(">I", 5) + b"CF-43"
SERVER_FRAME = (
    b"\x00\x00\x00\x01" + struct.pack(">HHHHi", 0, 0, 2, 1, 0) + PIXELS
)
# RFB 3.8 keyboard and pointer events (six/eight-byte framing).
EXPECTED_INPUTS = (
    struct.pack(">BBHI", 4, 1, 0, 0xFF0D),  # Return key down
    struct.pack(">BBHI", 4, 0, 0, 0xFF0D),  # Return key up
    struct.pack(">BBHH", 5, 1, 1, 0),       # button down
    struct.pack(">BBHH", 5, 0, 1, 0),       # button up
)


class SyntheticRfbError(RuntimeError):
    """Fail-closed synthetic protocol error; never exposes RFB payloads."""


class SyntheticBrowser:
    """Receives ordered RFB bytes over real client/broker protocol envelopes."""

    def __init__(
        self, stream: NativeRfbClientSession,
        relay: NativeRdpRelaySession,
        inbound: asyncio.Queue,
    ):
        self.stream = stream
        self.relay = relay
        self.inbound = inbound
        self.next_sent = 0
        self.buffer = bytearray()
        self.received_frames = 0

    async def await_ready(self) -> None:
        packet = await asyncio.wait_for(self.inbound.get(), 3)
        if packet.get("type") != "native_rdp_ready":
            raise SyntheticRfbError("Synthetic broker not ready")

    async def send(self, payload: bytes) -> None:
        if not payload or len(payload) > 16 * 1024:
            raise SyntheticRfbError("Unsafe synthetic browser frame")
        packet = encode_chunk(
            session_id=SESSION, stream_id=STREAM,
            seq=self.next_sent, payload=payload,
        )
        self.relay.accept_chunk(packet, origin="browser")
        self.next_sent += 1
        await self.stream.receive(packet)

    async def readexactly(self, count: int) -> bytes:
        if not 0 < count <= 64 * 1024:
            raise SyntheticRfbError("Synthetic framebuffer request too large")
        while len(self.buffer) < count:
            packet = await asyncio.wait_for(self.inbound.get(), 3)
            kind = packet.get("type")
            if kind == "native_rdp_ack":
                continue  # validated by the authoritative broker callback
            if kind != "native_rdp_chunk":
                raise SyntheticRfbError("Unexpected synthetic RFB stream state")
            parsed = decode_chunk(packet, session_id=SESSION, stream_id=STREAM)
            self.buffer.extend(parsed.payload)
            self.received_frames += 1
            acknowledgement = {
                "type": "native_rdp_ack", "protocol": 1,
                "session_id": SESSION, "stream_id": STREAM, "seq": parsed.seq,
            }
            self.relay.accept_ack(acknowledgement, origin="browser")
            await self.stream.receive(acknowledgement)
            if len(self.buffer) > 64 * 1024:
                raise SyntheticRfbError("Unbounded synthetic RFB receive buffer")
        result = bytes(self.buffer[:count])
        del self.buffer[:count]
        return result


async def synthetic_producer(reader, writer, captured: asyncio.Queue) -> None:
    """A tiny RFB 3.8 producer ONLY for this test, never installed as a daemon."""
    try:
        writer.write(BANNER)
        await writer.drain()
        if await asyncio.wait_for(reader.readexactly(12), 3) != BANNER:
            raise SyntheticRfbError("Incorrect RFB protocol version")
        # Type 1 'None' is safe ONLY here: private synthetic CI transport.
        # Never use this unauthenticated mode in a deployed product.
        writer.write(b"\x01\x01")
        await writer.drain()
        if await asyncio.wait_for(reader.readexactly(1), 3) != b"\x01":
            raise SyntheticRfbError("RFB security negotiation not matched")
        writer.write(b"\x00\x00\x00\x00")
        await writer.drain()
        if await asyncio.wait_for(reader.readexactly(1), 3) != b"\x01":
            raise SyntheticRfbError("RFB ClientInit missing")
        writer.write(SERVER_INIT)
        await writer.drain()
        set_encodings = await asyncio.wait_for(reader.readexactly(8), 3)
        if set_encodings != b"\x02\x00\x00\x01\x00\x00\x00\x00":
            raise SyntheticRfbError("Only raw RFB encoding permitted in proof")
        request = await asyncio.wait_for(reader.readexactly(10), 3)
        if request != b"\x03\x00\x00\x00\x00\x00\x00\x02\x00\x01":
            raise SyntheticRfbError("Unexpected framebuffer request")
        writer.write(SERVER_FRAME)
        await writer.drain()
        actual = []
        for size in (8, 8, 6, 6):
            actual.append(await asyncio.wait_for(reader.readexactly(size), 3))
        captured.put_nowait(tuple(actual))
    finally:
        writer.close()
        await writer.wait_closed()


async def probe() -> dict:
    if os.geteuid() <= 0:
        raise SyntheticRfbError("Synthetic RFB proof requires non-root runner")
    if local_gate.PRODUCER_APPROVED is not False:
        raise SyntheticRfbError("Deployed RFB source lock unexpectedly enabled")
    with tempfile.TemporaryDirectory(prefix="cf43-", dir="/tmp") as temp:
        root = Path(temp)
        os.chmod(root, 0o700)
        path = local_gate.socket_path(SESSION, runtime_root=root)
        captured: asyncio.Queue = asyncio.Queue(maxsize=1)
        accepted = asyncio.Event()
        errors: list[Exception] = []

        async def server_handler(reader, writer):
            try:
                await synthetic_producer(reader, writer, captured)
            except Exception as exc:
                errors.append(exc)
            finally:
                accepted.set()

        server = await asyncio.start_unix_server(server_handler, path=str(path))
        os.chmod(path, 0o600)
        inbound: asyncio.Queue = asyncio.Queue(maxsize=64)
        relay = NativeRdpRelaySession(SESSION, client_id=3, stream_id=STREAM)

        async def agent_send(packet):
            kind = packet.get("type")
            if kind == "native_rdp_ready":
                relay.agent_ready(packet)
            elif kind == "native_rdp_chunk":
                relay.accept_chunk(packet, origin="agent")
            elif kind == "native_rdp_ack":
                relay.accept_ack(packet, origin="agent")
            elif kind == "native_rdp_close":
                relay.stop(packet)
            else:
                raise SyntheticRfbError("Unexpected agent protocol frame")
            inbound.put_nowait(packet)

        task = None
        try:
            inspected = local_gate.inspect_socket(
                SESSION, runtime_root=root, expected_uid=os.geteuid(),
            )
            if inspected.socket_inode <= 0 or inspected.owner_uid != os.geteuid():
                raise SyntheticRfbError("Private Unix source socket invalid")
            # This is a SYNTHETIC fixture connection, NOT the product
            # open_approved_socket() path: the approval lock stays false.
            reader, writer = await asyncio.open_unix_connection(str(path))
            local_gate.revalidate_socket(inspected)
            stream = NativeRfbClientSession(
                session_id=SESSION, stream_id=STREAM,
                reader=reader, writer=writer, send_json=agent_send,
            )
            browser = SyntheticBrowser(stream, relay, inbound)
            task = asyncio.create_task(stream.run())
            await browser.await_ready()

            if await browser.readexactly(12) != BANNER:
                raise SyntheticRfbError("RFB 3.8 banner mismatch")
            await browser.send(BANNER)
            if await browser.readexactly(2) != b"\x01\x01":
                raise SyntheticRfbError("RFB mock security types mismatch")
            await browser.send(b"\x01")
            if await browser.readexactly(4) != b"\x00\x00\x00\x00":
                raise SyntheticRfbError("RFB mock security acknowledgement mismatch")
            await browser.send(b"\x01")
            if await browser.readexactly(len(SERVER_INIT)) != SERVER_INIT:
                raise SyntheticRfbError("RFB mock screen properties mismatch")
            await browser.send(b"\x02\x00\x00\x01\x00\x00\x00\x00")
            await browser.send(b"\x03\x00\x00\x00\x00\x00\x00\x02\x00\x01")
            frame = await browser.readexactly(len(SERVER_FRAME))
            if frame != SERVER_FRAME or not frame.endswith(PIXELS):
                raise SyntheticRfbError("RFB raw pixel frames corrupted")

            for msg in EXPECTED_INPUTS:
                await browser.send(msg)
            if await asyncio.wait_for(captured.get(), 3) != EXPECTED_INPUTS:
                raise SyntheticRfbError("RFB key/button down-up mismatch")
            await asyncio.wait_for(accepted.wait(), 3)
            if errors:
                raise SyntheticRfbError("Synthetic RFB producer rejected input")
            await asyncio.wait_for(task, 3)
            if not stream.closed or not relay.closed:
                raise SyntheticRfbError("Synthetic RFB generation was not closed")
            if local_gate.PRODUCER_APPROVED is not False:
                raise SyntheticRfbError("RFB activation source lock changed")
            return {
                "schema": "63d43-private-synthetic-rfb38-v1",
                "af_unix_real_os_socket": True,
                "rfb_version_banner": "3.8 (synthetic only)",
                "fb_width": 2,
                "fb_height": 1,
                "pixel_bytes_verified": len(PIXELS),
                "input_events_verified": 4,
                "mouse_up_and_key_up_verified": True,
                "backend_session_bound_sequence_and_ack": True,
                "client_stream_bounded_and_closed": True,
                "private_socket_revalidated": True,
                "synthetic_browser_input_to_pixel_only": True,
                "actual_x11vnc_executed": False,
                "real_desktop_pixels_proven": False,
                "browser_novnc_render_proven": False,
                "producer_approved": False,
                "activation_permitted": False,
                "viborg1_changed": False,
            }
        finally:
            if task and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, 2)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
            server.close()
            await server.wait_closed()
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def main() -> int:
    try:
        release = Path("/etc/os-release").read_text(encoding="utf-8")
        if not ci_gate.authorized_ci(dict(os.environ), release, os.geteuid()):
            raise SyntheticRfbError("Only unprivileged ephemeral Ubuntu 26.04 GitHub CI")
        result = asyncio.run(asyncio.wait_for(probe(), timeout=25))
        success = True
    except (OSError, ValueError, SyntheticRfbError, asyncio.TimeoutError) as exc:
        result = {
            "schema": "63d43-private-synthetic-rfb38-v1",
            "evidence_pass": False,
            "producer_approved": False,
            "activation_permitted": False,
            "viborg1_changed": False,
            "reason": "STOP: " + str(exc),
        }
        success = False
    print(json.dumps(result, sort_keys=True, indent=2), flush=True)
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
