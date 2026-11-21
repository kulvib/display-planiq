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
    assert controller.jpeg_quality(72, now=4.0) == 68
    assert not controller.should_defer(0, now=4.0)
    assert controller.jpeg_quality(72, now=18.1) == 72
    assert controller.jpeg_quality(35, now=5.0) == 35


def test_slow_write_triggers_jpeg_quality_reduction_without_socket_telemetry():
    controller = pressure.MediaPressure()
    controller.observe_send(349.9, now=1.0)
    assert controller.jpeg_quality(72, now=2.0) == 72
    controller.observe_send(350.0, now=3.0)
    assert controller.jpeg_quality(72, now=4.0) == 68
    controller.observe_send(450.0, now=15.0)
    assert controller.jpeg_quality(72, now=22.9) == 68
    assert controller.jpeg_quality(72, now=23.0) == 72


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


def test_16_by_9_native_capture_is_bounded_without_changing_pointer_geometry():
    assert pressure.bounded_capture_dimensions(3840, 2160, congested=False) == (1920, 1080)
    assert pressure.bounded_capture_dimensions(3840, 2160, congested=True) == (1600, 900)
    assert pressure.bounded_capture_dimensions(1280, 720, congested=False) == (1280, 720)
    assert pressure.bounded_capture_dimensions(1920, 1200, congested=False) == (1728, 1080)
    assert pressure.bounded_capture_dimensions(1080, 1920, congested=True) == (506, 900)
    # Viborg1 physical display: the text-bearing 2560×1080 wide desktop
    # must never collapse to the unreadable 960×404 / quality-40 profile.
    assert pressure.bounded_capture_dimensions(2560, 1080, congested=False) == (1920, 810)
    assert pressure.bounded_capture_dimensions(2560, 1080, congested=True) == (1600, 674)
    assert pressure.CONGESTED_JPEG_QUALITY >= 68
    assert pressure.CONGESTED_MAX_FRAME_WIDTH >= 1600


def test_remote_capture_scales_jpeg_only_after_native_probe_preserving_mouse_coordinates():
    import asyncio
    import time
    from clientflow_runtime import remote_desktop_agent as runtime

    class Media:
        name = "fake_jpeg"
        def __init__(self):
            self.calls = []

        async def capture(self, settings):
            self.calls.append(dict(settings))
            # Native GStreamer mode ignores capture width and height settings.
            w, h = (
                (3840, 2160) if settings["native"]
                else (settings["width"], settings["height"])
            )
            return {
                "data": "YWJj",
                "width": w, "height": h,
                "screen_width": w, "screen_height": h,
                "encoding": "base64", "mime_type": "image/jpeg",
            }, 12.0

    async def scenario():
        agent = object.__new__(runtime.RemoteDesktopAgent)
        agent.media_transport = Media()
        agent.media_pressure = {}
        agent.native_screen_geometry = {}
        agent.media_telemetry = {}
        agent.last_frame_digest = {}
        agent.last_frame_sent_at = {}
        agent.pending_input_at = {}
        agent.control_ws = object()
        agent._record_media_telemetry = lambda *args, **kwargs: None
        outbound = []
        async def send(message):
            outbound.append(message)
        agent._send_control = send
        options = {"native": True, "width": 1280, "height": 720, "quality": 72, "fps": 8}
        await agent._capture("session-test", options, force=True)
        assert agent.native_screen_geometry["session-test"] == (3840, 2160)
        agent.media_pressure["session-test"].congested_until = time.monotonic() + 100
        await agent._capture("session-test", options, force=True)
        agent.media_pressure["session-test"].congested_until = 0
        await agent._capture("session-test", options, force=True)

        first, stressed, restored = agent.media_transport.calls
        assert first["native"] is True
        assert stressed["native"] is False
        assert (stressed["width"], stressed["height"], stressed["quality"]) == (1600, 900, 68)
        assert restored["native"] is False
        assert (restored["width"], restored["height"], restored["quality"]) == (1920, 1080, 72)
        assert [(item["width"], item["height"]) for item in outbound] == [
            (3840, 2160), (1600, 900), (1920, 1080)
        ]
        assert all(
            (item["screen_width"], item["screen_height"]) == (3840, 2160)
            for item in outbound
        )
        assert agent.media_telemetry["session-test"]["native_screen_width"] == 3840
        assert agent.media_telemetry["session-test"]["capture_width_last"] == 1920

    asyncio.run(scenario())
