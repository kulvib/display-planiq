"""Disconnect must never be misreported as a PipeWire capture failure."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from websockets.exceptions import ConnectionClosedError

from clientflow_runtime.remote_desktop_agent import RemoteDesktopAgent


def _fixture():
    agent = RemoteDesktopAgent.__new__(RemoteDesktopAgent)
    class Logger:
        def __init__(self):
            self.events = []
        def info(self, msg, **kw):
            self.events.append(msg)
        def warning(self, msg, **kw):
            self.events.append(msg)
        def exception(self, msg, **kw):
            self.events.append(msg)
    agent.logger = Logger()
    agent.stream_tasks = {'s1': object()}
    agent.stream_options = {'s1': {'fps': 10}}
    agent._event = AsyncMock()
    agent._stop_capture_if_idle = AsyncMock()
    agent._capture = AsyncMock()
    agent._send_control = AsyncMock()
    return agent


def _disconnect():
    return ConnectionClosedError(None, None)


def test_disconnected_frame_transport_does_not_emit_capture_failure():
    async def scenario():
        agent = _fixture()
        async def send(payload):
            if payload['type'] == 'frame' or payload['type'] == 'stream_stopped':
                raise _disconnect()
        agent._send_control.side_effect = send
        async def capture(*_args):
            await agent._send_control({'type': 'frame'})
        agent._capture.side_effect = capture
        await agent._stream_loop('s1')
        assert 'transport_disconnected' in agent.logger.events
        assert 'capture_stream_failed' not in agent.logger.events
        assert 's1' not in agent.stream_tasks
        agent._stop_capture_if_idle.assert_awaited_once()
    asyncio.run(scenario())


def test_capture_fault_cleanup_survives_closed_transport():
    async def scenario():
        agent = _fixture()
        agent._capture.side_effect = RuntimeError('GStreamer returnerede ingen frame')
        async def send(payload):
            if payload['type'] in {'error', 'stream_stopped'}:
                raise _disconnect()
        agent._send_control.side_effect = send
        await agent._stream_loop('s1')
        assert 'capture_stream_failed' in agent.logger.events
        assert 's1' not in agent.stream_tasks
        agent._stop_capture_if_idle.assert_awaited_once()
    asyncio.run(scenario())
