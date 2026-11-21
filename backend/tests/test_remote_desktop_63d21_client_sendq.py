"""63D-21: bounded upstream JPEG media while retaining remote input semantics."""
from __future__ import annotations

from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client" / "runtime"))

from clientflow_runtime import remote_desktop_media_pressure as pressure  # noqa: E402


def test_socket_query_does_not_report_false_zero_on_http_fallback_or_missing_socket():
    assert pressure.socket_send_queue_bytes(None) is None
    assert pressure.socket_send_queue_bytes(object()) is None
    assert pressure.socket_send_queue_bytes(type("Http", (), {"transport": object()})()) is None


def test_linux_socket_outgoing_bytes_are_observed_without_exposing_peers(monkeypatch):
    class FakeSocket:
        family = socket.AF_INET

        def fileno(self):
            return 71

    class FakeTransport:
        def get_extra_info(self, name):
            assert name == "socket"
            return FakeSocket()

    class FakeWs:
        transport = FakeTransport()

    def fake_ioctl(fd, code, pending, mutate=True):
        assert fd == 71
        assert code == pressure._LINUX_SIOCOUTQ
        pending[0] = 3_500_000

    monkeypatch.setattr(pressure.fcntl, "ioctl", fake_ioctl)
    assert pressure.socket_send_queue_bytes(FakeWs()) == 3_500_000


def test_actual_socket_pressure_defers_only_video_and_recovers():
    controller = pressure.MediaPressure()
    limit = pressure.MAX_CONTROL_SENDQ_BYTES
    assert controller.jpeg_quality(72, now=1.0) == 72
    assert not controller.should_defer(None, now=1.0)
    assert not controller.should_defer(limit - 1, now=2.0)
    assert controller.should_defer(limit, now=3.0)
    assert controller.deferred_frames == 1
    assert controller.jpeg_quality(72, now=4.0) == 40
    assert not controller.should_defer(0, now=4.0)
    assert controller.jpeg_quality(72, now=18.1) == 72
    assert controller.jpeg_quality(35, now=5.0) == 35


def test_slow_write_triggers_jpeg_quality_reduction_without_socket_telemetry():
    controller = pressure.MediaPressure()
    controller.observe_send(349.9, now=1.0)
    assert controller.jpeg_quality(72, now=2.0) == 72
    controller.observe_send(350.0, now=3.0)
    assert controller.jpeg_quality(72, now=4.0) == 40
    controller.observe_send(450.0, now=15.0)
    assert controller.jpeg_quality(72, now=29.0) == 40
    assert controller.jpeg_quality(72, now=30.0) == 72


def test_video_is_gated_before_capture_and_input_lane_untouched():
    source = (
        ROOT / "client" / "runtime" / "clientflow_runtime" /
        "remote_desktop_agent.py"
    ).read_text(encoding="utf-8")
    stream_loop = source.split("async def _stream_loop(", 1)[1].split(
        "async def _start_stream(", 1
    )[0]
    assert stream_loop.index("pressure.should_defer(") < stream_loop.index(
        "await self._capture("
    )
    assert "frames_deferred_for_control_sendq" in stream_loop
    assert "await asyncio.sleep(0.06)" in stream_loop
    assert "if isinstance(self.control_ws, _HttpRelaySocket):" in stream_loop
    assert 'self.media_pressure.pop(session_id, None)' in source
    assert "if message_type not in {\"mouse\", \"key\", \"text\"}:" in source
    assert "await self._input_rpc(socket, request)" in source
