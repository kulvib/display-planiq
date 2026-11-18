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
        agent.control_sessions = {sid}
        agent.input_rpc_lock = asyncio.Lock()
        agent.completed_input_ids = set()
        from collections import deque
        agent.recent_input_ids = deque()
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
        assert calls[0][1] == {"action": "mouse", "session_id": sid, "event": "move", "x": 0.25, "y": 0.75}
        assert [output["type"] for output in outputs] == ["input_ready"]  # no per-move HTTP ACK
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
        from types import SimpleNamespace
        input_channel = SimpleNamespace(ready_sessions=set())
        sid = str(uuid.uuid4())
        async def fake_send(channel, payload):
            sent.append((channel, payload))
        monkeypatch.setattr(remote, "_send_agent", fake_send)
        monkeypatch.setattr(remote, "_configured_resolution", lambda _: (1920, 1080))
        monkeypatch.setitem(remote.CONTROL_AGENTS, 999, control)
        monkeypatch.setitem(remote.INPUT_AGENTS, 999, input_channel)
        try:
            await remote._browser_control_message(999, sid, {
                "type": "mouse", "action": "down", "x": 500, "y": 200, "button": 1,
            })
            assert sent and all(channel is control for channel, _ in sent)  # no ACK yet
            sent.clear()
            input_channel.ready_sessions.add(sid)
            await remote._browser_control_message(999, sid, {"type": "key", "key": "Enter"})
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
    assert 'session_id in input_channel.ready_sessions' in server
    assert 'input_websocket=websocket' in server
    assert 'self._run_input_on_demand()' in agent
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


def test_input_rpc_replay_is_idempotent_across_control_and_input(monkeypatch):
    async def scenario():
        from collections import deque
        agent = object.__new__(agent_module.RemoteDesktopAgent)
        agent.input_rpc_lock = asyncio.Lock()
        agent.completed_input_ids = set()
        agent.recent_input_ids = deque()
        requests = []
        def fake_rpc(socket, request, timeout):
            requests.append((socket, request))
            return {"accepted": True}
        monkeypatch.setattr(agent_module, "call", fake_rpc)
        msg = {"action": "mouse", "event": "down", "session_id": str(uuid.uuid4()),
               "input_id": str(uuid.uuid4())}
        agent.control_sessions = {msg["session_id"]}
        result1, result2 = await asyncio.gather(
            agent._input_rpc(agent_module.INPUT_SOCKET, msg),
            agent._input_rpc(agent_module.INPUT_SOCKET, msg),
        )
        assert result1 == {"accepted": True}
        assert result2 == {"accepted": True, "duplicate": True}
        assert len(requests) == 1
    asyncio.run(scenario())


def test_cancelled_inflight_input_rpc_finishes_before_release(monkeypatch):
    import threading
    import time
    from collections import deque
    async def scenario():
        agent = object.__new__(agent_module.RemoteDesktopAgent)
        agent.input_rpc_lock = asyncio.Lock()
        agent.completed_input_ids = set()
        agent.recent_input_ids = deque()
        started, finished = threading.Event(), threading.Event()
        def blocking_rpc(*_args, **_kwargs):
            started.set()
            time.sleep(0.06)
            finished.set()
            return {"accepted": True}
        monkeypatch.setattr(agent_module, "call", blocking_rpc)
        task = asyncio.create_task(agent._input_rpc(agent_module.INPUT_SOCKET, {"action": "mouse"}))
        await asyncio.to_thread(started.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()
    asyncio.run(scenario())


def test_input_lane_only_connects_while_control_session_active(monkeypatch):
    async def scenario():
        agent = object.__new__(agent_module.RemoteDesktopAgent)
        agent.input_demand = asyncio.Event()
        agent.control_sessions = set()
        started, cancelled = asyncio.Event(), asyncio.Event()
        async def fake_channel(name):
            assert name == "input"
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        monkeypatch.setattr(agent, "_channel", fake_channel)
        manager = asyncio.create_task(agent._run_input_on_demand())
        await asyncio.sleep(0.01)
        assert not started.is_set()
        agent.control_sessions.add(str(uuid.uuid4()))
        agent.input_demand.set()
        await asyncio.wait_for(started.wait(), 1)
        agent.control_sessions.clear()
        agent.input_demand.set()
        await asyncio.wait_for(cancelled.wait(), 1)
        manager.cancel()
        await asyncio.gather(manager, return_exceptions=True)
    asyncio.run(scenario())


def test_hls_manifest_cannot_rewind_within_generation(tmp_path):
    from clientflow_runtime.livestream_uploader import Uploader
    _playlist(tmp_path, 200)
    _, new_manifest = current_playlist_uploads(tmp_path)
    uploader = object.__new__(Uploader)
    uploader.published_manifest_generation = "gen-a"
    uploader.published_manifest_span = (204, 207)
    assert uploader._manifest_can_advance("gen-a", new_manifest)
    _playlist(tmp_path, 190)
    _, stale_manifest = current_playlist_uploads(tmp_path)
    assert not uploader._manifest_can_advance("gen-a", stale_manifest)
    assert uploader._manifest_can_advance("gen-b", stale_manifest)
    _playlist(tmp_path, 210)
    _, newer_manifest = current_playlist_uploads(tmp_path)
    assert uploader._manifest_can_advance("gen-a", newer_manifest)


def test_hls_unknown_metadata_does_not_allow_reordered_segments(tmp_path):
    _playlist(tmp_path, 10)
    playlist = tmp_path / "index.m3u8"
    raw = playlist.read_text()
    raw = raw.replace("#EXTINF:2.000,\nsegment-000000011.ts", "#EXT-X-DISCONTINUITY\n#EXTINF:2.000,\nsegment-000000012.ts")
    playlist.write_text(raw)
    assert current_playlist_uploads(tmp_path) is None


def _isolated_backend_functions(*names, **bindings):
    """Exercise the actual backend AST without optional SQLModel dependencies."""
    import ast
    import logging
    tree = ast.parse((ROOT / "backend/service1/routers/remote_desktop_v2.py").read_text())
    functions = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name in names]
    assert len(functions) == len(names)
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
                              *functions], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"asyncio": asyncio, "uuid": uuid, "logger": logging.getLogger(__name__), **bindings}
    exec(compile(module, "actual-remote_desktop_v2.py", "exec"), namespace)
    return namespace


