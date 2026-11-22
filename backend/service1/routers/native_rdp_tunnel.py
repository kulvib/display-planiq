"""Session-bound, outbound-only GNOME RDP binary tunnel for the Viborg1 browser pilot.

The existing Remote Desktop browser websocket is the control-plane authority.
This route is a byte-preserving data plane: never decode, cache, log, reorder or
drop RDP packets. Each connection is bound to one active browser session,
one ClientFlow remote-desktop credential and one randomly generated generation.
No listening RDP port is opened on Render or on the ClientFlow agent.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
import time
import uuid

from fastapi import APIRouter, WebSocket
from fastapi.websockets import WebSocketDisconnect
from sqlmodel import Session

from ..db import engine
from ..remote_desktop_v2 import verify_remote_desktop_agent_token
from ..websocket_auth import authenticate_browser_websocket_with_context
from .remote_desktop_v2 import (
    BROWSERS,
    CONTROL_AGENTS,
    _extract_agent_bearer,
    _platform_client_accessible,
    _remote_desktop_browser_auth_state,
    _remote_desktop_agent_channel_valid,
    _send_agent,
    _ws_origin_allowed,
)

router = APIRouter(tags=["native-rdp-pilot"])
logger = logging.getLogger(__name__)

MAX_BINARY_PACKET = 64 * 1024
MAX_TUNNELS = 128
VIBORG1_PILOT_CLIENT_ID = 3  # Fail closed for all other clients until fleet approval.
MAX_TUNNEL_LIFETIME = 60 * 60
CHECK_INTERVAL = 15.0
OPEN_TIMEOUT = 12.0
SEND_TIMEOUT = 8.0  # Bounded backpressure: close stalled tunnel, never retain GBs of RDP frames.
CLOSE_TIMEOUT = 3.0
_TUNNELS: dict[str, "NativeRdpTunnel"] = {}
_CLIENT_TUNNELS: dict[int, str] = {}
_LOCK = asyncio.Lock()


@dataclass
class NativeRdpTunnel:
    client_id: int
    session_id: str
    tunnel_id: str
    user_id: int
    browser: WebSocket
    created_at: float = field(default_factory=time.monotonic)
    agent: WebSocket | None = None
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    closed: asyncio.Event = field(default_factory=asyncio.Event)
    to_browser: asyncio.Lock = field(default_factory=asyncio.Lock)
    to_agent: asyncio.Lock = field(default_factory=asyncio.Lock)
    agent_credential_id: str | None = None
    agent_token_version: int | None = None

    def authorized_browser(self) -> bool:
        active = BROWSERS.get(self.session_id)
        if active is None or active.client_id != self.client_id or active.user_id != self.user_id:
            return False
        current, state = _remote_desktop_browser_auth_state(active)
        return bool(current is not None and state == "ok")

    def authorized_agent(self) -> bool:
        # On an established socket the short-lived handshake token may expire.
        # Recheck credential revocation and version, not its original JWT exp.
        # Reuse the existing agent-control-channel validator; never store JWTs
        # or query PostgreSQL for every binary RDP packet.
        control = CONTROL_AGENTS.get(self.client_id)
        if not control or not self.agent_credential_id:
            return False
        if (
            str(control.credential_id) != self.agent_credential_id
            or int(control.token_version) != self.agent_token_version
        ):
            return False
        try:
            return _remote_desktop_agent_channel_valid(control)
        except Exception:
            return False


async def _reject(ws: WebSocket, reason: str, code: int = 4403) -> None:
    try:
        await asyncio.wait_for(
            ws.close(code=code, reason=reason[:100]), timeout=CLOSE_TIMEOUT
        )
    except (asyncio.TimeoutError, RuntimeError, OSError, WebSocketDisconnect):
        pass


async def _pump(tunnel: NativeRdpTunnel, incoming: WebSocket, *, browser_side: bool) -> None:
    """Backpressure is TCP-like: await every byte send, never latest-frame drop."""
    next_check = time.monotonic() + CHECK_INTERVAL
    while not tunnel.closed.is_set():
        if time.monotonic() >= tunnel.created_at + MAX_TUNNEL_LIFETIME:
            return
        receive = asyncio.create_task(incoming.receive())
        stop = asyncio.create_task(tunnel.closed.wait())
        try:
            done, _ = await asyncio.wait(
                (receive, stop),
                timeout=max(0.0, min(CHECK_INTERVAL, next_check - time.monotonic())),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stop in done or tunnel.closed.is_set():
                return
            if receive not in done:
                if not (tunnel.authorized_browser() and tunnel.authorized_agent()):
                    return
                next_check = time.monotonic() + CHECK_INTERVAL
                continue

            message = receive.result()
            if message.get("type") == "websocket.disconnect":
                return
            packet = message.get("bytes")
            if not isinstance(packet, bytes) or not (0 < len(packet) <= MAX_BINARY_PACKET):
                return
            peer = tunnel.agent if browser_side else tunnel.browser
            if peer is None:
                return
            lock = tunnel.to_agent if browser_side else tunnel.to_browser
            async with lock:
                # A peer that stops reading must not hold a websocket task or
                # the single Render worker indefinitely. TCP ordering stays
                # intact: a stalled send terminates both endpoints.
                await asyncio.wait_for(peer.send_bytes(packet), timeout=SEND_TIMEOUT)
            if time.monotonic() >= next_check:
                if not (tunnel.authorized_browser() and tunnel.authorized_agent()):
                    return
                next_check = time.monotonic() + CHECK_INTERVAL
        finally:
            for task in (receive, stop):
                if not task.done():
                    task.cancel()
            await asyncio.gather(receive, stop, return_exceptions=True)


async def _cleanup(tunnel: NativeRdpTunnel) -> None:
    tunnel.closed.set()
    async with _LOCK:
        if _TUNNELS.get(tunnel.tunnel_id) is tunnel:
            _TUNNELS.pop(tunnel.tunnel_id, None)
        if _CLIENT_TUNNELS.get(tunnel.client_id) == tunnel.tunnel_id:
            _CLIENT_TUNNELS.pop(tunnel.client_id, None)
    for socket in (tunnel.agent, tunnel.browser):
        if socket is not None:
            await _reject(socket, "RDP-session afsluttet", 1000)


@router.websocket("/remote-desktop/browser/{client_id}/native-rdp/{session_id}/ws")
async def native_rdp_browser_ws(ws: WebSocket, client_id: int, session_id: str) -> None:
    if client_id != VIBORG1_PILOT_CLIENT_ID:
        await _reject(ws, "GNOME RDP-piloten gælder kun Viborg1", 4403)
        return
    if not _ws_origin_allowed(ws):
        await _reject(ws, "Ugyldig Origin")
        return
    try:
        with Session(engine) as db:
            user, protocol, binding = authenticate_browser_websocket_with_context(
                ws, client_id=client_id, capability="remote_desktop", session=db
            )
        active = BROWSERS.get(session_id)
        valid = bool(
            user is not None and user.id is not None
            and user.is_active and user.is_superadmin
            and active is not None
            and active.client_id == client_id
            and active.user_id == int(user.id)
            and active.user_token_version == int(user.token_version or 0)
            and active.auth_session_binding == binding
            and _platform_client_accessible(client_id, user)
            and CONTROL_AGENTS.get(client_id) is not None
        )
        if valid:
            current, state = _remote_desktop_browser_auth_state(active)
            valid = current is not None and state == "ok"
        if not valid:
            await _reject(ws, "RDP-session ikke godkendt")
            return
        try:
            uuid.UUID(session_id)
        except (TypeError, ValueError):
            await _reject(ws, "RDP-session-id ugyldigt", 4400)
            return

        tunnel = NativeRdpTunnel(
            client_id=client_id, session_id=session_id,
            tunnel_id=str(uuid.uuid4()), user_id=int(user.id), browser=ws,
        )
        async with _LOCK:
            if len(_TUNNELS) >= MAX_TUNNELS or client_id in _CLIENT_TUNNELS:
                await _reject(ws, "RDP-kanalen er allerede i brug", 4409)
                return
            _TUNNELS[tunnel.tunnel_id] = tunnel
            _CLIENT_TUNNELS[client_id] = tunnel.tunnel_id

        await ws.accept(subprotocol=protocol)
        try:
            await _send_agent(CONTROL_AGENTS[client_id], {
                "type": "native_rdp_open",
                "session_id": session_id,
                "tunnel_id": tunnel.tunnel_id,
            })
            await asyncio.wait_for(tunnel.ready.wait(), timeout=OPEN_TIMEOUT)
            if tunnel.agent is None or tunnel.closed.is_set():
                return
            await _pump(tunnel, ws, browser_side=True)
        except (asyncio.TimeoutError, WebSocketDisconnect, OSError, RuntimeError) as exc:
            logger.info("native_rdp_browser_closed client_id=%s reason=%s", client_id, type(exc).__name__)
        finally:
            await _cleanup(tunnel)
    except WebSocketDisconnect:
        return


@router.websocket("/remote-desktop-agent/clients/{client_id}/native-rdp/{session_id}/{tunnel_id}/ws")
async def native_rdp_agent_ws(ws: WebSocket, client_id: int, session_id: str, tunnel_id: str) -> None:
    if client_id != VIBORG1_PILOT_CLIENT_ID:
        await _reject(ws, "GNOME RDP-piloten gælder kun Viborg1", 4403)
        return
    try:
        token = _extract_agent_bearer(ws)
        with Session(engine) as db:
            credential = verify_remote_desktop_agent_token(db, token, client_id=client_id)
    except Exception:
        await _reject(ws, "Ugyldig agentgodkendelse", 4401)
        return
    async with _LOCK:
        tunnel = _TUNNELS.get(tunnel_id)
        if (
            tunnel is None or tunnel.client_id != client_id or tunnel.session_id != session_id
            or tunnel.closed.is_set() or tunnel.agent is not None
            or not tunnel.authorized_browser()
        ):
            await _reject(ws, "RDP-tunnel er lukket eller tilhører en anden session")
            return
        control = CONTROL_AGENTS.get(client_id)
        if (
            control is None or str(control.credential_id) != str(credential.id)
            or int(control.token_version) != int(credential.token_version)
        ):
            await _reject(ws, "Agent og kontrolkanal har forskellig identitet", 4401)
            return
        tunnel.agent = ws
        tunnel.agent_credential_id = str(credential.id)
        tunnel.agent_token_version = int(credential.token_version)

    await ws.accept()
    tunnel.ready.set()
    try:
        await _pump(tunnel, ws, browser_side=False)
    except (asyncio.TimeoutError, WebSocketDisconnect, OSError, RuntimeError) as exc:
        logger.info("native_rdp_agent_closed client_id=%s reason=%s", client_id, type(exc).__name__)
    finally:
        await _cleanup(tunnel)
