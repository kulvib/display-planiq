"""Pilot-only WebSocket transport limits, before ASGI message allocation.

The installed server must use the same legacy protocol as Uvicorn's auto
selection. Never switch the protocol implementation for existing RDP,
terminal or other sockets silently. The locked-dependency real-socket test
is a release gate for this adapter.
"""
from __future__ import annotations

import os
import re
from urllib.parse import unquote

import uvicorn
from uvicorn.protocols.websockets.auto import AutoWebSocketsProtocol
from uvicorn.protocols.websockets.websockets_impl import WebSocketProtocol

from .livestream_wss_admission import PILOT_CLIENT_ID
from .livestream_wss_core import HEADER, MAX_FRAGMENT

_PUBLISH = re.compile(r"/api/livestream-agent/clients/[^/]+/generations/[^/]+/media/ws/?\Z")
_SUBSCRIBE = re.compile(r"/api/livestream-wss/clients/[^/]+/generations/[^/]+/subscribe/?\Z")


def media_receive_limit(raw_path: str) -> int | None:
    # Match the same URL decoding boundary as the inherited Uvicorn router.
    path = unquote(raw_path.partition("?")[0])
    if _PUBLISH.fullmatch(path):
        return HEADER.size + MAX_FRAGMENT
    if _SUBSCRIBE.fullmatch(path):
        return 1024
    return None


class LivestreamPilotProtocol(WebSocketProtocol):
    _media_socket = False

    async def process_request(self, path, request_headers):
        maximum = media_receive_limit(self.root_path + path)
        if maximum is not None:
            # Legacy websockets consumes these fields before receiving a
            # complete data message. One queued message plus at most one
            # in-flight message; compression is not negotiated for media.
            if not hasattr(self, "max_size") or not hasattr(self, "max_queue"):
                raise RuntimeError("Unsupported Livestream WebSocket transport")
            self.max_size = maximum
            self.max_queue = 1
            self._media_socket = True
        return await super().process_request(path, request_headers)

    def process_extensions(self, headers, available_extensions):
        return super().process_extensions(
            headers, None if self._media_socket else available_extensions,
        )


def protocol_for_pilot():
    if AutoWebSocketsProtocol is not WebSocketProtocol:
        raise RuntimeError("Livestream pilot requires verified Uvicorn WebSocket auto protocol")
    return LivestreamPilotProtocol


def main():
    ws = protocol_for_pilot() if PILOT_CLIENT_ID is not None else "auto"
    uvicorn.run("service1.main:app", host="0.0.0.0",
                port=int(os.environ.get("PORT") or "10000"), workers=1,
                log_level="info", ws=ws)


if __name__ == "__main__":
    main()