def test_backend_input_lane_falls_back_on_send_error_without_closing_browser():
    async def scenario():
        from types import SimpleNamespace
        session_id = str(uuid.uuid4())
        client_id = 345
        control = SimpleNamespace(ready_sessions=set())
        lane = SimpleNamespace(ready_sessions={session_id})
        sent = []
        async def send(channel, payload):
            sent.append((channel, payload.copy()))
            if channel is lane:
                raise OSError("socket disconnected")
        failures = []
        async def tell_browser(sid, cid, payload):
            failures.append(payload)
        module = _isolated_backend_functions(
            "_send_browser_input", INPUT_AGENTS={client_id: lane},
            _send_agent=send, _send_browser=tell_browser,
        )
        await module["_send_browser_input"](client_id, session_id, control, {"type": "mouse", "event": "click"})
        assert len(sent) == 2 and sent[0][0] is lane and sent[1][0] is control
        assert sent[0][1] == sent[1][1]  # stable event ID for broker dedup
        assert str(uuid.UUID(sent[0][1]["input_id"])) == sent[0][1]["input_id"]
        assert session_id not in lane.ready_sessions
        assert failures == []
    asyncio.run(scenario())


def test_backend_both_input_channels_down_reports_error_not_disconnect():
    async def scenario():
        from types import SimpleNamespace
        session_id = str(uuid.uuid4())
        lane = SimpleNamespace(ready_sessions={session_id})
        reports = []
        async def send(*_args):
            raise OSError("transport down")
        async def send_browser(_sid, _cid, payload):
            reports.append(payload)
        namespace = _isolated_backend_functions(
            "_send_browser_input", INPUT_AGENTS={5: lane}, _send_agent=send, _send_browser=send_browser,
        )
        await namespace["_send_browser_input"](5, session_id, object(), {"type": "key", "event": "down"})
        assert reports == [{"type": "error", "message": "Remote Desktop-input kunne ikke leveres. Prøv igen."}]
    asyncio.run(scenario())


def test_backend_ack_requires_current_input_socket_and_existing_browser():
    async def scenario():
        from types import SimpleNamespace
        sid = str(uuid.uuid4())
        old_socket, new_socket = object(), object()
        channel = SimpleNamespace(websocket=new_socket, ready_sessions=set())
        sessions = {sid: SimpleNamespace(session_id=sid)}
        lock = asyncio.Lock()
        async def find(s, client_id):
            return sessions.get(s)
        namespace = _isolated_backend_functions(
            "_handle_control_agent_message", LOCK=lock,
            INPUT_AGENTS={7: channel}, BROWSERS=sessions, _browser_for_session=find,
        )
        receive = namespace["_handle_control_agent_message"]
        await receive(7, "credential", {"type": "input_ready", "session_id": sid}, input_websocket=old_socket)
        assert sid not in channel.ready_sessions
        await receive(7, "credential", {"type": "input_ready", "session_id": sid}, input_websocket=new_socket)
        assert sid in channel.ready_sessions
        sessions.clear()
        channel.ready_sessions.clear()
        await receive(7, "credential", {"type": "input_ready", "session_id": sid}, input_websocket=new_socket)
        assert sid not in channel.ready_sessions
    asyncio.run(scenario())


