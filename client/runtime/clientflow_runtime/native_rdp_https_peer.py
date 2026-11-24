"""Experimental agent-side ordered binary HTTPS peer.

Not wired into the production forwarder. An explicitly approved transport
owner must supply a bounded, authenticated, non-retrying HTTP request function
and a fresh native tunnel generation. No fallback on authorization failure.
"""
from __future__ import annotations

import asyncio
from collections import deque
import json
import re
import struct
import uuid
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request as UrlRequest, HTTPRedirectHandler, HTTPSHandler, build_opener
from typing import Awaitable, Callable, Protocol

MAX_FRAME = 65536
MAX_BATCH = 262144
MAX_FRAMES = 128
MAX_SEQUENCE = (1 << 53) - 1
PREFIX = struct.Struct(">I")


class PeerError(ConnectionError):
    pass


class Reply(Protocol):
    status_code: int
    body: bytes
    headers: dict[str, str]


Request = Callable[[str, str, bytes | None, int, float], Awaitable[Reply]]


def _uuid(raw: str) -> str:
    try:
        if str(uuid.UUID(raw)) == raw:
            return raw
    except (ValueError, TypeError):
        pass
    raise PeerError("invalid ClientFlow generation")


def encode(frames: list[bytes]) -> bytes:
    if not 0 < len(frames) <= MAX_FRAMES:
        raise PeerError("invalid binary frame count")
    size = 0
    for frame in frames:
        if type(frame) is not bytes or not 0 < len(frame) <= MAX_FRAME:
            raise PeerError("invalid binary frame")
        size += len(frame) + PREFIX.size
        if size > MAX_BATCH:
            raise PeerError("binary batch too large")
    return b"".join(PREFIX.pack(len(frame)) + frame for frame in frames)


def decode(body: bytes) -> list[bytes]:
    if type(body) is not bytes or not 0 < len(body) <= MAX_BATCH:
        raise PeerError("invalid binary response")
    frames = []
    offset = 0
    while offset < len(body):
        if len(frames) >= MAX_FRAMES or len(body) - offset < PREFIX.size:
            raise PeerError("invalid binary framing")
        size = PREFIX.unpack_from(body, offset)[0]
        offset += PREFIX.size
        if not 0 < size <= MAX_FRAME or offset + size > len(body):
            raise PeerError("invalid binary framing")
        frames.append(body[offset:offset + size])
        offset += size
    return frames


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def make_agent_https_request(transport, ssl_context) -> Request:
    """One bounded HTTPS request per operation; no retry or redirect."""
    origin = transport.credential.backend_url.rstrip("/")
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.path or parsed.query or parsed.fragment
            or not ssl_context.check_hostname):
        raise PeerError("invalid HTTPS origin")

    def perform(method, path, body, cap, seconds):
        if (not path.startswith("/api/remote-desktop") or "?" in path or "#" in path
                or ".." in path or not 0 <= cap <= MAX_BATCH):
            raise PeerError("invalid HTTPS request")
        headers = {"Authorization": "Bearer " + transport.access_token(),
                   "Accept": "application/octet-stream, application/json",
                   "Cache-Control": "no-store"}
        if body is not None:
            headers["Content-Type"] = "application/octet-stream"
        request = UrlRequest(origin + path, data=body, method=method, headers=headers)
        opener = build_opener(HTTPSHandler(context=ssl_context), _NoRedirect())
        try:
            with opener.open(request, timeout=seconds) as response:
                data = response.read(cap + 1)
                if len(data) > cap:
                    raise PeerError("HTTPS response too large")
                from types import SimpleNamespace
                return SimpleNamespace(status_code=int(response.status), body=data,
                                       headers={key.lower(): value for key, value in response.headers.items()})
        except HTTPError as exc:
            exc.close()
            raise PeerError("HTTPS request rejected") from None

    async def request(method, path, body, cap, seconds):
        return await asyncio.to_thread(perform, method, path, body, cap, seconds)

    return request


