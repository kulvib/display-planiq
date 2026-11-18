"""63C: media relay timing is content-free, while capture and Livestream remain isolated."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from clientflow_runtime import remote_desktop_agent as agent_module


def test_remote_desktop_telemetry_separates_capture_from_relay_send(tmp_path, monkeypatch):
    path = tmp_path / "media.json"
    monkeypatch.setattr(agent_module, "TELEMETRY_PATH", path)
    agent = agent_module.RemoteDesktopAgent.__new__(agent_module.RemoteDesktopAgent)
    agent.media_transport = SimpleNamespace(name="jpeg_rpc")
    agent.media_telemetry = {}
    agent.pending_input_at = {}
    agent._last_telemetry_write = 0.0
    agent.logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    agent._record_media_telemetry(
        "dummy-session", capture_ms=19.0, frame_bytes=12345,
        relayed=True, unchanged=False, relay_send_ms=810.0,
    )
    agent._record_media_telemetry(
        "dummy-session", capture_ms=21.0, frame_bytes=12345,
        relayed=True, unchanged=True, relay_send_ms=90.0,
    )
    row = agent.media_telemetry["dummy-session"]
    assert row["capture_ms_avg"] == 20.0
    assert row["relay_send_ms_avg"] == 450.0
    assert row["relay_send_ms_max"] == 810.0
    assert row["relay_send_samples"] == 2
    assert row["relayed_bytes"] == 24690
    content = json.loads(path.read_text(encoding="utf8"))
    # The file is intentionally sampled at most once every five seconds;
    # in-memory statistics immediately include the second frame.
    assert row["relay_send_ms_last"] == 90.0
    assert content["sessions"]["dummy-session"]["relay_send_ms_last"] == 810.0
    assert "data" not in content["sessions"]["dummy-session"]


def test_independent_remote_desktop_and_livestream_capture_contracts():
    root = Path(__file__).resolve().parents[2]
    remote = (root / "client/runtime/clientflow_runtime/remote_desktop_mutter_worker.py").read_text()
    livestream = (root / "client/runtime/clientflow_runtime/livestream_wayland_capture.py").read_text()
    producer = (root / "client/runtime/clientflow_runtime/livestream_producer.py").read_text()
    # Keep separate Mutter lifetime ownership until a separately tested shared
    # capture service is explicitly approved. No global GNOME/PipeWire restart.
    for source in (remote, livestream):
        assert '"CreateSession"' in source
        assert '"Stop"' in source
        assert 'pipewiresrc' in source
        assert '"RecordMonitor"' in source
    assert "RETRY_MAX_SECONDS = 120" in producer
    assert 'self._schedule_retry("startup_failed")' in producer
    assert "systemctl restart pipewire" not in remote + livestream + producer
