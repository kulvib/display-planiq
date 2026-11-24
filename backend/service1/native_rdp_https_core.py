"""Experimental native binary HTTPS peer; deliberately not exposed by a router.

Single event loop, no application authorization here. The future HTTP boundary
must authenticate before allocating a peer, bind every request to the same
owner/generation, bound streaming reads before push(), and close on ambiguous
HTTP delivery. No bytes are replayed or replaced. Not a generic TCP proxy.
"""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
import struct
import time
from typing import Callable

MAX_FRAME = 64 * 1024
MAX_BATCH = 256 * 1024
MAX_BATCH_FRAMES = 128
MAX_QUEUE = 2 * 1024 * 1024
MAX_QUEUE_FRAMES = 512
MAX_GLOBAL_QUEUE = 32 * 1024 * 1024
MAX_SEQUENCE = (1 << 53) - 1
POLL_SECONDS = 20.0
CONTACT_SECONDS = 45.0
_PREFIX = struct.Struct(">I")


class BinaryPeerFault(RuntimeError):
    """Fixed, content-free error; never echo an input frame or owner."""


@dataclass
class QueueBudget:
    limit: int = MAX_GLOBAL_QUEUE
    used: int = 0

    def reserve(self, size: int) -> bool:
        if size < 0 or self.used + size > self.limit:
            return False
        self.used += size
        return True

    def release(self, size: int) -> None:
        if not 0 <= size <= self.used:
            raise AssertionError("binary queue accounting")
        self.used -= size


def _valid_sequence(value: int) -> bool:
    return type(value) is int and 0 <= value < MAX_SEQUENCE


def _wire_size(frame: bytes) -> int:
    return _PREFIX.size + len(frame)


def _validate_frame(frame: bytes) -> None:
    if type(frame) is not bytes or not 0 < len(frame) <= MAX_FRAME:
        raise BinaryPeerFault("invalid binary frame")


def encode_batch(frames: list[bytes]) -> bytes:
    if not 0 < len(frames) <= MAX_BATCH_FRAMES:
        raise BinaryPeerFault("invalid binary batch count")
    total = 0
    for frame in frames:
        _validate_frame(frame)
        total += _wire_size(frame)
        if total > MAX_BATCH:
            raise BinaryPeerFault("binary batch too large")
    return b"".join(_PREFIX.pack(len(frame)) + frame for frame in frames)


def decode_batch(body: bytes) -> list[bytes]:
    if type(body) is not bytes or not 0 < len(body) <= MAX_BATCH:
        raise BinaryPeerFault("invalid binary batch")
    # Validate the entire body before exposing any frame to the tunnel.
    spans = []
    offset = 0
    while offset < len(body):
        if len(spans) >= MAX_BATCH_FRAMES or len(body) - offset < _PREFIX.size:
            raise BinaryPeerFault("invalid binary batch framing")
        size = _PREFIX.unpack_from(body, offset)[0]
        offset += _PREFIX.size
        end = offset + size
        if not 0 < size <= MAX_FRAME or end > len(body):
            raise BinaryPeerFault("invalid binary batch framing")
        spans.append((offset, end))
        offset = end
    return [body[start:end] for start, end in spans]


@dataclass(frozen=True)
class PollBatch:
    sequence: int
    body: bytes
    closed: bool = False