class NativeHttpsAgentPeer:
    def __init__(self, request: Request, *, client_id: int, session_id: str,
                 tunnel_id: str, approved: bool = False):
        if approved is not True or type(client_id) is not int or client_id != 3:
            raise PeerError("ClientFlow HTTPS is not approved")
        self._request = request
        self._open_path = (
            f"/api/remote-desktop-agent/clients/{client_id}/native-https/"
            f"{_uuid(session_id)}/{_uuid(tunnel_id)}/open"
        )
        self._base = f"/api/remote-desktop/native-https/agent/{client_id}/"
        self._peer: str | None = None
        self._closed = False
        self._opening = False
        self._sending = False
        self._receiving = False
        self._up = 0
        self._down = 0
        self._pending: deque[bytes] = deque()

    async def _call(self, method: str, path: str, body: bytes | None,
                    cap: int, seconds: float) -> Reply:
        async with asyncio.timeout(seconds):
            result = await self._request(method, path, body, cap, seconds)
        if type(result.body) is not bytes or len(result.body) > cap:
            raise PeerError("invalid response size")
        return result

    async def open(self) -> None:
        if self._closed or self._peer is not None or self._opening:
            raise PeerError("invalid peer opening")
        self._opening = True
        try:
            reply = await self._call("POST", self._open_path, None, 1024, 12)
            if reply.status_code != 200:
                raise PeerError("ClientFlow open rejected")
            data = json.loads(reply.body)
            if (not isinstance(data, dict)
                    or not isinstance(data.get("peer_id"), str)
                    or not re.fullmatch(r"[0-9a-f]{32}", data["peer_id"])
                    or type(data.get("upload_sequence")) is not int or data["upload_sequence"] != 0
                    or type(data.get("download_sequence")) is not int or data["download_sequence"] != 0):
                raise PeerError("invalid ClientFlow peer")
            self._peer = data["peer_id"]
            if self._closed:
                await self._delete()
                raise PeerError("peer closed during opening")
        except BaseException:
            await self.close()
            raise
        finally:
            self._opening = False

    def _path(self) -> str:
        if self._closed or self._peer is None:
            raise PeerError("ClientFlow peer closed")
        return self._base + self._peer

    async def send(self, frame: bytes) -> None:
        if self._sending:
            await self.close()
            raise PeerError("concurrent upload")
        self._sending = True
        try:
            path = self._path()
            if self._up >= MAX_SEQUENCE:
                raise PeerError("upload sequence exhausted")
            reply = await self._call("POST", f"{path}/send/{self._up}", encode([frame]), 0, 12)
            if (self._closed or reply.status_code != 204
                    or reply.headers.get("x-clientflow-sequence") != str(self._up + 1)):
                raise PeerError("upload rejected")
            self._up += 1
        except BaseException:
            await self.close()
            raise
        finally:
            self._sending = False

    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes:
        if self._closed:
            raise StopAsyncIteration
        if self._receiving:
            await self.close()
            raise PeerError("concurrent poll")
        self._receiving = True
        try:
            while not self._closed:
                if self._pending:
                    return self._pending.popleft()
                path = self._path()
                if self._down >= MAX_SEQUENCE:
                    raise PeerError("download sequence exhausted")
                reply = await self._call("GET", f"{path}/poll/{self._down}", None, MAX_BATCH, 28)
                if self._closed:
                    break
                if (reply.status_code != 200
                        or reply.headers.get("content-type") != "application/octet-stream"
                        or reply.headers.get("x-clientflow-sequence") != str(self._down)):
                    raise PeerError("poll rejected")
                if reply.body:
                    self._pending.extend(decode(reply.body))
                    self._down += 1
                else:
                    await asyncio.sleep(0.01)
        except BaseException:
            await self.close()
            raise
        finally:
            self._receiving = False
        raise StopAsyncIteration

    async def _delete(self) -> None:
        peer, self._peer = self._peer, None
        if peer:
            try:
                await self._call("DELETE", self._base + peer, None, 0, 3)
            except (Exception, asyncio.CancelledError):
                # The independent backend contact supervisor remains authoritative.
                pass

    async def close(self) -> None:
        self._closed = True
        self._pending.clear()
        await self._delete()

    async def __aenter__(self):
        await self.open()
        return self

    async def __aexit__(self, *_args):
        await self.close()
