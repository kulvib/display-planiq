"""63D-34: strictly bounded native RDP byte framing for a future browser tunnel.

Pure protocol only. It deliberately has NO network listener, GNOME activation,
credentials, subprocesses or session authorisation. The authenticated FastAPI
broker must bind session_id and stream_id before accepting these envelopes.
"""
from __future__ import annotations

import base64
import binascii
from collections import deque
from dataclasses import dataclass, field
import re
import uuid

PROTOCOL_VERSION = 1
MAX_CHUNK_BYTES = 16 * 1024
MAX_UNACKED_CHUNKS = 8
MAX_SEQUENCE = 2**31 - 1
_FRAME_KEYS = {"type", "protocol", "session_id", "stream_id", "seq", "data"}
_CANONICAL_BASE64 = re.compile(r"^[A-Za-z0-9+/]*={0,2}$")


class NativeRdpProtocolError(ValueError):
    """Fail-closed protocol error; never include untrusted frame contents."""


def _identity(raw: object) -> str:
    if type(raw) is not str:
        raise NativeRdpProtocolError("invalid RDP stream identity")
    try:
        result = str(uuid.UUID(raw))
    except (TypeError, ValueError, AttributeError) as exc:
        raise NativeRdpProtocolError("invalid RDP stream identity") from exc
    if raw != result:
        raise NativeRdpProtocolError("noncanonical RDP stream identity")
    return result


@dataclass(frozen=True)
class NativeRdpChunk:
    session_id: str
    stream_id: str
    seq: int
    payload: bytes


def encode_chunk(*, session_id: str, stream_id: str, seq: int, payload: bytes) -> dict:
    session_id = _identity(session_id)
    stream_id = _identity(stream_id)
    if type(seq) is not int or not 0 <= seq <= MAX_SEQUENCE:
        raise NativeRdpProtocolError("invalid RDP sequence")
    if type(payload) is not bytes or not 0 < len(payload) <= MAX_CHUNK_BYTES:
        raise NativeRdpProtocolError("invalid RDP chunk size")
    return {
        "type": "native_rdp_chunk", "protocol": PROTOCOL_VERSION,
        "session_id": session_id, "stream_id": stream_id, "seq": seq,
        "data": base64.b64encode(payload).decode("ascii"),
    }


def decode_chunk(message: object, *, session_id: str, stream_id: str) -> NativeRdpChunk:
    expected_session = _identity(session_id)
    expected_stream = _identity(stream_id)
    if type(message) is not dict or set(message) != _FRAME_KEYS:
        raise NativeRdpProtocolError("invalid RDP envelope")
    if message.get("type") != "native_rdp_chunk" or type(message.get("protocol")) is not int or message["protocol"] != PROTOCOL_VERSION:
        raise NativeRdpProtocolError("unsupported RDP envelope")
    if _identity(message["session_id"]) != expected_session or _identity(message["stream_id"]) != expected_stream:
        raise NativeRdpProtocolError("RDP session or stream mismatch")
    seq = message["seq"]
    if type(seq) is not int or not 0 <= seq <= MAX_SEQUENCE:
        raise NativeRdpProtocolError("invalid RDP sequence")
    raw = message["data"]
    if type(raw) is not str or not raw or len(raw) > ((MAX_CHUNK_BYTES + 2) // 3) * 4 or not _CANONICAL_BASE64.fullmatch(raw):
        raise NativeRdpProtocolError("invalid RDP base64 chunk")
    try:
        payload = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise NativeRdpProtocolError("invalid RDP base64 chunk") from exc
    if not payload or len(payload) > MAX_CHUNK_BYTES or base64.b64encode(payload).decode("ascii") != raw:
        raise NativeRdpProtocolError("noncanonical RDP chunk")
    return NativeRdpChunk(expected_session, expected_stream, seq, payload)


@dataclass
class NativeRdpSequenceWindow:
    """Separate instance PER direction and PER authorised session/stream.

    RDP is an ordered byte stream: unlike a JPEG frame, no chunk may be
    dropped, replaced, reordered or replayed. A new connection uses a new
    stream UUID and a new window; credits stay bounded under backpressure.
    """

    session_id: str
    stream_id: str
    next_seq: int = 0
    pending: deque[int] = field(default_factory=deque)

    def __post_init__(self) -> None:
        self.session_id = _identity(self.session_id)
        self.stream_id = _identity(self.stream_id)

    def accept(self, message: object) -> bytes:
        chunk = decode_chunk(message, session_id=self.session_id, stream_id=self.stream_id)
        if chunk.seq != self.next_seq or self.next_seq >= MAX_SEQUENCE:
            raise NativeRdpProtocolError("out-of-order RDP chunk")
        if len(self.pending) >= MAX_UNACKED_CHUNKS:
            raise NativeRdpProtocolError("RDP credit limit exceeded")
        self.pending.append(chunk.seq)
        self.next_seq += 1
        return chunk.payload

    def acknowledge(self, seq: int) -> None:
        if type(seq) is not int or not self.pending or seq != self.pending[0]:
            raise NativeRdpProtocolError("out-of-order RDP acknowledgement")
        self.pending.popleft()

    def close(self) -> None:
        self.pending.clear()
        self.next_seq = MAX_SEQUENCE
