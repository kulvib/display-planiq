"""Deterministic zero-frame retry / bounded recovery for Mutter capture.

No Mutter session, PipeWire node, network or real systemd process is started.
"""
from __future__ import annotations

from contextlib import redirect_stdout
import ast
import io
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client/runtime"))
from clientflow_runtime import livestream_producer as mod  # noqa: E402

CAPTURE = ROOT / "client/runtime/clientflow_runtime/livestream_wayland_capture.py"
GEN_A = "35e263bf-727a-4053-9616-9334fa73ee98"
GEN_B = "4eab8890-c11a-4c7b-ad49-5d4a10ee5ff9"


class Clock:
    now = 0.0

    def monotonic(self):
        return self.now

    def time(self):
        return 1_794_674_000 + self.now

    def sleep(self, seconds):
        self.now += seconds


def fake_producer(monkeypatch, clock):
    monkeypatch.setattr(mod, "time", clock)
    producer = mod.Producer.__new__(mod.Producer)
    producer.logger = SimpleNamespace(
        warning=lambda *_args, **_kw: None,
        exception=lambda *_args, **_kw: None,
    )
    producer.generation_id = None
    producer.process = None
    producer._last_start_attempt = 0
    producer._retry_generation = None
    producer._retry_attempts = 0
    producer._retry_deadline = 0
    producer._healthy_since = None
    statuses = []
    producer._status = lambda state, **details: statuses.append((state, details))
    producer._stop = lambda: (
        setattr(producer, "process", None),
        setattr(producer, "generation_id", None),
    )
    return producer, statuses


def test_exponential_retry_is_bounded_even_after_many_failures():
    assert [mod.retry_delay_seconds(i) for i in range(1, 9)] == [5, 10, 20, 40, 80, 120, 120, 120]
    assert mod.retry_delay_seconds(10_000) == 120


def test_zero_frame_startups_back_off_without_restart_storm(monkeypatch):
    clock = Clock()
    producer, statuses = fake_producer(monkeypatch, clock)
    attempts = []

    def start(generation):
        attempts.append((clock.now, generation))
        producer.generation_id = generation
        raise RuntimeError("No first source buffer")

    producer._start = start

    def read(_path):
        if clock.now >= 37:
            raise KeyboardInterrupt
        return {"desired": "running", "generation_id": GEN_A}

    producer._read_json = read
    assert producer.run() == 0
    assert [t for t, _ in attempts] == [0, 5, 15, 35]
    retry = [data for state, data in statuses if state == "retrying"]
    assert [data["retry_after_seconds"] for data in retry] == [5, 10, 20, 40]
    assert {data["reason"] for data in retry} == {"startup_failed"}
    assert all("No first source buffer" not in str(data) for data in retry)


def test_operator_stop_and_new_generation_interrupt_backoff(monkeypatch):
    clock = Clock()
    producer, statuses = fake_producer(monkeypatch, clock)
    attempts = []

    def start(generation):
        attempts.append((clock.now, generation))
        producer.generation_id = generation
        raise RuntimeError("Capture startup failed")

    producer._start = start

    def read(_path):
        if clock.now < 2:
            return {"desired": "running", "generation_id": GEN_A}
        if clock.now < 4:
            return {"desired": "stopped", "generation_id": GEN_A}
        if clock.now < 7:
            return {"desired": "running", "generation_id": GEN_B}
        raise KeyboardInterrupt

    producer._read_json = read
    assert producer.run() == 0
    assert attempts == [(0, GEN_A), (4, GEN_B)]
    assert [d["attempt"] for state, d in statuses if state == "retrying"] == [1, 1]


def test_short_lived_success_does_not_reset_failure_backoff(monkeypatch):
    clock = Clock()
    producer, statuses = fake_producer(monkeypatch, clock)
    attempts = []
    current = {"poll": None}

    def start(generation):
        attempts.append(clock.now)
        producer.generation_id = generation
        # A child can be valid at first HLS but exit immediately afterwards.
        producer.process = SimpleNamespace(poll=lambda: current["poll"], pid=100)

    def read(_path):
        if clock.now == 1:
            current["poll"] = 1
        if clock.now >= 7:
            raise KeyboardInterrupt
        return {"desired": "running", "generation_id": GEN_A}

    producer._start = start
    producer._read_json = read
    assert producer.run() == 0
    assert attempts[:2] == [0, 6]
    assert any(state == "failed" and data.get("exit_code") == 1 for state, data in statuses)
    assert any(state == "retrying" and data.get("reason") == "capture_exited" for state, data in statuses)


def test_no_source_buffers_produces_stage_diagnostics_without_screen_data(tmp_path):
    function = next(
        node for node in ast.parse(CAPTURE.read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef) and node.name == "_run_pipeline"
    )
    scope = {"_STOP": False, "Path": Path}
    removed = []

    class Pad:
        def add_probe(self, flags, callback, stage):
            return 13
        def remove_probe(self, value):
            removed.append(value)
        def get_current_caps(self):
            return None

    class Element:
        def get_static_pad(self, name):
            return Pad()

    class Bus:
        ticks = 0
        def timed_pop_filtered(self, *_args):
            self.ticks += 1
            if self.ticks >= 2:
                scope["_STOP"] = True
            return None

    class Pipeline:
        def get_bus(self):
            return Bus()
        def get_by_name(self, _name):
            return Element()
        def set_state(self, _state):
            return "SUCCESS"
        def get_state(self, _timeout):
            return "SUCCESS", SimpleNamespace(value_nick="playing"), "VOID_PENDING"

    times = iter([0, 11, 12, 13])
    scope.update({
        "time": SimpleNamespace(monotonic=lambda: next(times)),
        "Gst": SimpleNamespace(
            PadProbeType=SimpleNamespace(BUFFER=1, BUFFER_LIST=2),
            PadProbeReturn=SimpleNamespace(OK=1),
            State=SimpleNamespace(PLAYING="PLAYING", NULL="NULL"),
            StateChangeReturn=SimpleNamespace(FAILURE="FAILURE"),
            MessageType=SimpleNamespace(ERROR=1, EOS=2),
            SECOND=1,
        ),
    })
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(CAPTURE), "exec"), scope)
    output = io.StringIO()
    with redirect_stdout(output):
        scope["_run_pipeline"](Pipeline(), tmp_path)
    result = output.getvalue()
    assert "clientflow_capture_startup_stage elapsed_s=11 stage=pipewire_no_buffers pipeline_state=playing source_caps=no" in result
    assert "source_buffers=0" in result
    assert removed == [13] * 3


def test_agent_never_acknowledges_a_retrying_generation_as_started(monkeypatch):
    from clientflow_runtime import livestream_agent as agent

    writes = []
    transport = SimpleNamespace(
        credential=SimpleNamespace(client_id=3),
        json_request=lambda *args, **kwargs: writes.append((args, kwargs)),
    )
    handler = agent.LivestreamHandler(transport)
    requested = []
    handler._wait_producer = lambda generation, states: (
        requested.append((generation, states)) or {"state": "retrying", "retry_after_seconds": 10}
    )
    monkeypatch.setattr(agent, "call", lambda *_args, **_kwargs: {"desired": "running"})
    command = SimpleNamespace(command_type="start", payload={"generation_id": GEN_A})
    try:
        handler(command)
    except agent.CommandRejected as exc:
        assert exc.code == "producer_retrying"
        assert exc.retryable is True
    else:
        raise AssertionError("Retrying capture must never be acknowledged as started")
    assert requested == [(GEN_A, {"running"})]
    assert writes == []
