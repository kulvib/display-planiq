"""Pilot-only authenticated continuous Livestream router factory.

Registered only for an explicitly configured temporary pilot client.
An idle publisher sends no media until an authenticated subscriber is present.
One event-loop/worker; no media queues, per-fragment database calls, media
persistence, or dependency on the native RDP/control transport.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket
from pydantic import BaseModel, Field
from sqlmodel import Session
from starlette.concurrency import run_in_threadpool

from ..auth import (
    get_current_user, oauth2_scheme, require_active_browser_auth_session_binding,
    validate_browser_auth_session_binding, _maintenance_snapshot_or_503,
)
from ..client_ip import get_client_ip
from ..db import engine
from ..livestream_presence import active_keys
from ..livestream_v2 import (
    VIEWER_LEASE_SECONDS, _principal_key, _require_livestream_start_allowed,
    ensure_current_generation, explicit_stop_latched, require_agent_token,
)
from ..livestream_wss_admission import (
    Admission, MAX_PUBLISHERS, TICKET_PROTOCOL, TICKET_TTL, TicketCapacity,
    TicketStore, ViewerBinding, canonical_generation, offered_ticket,
)
from ..livestream_wss_core import (
    FRAGMENT, HEADER, MAX_FRAGMENT, Epoch, LiveRelay, MediaFault, decode_frame,
)
from ..models import Client, User
from ..rate_limit import enforce_key_rate_limit, enforce_request_rate_limit
from .livestream_media import require_hls_access

RECHECK_SECONDS = 5.0
MEDIA_IDLE_SECONDS = 5.0
SEND_SECONDS = 1.0
MAX_MESSAGES_PER_SECOND = 8
MAX_BYTES_PER_SECOND = 8 * 1024 * 1024


class TicketRequest(BaseModel):
    viewer_id: str = Field(min_length=1, max_length=120)
    probe_only: bool = False


@dataclass
class Publisher:
    epoch: Epoch
    changed: asyncio.Event
    last_fragment: float | None = None


def _generation_allowed(session, client_id, generation_id):
    if not canonical_generation(generation_id):
        raise HTTPException(403, "Invalid Livestream generation")
    client = session.get(Client, client_id)
    if (client is None or client.status != "approved" or client.deleted_at is not None):
        raise HTTPException(403, "Inactive Livestream client")
    _require_livestream_start_allowed(client)
    if explicit_stop_latched(session, client_id):
        raise HTTPException(409, "Livestream stopped")
    ensure_current_generation(
        session, client_id=client_id, generation_id=generation_id,
        allowed_states={"running"},
    )


def _check_viewer(binding):
    with Session(engine) as session:
        user = validate_browser_auth_session_binding(
            session, user_id=binding.user_id,
            user_token_version=binding.token_version,
            auth_session_binding=binding.auth_session_binding,
        )
        if user is None:
            raise HTTPException(401, "Inactive login")
        if not getattr(user, "is_superadmin", False) and _maintenance_snapshot_or_503(session).enabled:
            raise HTTPException(503, "Maintenance active")
        _generation_allowed(session, binding.client_id, binding.generation_id)
        require_hls_access(user, str(binding.client_id))
        # Require a live in-process lease from the existing heartbeat. A socket
        # never renews a lease, creates a viewer, or starts the producer itself.
        if (binding.viewer_id, _principal_key(user)) not in active_keys(
            binding.client_id, lease_seconds=VIEWER_LEASE_SECONDS
        ):
            raise HTTPException(403, "Inactive viewer")


def _check_publisher(client_id, generation_id, authorization):
    with Session(engine) as session:
        require_agent_token(session, authorization, client_id=client_id)
        _generation_allowed(session, client_id, generation_id)
        if not active_keys(client_id, lease_seconds=VIEWER_LEASE_SECONDS):
            raise HTTPException(403, "No active Livestream viewer")


def _handshake_limit(ws):
    enforce_key_rate_limit(
        bucket="livestream-wss-handshake", key=get_client_ip(ws),
        max_attempts=60, window_seconds=60,
    )


async def _close(ws, code):
    try:
        await asyncio.wait_for(ws.close(code=code), timeout=SEND_SECONDS)
    except Exception:
        pass


async def _cancel(task):
    if task is not None:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def create_livestream_wss_router(*, allowed_origins, allowed_client_id):
    """Caller must provide the normalized, trusted frontend origin allowlist."""
    origins = frozenset(allowed_origins)
    if not origins or "*" in origins:
        raise ValueError("explicit Livestream origin allowlist required")
    if type(allowed_client_id) is not int or allowed_client_id <= 0:
        raise ValueError("explicit Livestream pilot client required")
    router = APIRouter()
    tickets = TicketStore()
    admission = Admission()
    relay = LiveRelay(max_channels=MAX_PUBLISHERS)
    channels = {}
    subscribers = set()  # (generation, handle); only after auth/accept

    def has_demand(generation_id):
        return any(generation == generation_id for generation, _ in subscribers)

    @router.post("/livestream-wss/clients/{client_id}/generations/{generation_id}/ticket")
    def ticket(
        client_id: int, generation_id: str, body: TicketRequest,
        request: Request, response: Response,
        user: User = Depends(get_current_user),
        token: str = Depends(oauth2_scheme),
    ):
        origin = request.headers.get("origin")
        if client_id != allowed_client_id or origin not in origins:
            raise HTTPException(403, "Invalid Livestream origin")
        enforce_request_rate_limit(
            request, bucket="livestream-wss-ticket", max_attempts=60, window_seconds=60,
        )
        if body.viewer_id != body.viewer_id.strip() or not canonical_generation(generation_id):
            raise HTTPException(400, "Invalid Livestream binding")
        with Session(engine) as session:
            binding = ViewerBinding(
                client_id, generation_id, body.viewer_id, int(user.id),
                int(user.token_version or 0),
                require_active_browser_auth_session_binding(session, token=token, user=user),
                origin,
            )
        _check_viewer(binding)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        if body.probe_only:
            channel = channels.get(client_id)
            return {"available": channel is not None and channel.epoch.generation_id == generation_id}
        try:
            raw = tickets.issue(binding)
        except TicketCapacity:
            raise HTTPException(503, "Livestream ticket capacity") from None
        return {"ticket": raw, "subprotocol": TICKET_PROTOCOL, "ttl_seconds": TICKET_TTL}

    @router.websocket("/livestream-agent/clients/{client_id}/generations/{generation_id}/media/ws")
    async def publish(ws: WebSocket, client_id: int, generation_id: str):
        authorization = ws.headers.get("authorization") or ""
        if (client_id != allowed_client_id or ws.headers.get("origin") is not None or ws.url.query
                or not canonical_generation(generation_id) or client_id <= 0
                or not authorization.lower().startswith("bearer ") or len(authorization) > 4096):
            await _close(ws, 4403)
            return
        if not admission.admit_publisher(client_id):
            await _close(ws, 1013)
            return
        channel = None
        pending = None
        code = 1011
        try:
            await run_in_threadpool(_handshake_limit, ws)
            await run_in_threadpool(_check_publisher, client_id, generation_id, authorization)
            channel = Publisher(relay.open(client_id, generation_id), asyncio.Event())
            channels[client_id] = channel
            await asyncio.wait_for(ws.accept(), timeout=SEND_SECONDS)
            now = time.monotonic()
            next_auth = now + RECHECK_SECONDS
            deadline = None
            streaming = False
            window = now
            messages = volume = 0
            pending = asyncio.create_task(ws.receive())
            while True:
                now = time.monotonic()
                if now >= next_auth:
                    await run_in_threadpool(_check_publisher, client_id, generation_id, authorization)
                    next_auth = time.monotonic() + RECHECK_SECONDS
                    now = time.monotonic()
                demand = has_demand(generation_id)
                if streaming and not demand:
                    # Drop all retained media in finally. A reconnect creates
                    # a new epoch; no old init/fragment survives idle periods.
                    code = 1000
                    break
                if demand and not streaming:
                    await asyncio.wait_for(ws.send_text("media:on"), timeout=SEND_SECONDS)
                    streaming = True
                    deadline = time.monotonic() + MEDIA_IDLE_SECONDS
                if deadline is not None and now >= deadline:
                    code = 1013
                    break
                wake_at = min(next_auth, now + 0.25, deadline if deadline is not None else next_auth)
                done, _ = await asyncio.wait(
                    {pending}, timeout=max(0.0, wake_at - now)
                )
                if not done:
                    continue
                message = pending.result()
                pending = None
                if message["type"] == "websocket.disconnect":
                    code = 1000
                    break
                if not streaming or not has_demand(generation_id):
                    code = 1008
                    break
                wire = message.get("bytes")
                if type(wire) is not bytes or len(wire) > HEADER.size + MAX_FRAGMENT:
                    code = 1009
                    break
                now = time.monotonic()
                if now - window >= 1.0:
                    messages = volume = 0
                    window = now
                messages += 1
                volume += len(wire)
                if messages > MAX_MESSAGES_PER_SECOND or volume > MAX_BYTES_PER_SECOND:
                    code = 1008
                    break
                frame = decode_frame(wire)
                relay.publish(channel.epoch, wire)
                if frame.kind == FRAGMENT:
                    channel.last_fragment = now
                    deadline = now + MEDIA_IDLE_SECONDS
                previous = channel.changed
                channel.changed = asyncio.Event()
                previous.set()
                pending = asyncio.create_task(ws.receive())
        except HTTPException:
            code = 4403
        except MediaFault:
            code = 1008
        except Exception:
            # Never log media, bearer headers, or exception text at this boundary.
            code = 1011
        finally:
            if channel is not None:
                relay.close(channel.epoch)
                if channels.get(client_id) is channel:
                    del channels[client_id]
                channel.changed.set()
            await _cancel(pending)
            await _close(ws, code)
            admission.release_publisher(client_id)

    @router.websocket("/livestream-wss/clients/{client_id}/generations/{generation_id}/subscribe")
    async def subscribe(ws: WebSocket, client_id: int, generation_id: str):
        raw = offered_ticket(ws.headers.get("sec-websocket-protocol") or "")
        origin = ws.headers.get("origin")
        if (client_id != allowed_client_id or origin not in origins or ws.url.query
                or not canonical_generation(generation_id) or raw is None):
            await _close(ws, 4403)
            return
        handle = admission.admit_viewer(client_id)
        if handle is None:
            await _close(ws, 1013)
            return
        incoming = None
        wake = None
        code = 1011
        try:
            await run_in_threadpool(_handshake_limit, ws)
            binding = tickets.consume(raw, client_id=client_id, generation_id=generation_id, origin=origin)
            if binding is None:
                raise HTTPException(403, "Invalid Livestream ticket")
            await run_in_threadpool(_check_viewer, binding)
            channel = channels.get(client_id)
            if channel is None or channel.epoch.generation_id != generation_id:
                code = 1013
                return
            await asyncio.wait_for(ws.accept(subprotocol=TICKET_PROTOCOL), timeout=SEND_SECONDS)
            subscribers.add((generation_id, handle))
            incoming = asyncio.create_task(ws.receive())
            cursor = 0
            start = time.monotonic()
            next_auth = start + RECHECK_SECONDS
            while True:
                now = time.monotonic()
                if incoming.done():
                    msg = incoming.result()
                    code = 1000 if msg["type"] == "websocket.disconnect" else 1008
                    break
                if channels.get(client_id) is not channel:
                    code = 1013
                    break
                if now >= next_auth:
                    await run_in_threadpool(_check_viewer, binding)
                    next_auth = time.monotonic() + RECHECK_SECONDS
                    continue
                last = channel.last_fragment
                if now - (last if last is not None else start) >= MEDIA_IDLE_SECONDS:
                    code = 1013
                    break
                snapshot = relay.latest(channel.epoch, cursor)
                if snapshot is not None:
                    # First read and sequence gaps include init + newest complete
                    # fragment. Client must reset its decoder on a repeated init.
                    for frame in snapshot.frames:
                        if channels.get(client_id) is not channel:
                            raise MediaFault("stale channel")
                        await asyncio.wait_for(ws.send_bytes(frame.wire), timeout=SEND_SECONDS)
                    cursor = snapshot.sequence
                    continue
                wake = asyncio.create_task(channel.changed.wait())
                await asyncio.wait(
                    {incoming, wake},
                    timeout=max(0.0, min(next_auth, (last if last is not None else start) + MEDIA_IDLE_SECONDS) - now),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                await _cancel(wake)
                wake = None
        except HTTPException:
            code = 4403
        except (MediaFault, asyncio.TimeoutError):
            code = 1013
        except Exception:
            code = 1011
        finally:
            subscribers.discard((generation_id, handle))
            await _cancel(wake)
            await _cancel(incoming)
            await _close(ws, code)
            admission.release_viewer(handle)

    return router
