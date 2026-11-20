"""63D-15: deterministic zero-frame alternate buffer policy for both media domains.

No actual Mutter session, screen, PipeWire server, display data or network.
All capture tests stub GStreamer and operate only on pipeline specifications.
"""
from __future__ import annotations

import ast
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client/runtime"))

from clientflow_runtime import livestream_producer  # noqa: E402

LIVESTREAM = ROOT / "client/runtime/clientflow_runtime/livestream_wayland_capture.py"
REMOTE = ROOT / "client/runtime/clientflow_runtime/remote_desktop_mutter_worker.py"


def _ast_entry(path, name):
    return next(
        node for node in ast.parse(path.read_text(encoding="utf-8")).body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name
    )


def test_livestream_normal_then_bounded_capture_policy(monkeypatch):
    class Pipe:
        pass

    descriptions = []
    Gst = SimpleNamespace(Pipeline=Pipe, parse_launch=lambda desc: (descriptions.append(desc), Pipe())[1])
    scope = {"Gst": Gst}
    exec(compile(ast.Module(body=[_ast_entry(LIVESTREAM, "_build_pipeline")], type_ignores=[]), str(LIVESTREAM), "exec"), scope)
    build = scope["_build_pipeline"]

    for mode in ("normal", "bounded"):
        build(63, Path("/tmp/test"), 10, 12000, "veryfast", 2, 8, source_mode=mode)

    original, alternative = descriptions
    assert "pipewiresrc name=capture_source path=63" in original
    assert "use-bufferpool=" not in original
    assert "max-buffers=" not in original
    assert "min-buffers=" not in original
    assert "min-buffers=2 max-buffers=4 use-bufferpool=false" in alternative
    for desc in descriptions:
        assert "x264enc name=h264_encoder tune=zerolatency" in desc
        assert "video/x-raw,format=I420,framerate=10/1" in desc
        assert "hlssink target-duration=2 playlist-length=8" in desc
        assert "width=" not in desc and "height=" not in desc
        assert "videoscale" not in desc
    with pytest.raises(ValueError, match="Unknown PipeWire source mode"):
        build(63, Path("/tmp/test"), 10, 12000, "veryfast", 2, 8, source_mode="unsafe")


def test_producer_fallback_only_after_first_failed_attempt_and_generation_reset(monkeypatch):
    assert [livestream_producer.capture_source_mode(n) for n in (0, 1, 2, 9)] == [
        "normal", "bounded", "bounded", "bounded"
    ]
    producer = livestream_producer.Producer.__new__(livestream_producer.Producer)
    producer._retry_attempts = 0
    producer._retry_generation = None
    producer._retry_deadline = 0.0
    producer._healthy_since = None
    assert livestream_producer.capture_source_mode(producer._retry_attempts) == "normal"
    producer._reset_retry("f3056c30-d524-4a8d-9dd5-cc43fbcd41b6")
    producer._retry_attempts = 1
    assert livestream_producer.capture_source_mode(producer._retry_attempts) == "bounded"
    producer._reset_retry("5f166a2e-edfc-45ef-b4dc-286c3e799416")
    assert producer._retry_attempts == 0
    assert livestream_producer.capture_source_mode(producer._retry_attempts) == "normal"


def test_producer_only_passes_fixed_mode_argument_to_unprivileged_child(monkeypatch, tmp_path):
    import uuid
    producer = livestream_producer.Producer.__new__(livestream_producer.Producer)
    producer.generation_id = None
    producer.process = None
    producer._retry_attempts = 1
    producer._configuration = lambda: (10, 12000, "veryfast", 2, 8)
    producer._resolve_wayland_user = lambda: ("clientflow-kiosk", 1001, 1001, "/home/clientflow-kiosk", Path("/run/user/1001"))
    producer._prepare_capture_state = lambda _u, _i: tmp_path / "cache"
    producer._prepare_output = lambda _g, _u, _i: tmp_path / "output"
    producer._wait_ready = lambda _, **_kw: None
    statuses = []
    producer._status = lambda state, **kw: statuses.append((state, kw))
    calls = []

    class Child:
        pid = 1234
        def poll(self):
            return None

    def popen(cmd, **kw):
        calls.append((cmd, kw))
        return Child()

    monkeypatch.setattr(livestream_producer.subprocess, "Popen", popen)
    producer._start(str(uuid.uuid4()))
    assert len(calls) == 1
    cmd, options = calls[0]
    assert cmd[cmd.index("--source-mode") + 1] == "bounded"
    assert "--output" in cmd
    assert options["stdin"] == livestream_producer.subprocess.DEVNULL
    assert options["close_fds"] is True
    assert options["start_new_session"] is True
    assert options["env"]["XDG_SESSION_TYPE"] == "wayland"
    assert [s for s, _ in statuses] == ["starting", "running"]
    assert all(data["source_mode"] == "bounded" for _, data in statuses)


