"""Bounded continuous Livestream relay core, deliberately not registered as a route.

A single event-loop owner must authorize client/generation and each reader
before using this core. Opaque fMP4 payloads must be validated by the capture
pipeline; a fragment flag is not proof of independent decodability. Never use
this lossy video relay for Remote Desktop. Socket/in-flight budgets are separate.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct

MAGIC = b"CFLS"
VERSION = 1
INIT = 1
FRAGMENT = 2
HEADER = struct.Struct(">4sBBHQQI")
MAX_INIT = 128 * 1024
MAX_FRAGMENT = 2 * 1024 * 1024
MAX_INTEGER = (1 << 53) - 1
MAX_CHANNELS = 16
MAX_RETAINED = 32 * 1024 * 1024


class MediaFault(ValueError):
    """Fixed error messages only; never include credentials or media."""


@dataclass(frozen=True)
class Frame:
    kind: int
    sequence: int
    timestamp_us: int
    wire: bytes


def decode_frame(wire: bytes) -> Frame:
    if type(wire) is not bytes or not HEADER.size < len(wire) <= HEADER.size + MAX_FRAGMENT:
        raise MediaFault("invalid frame size")
    magic, version, kind, reserved, seq, timestamp, size = HEADER.unpack_from(wire)
    if magic != MAGIC or version != VERSION or reserved != 0:
        raise MediaFault("invalid frame header")
    if seq > MAX_INTEGER or timestamp > MAX_INTEGER or size != len(wire) - HEADER.size:
        raise MediaFault("invalid frame fields")
    if kind == INIT:
        if seq != 0 or timestamp != 0 or size > MAX_INIT:
            raise MediaFault("invalid init")
    elif kind == FRAGMENT:
        if seq == 0 or size > MAX_FRAGMENT:
            raise MediaFault("invalid fragment")
    else:
        raise MediaFault("invalid frame kind")
    return Frame(kind, seq, timestamp, wire)


def encode_frame(kind: int, sequence: int, timestamp_us: int, payload: bytes) -> bytes:
    if (type(kind) is not int or kind not in (INIT, FRAGMENT)
            or type(sequence) is not int or not 0 <= sequence <= MAX_INTEGER
            or type(timestamp_us) is not int or not 0 <= timestamp_us <= MAX_INTEGER
            or type(payload) is not bytes or not 0 < len(payload) <= (MAX_INIT if kind == INIT else MAX_FRAGMENT)):
        raise MediaFault("invalid frame input")
    wire = HEADER.pack(MAGIC, VERSION, kind, 0, sequence, timestamp_us, len(payload)) + payload
    decode_frame(wire)
    return wire


@dataclass(frozen=True, eq=False)
class Epoch:
    """Identity-only handle; never serialize this as an authorization token."""
    client_id: int
    generation_id: str


@dataclass
class _Channel:
    epoch: Epoch
    init: Frame | None = None
    latest: Frame | None = None

    @property
    def retained(self) -> int:
        return sum(len(frame.wire) for frame in (self.init, self.latest) if frame is not None)


@dataclass(frozen=True)
class Latest:
    frames: tuple[Frame, ...]
    sequence: int
    reset_decoder: bool


class LiveRelay:
    """Retain only current init and newest complete independent fragment.

    No reader queue, no disk, no per-fragment DB work. Slow readers receive a
    reset plus the newest fragment, not an unbounded backlog. Returned snapshots
    are immutable and may still be held by callers: the router must separately
    limit viewers, in-flight references, send time and websocket message size.
    """

    def __init__(self, *, max_channels: int = MAX_CHANNELS, max_retained: int = MAX_RETAINED):
        if (type(max_channels) is not int or not 1 <= max_channels <= MAX_CHANNELS
                or type(max_retained) is not int or not 1 <= max_retained <= MAX_RETAINED):
            raise ValueError("invalid relay budget")
        self.max_channels = max_channels
        self.max_retained = max_retained
        self._channels: dict[int, _Channel] = {}
        self._retained = 0

    @property
    def retained(self) -> int:
        return self._retained

    def open(self, client_id: int, generation_id: str) -> Epoch:
        if (type(client_id) is not int or not 0 < client_id <= MAX_INTEGER
                or type(generation_id) is not str or not 1 <= len(generation_id) <= 128):
            raise MediaFault("invalid channel")
        if client_id in self._channels:
            raise MediaFault("publisher already active")
        if len(self._channels) >= self.max_channels:
            raise MediaFault("channel capacity")
        epoch = Epoch(client_id, generation_id)
        self._channels[client_id] = _Channel(epoch)
        return epoch

    def current(self, client_id: int, generation_id: str) -> Epoch | None:
        channel = self._channels.get(client_id)
        if channel is None or channel.epoch.generation_id != generation_id:
            return None
        return channel.epoch

    def _channel(self, epoch: Epoch) -> _Channel:
        if not isinstance(epoch, Epoch):
            raise MediaFault("invalid epoch")
        channel = self._channels.get(epoch.client_id)
        if channel is None or channel.epoch is not epoch:
            raise MediaFault("stale epoch")
        return channel

    def close(self, epoch: Epoch) -> bool:
        if not isinstance(epoch, Epoch):
            return False
        channel = self._channels.get(epoch.client_id)
        if channel is None or channel.epoch is not epoch:
            return False
        self._retained -= channel.retained
        del self._channels[epoch.client_id]
        return True

    def publish(self, epoch: Epoch, wire: bytes) -> int:
        channel = self._channel(epoch)
        try:
            frame = decode_frame(wire)
            if frame.kind == INIT:
                if channel.init is not None:
                    raise MediaFault("duplicate init")
                replaced = 0
            else:
                if channel.init is None:
                    raise MediaFault("missing init")
                if channel.latest is not None:
                    if (frame.sequence <= channel.latest.sequence
                            or frame.timestamp_us <= channel.latest.timestamp_us):
                        raise MediaFault("nonmonotonic fragment")
                replaced = len(channel.latest.wire) if channel.latest else 0
            next_retained = self._retained - replaced + len(wire)
            if next_retained > self.max_retained:
                raise MediaFault("retained capacity")
            if frame.kind == INIT:
                channel.init = frame
            else:
                channel.latest = frame
            self._retained = next_retained
            return frame.sequence
        except MediaFault:
            # A malformed publisher must not leave stale video available.
            self.close(epoch)
            raise

    def latest(self, epoch: Epoch, after: int = 0) -> Latest | None:
        channel = self._channel(epoch)
        if type(after) is not int or not 0 <= after <= MAX_INTEGER:
            raise MediaFault("invalid reader cursor")
        fragment = channel.latest
        if fragment is None:
            if after != 0:
                raise MediaFault("invalid reader cursor")
            return None
        if after > fragment.sequence:
            raise MediaFault("invalid reader cursor")
        if after == fragment.sequence:
            return None
        reset = after == 0 or fragment.sequence != after + 1
        if reset:
            assert channel.init is not None
            return Latest((channel.init, fragment), fragment.sequence, True)
        return Latest((fragment,), fragment.sequence, False)
