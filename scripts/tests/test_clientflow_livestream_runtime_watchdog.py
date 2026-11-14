"""Deterministic liveness contract for an already-ready, unprivileged HLS capture.

GStreamer is stubbed: this test must never open a Mutter session or a screen.
"""
from __future__ import annotations

import ast
from contextlib import redirect_stdout
import io
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client/runtime"))
CAPTURE = ROOT / "client/runtime/clientflow_runtime/livestream_wayland_capture.py"


def _load_pipeline(scope):
    tree = ast.parse(CAPTURE.read_text(encoding="utf-8"))
    function = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_run_pipeline"
    )
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(CAPTURE), "exec"), scope)
    return scope["_run_pipeline"]


def _run_case(tmp_path, *, times, update_hls, stop_at=None, mux_list=False):
    playlist = tmp_path / "index.m3u8"
    segment = tmp_path / "segment-000000001.ts"
    playlist.write_text("#EXTM3U\n", encoding="ascii")
    segment.write_bytes(b"video")
    counter = {"tick": 0}
    stdout = io.StringIO()
    probe_types = []
    removed = []
    scope = {"_STOP": False, "Path": Path}

    class ProbeInfo:
        type = 2
        def get_buffer_list(self):
            return SimpleNamespace(length=lambda: 7)

    class Pad:
        def add_probe(self, flags, callback, stage):
            probe_types.append(flags)
            callback(self, ProbeInfo() if mux_list and stage == "muxed" else None, stage)
            return 10
        def remove_probe(self, probe_id):
            removed.append(probe_id)

    class Element:
        def get_static_pad(self, name):
            assert name == "src"
            return Pad()

    class Bus:
        def timed_pop_filtered(self, *_args):
            counter["tick"] += 1
            if update_hls and counter["tick"] > 1:
                # Force an mtime-only update without depending on wall clock.
                stamp = 1_800_000_000_000_000_000 + counter["tick"] * 1_000_000_000
                os.utime(playlist, ns=(stamp, stamp))
                os.utime(segment, ns=(stamp, stamp))
            if stop_at and counter["tick"] >= stop_at:
                scope["_STOP"] = True
            return None

    class Pipeline:
        def get_by_name(self, name):
            assert name in {"capture_source", "h264_encoder", "ts_mux"}
            return Element()
        def get_bus(self):
            return Bus()
        def set_state(self, state):
            assert state in {"PLAYING", "NULL"}
            return "SUCCESS"

    ticks = iter(times)
    scope.update({
        "Gst": SimpleNamespace(
            PadProbeReturn=SimpleNamespace(OK=1),
            PadProbeType=SimpleNamespace(BUFFER=1, BUFFER_LIST=2),
            State=SimpleNamespace(PLAYING="PLAYING", NULL="NULL"),
            StateChangeReturn=SimpleNamespace(FAILURE="FAILURE"),
            SECOND=1,
            MessageType=SimpleNamespace(ERROR=1, EOS=2),
        ),
        "time": SimpleNamespace(monotonic=lambda: next(ticks)),
    })
    run = _load_pipeline(scope)
    try:
        with redirect_stdout(stdout):
            run(Pipeline(), tmp_path)
    except RuntimeError as exc:
        return str(exc), stdout.getvalue(), removed, probe_types
    return None, stdout.getvalue(), removed, probe_types


def test_hls_stall_raises_only_after_90_seconds_without_new_output(tmp_path):
    error, logs, removed, flags = _run_case(
        tmp_path, times=[0, 1, 30, 60, 91, 92], update_hls=False, mux_list=True
    )
    assert error == "HLS output stalled for 90 seconds (pipewire_no_buffers)"
    assert "clientflow_hls_first_segment" in logs
    assert "clientflow_hls_stalled output_age_s=90 stage=pipewire_no_buffers" in logs
    assert "muxed_buffers=7" in logs
    assert removed == [10] * 3
    assert flags == [3] * 3  # BUFFER | BUFFER_LIST


def test_hls_does_not_restart_static_scene_when_segments_keep_advancing(tmp_path):
    error, logs, removed, _ = _run_case(
        tmp_path, times=[0, 1, 31, 62, 93, 94], update_hls=True, stop_at=4
    )
    assert error is None
    assert "clientflow_hls_stalled" not in logs
    assert "clientflow_hls_running" in logs
    assert "clientflow_hls_final" in logs
    assert removed == [10] * 3


def test_hls_watchdog_never_runs_before_first_segment(tmp_path):
    text = CAPTURE.read_text(encoding="utf-8")
    assert 'if not ready_seen and now - last_report >= 5' in text
    assert 'elif ready_seen:' in text
    assert 'if now - last_output_at >= 90:' in text
    assert 'if marker is not None and marker != last_output_marker:' in text


def test_producer_records_capture_exit_before_attempting_recovery(monkeypatch):
    # A systemd service can remain running even when its unprivileged HLS child
    # dies. The error must be observable before the normal restart path.
    from clientflow_runtime import livestream_producer as module

    producer = module.Producer.__new__(module.Producer)
    log = []
    producer.logger = SimpleNamespace(warning=lambda event, **kw: log.append((event, kw)))
    producer.process = SimpleNamespace(poll=lambda: 1)
    producer.generation_id = "35e263bf-727a-4053-9616-9334fa73ee98"
    producer._last_start_attempt = 0.0
    statuses = []
    producer._status = lambda state, **kw: statuses.append((state, kw))
    producer._stop = lambda: (setattr(producer, "process", None), setattr(producer, "generation_id", None))
    producer._start = lambda generation: setattr(producer, "generation_id", generation)
    requests = iter([
        {"desired": "running", "generation_id": producer.generation_id},
        KeyboardInterrupt(),
    ])
    def read_json(_path):
        next_request = next(requests)
        if isinstance(next_request, BaseException):
            raise next_request
        return next_request
    producer._read_json = read_json
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    assert producer.run() == 0
    assert any(event == "capture_process_exited" and data["extra"]["exit_code"] == 1
               for event, data in log)
    assert any(state == "failed" and data["exit_code"] == 1 for state, data in statuses)
