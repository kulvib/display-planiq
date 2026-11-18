"""63D-9: real input queue/HLS helpers plus optional backend routing checks."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client" / "runtime"))

from clientflow_runtime.livestream_uploader import current_playlist_uploads  # noqa: E402
from clientflow_runtime.remote_desktop_input_queue import InputLaneQueue  # noqa: E402
from clientflow_runtime import remote_desktop_agent as agent_module  # noqa: E402


def _playlist(folder: Path, start: int, length: int = 8):
    folder.mkdir(exist_ok=True, parents=True)
    for n in range(start, start + length):
        (folder / f"segment-{n:09}.ts").write_bytes(b"complete-segment")
    content = (
        "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:2\n"
        f"#EXT-X-MEDIA-SEQUENCE:{start}\n"
        + "".join(f"#EXTINF:2.000,\nsegment-{n:09}.ts\n" for n in range(start, start + length))
    )
    (folder / "index.m3u8").write_text(content, encoding="utf-8")


def test_uploader_keeps_only_four_current_segments_with_correct_media_sequence(tmp_path):
    _playlist(tmp_path, 100)
    files, manifest = current_playlist_uploads(tmp_path)
    assert [p.name for p in files] == [f"segment-{n:09}.ts" for n in range(104, 108)]
    text = manifest.decode("utf-8")
    assert "#EXT-X-MEDIA-SEQUENCE:104" in text
    assert "segment-000000103.ts" not in text
    assert "segment-000000107.ts" in text
    assert text.count("#EXTINF:") == 4


def test_uploader_refuses_missing_segment_or_unsafe_manifest(tmp_path):
    _playlist(tmp_path, 0)
    (tmp_path / "segment-000000007.ts").unlink()
    assert current_playlist_uploads(tmp_path) is None
    _playlist(tmp_path, 0)
    playlist = tmp_path / "index.m3u8"
    playlist.write_text(playlist.read_text().replace("segment-000000007.ts", "../passwd"))
    assert current_playlist_uploads(tmp_path) is None
    _playlist(tmp_path, 0)
    playlist.write_text(playlist.read_text().replace("#EXT-X-MEDIA-SEQUENCE:0", "#EXT-X-MEDIA-SEQUENCE:500"))
    assert current_playlist_uploads(tmp_path) is None


def test_input_queue_coalesces_only_adjacent_mouse_moves_and_preserves_release():
    async def scenario():
        processed = []
        done = asyncio.Event()
        sid = str(uuid.uuid4())
        async def process(raw):
            processed.append(json.loads(raw))
            if len(processed) == 4:
                done.set()
        queue = InputLaneQueue(process, max_pending=8)
        def send(action, x=0):
            return json.dumps({"type": "mouse", "session_id": sid, "event": action, "x": x})
        await queue.put(send("move", 1))
        await queue.put(send("move", 2))
        await queue.put(send("down"))
        await queue.put(send("move", 3))
        await queue.put(send("move", 4))
        await queue.put(send("up"))
        assert queue.replaced_moves == 2
        worker = asyncio.create_task(queue.run())
        await asyncio.wait_for(done.wait(), 1)
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        assert [(item["event"], item["x"]) for item in processed] == [
            ("move", 2), ("down", 0), ("move", 4), ("up", 0)
        ]
    asyncio.run(scenario())


def test_input_queue_backpressures_instead_of_discarding_non_replaceable_actions():
    async def scenario():
        processed = []
        queue = InputLaneQueue(lambda raw: recorded(raw), max_pending=2)
        async def recorded(raw):
            processed.append(json.loads(raw)["event"])
        await queue.put('{"event":"down"}')
        await queue.put('{"event":"up"}')
        blocked = asyncio.create_task(queue.put('{"event":"key"}'))
        await asyncio.sleep(0)
        assert not blocked.done()
        worker = asyncio.create_task(queue.run())
        await asyncio.wait_for(blocked, 1)
        for _ in range(20):
            if len(processed) == 3:
                break
            await asyncio.sleep(0.001)
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        assert processed == ["down", "up", "key"]
        assert queue.high_water_mark == 2
    asyncio.run(scenario())


def test_input_lane_requires_open_session_and_rejects_capture(monkeypatch):
    async def scenario():
        sid = str(uuid.uuid4())
        agent = object.__new__(agent_module.RemoteDesktopAgent)
        agent.input_sessions = set()
        agent.media_transport = agent_module.JpegRpcMediaTransport()
        agent.media_telemetry = {}
        agent.pending_input_at = {}
        calls = []
        outputs = []
        def fake_rpc(socket, request, timeout):
            calls.append((socket, request, timeout))
            return {"accepted": True}
        async def fake_send(payload):
            outputs.append(payload)
        monkeypatch.setattr(agent_module, "call", fake_rpc)
        monkeypatch.setattr(agent, "_send_input", fake_send)
        await agent._handle_input({"type": "session_open", "session_id": sid})
        with pytest.raises(ValueError):
            await agent._handle_input({"type": "start_stream", "session_id": sid})
        await agent._handle_input({"type": "mouse", "event": "move", "x": 0.25, "y": 0.75, "session_id": sid})
        assert calls[0][0] == agent_module.INPUT_SOCKET
        assert calls[0][1] == {"action": "mouse", "event": "move", "x": 0.25, "y": 0.75}
        assert outputs[-1]["type"] == "input_result" and outputs[-1]["ok"] is True
        assert agent.media_telemetry[sid]["input_rpc_samples"] == 1
        await agent._handle_input({"type": "session_close", "session_id": sid})
        with pytest.raises(ValueError):
            await agent._handle_input({"type": "key", "session_id": sid})
    asyncio.run(scenario())


def test_backend_input_routes_when_optional_dependencies_available(monkeypatch):
    pytest.importorskip("sqlmodel")
    from service1.routers import remote_desktop_v2 as remote

    async def scenario():
        sent = []
        control = object()
        input_channel = object()
        async def fake_send(channel, payload):
            sent.append((channel, payload))
        monkeypatch.setattr(remote, "_send_agent", fake_send)
        monkeypatch.setattr(remote, "_configured_resolution", lambda _: (1920, 1080))
        monkeypatch.setitem(remote.CONTROL_AGENTS, 999, control)
        monkeypatch.setitem(remote.INPUT_AGENTS, 999, input_channel)
        try:
            await remote._browser_control_message(999, str(uuid.uuid4()), {
                "type": "mouse", "action": "down", "x": 500, "y": 200, "button": 1,
            })
            assert sent and all(channel is input_channel for channel, _ in sent)
            sent.clear()
            await remote._browser_control_message(999, str(uuid.uuid4()), {"type": "start_stream", "native": True})
            assert sent and all(channel is control for channel, _ in sent)
            sent.clear()
            remote.INPUT_AGENTS.pop(999, None)
            await remote._browser_control_message(999, str(uuid.uuid4()), {"type": "key", "key": "Enter"})
            assert sent and all(channel is control for channel, _ in sent)
        finally:
            remote.CONTROL_AGENTS.pop(999, None)
            remote.INPUT_AGENTS.pop(999, None)
    asyncio.run(scenario())


def test_route_and_frontend_contract_without_optional_runtime_dependencies():
    server = (ROOT / "backend/service1/routers/remote_desktop_v2.py").read_text()
    agent = (ROOT / "client/runtime/clientflow_runtime/remote_desktop_agent.py").read_text()
    frontend = (ROOT / "frontend/src/pages/clientdetailspage/remotedesktop/RemoteDesktop.jsx").read_text()
    assert '@router.websocket("/remote-desktop-agent/clients/{client_id}/input/ws")' in server
    assert "_authenticate_agent_websocket(websocket, client_id)" in server
    assert 'INPUT_AGENTS.get(client_id) or control' in server
    assert 'await asyncio.gather(self._channel("control"), self._channel("input"), self._channel("files"))' in agent
    assert "InputLaneQueue" in agent
    assert 'send({ type: "ping" })' in frontend
    assert "Transport RTT" in frontend


def test_input_queue_wakes_blocked_producer_on_broken_consumer():
    async def scenario():
        async def process(_raw):
            raise OSError("disconnected")
        queue = InputLaneQueue(process, max_pending=2)
        await queue.put('{"event":"down"}')
        await queue.put('{"event":"up"}')
        producer = asyncio.create_task(queue.put('{"event":"key"}'))
        await asyncio.sleep(0)
        worker = asyncio.create_task(queue.run())
        with pytest.raises(OSError):
            await asyncio.wait_for(worker, 1)
        with pytest.raises(RuntimeError, match="consumer failed"):
            await asyncio.wait_for(producer, 1)
    asyncio.run(scenario())


def test_uploader_preserves_safe_unknown_hls_metadata_instead_of_going_dark(tmp_path):
    _playlist(tmp_path, 40)
    playlist = tmp_path / "index.m3u8"
    original = playlist.read_text().replace(
        "#EXTINF:2.000,\nsegment-000000041.ts",
        "#EXT-X-PROGRAM-DATE-TIME:2026-11-18T20:00:00Z\n#EXTINF:2.000,\nsegment-000000041.ts",
    )
    playlist.write_text(original)
    result = current_playlist_uploads(tmp_path)
    assert result is not None
    assert len(result[0]) == 8
    assert result[1].decode() == original
    playlist.write_text(original.replace("#EXT-X-PROGRAM-DATE-TIME", '#EXT-X-KEY:URI="https://evil.invalid/key"\n#EXT-X-PROGRAM-DATE-TIME'))
    assert current_playlist_uploads(tmp_path) is None