def _load_remote_class(name, scope):
    exec(compile(ast.Module(body=[_ast_entry(REMOTE, name)], type_ignores=[]), str(REMOTE), "exec"), scope)
    return scope[name]


def test_remote_pipeline_preserves_native_and_scaled_geometry_in_both_modes():
    descriptions = []

    class Sink:
        pass

    class Pipeline:
        def get_by_name(self, key):
            assert key == "frame_sink"
            return Sink()
        def set_state(self, _):
            return "SUCCESS"

    Gst = SimpleNamespace(
        Pipeline=Pipeline,
        parse_launch=lambda description: (descriptions.append(description), Pipeline())[1],
        State=SimpleNamespace(PLAYING="PLAYING", NULL="NULL"),
        StateChangeReturn=SimpleNamespace(FAILURE="FAILURE"),
    )
    FramePipeline = _load_remote_class(
        "FramePipeline", {"Gst": Gst, "GstApp": SimpleNamespace(AppSink=Sink)}
    )
    obj = FramePipeline()
    obj.ensure(63, 1280, 720, 85, native=True, source_mode="normal")
    obj.ensure(63, 1280, 720, 85, native=True, source_mode="bounded")
    obj.ensure(63, 1280, 720, 85, native=False, source_mode="bounded")
    obj.ensure(63, 1280, 720, 85, native=False, source_mode="bounded")
    assert len(descriptions) == 3  # identical spec reuses running pipeline
    assert "use-bufferpool=" not in descriptions[0]
    assert "min-buffers=2 max-buffers=4 use-bufferpool=false" in descriptions[1]
    assert "min-buffers=2 max-buffers=4 use-bufferpool=false" in descriptions[2]
    assert "videoscale" not in descriptions[0] + descriptions[1]
    assert "videoscale" in descriptions[2]
    assert "pixel-aspect-ratio=1/1" in descriptions[2]
    assert "width=1280,height=720" in descriptions[2]
    assert "appsink name=frame_sink max-buffers=1 drop=true sync=false" in descriptions[2]
    with pytest.raises(ValueError, match="Ukendt PipeWire source mode"):
        obj.ensure(63, 1280, 720, 85, source_mode="unknown")


def test_remote_retries_just_once_with_bounded_buffers_only_on_no_frame():
    for first_error, expected_modes in (
        ("GStreamer returnerede ingen frame", ["normal", "bounded"]),
        ("Mutter returnerede ingen PipeWire-node", ["normal", "normal"]),
    ):
        seen = []

        class Cast:
            def start(self, monitor):
                assert monitor is None
                return 63, "HDMI-1"
            def close(self):
                pass

        class Pipeline:
            def close(self):
                pass
            def ensure(self, *_args, source_mode="normal", **_kw):
                seen.append(source_mode)
            def capture(self):
                if len(seen) == 1:
                    raise RuntimeError(first_error)
                return b"fake-jpeg", 1280, 720

        scope = {"MutterScreenCast": Cast, "FramePipeline": Pipeline,
                 "base64": __import__("base64")}
        Worker = _load_remote_class("Worker", scope)
        worker = Worker()
        result = worker.capture({"action": "capture", "width": 1280, "height": 720, "quality": 85})
        assert result["mime_type"] == "image/jpeg"
        assert result["monitor"] == "HDMI-1"
        assert seen == expected_modes
        assert worker.source_mode == expected_modes[-1]
        assert worker.node_id == 63
        assert worker.monitor == "HDMI-1"
        worker.stop_capture()
        assert worker.source_mode == "normal"


def test_remote_double_zero_frame_failure_has_bounded_termination():
    seen = []

    class Cast:
        def start(self, _):
            return 63, "HDMI-1"
        def close(self):
            pass

    class Pipeline:
        def close(self):
            pass
        def ensure(self, *_args, source_mode="normal", **_kw):
            seen.append(source_mode)
        def capture(self):
            raise RuntimeError("GStreamer returnerede ingen frame")

    scope = {"MutterScreenCast": Cast, "FramePipeline": Pipeline,
             "base64": __import__("base64")}
    Worker = _load_remote_class("Worker", scope)
    worker = Worker()
    with pytest.raises(RuntimeError, match="Mutter/PipeWire capture kunne ikke genetableres"):
        worker.capture({"action": "capture", "width": 1280, "height": 720, "quality": 85})
    assert seen == ["normal", "bounded"]
    assert worker.node_id is None
    assert worker.source_mode == "normal"


