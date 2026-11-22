"""63D-34: experimental, in-process GNOME RDP native browser transport.

Disabled by default. Uses authenticated PlanIQ Remote Desktop sessions and
the existing Render Docker service. It does NOT enable GNOME Remote Desktop,
open TCP/3389, generate TLS keys or ship a browser RDP decoder. No extra
listener, database table, background polling or paid service is introduced.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import re
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from sqlmodel import Session

from ..db import engine
from ..http_ws_relay import close_relay, create_relay, get_relay, require_relay_scope
from ..native_rdp_bridge_protocol import NativeRdpProtocolError
from ..native_rdp_session_bridge import (
    MAX_NATIVE_RDP_SESSION_SECONDS, NativeRdpRelaySession,
)
from ..remote_desktop_v2 import bearer_token, verify_remote_desktop_agent_token
from ..websocket_auth import authenticate_browser_websocket_with_context
from ..websocket_protocol import ProtocolError, decode_json_message
from . import remote_desktop_v2 as rd

router = APIRouter(tags=["native-rdp-pilot"])
# This branch cannot be activated by an accidental Render environment change.
# Flip only in a dedicated gated source change AFTER decoder and client runtime.
PILOT_ENABLED = False
MAX_WIRE_CHARS = 24_000
TICKET_RE = re.compile(r"^[A-Za-z0-9_-]{32,256}$")
AUTH_RECHECK_SECONDS = 15.0
MAX_NATIVE_SESSIONS_PER_CLIENT = 1
ALLOWED_AGENT_TYPES = {
    "native_rdp_ready", "native_rdp_chunk", "native_rdp_ack", "native_rdp_close",
}
ALLOWED_BROWSER_TYPES = {"native_rdp_chunk", "native_rdp_ack", "native_rdp_close"}


@dataclass
class BrowserPeer:
    bridge: NativeRdpRelaySession
    websocket: WebSocket
    owner_user_id: int
    owner_token_version: int
    auth_session_binding: str
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


# In-memory, per existing single-node Render process. NEVER persist native
# RDP bytes, GNOME credentials or raw screen content.
AGENTS: dict[int, rd.AgentChannel] = {}
PEERS: dict[str, BrowserPeer] = {}
LOCK = asyncio.Lock()


async def _send(ws: WebSocket, payload: dict, *, lock: asyncio.Lock) -> None:
    async with lock:
        await ws.send_text(json.dumps(payload, separators=(",", ":")))


async def _browser_owner_valid(peer: BrowserPeer, *, recheck_db: bool) -> bool:
    browser = await rd._browser_for_session(peer.bridge.session_id, peer.bridge.client_id)
    if browser is None:
        return False
    if (
        browser.user_id != peer.owner_user_id
        or browser.user_token_version != peer.owner_token_version
        or browser.auth_session_binding != peer.auth_session_binding
    ):
        return False
    if recheck_db:
        owner, _ = rd._remote_desktop_browser_auth_state(browser)
        return owner is not None
    return True


async def _abort(peer: BrowserPeer, *, notify_agent: bool = True) -> None:
    """Revoke one native generation. Never terminate the existing JPEG browser."""
    async with LOCK:
        current = PEERS.get(peer.bridge.session_id)
        if current is not peer:
            return
        PEERS.pop(peer.bridge.session_id, None)
        channel = AGENTS.get(peer.bridge.client_id)
    close_message = peer.bridge.fail_closed()
    if notify_agent and channel is not None:
        try:
            await rd._send_agent(channel, close_message)
        except Exception:
            pass
    try:
        await peer.websocket.close(code=1000, reason="Native RDP session stopped")
    except Exception:
        pass


async def _forward(peer: BrowserPeer, message: dict, *, from_side: str) -> None:
    if not await _browser_owner_valid(peer, recheck_db=False):
        raise NativeRdpProtocolError("native browser session revoked")
    if PEERS.get(peer.bridge.session_id) is not peer:
        raise NativeRdpProtocolError("native RDP generation replaced")
    if from_side == "browser":
        channel = AGENTS.get(peer.bridge.client_id)
        if channel is None:
            raise NativeRdpProtocolError("native agent disconnected")
        if message["type"] == "native_rdp_chunk":
            forwarded = peer.bridge.accept_chunk(message, origin="browser")
        elif message["type"] == "native_rdp_ack":
            forwarded = peer.bridge.accept_ack(message, origin="browser")
        elif message["type"] == "native_rdp_close":
            forwarded = peer.bridge.stop(message)
        else:
            raise NativeRdpProtocolError("native browser message forbidden")
        await rd._send_agent(channel, forwarded)
    else:
        if message["type"] == "native_rdp_ready":
            forwarded = peer.bridge.agent_ready(message)
        elif message["type"] == "native_rdp_chunk":
            forwarded = peer.bridge.accept_chunk(message, origin="agent")
        elif message["type"] == "native_rdp_ack":
            forwarded = peer.bridge.accept_ack(message, origin="agent")
        elif message["type"] == "native_rdp_close":
            forwarded = peer.bridge.stop(message)
        else:
            raise NativeRdpProtocolError("native agent message forbidden")
        await _send(peer.websocket, forwarded, lock=peer.send_lock)
    if message["type"] == "native_rdp_close":
        await _abort(peer, notify_agent=False)


def _decoded(raw: str, allowed: set[str]) -> dict:
    return decode_json_message(
        raw, allowed_types=allowed, max_chars=MAX_WIRE_CHARS,
    ).payload


def _pilot_or_404() -> None:
    if not PILOT_ENABLED:
        raise HTTPException(status_code=404, detail="Native RDP pilot disabled")


async def _native_browser_websocket(
    ws: WebSocket, *, client_id: int, session_id: str,
) -> None:
    if not PILOT_ENABLED:
        await rd._close_with_reason(ws, 4404, "Native RDP pilot disabled")
        return
    if not rd._ws_origin_allowed(ws):
        await rd._close_with_reason(ws, 4403, "Invalid Origin")
        return
    with Session(engine) as db:
        user, subprotocol, binding = authenticate_browser_websocket_with_context(
            ws, client_id=client_id, capability="remote_desktop", session=db,
        )
    if (
        user is None or user.id is None
        or not getattr(user, "is_superadmin", False) or not binding
        or not rd._platform_client_accessible(client_id, user)
    ):
        await rd._close_with_reason(ws, 4403, "Native RDP not authorised")
        return
    owner = await rd._browser_for_session(session_id, client_id)
    if (
        owner is None or owner.user_id != int(user.id)
        or owner.user_token_version != int(getattr(user, "token_version", 0) or 0)
        or owner.auth_session_binding != binding
        or rd._remote_desktop_browser_auth_state(owner)[0] is None
    ):
        await rd._close_with_reason(ws, 4403, "Existing browser session required")
        return
    await ws.accept(subprotocol=subprotocol)
    async with LOCK:
        channel = AGENTS.get(client_id)
        busy = any(p.bridge.client_id == client_id for p in PEERS.values())
        if channel is None or busy:
            peer = None
        else:
            bridge = NativeRdpRelaySession(session_id, client_id)
            peer = BrowserPeer(
                bridge, ws, int(user.id), int(getattr(user, "token_version", 0) or 0),
                binding,
            )
            PEERS[session_id] = peer
    if peer is None or channel is None:
        await rd._close_with_reason(ws, 4409, "Native RDP agent unavailable or busy")
        return
    try:
        await rd._send_agent(channel, peer.bridge.open_request())
        await _send(
            ws,
            {**peer.bridge.open_request(), "type": "native_rdp_pending"},
            lock=peer.send_lock,
        )
        next_check = time.monotonic() + AUTH_RECHECK_SECONDS
        while True:
            # One bounded connection. No persistent GNOME service is activated.
            remaining = (peer.bridge.created_at + MAX_NATIVE_RDP_SESSION_SECONDS) - time.monotonic()
            if remaining <= 0:
                break
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=min(remaining, AUTH_RECHECK_SECONDS))
            except asyncio.TimeoutError:
                raw = None
            if not await _browser_owner_valid(
                peer, recheck_db=(time.monotonic() >= next_check),
            ):
                break
            if time.monotonic() >= next_check:
                next_check = time.monotonic() + AUTH_RECHECK_SECONDS
            if raw is None:
                # A stalled/unready native decoder cannot keep RDP alive.
                if not peer.bridge.ready:
                    break
                continue
            await _forward(peer, _decoded(raw, ALLOWED_BROWSER_TYPES), from_side="browser")
    except (WebSocketDisconnect, ProtocolError, NativeRdpProtocolError, ValueError):
        pass
    finally:
        await _abort(peer)


async def _native_agent_websocket(ws: WebSocket, *, client_id: int) -> None:
    await ws.accept()
    if not PILOT_ENABLED:
        await rd._close_with_reason(ws, 4404, "Native RDP pilot disabled")
        return
    credential = await rd._authenticate_agent_websocket(ws, client_id)
    if credential is None:
        return
    channel = rd.AgentChannel(
        client_id=client_id, credential_id=credential.id,
        token_version=int(credential.token_version), websocket=ws,
    )
    async with LOCK:
        old = AGENTS.get(client_id)
        AGENTS[client_id] = channel
        active = [p for p in PEERS.values() if p.bridge.client_id == client_id]
    # Any agent reconnect invalidates all previous byte stream generations.
    for peer in active:
        await _abort(peer, notify_agent=False)
    if old and old.websocket is not ws:
        await rd._close_with_reason(old.websocket, 4400, "Native agent replaced")
    next_check = time.monotonic() + AUTH_RECHECK_SECONDS
    try:
        while True:
            if AGENTS.get(client_id) is not channel:
                break
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=AUTH_RECHECK_SECONDS)
            except asyncio.TimeoutError:
                raw = None
            if time.monotonic() >= next_check:
                if not rd._remote_desktop_agent_channel_valid(channel):
                    break
                next_check = time.monotonic() + AUTH_RECHECK_SECONDS
            if raw is None:
                continue
            message = _decoded(raw, ALLOWED_AGENT_TYPES)
            sid = message.get("session_id")
            peer = PEERS.get(sid) if type(sid) is str else None
            if (
                peer is None or peer.bridge.client_id != client_id
                or not await _browser_owner_valid(peer, recheck_db=False)
            ):
                raise NativeRdpProtocolError("native RDP stream not authorised")
            await _forward(peer, message, from_side="agent")
    except (WebSocketDisconnect, ProtocolError, NativeRdpProtocolError, ValueError):
        pass
    finally:
        async with LOCK:
            current = AGENTS.get(client_id)
            is_current = current is channel
            if is_current:
                AGENTS.pop(client_id, None)
            affected = [
                p for p in PEERS.values() if p.bridge.client_id == client_id
            ] if is_current else []
        for peer in affected:
            await _abort(peer, notify_agent=False)
        await rd._close_with_reason(ws, 1000, "Native agent disconnected")


@router.websocket("/remote-desktop/native/browser/{client_id}/{session_id}/ws")
async def browser_native_ws(ws: WebSocket, client_id: int, session_id: str):
    await _native_browser_websocket(ws, client_id=client_id, session_id=session_id)


@router.websocket("/remote-desktop/native/agent/{client_id}/ws")
async def agent_native_ws(ws: WebSocket, client_id: int):
    await _native_agent_websocket(ws, client_id=client_id)


def _http_scope(role: str, client_id: int, session_id: str, request: Request) -> dict:
    _pilot_or_404()
    if role == "agent":
        if session_id != "_agent":
            raise HTTPException(status_code=404, detail="Unknown native agent scope")
        token = bearer_token(request.headers.get("authorization"))
        with Session(engine) as db:
            credential = verify_remote_desktop_agent_token(
                db, token, client_id=client_id,
            )
        return {
            "kind": "native_rdp_agent", "client_id": client_id,
            "credential_id": credential.id, "token_version": int(credential.token_version),
        }
    if role == "browser":
        user = rd._require_superadmin(rd._get_http_user(request))
        binding = rd._http_browser_session_binding(request, user)
        existing = rd.BROWSERS.get(session_id)
        if (
            existing is None or existing.client_id != client_id
            or existing.user_id != user.id or existing.auth_session_binding != binding
            or existing.user_token_version != int(getattr(user, "token_version", 0) or 0)
        ):
            raise HTTPException(status_code=403, detail="Native browser session is not authorised")
        return {
            "kind": "native_rdp_browser", "client_id": client_id,
            "session_id": session_id, "user_id": int(user.id),
            "user_token_version": int(getattr(user, "token_version", 0) or 0),
            "auth_session_binding": binding,
        }
    raise HTTPException(status_code=404, detail="Unknown native RDP transport role")


@router.post("/remote-desktop/native/{role}/{client_id}/{session_id}/http/open")
async def native_http_open(
    role: str, client_id: int, session_id: str, request: Request,
):
    scope = _http_scope(role, client_id, session_id, request)
    if role == "browser":
        # A ticket is passed only through the existing JSON body / ephemeral
        # virtual-WebSocket subprotocol; NEVER by URL or persistent logging.
        raw_body = await request.body()
        if len(raw_body) > 1_024:
            raise HTTPException(status_code=413, detail="Native ticket exceeds limit")
        try:
            body = json.loads(raw_body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=400, detail="Invalid native ticket") from exc
        if (
            type(body) is not dict or set(body) != {"ticket", "subprotocol"}
            or type(body["ticket"]) is not str
            or type(body["subprotocol"]) is not str
            or not TICKET_RE.fullmatch(body["ticket"])
            or body["subprotocol"] != "planiq-ws-ticket"
        ):
            raise HTTPException(status_code=400, detail="Invalid native browser ticket")
        headers = {
            "sec-websocket-protocol": f'{body["subprotocol"]},{body["ticket"]}',
            "origin": request.headers.get("origin") or "",
        }
        handler = lambda ws: _native_browser_websocket(
            ws, client_id=client_id, session_id=session_id,
        )
    else:
        token = bearer_token(request.headers.get("authorization"))
        headers = {"authorization": f"Bearer {token}"}
        handler = lambda ws: _native_agent_websocket(ws, client_id=client_id)
    relay = await create_relay(
        handler, headers=headers,
        client_host=(request.client.host if request.client else None),
        scope=scope,
    )
    return {"relay_id": relay.relay_id, "transport": "https_long_poll"}


@router.post("/remote-desktop/native/{role}/{client_id}/{session_id}/http/{relay_id}/send")
async def native_http_send(
    role: str, client_id: int, session_id: str, relay_id: str,
    request: Request,
):
    scope = _http_scope(role, client_id, session_id, request)
    relay = await get_relay(relay_id)
    require_relay_scope(relay, **scope)
    raw_body = await request.body()
    if len(raw_body) > MAX_WIRE_CHARS:
        raise HTTPException(status_code=413, detail="Native RDP frame exceeds limit")
    try:
        body = json.loads(raw_body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid native relay envelope") from exc
    if type(body) is not dict or set(body) != {"payload"} or type(body["payload"]) is not dict:
        raise HTTPException(status_code=400, detail="Invalid native relay envelope")
    raw = json.dumps(body["payload"], separators=(",", ":"))
    if len(raw) > MAX_WIRE_CHARS:
        raise HTTPException(status_code=413, detail="Native RDP frame exceeds limit")
    await relay.push_from_http(raw)
    return {"ok": True}


@router.get("/remote-desktop/native/{role}/{client_id}/{session_id}/http/{relay_id}/poll")
async def native_http_poll(
    role: str, client_id: int, session_id: str, relay_id: str,
    request: Request, timeout_seconds: int = 25,
):
    scope = _http_scope(role, client_id, session_id, request)
    relay = await get_relay(relay_id)
    require_relay_scope(relay, **scope)
    return {
        "messages": await relay.poll_to_http(min(30, max(1, timeout_seconds))),
        "closed": relay.closed,
    }


@router.delete("/remote-desktop/native/{role}/{client_id}/{session_id}/http/{relay_id}")
async def native_http_close(
    role: str, client_id: int, session_id: str, relay_id: str,
    request: Request,
):
    scope = _http_scope(role, client_id, session_id, request)
    relay = await get_relay(relay_id)
    require_relay_scope(relay, **scope)
    await close_relay(relay_id, reason="native_rdp_http_closed")
    return {"ok": True}