def test_backend_registration_does_not_mark_input_usable_before_session_open():
    async def scenario():
        from types import SimpleNamespace
        sid = str(uuid.uuid4())
        sock = SimpleNamespace(close=lambda **kwargs: None)
        channel = SimpleNamespace(websocket=sock, ready_sessions=set())
        browsers = {sid: SimpleNamespace(client_id=8, session_id=sid)}
        registries = ({}, {}, {})
        sent = []
        async def send(target, payload):
            sent.append((target, payload))
        async def noop(*args):
            return None
        namespace = _isolated_backend_functions(
            "_register_agent_channel", LOCK=asyncio.Lock(),
            CONTROL_AGENTS=registries[0], INPUT_AGENTS=registries[1], FILE_AGENTS=registries[2],
            BROWSERS=browsers, _send_agent=send,
            _fail_file_channel_state=noop, _broadcast_agent_status=noop,
        )
        await namespace["_register_agent_channel"](8, "input", channel)
        assert registries[1][8] is channel
        assert sent == [(channel, {"type": "session_open", "session_id": sid})]
        assert not channel.ready_sessions
    asyncio.run(scenario())


def test_privileged_input_broker_tracks_remote_held_buttons_and_dedup(monkeypatch):
    import importlib.util
    import sys
    import threading
    from types import SimpleNamespace, ModuleType
    class Codes:
        def __init__(self):
            self._values = {}
        def __getattr__(self, name):
            return self._values.setdefault(name, len(self._values) + 100)
    class FakeInput:
        def __init__(self, *_args, **_kwargs):
            self.events = []
        def write(self, kind, code, value):
            self.events.append((kind, code, value))
        def syn(self):
            self.events.append("syn")
    fake_evdev = ModuleType("evdev")
    fake_evdev.ecodes = Codes()
    fake_evdev.UInput = FakeInput
    fake_evdev.AbsInfo = lambda *args: args
    monkeypatch.setitem(sys.modules, "evdev", fake_evdev)
    name = "clientflow_runtime._phase63d9r_broker"
    path = ROOT / "client/runtime/clientflow_runtime/remote_desktop_input_broker.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        device = module.InputDevice()
        monkeypatch.setattr(module, "_device", lambda: device)
        sid_a, sid_b = str(uuid.uuid4()), str(uuid.uuid4())
        ident = str(uuid.uuid4())
        def event(sid, action, key="Control", ident=None):
            return module.handle({"action": "key", "key": key, "event": action,
                                  "session_id": sid, "input_id": ident})
        assert event(sid_a, "down", ident=ident)["accepted"]
        assert event(sid_a, "down", ident=ident)["duplicate"]
        assert event(sid_b, "down")["accepted"]
        key_code = module._KEY_MAP["Control"]
        presses = [entry for entry in device.device.events if isinstance(entry, tuple) and entry[1] == key_code and entry[2] == 1]
        assert len(presses) == 1
        module.handle({"action": "release_session", "session_id": sid_a})
        assert key_code in device.pressed_by_session[sid_b]  # do not release another operator
        releases = [entry for entry in device.device.events if isinstance(entry, tuple) and entry[1] == key_code and entry[2] == 0]
        assert not releases
        module.handle({"action": "release_session", "session_id": sid_b})
        releases = [entry for entry in device.device.events if isinstance(entry, tuple) and entry[1] == key_code and entry[2] == 0]
        assert len(releases) == 1
        with pytest.raises(ValueError, match="session-id"):
            module.handle({"action": "release_session", "session_id": "bad"})
    finally:
        sys.modules.pop(name, None)


def test_hls_uploader_loop_never_publishes_older_manifest(tmp_path, monkeypatch):
    from clientflow_runtime import livestream_uploader as hls
    generation = str(uuid.uuid4())
    output = tmp_path / generation / "out"
    _playlist(output, 20)
    uploader = object.__new__(hls.Uploader)
    uploader.uploaded = {}
    uploader.published_manifest_generation = generation
    uploader.published_manifest_span = (100, 103)
    uploader.latest_segment_local_age_seconds = None
    uploaded = []
    uploader._read_desired = lambda: {"desired": "running", "generation_id": generation}
    uploader._upload = lambda _gen, path, *, data=None: uploaded.append(path.name)
    uploader._status = lambda *_args, **_kwargs: None
    monkeypatch.setattr(hls, "GENERATIONS_DIR", tmp_path)
    def stop_after_one(_interval):
        raise KeyboardInterrupt
    monkeypatch.setattr(hls.time, "sleep", stop_after_one)
    assert uploader.run() == 0
    assert uploaded == []


def test_hls_uploader_restores_published_manifest_span_after_restart(tmp_path, monkeypatch):
    from clientflow_runtime import livestream_uploader as hls
    generation = str(uuid.uuid4())
    status = tmp_path / "status.json"
    status.write_text(json.dumps({
        "manifest_generation_id": generation,
        "manifest_first_sequence": 215,
        "manifest_last_sequence": 218,
    }))
    monkeypatch.setattr(hls, "UPLOADER_STATUS_PATH", status)
    uploader = object.__new__(hls.Uploader)
    uploader.published_manifest_generation = None
    uploader.published_manifest_span = None
    uploader._restore_published_manifest()
    assert uploader.published_manifest_generation == generation
    assert uploader.published_manifest_span == (215, 218)
    _playlist(tmp_path, 180)
    _, playlist = hls.current_playlist_uploads(tmp_path)
    assert not uploader._manifest_can_advance(generation, playlist)