def test_phase63d13_update_coordinator_fix_is_still_in_source():
    transaction = (ROOT / "client/release/lib/clientflow_release/transaction.py").read_text()
    controller = (ROOT / "client/release/lib/clientflow_release/update_controller.py").read_text()
    assert "expected_update_deployment_id" in transaction
    assert "expected_update_deployment_id=snapshot.deployment_id" in controller


def _fake_livestream_start(monkeypatch, tmp_path, *, first_error, second_error=None):
    import uuid
    producer = livestream_producer.Producer.__new__(livestream_producer.Producer)
    producer._retry_attempts = 0
    producer.generation_id = None
    producer.process = None
    producer.logger = SimpleNamespace(warning=lambda *_args, **_kw: None)
    producer._configuration = lambda: (10, 12000, "veryfast", 2, 8)
    producer._resolve_wayland_user = lambda: ("clientflow-kiosk", 1001, 1001, "/home/clientflow-kiosk", Path("/run/user/1001"))
    producer._prepare_capture_state = lambda _u, _i: tmp_path / "cache"
    producer._prepare_output = lambda _g, _u, _i: tmp_path / "output"
    modes = []
    timeouts = []
    states = []

    class Child:
        pid = 2345
        def poll(self):
            return None

    def popen(cmd, **_kw):
        modes.append(cmd[cmd.index("--source-mode") + 1])
        return Child()

    def wait(_path, *, timeout):
        timeouts.append(timeout)
        if len(timeouts) == 1 and first_error:
            raise RuntimeError(first_error)
        if len(timeouts) == 2 and second_error:
            raise RuntimeError(second_error)

    producer._status = lambda state, **_kw: states.append(state)
    producer._stop = lambda: (
        states.append("stopped"), setattr(producer, "process", None),
        setattr(producer, "generation_id", None),
    )
    producer._wait_ready = wait
    monkeypatch.setattr(livestream_producer.subprocess, "Popen", popen)
    return producer, modes, timeouts, states, str(uuid.uuid4())


def test_livestream_ready_fallback_completes_before_agent_command_expires(monkeypatch, tmp_path):
    producer, modes, timeouts, states, generation = _fake_livestream_start(
        monkeypatch, tmp_path,
        first_error="Wayland capture blev ikke HLS-klar inden for 12 sekunder",
    )
    producer._start(generation)
    assert modes == ["normal", "bounded"]
    assert timeouts == [12.0, 14.0]
    assert sum(timeouts) < 45.0  # agent timeout includes remaining process-cleanup time
    assert states == ["starting", "stopped", "starting", "running"]
    assert producer.generation_id == generation


def test_livestream_non_timeout_error_does_not_attempt_bounded_mode(monkeypatch, tmp_path):
    producer, modes, timeouts, states, generation = _fake_livestream_start(
        monkeypatch, tmp_path, first_error="No valid Mutter monitor found",
    )
    with pytest.raises(RuntimeError, match="No valid Mutter monitor found"):
        producer._start(generation)
    assert modes == ["normal"]
    assert timeouts == [12.0]
    assert states == ["starting", "stopped"]


def test_livestream_failed_bounded_retry_stops_no_duplicate_third_capture(monkeypatch, tmp_path):
    producer, modes, timeouts, states, generation = _fake_livestream_start(
        monkeypatch, tmp_path,
        first_error="Wayland capture blev ikke HLS-klar inden for 12 sekunder",
        second_error="Wayland capture blev ikke HLS-klar inden for 14 sekunder",
    )
    with pytest.raises(RuntimeError, match="14 sekunder"):
        producer._start(generation)
    assert modes == ["normal", "bounded"]
    assert states == ["starting", "stopped", "starting", "stopped"]
    assert "running" not in states


def test_lease_wait_exceeds_bounded_attempt_budget_without_raising_default():
    import inspect
    from clientflow_runtime import livestream_agent
    assert inspect.signature(livestream_agent.LivestreamHandler._wait_producer).parameters["timeout"].default == 45.0
