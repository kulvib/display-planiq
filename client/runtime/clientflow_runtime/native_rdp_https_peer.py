"""Experimental agent-side ordered binary HTTPS peer.

The explicitly approved HTTPS pilot forwarder uses this transport. Its
owner must supply a bounded, authenticated, non-retrying HTTP request function
and a fresh native tunnel generation. No fallback on authorization failure.
"""
from __future__ import annotations

import asyncio
from collections import deque
import json
import http.client
import logging
import ssl
import threading
import time
from types import SimpleNamespace
import re
import struct
import uuid
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import (Request as UrlRequest, HTTPRedirectHandler, HTTPSHandler,
                            build_opener, getproxies, proxy_bypass)
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
    except (ValueError, TypeError, AttributeError):
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


class _Lane:
    """At most one worker per lane; retired sockets are never reused."""
    def __init__(self):
        self.connection = None
        self.busy = False
        self.retired = threading.Event()


def make_agent_https_request(transport, ssl_context) -> Request:
    """Separate persistent TLS upload/poll lanes, no retries or redirects.

    Preserve urllib's configured proxy policy rather than silently bypassing
    a proxy. The proxied path intentionally retains one-shot requests.
    """
    origin = transport.credential.backend_url.rstrip("/")
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.path or parsed.query or parsed.fragment
            or not ssl_context.check_hostname or ssl_context.verify_mode != ssl.CERT_REQUIRED):
        raise PeerError("invalid HTTPS origin")
    proxied = bool(getproxies().get("https") and not proxy_bypass(parsed.netloc))
    lanes = {name: _Lane() for name in ("upload", "poll", "delete")}
    closed = False
    counts = {"requests": 0, "connections": 0, "errors": 0, "response_ms": 0}
    logger = logging.getLogger(__name__)

    def perform(lane, method, path, body, cap, seconds):
        started = time.monotonic()
        counts["requests"] += 1
        try:
            if lane.retired.is_set():
                raise PeerError("HTTPS lane retired")
            headers = {"Authorization": "Bearer " + transport.access_token(),
                       "Accept": "application/octet-stream, application/json",
                       "Cache-Control": "no-store"}
            if lane.retired.is_set():
                raise PeerError("HTTPS lane retired")
            if body is not None:
                headers["Content-Type"] = "application/octet-stream"
            if proxied:
                req = UrlRequest(origin + path, data=body, method=method, headers=headers)
                opener = build_opener(HTTPSHandler(context=ssl_context), _NoRedirect())
                counts["connections"] += 1
                try:
                    with opener.open(req, timeout=seconds) as response:
                        expected = response.length
                        data = response.read(cap + 1)
                        if ((expected is not None and len(data) != expected)
                                or len(data) > cap or not 200 <= response.status < 300):
                            raise PeerError("HTTPS response rejected")
                        return SimpleNamespace(status_code=int(response.status), body=data,
                                               headers={k.lower(): v for k, v in response.headers.items()})
                except HTTPError as exc:
                    exc.close()
                    raise PeerError("HTTPS request rejected") from None
            connection = lane.connection
            if connection is None:
                connection = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443,
                                                         timeout=seconds, context=ssl_context)
                lane.connection = connection
            connection.timeout = seconds
            if connection.sock is not None:
                connection.sock.settimeout(seconds)
            else:
                counts["connections"] += 1
            # http.client never replays a request on a failed reused socket.
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            try:
                if not 200 <= response.status < 300:
                    raise PeerError("HTTPS request rejected")
                expected = response.length
                if expected is not None and expected > cap:
                    raise PeerError("HTTPS response too large")
                data = response.read(cap + 1)
                if expected is not None and len(data) != expected:
                    raise PeerError("HTTPS response truncated")
                if len(data) > cap:
                    raise PeerError("HTTPS response too large")
                # A bounded read can leave HTTP framing pending. Never reuse
                # until EOF of this response is proven.
                if not response.isclosed():
                    if response.read(1):
                        raise PeerError("HTTPS response too large")
                return SimpleNamespace(status_code=int(response.status), body=data,
                                       headers={k.lower(): v for k, v in response.headers.items()})
            finally:
                response.close()
        except BaseException:
            counts["errors"] += 1
            if lane.connection is not None:
                lane.connection.close()
                lane.connection = None
            raise
        finally:
            counts["response_ms"] += int((time.monotonic() - started) * 1000)
            if lane.retired.is_set() and lane.connection is not None:
                lane.connection.close()
                lane.connection = None

    async def request(method, path, body, cap, seconds):
        if (closed or method not in {"GET", "POST", "DELETE"}
                or not path.startswith("/api/remote-desktop") or "?" in path or "#" in path
                or ".." in path or not 0 <= cap <= MAX_BATCH):
            raise PeerError("invalid HTTPS request")
        lane = lanes["poll" if method == "GET" else "delete" if method == "DELETE" else "upload"]
        if lane.busy or lane.retired.is_set():
            raise PeerError("HTTPS lane unavailable")
        lane.busy = True
        # Shield the worker from coroutine cancellation. A cancelled operation
        # permanently retires its lane; the bounded socket worker closes it.
        job = asyncio.create_task(asyncio.to_thread(perform, lane, method, path, body, cap, seconds))
        def finished(task):
            lane.busy = False
            if not task.cancelled():
                task.exception()
        job.add_done_callback(finished)
        try:
            return await asyncio.shield(job)
        except asyncio.CancelledError:
            lane.retired.set()
            raise

    def close():
        nonlocal closed
        if closed:
            return
        closed = True
        for lane in lanes.values():
            lane.retired.set()
            if not lane.busy and lane.connection is not None:
                lane.connection.close()
                lane.connection = None
        logger.info("native_rdp_https_agent requests=%d connections=%d errors=%d response_ms=%d proxied=%s",
                    counts["requests"], counts["connections"], counts["errors"],
                    counts["response_ms"], proxied)

    request.close = close
    return request


async def upload_stream(reader, peer, guard, sent):
    """Read ahead while a single ordered upload is awaiting acknowledgement.

    No deliberate delay on the first block. Batch only already available
    blocks, cap the queue at 15 x 16 KiB, never drop or reorder ciphertext.
    """
    queue = asyncio.Queue(maxsize=15)

    async def read():
        while True:
            guard()
            packet = await reader.read(16 * 1024)
            await queue.put(packet)
            if not packet:
                return

    async def upload():
        while True:
            first = await queue.get()
            if not first:
                return
            frames = [first]
            eof = False
            while len(frames) < 15:
                try:
                    packet = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if not packet:
                    eof = True
                    break
                frames.append(packet)
            guard()
            await peer.send_many(frames)
            for frame in frames:
                sent(frame)
            if eof:
                return

    async with asyncio.TaskGroup() as group:
        group.create_task(read())
        group.create_task(upload())


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
        await self.send_many([frame])

    async def send_many(self, frames: list[bytes]) -> None:
        if self._sending:
            await self.close()
            raise PeerError("concurrent upload")
        self._sending = True
        try:
            path = self._path()
            if self._up >= MAX_SEQUENCE:
                raise PeerError("upload sequence exhausted")
            reply = await self._call("POST", f"{path}/send/{self._up}", encode(frames), 0, 12)
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
        try:
            await self._delete()
        finally:
            close_request = getattr(self._request, "close", None)
            if close_request is not None:
                close_request()

    async def __aenter__(self):
        await self.open()
        return self

    async def __aexit__(self, *_args):
        await self.close()
