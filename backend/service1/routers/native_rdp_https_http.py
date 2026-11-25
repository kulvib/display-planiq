"""Experimental authenticated HTTP boundary for the native binary tunnel.

Mounted only with explicit deployment opt-in; the request gate defaults off.
Existing native tunnel handlers remain the only tunnel allocation authority.
No alternate RDP host/port, persisted media, or credentials in URLs.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
import os
import re
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
import uuid

from fastapi import APIRouter, HTTPException, Request, Response
from sqlmodel import Session
from starlette.requests import ClientDisconnect

from ..db import engine
from ..native_rdp_https_core import BinaryHttpsPeer, BinaryPeerFault, MAX_BATCH, QueueBudget
from ..remote_desktop_v2 import verify_remote_desktop_agent_token
from . import native_rdp_tunnel as native
from . import remote_desktop_v2 as control

router = APIRouter(tags=["experimental-native-binary-https"])
logger = logging.getLogger(__name__)
MAX_PEERS = 16
BODY_TIMEOUT = 8.0
OPEN_TIMEOUT = 8.0
_BUDGET = QueueBudget()
_PEERS: dict[str, "Entry"] = {}
_TICKET = re.compile(r"[A-Za-z0-9_-]{32,256}", re.ASCII)
_SEQUENCE = re.compile(r"0|[1-9][0-9]{0,15}", re.ASCII)


def _gate(client_id: int) -> None:
    if (os.environ.get("CLIENTFLOW_NATIVE_BINARY_HTTPS_ENABLED") != "true"
            or client_id != native.VIBORG1_PILOT_CLIENT_ID):
        raise HTTPException(404, "ClientFlow-transport ikke tilgængelig")


def _uuid(value: str) -> str:
    try:
        if str(uuid.UUID(value)) == value:
            return value
    except (TypeError, ValueError):
        pass
    raise HTTPException(404, "ClientFlow-session ikke fundet")


def _sequence(value: str) -> int:
    if not _SEQUENCE.fullmatch(value) or int(value) >= 2**53 - 1:
        raise HTTPException(400, "Ugyldig sekvens")
    return int(value)


class HttpPeer(BinaryHttpsPeer):
    """Minimal handshake surface consumed by the existing native handlers."""

    def __init__(self, headers: dict[str, str], host: str | None):
        super().__init__(_BUDGET)
        self.headers = headers
        self.cookies: dict[str, str] = {}
        self.query_params: dict[str, str] = {}
        self.client = SimpleNamespace(host=host) if host else None
        self.accepted = asyncio.Event()

    async def accept(self, subprotocol: str | None = None) -> None:
        self.headers.clear()
        if not self.closed.is_set():
            self.accepted.set()

    async def close(self, **kwargs: Any) -> None:
        self.headers.clear()
        await super().close(**kwargs)


@dataclass(frozen=True)
class Owner:
    role: str
    client_id: int
    principal: str
    version: int
    binding: str = ""


@dataclass
class TransportCounters:
    """Per-peer accepted work, not an assertion of remote delivery.

    Counts are fixed-size and content-free; no DB operations or per-packet
    logging. Report once at peer retirement.
    """
    started: float = field(default_factory=time.monotonic)
    uploads: int = 0
    upload_bytes: int = 0
    nonempty_polls: int = 0
    empty_polls: int = 0
    download_bytes: int = 0
    delivery_errors: int = 0

    def report(self, role: str) -> None:
        # Role is drawn only from the two authenticated endpoint types.
        if role not in {"agent", "browser"}:
            return
        logger.info(
            "native_rdp_https_summary role=%s elapsed_ms=%d uploads=%d "
            "upload_wire_bytes=%d nonempty_polls=%d empty_polls=%d "
            "download_wire_bytes=%d response_delivery_errors_observed=%d",
            role, max(0, int((time.monotonic() - self.started) * 1000)),
            self.uploads, self.upload_bytes, self.nonempty_polls,
            self.empty_polls, self.download_bytes, self.delivery_errors,
        )


@dataclass
class Entry:
    peer_id: str
    owner: Owner
    session_id: str
    request_id: str
    active: Any
    channel: Any
    peer: HttpPeer
    tunnel_id: str | None = None
    task: asyncio.Task | None = None
    uploading: bool = False
    polling: bool = False
    counters: TransportCounters = field(default_factory=TransportCounters)


def _browser_owner(request: Request, client_id: int) -> Owner:
    # Require an explicit allowed origin, including in development. Cookies
    # alone cannot authorize a cross-origin binary write.
    origin = request.headers.get("origin")
    if origin:
        if not control._ws_origin_allowed(request):
            raise HTTPException(403, "Ugyldig Origin")
    elif not (request.method == "GET" and request.headers.get("sec-fetch-site") == "same-origin"):
        raise HTTPException(403, "Ugyldig Origin")
    # Data transport uses bearer auth only, including same-origin GET.
    if not request.headers.get("authorization", "").lower().startswith("bearer "):
        raise HTTPException(401, "ClientFlow-adgangstoken mangler")
    user = control._require_superadmin(control._get_http_user(request))
    binding = control._http_browser_session_binding(request, user)
    if not binding or not control._platform_client_accessible(client_id, user):
        raise HTTPException(403, "ClientFlow-adgang afvist")
    return Owner("browser", client_id, str(user.id), int(user.token_version or 0), binding)


def _agent_owner(request: Request, client_id: int) -> Owner:
    try:
        with Session(engine) as db:
            credential = verify_remote_desktop_agent_token(
                db, control._extract_agent_bearer(request), client_id=client_id
            )
            return Owner("agent", client_id, str(credential.id), int(credential.token_version))
    except Exception as exc:
        raise HTTPException(401, "Ugyldig agentgodkendelse") from exc


def _identity_context(owner: Owner, session_id: str) -> tuple[Any, Any, str]:
    active = control.BROWSERS.get(session_id)
    channel = control.CONTROL_AGENTS.get(owner.client_id)
    if (active is None or channel is None or active.client_id != owner.client_id
            or not active.native_rdp_managed_request_id
            or not active.native_rdp_managed_ready
            or not active.native_rdp_managed_renewable
            or active.native_rdp_managed_channel is not channel):
        raise HTTPException(404, "ClientFlow-session ikke fundet")
    if owner.role == "browser":
        valid = (str(active.user_id) == owner.principal
                 and active.user_token_version == owner.version
                 and active.auth_session_binding == owner.binding)
    else:
        valid = (str(channel.credential_id) == owner.principal
                 and int(channel.token_version) == owner.version)
    if not valid:
        raise HTTPException(404, "ClientFlow-session ikke fundet")
    idle = getattr(active, "native_idle", None)
    expiry = getattr(active, "expires_at", None)
    if ((idle is not None and idle.expired(time.monotonic()))
            or (expiry is not None and expiry <= datetime.now(timezone.utc).replace(tzinfo=None))):
        raise HTTPException(403, "ClientFlow-session ikke godkendt")
    return active, channel, active.native_rdp_managed_request_id


def _active_context(owner: Owner, session_id: str) -> tuple[Any, Any, str]:
    active, channel, request_id = _identity_context(owner, session_id)
    current, state = control._remote_desktop_browser_auth_state(active)
    if current is None or not current.is_superadmin or state != "ok":
        raise HTTPException(403, "ClientFlow-session ikke godkendt")
    if not control._remote_desktop_agent_channel_valid(channel):
        raise HTTPException(403, "ClientFlow-agent ikke godkendt")
    return active, channel, request_id


def _tunnel(entry: Entry):
    tunnel_id = entry.tunnel_id or native._CLIENT_TUNNELS.get(entry.owner.client_id)
    tunnel = native._TUNNELS.get(tunnel_id) if tunnel_id else None
    if (tunnel is None or tunnel.closed.is_set()
            or tunnel.client_id != entry.owner.client_id
            or tunnel.session_id != entry.session_id
            or tunnel.managed_request_id != entry.request_id
            or tunnel.control_channel is not entry.channel):
        return None
    attached = tunnel.browser if entry.owner.role == "browser" else tunnel.agent
    return tunnel if attached is entry.peer else None


async def _live(entry: Entry, *, database: bool = True) -> None:
    try:
        _gate(entry.owner.client_id)
        validate = _active_context if database else _identity_context
        active, channel, request_id = validate(entry.owner, entry.session_id)
        if (active is not entry.active or channel is not entry.channel
                or request_id != entry.request_id or _tunnel(entry) is None
                or entry.peer.closed.is_set()):
            raise HTTPException(410, "ClientFlow-session afsluttet")
    except Exception:
        await entry.peer.close()
        raise


def _empty_open(request: Request) -> None:
    if (request.headers.get("content-length", "0") != "0"
            or request.headers.get("transfer-encoding")):
        raise HTTPException(400, "Åbning kræver tom body")


async def _run(entry: Entry) -> None:
    supervisor = asyncio.create_task(entry.peer.supervise())
    try:
        if entry.owner.role == "browser":
            await native.native_rdp_browser_ws(entry.peer, entry.owner.client_id, entry.session_id)
        else:
            await native.native_rdp_agent_ws(
                entry.peer, entry.owner.client_id, entry.session_id, entry.tunnel_id
            )
    finally:
        await entry.peer.close()
        supervisor.cancel()
        await asyncio.gather(supervisor, return_exceptions=True)
        if _PEERS.get(entry.peer_id) is entry:
            _PEERS.pop(entry.peer_id, None)
        entry.counters.report(entry.owner.role)


async def _open(request: Request, owner: Owner, session_id: str,
                tunnel_id: str | None = None) -> dict:
    _empty_open(request)
    _uuid(session_id)
    active, channel, request_id = _active_context(owner, session_id)
    if owner.role == "browser":
        ticket = request.headers.get("x-clientflow-ticket", "")
        if not _TICKET.fullmatch(ticket):
            raise HTTPException(401, "Ugyldig ClientFlow-ticket")
        # The unchanged native handler consumes the one-time ticket and
        # verifies the same active login binding again before accepting.
        headers = {"sec-websocket-protocol": "planiq-ws-ticket," + ticket,
                   "origin": request.headers["origin"]}
    else:
        _uuid(tunnel_id or "")
        tunnel = native._TUNNELS.get(tunnel_id)
        if (tunnel is None or tunnel.closed.is_set() or tunnel.agent is not None
                or tunnel.client_id != owner.client_id or tunnel.session_id != session_id
                or tunnel.managed_request_id != request_id or tunnel.control_channel is not channel):
            raise HTTPException(404, "ClientFlow-tunnel ikke fundet")
        headers = {"authorization": request.headers.get("authorization", "")}
    # No await between reservation check and insertion: single event loop.
    if len(_PEERS) >= MAX_PEERS or any(
        item.owner.role == owner.role and item.owner.client_id == owner.client_id
        for item in _PEERS.values()
    ):
        raise HTTPException(409, "ClientFlow-transport optaget")
    peer = HttpPeer(headers, request.client.host if request.client else None)
    entry = Entry(uuid.uuid4().hex, owner, session_id, request_id, active, channel, peer, tunnel_id)
    _PEERS[entry.peer_id] = entry
    entry.task = asyncio.create_task(_run(entry))
    accepted = asyncio.create_task(peer.accepted.wait())
    closed = asyncio.create_task(peer.closed.wait())
    try:
        await asyncio.wait((accepted, closed), timeout=OPEN_TIMEOUT,
                           return_when=asyncio.FIRST_COMPLETED)
        if not peer.accepted.is_set() or peer.closed.is_set():
            raise HTTPException(403, "ClientFlow-forbindelse ikke godkendt")
        await _live(entry)
        return {"peer_id": entry.peer_id, "upload_sequence": 0, "download_sequence": 0}
    except BaseException:
        await peer.close()
        raise
    finally:
        for task in (accepted, closed):
            task.cancel()
        await asyncio.gather(accepted, closed, return_exceptions=True)


def _entry(owner: Owner, peer_id: str) -> Entry:
    entry = _PEERS.get(peer_id)
    if entry is None or entry.owner != owner:
        # Wrong owner cannot close or otherwise affect a valid peer.
        raise HTTPException(404, "ClientFlow-transport ikke fundet")
    return entry


async def _body(request: Request) -> bytes:
    if request.headers.get("content-type", "").lower() != "application/octet-stream":
        raise HTTPException(415, "Kun binære ClientFlow-data")
    declared = request.headers.get("content-length")
    if declared is not None:
        if not declared.isascii() or not declared.isdecimal() or len(declared) > 6:
            raise HTTPException(413, "ClientFlow-body for stor")
        if not 0 < int(declared) <= MAX_BATCH:
            raise HTTPException(413, "ClientFlow-body for stor")
    buffer = bytearray()
    async with asyncio.timeout(BODY_TIMEOUT):
        async for chunk in request.stream():
            if len(chunk) > MAX_BATCH - len(buffer):
                raise HTTPException(413, "ClientFlow-body for stor")
            buffer.extend(chunk)
    if not buffer or (declared is not None and int(declared) != len(buffer)):
        raise HTTPException(400, "Ugyldig ClientFlow-body")
    return bytes(buffer)


class PeerResponse(Response):
    """Hold the request lane through ASGI delivery, not only queue removal."""

    def __init__(self, entry: Entry, lane: str, **kwargs: Any):
        super().__init__(**kwargs)
        self.entry = entry
        self.lane = lane

    async def __call__(self, scope, receive, send):
        try:
            async with asyncio.timeout(BODY_TIMEOUT):
                await super().__call__(scope, receive, send)
        except BaseException:
            self.entry.counters.delivery_errors += 1
            await self.entry.peer.close()
            raise
        finally:
            setattr(self.entry, self.lane, False)


async def _send(request: Request, entry: Entry, sequence: str) -> Response:
    await _live(entry, database=False)
    if entry.uploading:
        await entry.peer.close()
        raise HTTPException(409, "Samtidig ClientFlow-upload")
    entry.uploading = True
    try:
        seq = _sequence(sequence)
        body = await _body(request)
        await _live(entry)
        next_seq = entry.peer.push(seq, body)
        entry.counters.uploads += 1
        entry.counters.upload_bytes += len(body)
        return PeerResponse(entry, "uploading", status_code=204,
                            headers={"X-ClientFlow-Sequence": str(next_seq), "Cache-Control": "no-store"})
    except (BinaryPeerFault, ClientDisconnect, asyncio.TimeoutError) as exc:
        await entry.peer.close()
        entry.uploading = False
        raise HTTPException(409, "ClientFlow-upload afsluttet") from exc
    except BaseException:
        await entry.peer.close()
        entry.uploading = False
        raise


async def _poll(entry: Entry, sequence: str) -> Response:
    await _live(entry, database=False)
    if entry.polling:
        await entry.peer.close()
        raise HTTPException(409, "Samtidig ClientFlow-poll")
    entry.polling = True
    try:
        batch = await entry.peer.poll(_sequence(sequence))
        if batch.closed:
            raise HTTPException(410, "ClientFlow-session afsluttet")
        await _live(entry)
        if batch.body:
            entry.counters.nonempty_polls += 1
            entry.counters.download_bytes += len(batch.body)
        else:
            entry.counters.empty_polls += 1
        return PeerResponse(entry, "polling", content=batch.body,
                            media_type="application/octet-stream",
                            headers={"X-ClientFlow-Sequence": str(batch.sequence), "Cache-Control": "no-store"})
    except BinaryPeerFault as exc:
        await entry.peer.close()
        entry.polling = False
        raise HTTPException(409, "ClientFlow-poll afsluttet") from exc
    except BaseException:
        await entry.peer.close()
        entry.polling = False
        raise


@router.post("/remote-desktop/browser/{client_id}/native-https/{session_id}/open")
async def browser_open(client_id: int, session_id: str, request: Request):
    _gate(client_id)
    return await _open(request, _browser_owner(request, client_id), session_id)


@router.post("/remote-desktop-agent/clients/{client_id}/native-https/{session_id}/{tunnel_id}/open")
async def agent_open(client_id: int, session_id: str, tunnel_id: str, request: Request):
    _gate(client_id)
    return await _open(request, _agent_owner(request, client_id), session_id, tunnel_id)


def _request_entry(request: Request, client_id: int, role: str, peer_id: str) -> Entry:
    _gate(client_id)
    if role == "browser":
        owner = _browser_owner(request, client_id)
    elif role == "agent":
        owner = _agent_owner(request, client_id)
    else:
        raise HTTPException(404, "ClientFlow-transport ikke fundet")
    return _entry(owner, peer_id)


@router.post("/remote-desktop/native-https/{role}/{client_id}/{peer_id}/send/{sequence}")
async def send_batch(role: str, client_id: int, peer_id: str, sequence: str, request: Request):
    return await _send(request, _request_entry(request, client_id, role, peer_id), sequence)


@router.get("/remote-desktop/native-https/{role}/{client_id}/{peer_id}/poll/{sequence}")
async def poll_batch(role: str, client_id: int, peer_id: str, sequence: str, request: Request):
    return await _poll(_request_entry(request, client_id, role, peer_id), sequence)


@router.delete("/remote-desktop/native-https/{role}/{client_id}/{peer_id}")
async def close_peer(role: str, client_id: int, peer_id: str, request: Request):
    entry = _request_entry(request, client_id, role, peer_id)
    await entry.peer.close()
    return Response(status_code=204, headers={"Cache-Control": "no-store"})