class BinaryHttpsPeer:
    """One authenticated HTTP endpoint's future data-plane socket adapter.

    push() consumes one ordered nonempty upload batch. poll() consumes one
    ordered download batch. An empty poll does not advance sequence. Sequence
    starts at zero; the next poll acknowledges the previous batch. Ambiguous
    delivery is terminal, not resumable. A new session must use a new peer.

    A shared QueueBudget covers both directions across all peers. It counts
    framed payload bytes, not Python objects or transient HTTP request memory;
    the HTTP boundary must separately cap concurrent bodies and responses.
    """

    def __init__(self, budget: QueueBudget, *, clock: Callable[[], float] = time.monotonic):
        self._budget = budget
        self._clock = clock
        self._last_contact = clock()
        self._incoming: deque[bytes] = deque()
        self._outgoing: deque[bytes] = deque()
        self._incoming_size = 0
        self._outgoing_size = 0
        self._upload_sequence = 0
        self._download_sequence = 0
        self._polling = False
        self._receiving = False
        self._in_ready = asyncio.Event()
        self._out_ready = asyncio.Event()
        self.closed = asyncio.Event()

    @property
    def queued_bytes(self) -> int:
        return self._incoming_size + self._outgoing_size

    def _close(self) -> None:
        if self.closed.is_set():
            return
        self.closed.set()
        self._budget.release(self.queued_bytes)
        self._incoming.clear()
        self._outgoing.clear()
        self._incoming_size = 0
        self._outgoing_size = 0
        self._in_ready.set()
        self._out_ready.set()

    def _fault(self, reason: str) -> None:
        self._close()
        raise BinaryPeerFault(reason)

    def _ensure_open(self) -> None:
        if self.closed.is_set():
            raise BinaryPeerFault("binary peer closed")
        if self._clock() - self._last_contact >= CONTACT_SECONDS:
            self._fault("binary peer contact expired")

    def push(self, sequence: int, body: bytes) -> int:
        """Return next expected upload sequence; never accept a replay."""
        self._ensure_open()
        if not _valid_sequence(sequence) or sequence != self._upload_sequence:
            self._fault("invalid upload sequence")
        try:
            frames = decode_batch(body)
        except BinaryPeerFault:
            self._close()
            raise
        size = len(body)
        if (self._incoming_size + size > MAX_QUEUE
                or len(self._incoming) + len(frames) > MAX_QUEUE_FRAMES
                or not self._budget.reserve(size)):
            self._fault("binary incoming capacity")
        self._incoming.extend(frames)
        self._incoming_size += size
        self._upload_sequence += 1
        self._last_contact = self._clock()
        self._in_ready.set()
        return self._upload_sequence

    async def receive(self) -> dict:
        """Native tunnel's receive() surface: binary data or disconnect."""
        if self._receiving:
            self._fault("concurrent binary receive")
        self._receiving = True
        try:
            while not self.closed.is_set():
                self._ensure_open()
                if self._incoming:
                    frame = self._incoming.popleft()
                    size = _wire_size(frame)
                    self._incoming_size -= size
                    self._budget.release(size)
                    return {"type": "websocket.receive", "bytes": frame}
                self._in_ready.clear()
                await self._in_ready.wait()
            return {"type": "websocket.disconnect", "code": 1000}
        except asyncio.CancelledError:
            self._close()
            raise
        finally:
            self._receiving = False

    async def send_bytes(self, frame: bytes) -> None:
        self._ensure_open()
        try:
            _validate_frame(frame)
        except BinaryPeerFault:
            self._close()
            raise
        size = _wire_size(frame)
        if (self._outgoing_size + size > MAX_QUEUE
                or len(self._outgoing) >= MAX_QUEUE_FRAMES
                or not self._budget.reserve(size)):
            self._fault("binary outgoing capacity")
        self._outgoing.append(frame)
        self._outgoing_size += size
        self._out_ready.set()

    async def poll(self, sequence: int, *, timeout: float = POLL_SECONDS) -> PollBatch:
        if self.closed.is_set():
            return PollBatch(self._download_sequence, b"", closed=True)
        self._ensure_open()
        if not _valid_sequence(sequence) or sequence != self._download_sequence:
            self._fault("invalid download acknowledgement")
        if self._polling:
            self._fault("concurrent binary poll")
        if type(timeout) not in (int, float) or not 0 < timeout <= POLL_SECONDS:
            self._fault("invalid poll timeout")
        self._polling = True
        self._last_contact = self._clock()
        try:
            if not self._outgoing:
                self._out_ready.clear()
                try:
                    await asyncio.wait_for(self._out_ready.wait(), timeout=timeout)
                except asyncio.TimeoutError:
                    pass
            if self.closed.is_set():
                return PollBatch(sequence, b"", closed=True)
            self._ensure_open()
            frames = []
            size = 0
            while self._outgoing and len(frames) < MAX_BATCH_FRAMES:
                frame = self._outgoing[0]
                framed_size = _wire_size(frame)
                if size + framed_size > MAX_BATCH:
                    break
                frames.append(self._outgoing.popleft())
                size += framed_size
            if not frames:
                return PollBatch(sequence, b"")
            self._outgoing_size -= size
            self._budget.release(size)
            self._download_sequence += 1
            return PollBatch(sequence, encode_batch(frames))
        except asyncio.CancelledError:
            self._close()
            raise
        finally:
            self._polling = False

    async def supervise(self, *, interval: float = 1.0) -> None:
        """Mandatory independent lifecycle task for any future HTTP owner."""
        if type(interval) not in (int, float) or not 0 < interval <= 1:
            self._fault("invalid supervisor interval")
        try:
            while not self.closed.is_set():
                if self._clock() - self._last_contact >= CONTACT_SECONDS:
                    self._close()
                    return
                try:
                    await asyncio.wait_for(self.closed.wait(), timeout=interval)
                except asyncio.TimeoutError:
                    pass
        finally:
            self._close()

    async def close(self, **_kwargs) -> None:
        self._close()
