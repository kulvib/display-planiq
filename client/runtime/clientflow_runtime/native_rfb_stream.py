"""63D-35: bounded client-side RFB byte relay over the authenticated native lane.

The GNOME Desktop Sharing -> FreeRDP/Xvfb -> local RFB bridge must be
provisioned by a separately approved root supervisor. This module receives an
ALREADY CONNECTED local stream; it cannot start an RDP/VNC server, open a
listener, select a remote host/port, or bypass its watchdog.

Both directions are ordered, 16 KiB, 8-credit ACK bounded, session/generation
bound and fully fail-closed. No screen pixels or secrets are written to disk.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
from collections import deque
import json
import time
from typing import Awaitable, Callable
import uuid

MAX_CHUNK = 16 * 1024
MAX_UNACKED = 8
MAX_SEQ = 2**31 - 1
LEASE_SECONDS = 360
_PROTOCOL = 1
_HEADER = {"type", "protocol", "session_id", "stream_id"}
_DATA_KEYS = _HEADER | {"seq", "data"}
_ACK_KEYS = _HEADER | {"seq"}


class NativeRfbStreamError(ValueError):
    """Invalid/replayed/oversized byte stream; never expose payload bytes."""


def _id(value: object) -> str:
    if type(value) is not str:
        raise NativeRfbStreamError("invalid stream identity")
    try:
        if str(uuid.UUID(value)) != value:
            raise NativeRfbStreamError("noncanonical stream identity")
    except (ValueError, TypeError, AttributeError) as exc:
        raise NativeRfbStreamError("invalid stream identity") from exc
    return value


def _seq(value: object) -> int:
    if type(value) is not int or not 0 <= value <= MAX_SEQ:
        raise NativeRfbStreamError("invalid stream sequence")
    return value


def _wire(payload: bytes, *, session_id: str, stream_id: str, seq: int) -> dict:
    if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_CHUNK:
        raise NativeRfbStreamError("invalid stream payload size")
    return {
        "type": "native_rdp_chunk", "protocol": _PROTOCOL,
        "session_id": session_id, "stream_id": stream_id,
        "seq": _seq(seq), "data": base64.b64encode(payload).decode("ascii"),
    }


class NativeRfbClientSession:
    """One RFB generation, owning exactly one preconnected socket."""

    def __init__(
        self, *, session_id: str, stream_id: str,
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
        send_json: Callable[[dict], Awaitable[None]],
        started_at: float | None = None,
    ) -> None:
        self.session_id = _id(session_id)
        self.stream_id = _id(stream_id)
        self.reader = reader
        self.writer = writer
        self.send_json = send_json
        self.started_at = time.monotonic() if started_at is None else started_at
        self.closed = False
        self.next_out = 0
        self.next_in = 0
        self.pending: deque[int] = deque()
        self.credit = asyncio.Event()
        self.credit.set()
        self.send_lock = asyncio.Lock()
        self.in_lock = asyncio.Lock()
        self.done = asyncio.Event()

    def _message(self, kind: str) -> dict:
        return {"type": kind, "protocol": _PROTOCOL,
                "session_id": self.session_id, "stream_id": self.stream_id}

    async def _send(self, message: dict) -> None:
        if self.closed:
            raise NativeRfbStreamError("stream already closed")
        async with self.send_lock:
            await self.send_json(message)

    def _check(self, message: object, kind: str, keys: set[str]) -> dict:
        if (type(message) is not dict or set(message) != keys
                or message.get("type") != kind
                or type(message.get("protocol")) is not int
                or message["protocol"] != _PROTOCOL
                or message.get("session_id") != self.session_id
                or message.get("stream_id") != self.stream_id):
            raise NativeRfbStreamError("invalid stream envelope")
        return message

    def _expiry(self) -> None:
        if self.closed or time.monotonic() - self.started_at >= LEASE_SECONDS:
            raise NativeRfbStreamError("stream expired or closed")

    async def receive(self, message: object) -> None:
        """Called only with JSON from the authenticated matching agent lane."""
        try:
            self._expiry()
            if type(message) is not dict:
                raise NativeRfbStreamError("invalid stream frame")
            kind = message.get("type")
            if kind == "native_rdp_chunk":
                frame = self._check(message, kind, _DATA_KEYS)
                seq = _seq(frame["seq"])
                async with self.in_lock:
                    if seq != self.next_in:
                        raise NativeRfbStreamError("reordered RFB input")
                    raw = frame["data"]
                    if type(raw) is not str or len(raw) > ((MAX_CHUNK + 2)//3)*4:
                        raise NativeRfbStreamError("invalid RFB input")
                    try:
                        payload = base64.b64decode(raw, validate=True)
                    except (binascii.Error, ValueError) as exc:
                        raise NativeRfbStreamError("invalid RFB input") from exc
                    if (not payload or len(payload) > MAX_CHUNK
                            or base64.b64encode(payload).decode("ascii") != raw):
                        raise NativeRfbStreamError("noncanonical RFB input")
                    self.writer.write(payload)
                    await asyncio.wait_for(self.writer.drain(), timeout=5)
                    self.next_in += 1
                    await self._send({**self._message("native_rdp_ack"), "seq": seq})
            elif kind == "native_rdp_ack":
                frame = self._check(message, kind, _ACK_KEYS)
                seq = _seq(frame["seq"])
                if not self.pending or self.pending[0] != seq:
                    raise NativeRfbStreamError("unexpected RFB acknowledgement")
                self.pending.popleft()
                self.credit.set()
            elif kind == "native_rdp_close":
                self._check(message, kind, _HEADER)
                await self.close()
            else:
                raise NativeRfbStreamError("invalid RFB stream message")
        except (NativeRfbStreamError, OSError, asyncio.TimeoutError):
            await self.close()
            raise

    async def run(self) -> None:
        """Send RFB bytes while session is open; stop on EOF/timeout/cancel."""
        try:
            self._expiry()
            await self._send(self._message("native_rdp_ready"))
            while not self.closed:
                self._expiry()
                if len(self.pending) >= MAX_UNACKED:
                    self.credit.clear()
                    try:
                        await asyncio.wait_for(self.credit.wait(), timeout=5)
                    except asyncio.TimeoutError as exc:
                        raise NativeRfbStreamError("RFB receiver not acknowledging") from exc
                    continue
                try:
                    payload = await asyncio.wait_for(self.reader.read(MAX_CHUNK), timeout=2)
                except asyncio.TimeoutError:
                    continue
                if not payload:
                    return
                seq = _seq(self.next_out)
                # Track before sending so a synchronous ACK cannot race state.
                self.pending.append(seq)
                self.next_out += 1
                await self._send(_wire(payload, session_id=self.session_id,
                                       stream_id=self.stream_id, seq=seq))
        finally:
            if not self.closed:
                try:
                    await self._send(self._message("native_rdp_close"))
                except Exception:
                    pass
            await self.close()

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.done.set()
        self.credit.set()
        self.pending.clear()
        self.writer.close()
        try:
            await asyncio.wait_for(self.writer.wait_closed(), timeout=2)
        except (OSError, asyncio.TimeoutError):
            pass
