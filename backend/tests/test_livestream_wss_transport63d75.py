"""Actual loopback WebSocket handshake and pre-ASGI receive limits."""
import asyncio
import socket

import pytest
import uvicorn
from uvicorn.protocols.http.auto import AutoHTTPProtocol
from uvicorn.protocols.http.h11_impl import H11Protocol
from uvicorn.protocols.websockets.auto import AutoWebSocketsProtocol
from websockets.exceptions import ConnectionClosed
from websockets.legacy.client import connect

from service1.livestream_pilot_server import (LivestreamPilotProtocol, http_protocol_for_pilot,
                                              media_receive_limit)
from service1.livestream_wss_core import HEADER, MAX_FRAGMENT

PUBLISH = "/api/livestream-agent/clients/3/generations/test/media/ws"
SUBSCRIBE = "/api/livestream-wss/clients/3/generations/test/subscribe"
NORMAL = "/api/native-rdp/test"
MAX_WIRE = HEADER.size + MAX_FRAGMENT


def test_only_livestream_paths_are_limited():
    assert media_receive_limit(PUBLISH) == MAX_WIRE
    assert media_receive_limit(PUBLISH.replace("media", "%6dedia") + "?x=y") == MAX_WIRE
    assert media_receive_limit(SUBSCRIBE) == 1024
    for path in (NORMAL, "/api/terminal/ws", PUBLISH + "/other", "/api/livestream-v2/hls/3"):
        assert media_receive_limit(path) is None


@pytest.mark.parametrize("http_base", [H11Protocol, AutoHTTPProtocol])
def test_real_transport_limits_and_unchanged_other_socket(http_base):
    async def scenario():
        observed = []

        async def app(scope, receive, send):
            assert scope["type"] == "websocket"
            assert (await receive())["type"] == "websocket.connect"
            await send({"type": "websocket.accept"})
            while True:
                message = await receive()
                if message["type"] == "websocket.disconnect":
                    return
                payload = message["bytes"]
                observed.append((scope["path"], len(payload)))
                await send({"type": "websocket.send", "text": str(len(payload))})

        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        host, port = listener.getsockname()
        config = uvicorn.Config(app, ws="auto", http=http_protocol_for_pilot(http_base),
                                lifespan="off", log_level="warning")
        server = uvicorn.Server(config)
        task = asyncio.create_task(server.serve(sockets=[listener]))
        root = f"ws://{host}:{port}"
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    if task.done():
                        await task
                        raise AssertionError("server exited")
                    await asyncio.sleep(0.01)
                async with connect(root + PUBLISH, compression="deflate", close_timeout=1) as peer:
                    assert not peer.extensions
                    proto = next(p for p in server.server_state.connections if p.scope["path"] == PUBLISH)
                    assert type(proto) is LivestreamPilotProtocol
                    assert proto.max_size == MAX_WIRE and proto.max_queue == 1
                    await peer.send(b"x" * MAX_WIRE)
                    assert await peer.recv() == str(MAX_WIRE)
                    await peer.send(b"x" * (MAX_WIRE + 1))
                    with pytest.raises(ConnectionClosed) as exc:
                        await peer.recv()
                    assert exc.value.rcvd is not None and exc.value.rcvd.code == 1009
                async with connect(root + SUBSCRIBE, close_timeout=1) as peer:
                    await peer.send(b"x" * 1025)
                    with pytest.raises(ConnectionClosed) as exc:
                        await peer.recv()
                    assert exc.value.rcvd is not None and exc.value.rcvd.code == 1009
                async with connect(root + NORMAL, compression="deflate", close_timeout=1) as peer:
                    proto = next(p for p in server.server_state.connections if p.scope["path"] == NORMAL)
                    assert type(proto) is AutoWebSocketsProtocol
                    assert config.ws_protocol_class is AutoWebSocketsProtocol
                    assert peer.extensions
                    await peer.send(b"x" * (MAX_WIRE + 1))
                    assert await peer.recv() == str(MAX_WIRE + 1)
                assert observed == [(PUBLISH, MAX_WIRE), (NORMAL, MAX_WIRE + 1)]
        finally:
            server.should_exit = True
            try:
                await asyncio.wait_for(task, 10)
            finally:
                listener.close()

    asyncio.run(scenario())
