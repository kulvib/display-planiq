"""63D-34: bounded, session-bound RDP stream ownership and flow control.

The only source of trust is the authenticated PlanIQ broker. An opaque RDP byte
stream is NOT a JPEG frame and must never use the latest-frame-drop algorithm.
Nothing here opens GNOME/RDP, creates credentials or exposes a TCP listener.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import time
import uuid

from .native_rdp_bridge_protocol import (
    MAX_SEQUENCE, PROTOCOL_VERSION, NativeRdpProtocolError,
    NativeRdpSequenceWindow,
)

MAX_NATIVE_RDP_SESSION_SECONDS = 360
_ACK_FIELDS = {"type", "protocol", "session_id", "stream_id", "seq"}
_STATE_FIELDS = {"type", "protocol", "session_id", "stream_id"}


def _validate_header(message: object, *, expected_type: str, session_id: str,
                     stream_id: str, fields: set[str]) -> dict:
    if type(message) is not dict or set(message) != fields:
        raise NativeRdpProtocolError("invalid RDP control envelope")
    if (message.get("type") != expected_type
            or type(message.get("protocol")) is not int
            or message["protocol"] != PROTOCOL_VERSION
            or message.get("session_id") != session_id
            or message.get("stream_id") != stream_id):
        raise NativeRdpProtocolError("RDP session, generation or protocol mismatch")
    return message


@dataclass
class NativeRdpRelaySession:
    """One mutually exclusive GNOME RDP bridge generation per browser session."""

    session_id: str
    client_id: int
    stream_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = field(default_factory=time.monotonic)
    ready: bool = False
    closed: bool = False
    browser_to_agent: NativeRdpSequenceWindow = field(init=False)
    agent_to_browser: NativeRdpSequenceWindow = field(init=False)

    def __post_init__(self) -> None:
        if type(self.client_id) is not int or self.client_id < 1:
            raise NativeRdpProtocolError("invalid RDP client identity")
        self.browser_to_agent = NativeRdpSequenceWindow(self.session_id, self.stream_id)
        self.agent_to_browser = NativeRdpSequenceWindow(self.session_id, self.stream_id)

    def _active(self, now: float | None = None) -> None:
        if self.closed or (time.monotonic() if now is None else now) >= (
                self.created_at + MAX_NATIVE_RDP_SESSION_SECONDS):
            self.close()
            raise NativeRdpProtocolError("RDP generation expired or closed")

    def _control(self, kind: str) -> dict:
        return {"type": kind, "protocol": PROTOCOL_VERSION,
                "session_id": self.session_id, "stream_id": self.stream_id}

    def open_request(self, *, now: float | None = None) -> dict:
        self._active(now)
        return self._control("native_rdp_open")

    def agent_ready(self, message: object, *, now: float | None = None) -> dict:
        self._active(now)
        if self.ready:
            raise NativeRdpProtocolError("duplicate RDP readiness")
        _validate_header(message, expected_type="native_rdp_ready",
                         session_id=self.session_id, stream_id=self.stream_id,
                         fields=_STATE_FIELDS)
        self.ready = True
        return self._control("native_rdp_ready")

    def accept_chunk(self, message: object, *, origin: str,
                     now: float | None = None) -> dict:
        self._active(now)
        if not self.ready:
            raise NativeRdpProtocolError("RDP stream not ready")
        window = self.browser_to_agent if origin == "browser" else (
            self.agent_to_browser if origin == "agent" else None)
        if window is None:
            raise NativeRdpProtocolError("unknown RDP origin")
        window.accept(message)
        return message  # validated, never modified or logged

    def accept_ack(self, message: object, *, origin: str,
                   now: float | None = None) -> dict:
        self._active(now)
        if not self.ready:
            raise NativeRdpProtocolError("RDP stream not ready")
        _validate_header(message, expected_type="native_rdp_ack",
                         session_id=self.session_id, stream_id=self.stream_id,
                         fields=_ACK_FIELDS)
        seq = message["seq"]
        if type(seq) is not int or not 0 <= seq <= MAX_SEQUENCE:
            raise NativeRdpProtocolError("invalid RDP acknowledgement sequence")
        # Browser acknowledges data originally sent by agent; vice versa.
        window = self.agent_to_browser if origin == "browser" else (
            self.browser_to_agent if origin == "agent" else None)
        if window is None:
            raise NativeRdpProtocolError("unknown RDP origin")
        window.acknowledge(seq)
        return message

    def stop(self, message: object, *, now: float | None = None) -> dict:
        self._active(now)
        _validate_header(message, expected_type="native_rdp_close",
                         session_id=self.session_id, stream_id=self.stream_id,
                         fields=_STATE_FIELDS)
        result = self._control("native_rdp_close")
        self.close()
        return result

    def close(self) -> None:
        self.closed = True
        self.ready = False
        self.browser_to_agent.close()
        self.agent_to_browser.close()

    def fail_closed(self) -> dict:
        result = self._control("native_rdp_close")
        self.close()
        return result
