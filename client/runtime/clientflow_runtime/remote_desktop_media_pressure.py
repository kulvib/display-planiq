"""Bound Remote Desktop JPEG production to the Linux control WebSocket's TCP pressure.

Only video capture is deferred. Input, clicks, keyboard, file and control events
are never dropped or throttled. If Linux socket telemetry is unavailable, the
system retains the existing send path and still lowers JPEG quality when a send
operation itself becomes slow.
"""
from __future__ import annotations

import array
import fcntl
import socket
from typing import Any

# TIOCOUTQ/SIOCOUTQ on Linux: bytes waiting in the TCP send queue.
_LINUX_SIOCOUTQ = 0x5411
MAX_CONTROL_SENDQ_BYTES = 192 * 1024
PRESSURE_HOLD_SECONDS = 15.0
SLOW_SEND_MILLISECONDS = 350.0
CONGESTED_JPEG_QUALITY = 40


def socket_send_queue_bytes(websocket: Any) -> int | None:
    """Read the actual Linux socket queue without exposing any peer or secrets.

    Unlike the asyncio transport buffer, TCP outq includes kernel-side pressure.
    HTTP relay and unsupported socket adapters return None (not a false zero).
    """
    try:
        transport = getattr(websocket, "transport", None)
        if transport is None:
            return None
        getter = getattr(transport, "get_extra_info", None)
        if not callable(getter):
            return None
        sock = getter("socket")
        if sock is None or sock.family not in (socket.AF_INET, socket.AF_INET6):
            return None
        pending = array.array("i", [0])
        fcntl.ioctl(sock.fileno(), _LINUX_SIOCOUTQ, pending, True)
        return max(0, int(pending[0]))
    except (AttributeError, TypeError, ValueError, OSError):
        return None


class MediaPressure:
    """Session-local control for video only; no client input path uses this."""

    def __init__(self) -> None:
        self.congested_until = 0.0
        self.deferred_frames = 0

    def should_defer(self, pending_bytes: int | None, *, now: float) -> bool:
        if pending_bytes is None or pending_bytes < MAX_CONTROL_SENDQ_BYTES:
            return False
        self.congested_until = max(self.congested_until, now + PRESSURE_HOLD_SECONDS)
        self.deferred_frames += 1
        return True

    def observe_send(self, elapsed_ms: float, *, now: float) -> None:
        if elapsed_ms >= SLOW_SEND_MILLISECONDS:
            self.congested_until = max(self.congested_until, now + PRESSURE_HOLD_SECONDS)

    def jpeg_quality(self, requested: int, *, now: float) -> int:
        if now < self.congested_until:
            return max(35, min(int(requested), CONGESTED_JPEG_QUALITY))
        return int(requested)
