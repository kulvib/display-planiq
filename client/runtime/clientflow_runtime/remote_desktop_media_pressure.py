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
PRESSURE_HOLD_SECONDS = 8.0
SLOW_SEND_MILLISECONDS = 350.0
CONGESTED_JPEG_QUALITY = 68


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

# Keep native desktop coordinates independent of encoded JPEG size.
# Preserve readable UI text: 1920px normal, at least 1600px under pressure.
NORMAL_MAX_FRAME_WIDTH = 1920
NORMAL_MAX_FRAME_HEIGHT = 1080
CONGESTED_MAX_FRAME_WIDTH = 1600
CONGESTED_MAX_FRAME_HEIGHT = 900


def bounded_capture_dimensions(
    native_width: int, native_height: int, *, congested: bool,
) -> tuple[int, int]:
    """Aspect-ratio preserving, even-pixel JPEG bounds for non-native capture.

    Only used after the first genuine native capture reports the screen geometry.
    The original width and height must remain the *screen* geometry forwarded
    to the browser for mouse input and accurate aspect ratio.
    """
    width, height = int(native_width), int(native_height)
    if not 320 <= width <= 7680 or not 200 <= height <= 4320:
        raise ValueError("Ugyldige oprindelige skærmdimensioner")
    max_width = CONGESTED_MAX_FRAME_WIDTH if congested else NORMAL_MAX_FRAME_WIDTH
    max_height = CONGESTED_MAX_FRAME_HEIGHT if congested else NORMAL_MAX_FRAME_HEIGHT
    factor = min(1.0, max_width / width, max_height / height)
    if factor == 1.0:
        return (width, height)
    # GStreamer needs at least 320x200. Extreme portrait/landscape displays
    # can exceed one nominal budget slightly to preserve their aspect ratio.
    factor = max(factor, 320 / width, 200 / height)
    # Even dimensions minimize video backend and encoder compatibility issues.
    scaled_w = max(320, int(width * factor) // 2 * 2)
    scaled_h = max(200, int(height * factor) // 2 * 2)
    return (min(width, scaled_w), min(height, scaled_h))
