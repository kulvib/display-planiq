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
from datetime import datetime, timedelta, timezone
import logging
import time
import uuid

from fastapi import APIRouter, WebSocket
from fastapi.websockets import WebSocketDisconnect
from sqlalchemy import update
from sqlmodel import Session

from ..db import engine
from ..remote_desktop_v2 import SESSION_SECONDS, verify_remote_desktop_agent_token
from ..remote_desktop_session_models import RemoteDesktopSession
from ..websocket_auth import authenticate_browser_websocket_with_context
from .remote_desktop_v2 import (
    BROWSERS,
    CONTROL_AGENTS,
    _extract_agent_bearer,
    _platform_client_accessible,
    _remote_desktop_browser_auth_state,
    _remote_desktop_agent_channel_valid,
    _send_agent,
    _send_browser,
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
class BinaryFlow:
    """Opaque frame/byte counters; never parse or retain RDP contents."""
    frames: int = 0
    bytes: int = 0
    first_at: float | None = None

    def record(self, length: int) -> None:
        if self.first_at is None:
            self.first_at = time.monotonic()
        self.frames += 1
        self.bytes += length


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
    # Keep the exact control-plane channel generation, not just its credential.
    control_channel: object | None = None
    agent_credential_id: str | None = None
    agent_token_version: int | None = None
    managed_request_id: str | None = None
    renewable: bool = False
    status_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    status_announced: bool = False
    browser_to_agent: BinaryFlow = field(default_factory=BinaryFlow)
    agent_to_browser: BinaryFlow = field(default_factory=BinaryFlow)

    def authorized_browser(self) -> bool:
        active = BROWSERS.get(self.session_id)
        if active is None or active.client_id != self.client_id or active.user_id != self.user_id:
            return False
        current, state = _remote_desktop_browser_auth_state(active)
        return bool(current is not None and current.is_superadmin and state == "ok")

    def authorized_agent(self) -> bool:
        # On an established socket the short-lived handshake token may expire.
        # Recheck credential revocation and version, not its original JWT exp.
        # Reuse the existing agent-control-channel validator; never store JWTs
        # or query PostgreSQL for every binary RDP packet.
        control = CONTROL_AGENTS.get(self.client_id)
        if not control or control is not self.control_channel or not self.agent_credential_id:
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


def _traffic_summary(tunnel: NativeRdpTunnel, phase: str) -> None:
    """Periodic bounded diagnostics; no tickets, secrets, packet content or IDs."""
    # Uvicorn configures uvicorn.error at INFO, while other module loggers may
    # inherit root WARNING. The latter silently hid the physical 63D-45 flow
    # counters even though the browser/agent WebSockets were accepted.
    # Preserve normal module logging when enabled (including pytest caplog),
    # otherwise route ONLY these content-blind summaries via uvicorn.error.
    flow_logger = logger if logger.isEnabledFor(logging.INFO) else logging.getLogger("uvicorn.error")
    flow_logger.info(
        "native_rdp_flow client_id=%d phase=%s elapsed_s=%d "
        "browser_to_agent_frames=%d browser_to_agent_bytes=%d "
        "agent_to_browser_frames=%d agent_to_browser_bytes=%d "
        "first_browser_byte_ms=%d first_agent_byte_ms=%d",
        tunnel.client_id, phase, int(time.monotonic() - tunnel.created_at),
        tunnel.browser_to_agent.frames, tunnel.browser_to_agent.bytes,
        tunnel.agent_to_browser.frames, tunnel.agent_to_browser.bytes,
        int((tunnel.browser_to_agent.first_at - tunnel.created_at) * 1000)
        if tunnel.browser_to_agent.first_at is not None else -1,
        int((tunnel.agent_to_browser.first_at - tunnel.created_at) * 1000)
        if tunnel.agent_to_browser.first_at is not None else -1,
    )


async def _watch_traffic(tunnel: NativeRdpTunnel) -> None:
    while not tunnel.closed.is_set():
        try:
            await asyncio.wait_for(tunnel.closed.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            _traffic_summary(tunnel, "active")
            if tunnel.renewable:
                if not await renew_managed_tunnel(tunnel):
                    await _cleanup(tunnel)
                    return


def renew_persisted_session(browser) -> bool:
    """Extend an existing, already-authorized managed session before expiry.

    No resurrection, no changes to login lifetime, no per-frame DB writes.
    Only the current managed tunnel calls this after both auth checks.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if browser.expires_at <= now:
        return False
    # Renew near expiry only, including short configured session windows.
    window = min(120, max(20, SESSION_SECONDS // 3))
    if browser.expires_at > now + timedelta(seconds=window):
        return True
    expiry = now + timedelta(seconds=SESSION_SECONDS)
    with Session(engine) as db:
        result = db.execute(
            update(RemoteDesktopSession)
            .where(
                RemoteDesktopSession.id == browser.session_id,
                RemoteDesktopSession.client_id == browser.client_id,
                RemoteDesktopSession.requested_by_user_id == browser.user_id,
                RemoteDesktopSession.status.in_(("requested", "authorized", "connected")),
                RemoteDesktopSession.expires_at > now,
                RemoteDesktopSession.expires_at <= now + timedelta(seconds=window),
            )
            .values(expires_at=expiry)
        )
        if result.rowcount != 1:
            db.rollback()
            return False
        db.commit()
    browser.expires_at = expiry
    return True


async def renew_managed_tunnel(tunnel: NativeRdpTunnel) -> bool:
    # A renewal is authorized on the same server-side control generation.
    # No renewal is sent through the binary data stream or by the browser.
    active = BROWSERS.get(tunnel.session_id)
    control = CONTROL_AGENTS.get(tunnel.client_id)
    if (tunnel.closed.is_set() or not tunnel.ready.is_set() or not tunnel.renewable
            or not tunnel.managed_request_id or active is None
            or getattr(active, "native_rdp_managed_request_id", None) != tunnel.managed_request_id
            or not getattr(active, "native_rdp_managed_renewable", False)
            or not getattr(active, "native_rdp_managed_ready", False)
            or getattr(active, "native_rdp_managed_channel", None) is not control
            or control is not tunnel.control_channel
            or not tunnel.authorized_browser() or not tunnel.authorized_agent()):
        return False
    try:
        await asyncio.wait_for(_send_agent(control, {
            "type": "native_rdp_renew", "session_id": tunnel.session_id,
            "request_id": tunnel.managed_request_id, "tunnel_id": tunnel.tunnel_id,
        }), timeout=2)
        if (tunnel.closed.is_set() or BROWSERS.get(tunnel.session_id) is not active
                or CONTROL_AGENTS.get(tunnel.client_id) is not control
                or getattr(active, "native_rdp_managed_request_id", None) != tunnel.managed_request_id
                or not getattr(active, "native_rdp_managed_ready", False)):
            return False
        return renew_persisted_session(active)
    except (OSError, RuntimeError, asyncio.TimeoutError, WebSocketDisconnect):
        return False


async def _reject(ws: WebSocket, reason: str, code: int = 4403) -> None:
    try:
        await asyncio.wait_for(
            ws.close(code=code, reason=reason[:100]), timeout=CLOSE_TIMEOUT
        )
    except (asyncio.TimeoutError, RuntimeError, OSError, WebSocketDisconnect):
        pass


async def _pump(tunnel: NativeRdpTunnel, incoming: WebSocket, *, browser_side: bool) -> None:
    """Constant-task, byte-preserving RDP relay with periodic authorization.

    Keep the receive task alive across idle authorization checks, rather than
    cancelling and restarting it every 15 seconds or allocating two tasks and
    a gather per RDP frame. No RDP payload is inspected, buffered or dropped.
    """
    if not (tunnel.authorized_browser() and tunnel.authorized_agent()):
        return
    next_check = time.monotonic() + CHECK_INTERVAL
    receive_task: asyncio.Task | None = None
    closed_task = asyncio.create_task(tunnel.closed.wait())
    try:
        while not tunnel.closed.is_set():
            if not tunnel.renewable and time.monotonic() >= tunnel.created_at + MAX_TUNNEL_LIFETIME:
                return
            if receive_task is None:
                receive_task = asyncio.create_task(incoming.receive())
            done, _ = await asyncio.wait(
                (receive_task, closed_task),
                timeout=max(0.0, min(CHECK_INTERVAL, next_check - time.monotonic())),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if closed_task in done or tunnel.closed.is_set():
                return
            if not tunnel.renewable and time.monotonic() >= tunnel.created_at + MAX_TUNNEL_LIFETIME:
                return
            if receive_task not in done:
                if not (tunnel.authorized_browser() and tunnel.authorized_agent()):
                    return
                next_check = time.monotonic() + CHECK_INTERVAL
                continue

            message = receive_task.result()
            receive_task = None
            if message.get("type") == "websocket.disconnect":
                return
            packet = message.get("bytes")
            if not isinstance(packet, bytes) or not (0 < len(packet) <= MAX_BINARY_PACKET):
                frame_class = (
                    "nonbinary" if not isinstance(packet, bytes)
                    else "empty" if not packet else "oversized"
                )
                logger.warning(
                    "native_rdp_invalid_frame client_id=%d direction=%s class=%s",
                    tunnel.client_id, "browser_to_agent" if browser_side else "agent_to_browser",
                    frame_class,
                )
                return
            # The generation check is in-memory; no per-frame database query.
            if (tunnel.control_channel is not None and
                    CONTROL_AGENTS.get(tunnel.client_id) is not tunnel.control_channel):
                return
            peer = tunnel.agent if browser_side else tunnel.browser
            if peer is None:
                return
            lock = tunnel.to_agent if browser_side else tunnel.to_browser
            async with lock:
                # asyncio.timeout avoids a separate wait_for task on every RDP
                # frame; stalled peers still fail closed after SEND_TIMEOUT.
                async with asyncio.timeout(SEND_TIMEOUT):
                    await peer.send_bytes(packet)
            flow = tunnel.browser_to_agent if browser_side else tunnel.agent_to_browser
            flow.record(len(packet))
            if time.monotonic() >= next_check:
                if not (tunnel.authorized_browser() and tunnel.authorized_agent()):
                    return
                next_check = time.monotonic() + CHECK_INTERVAL
    finally:
        tasks = [closed_task]
        if receive_task is not None:
            tasks.append(receive_task)
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _binary_transport(peer: object) -> str:
    # Server-created HTTP adapter, never browser input or environment flags.
    return "https" if getattr(peer, "native_rdp_https_adapter", False) is True else "wss"


async def _publish_transport(tunnel: NativeRdpTunnel, *, ready: bool) -> None:
    """Best-effort UI-only status over the existing authorized control path."""
    async with tunnel.status_lock:
        if ready:
            if tunnel.closed.is_set() or tunnel.agent is None or not tunnel.ready.is_set():
                return
            if tunnel.status_announced:
                return
            tunnel.status_announced = True
        elif not tunnel.status_announced:
            return
        else:
            tunnel.status_announced = False
        payload = {
            "type": "native_rdp_transport",
            "session_id": tunnel.session_id,
            "tunnel_id": tunnel.tunnel_id,
            "phase": "ready" if ready else "closed",
        }
        if ready:
            payload.update(browser=_binary_transport(tunnel.browser),
                           agent=_binary_transport(tunnel.agent))
        try:
            await asyncio.wait_for(
                _send_browser(tunnel.session_id, tunnel.client_id, payload),
                timeout=0.5,
            )
        except Exception:
            # Presentation cannot prevent RDP data transfer or cleanup.
            pass


async def _cleanup(tunnel: NativeRdpTunnel) -> None:
    if tunnel.closed.is_set():
        return
    tunnel.closed.set()
    _traffic_summary(tunnel, "closed")
    # Retain the one-client reservation until both close attempts complete.
    # Otherwise a new tunnel could overlap an old, still-closing generation.
    try:
        await _publish_transport(tunnel, ready=False)
        await asyncio.gather(*(
            _reject(socket, "RDP-session afsluttet", 1000)
            for socket in (tunnel.agent, tunnel.browser) if socket is not None
        ))
    finally:
        async with _LOCK:
            if _TUNNELS.get(tunnel.tunnel_id) is tunnel:
                _TUNNELS.pop(tunnel.tunnel_id, None)
            if _CLIENT_TUNNELS.get(tunnel.client_id) == tunnel.tunnel_id:
                _CLIENT_TUNNELS.pop(tunnel.client_id, None)


async def close_native_rdp_session(client_id: int, session_id: str) -> None:
    """Close only the matching generation on control-plane session teardown."""
    async with _LOCK:
        tunnel_id = _CLIENT_TUNNELS.get(client_id)
        tunnel = _TUNNELS.get(tunnel_id) if tunnel_id is not None else None
        if tunnel is None or tunnel.session_id != session_id:
            return
    await _cleanup(tunnel)


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
        control = CONTROL_AGENTS.get(client_id)
        valid = bool(
            user is not None and user.id is not None
            and user.is_active and user.is_superadmin
            and active is not None
            and active.client_id == client_id
            and active.user_id == int(user.id)
            and active.user_token_version == int(user.token_version or 0)
            and active.auth_session_binding == binding
            and _platform_client_accessible(client_id, user)
            and control is not None
        )
        managed_request_id = getattr(active, "native_rdp_managed_request_id", None)
        if managed_request_id is not None:
            valid = valid and active.native_rdp_managed_ready and active.native_rdp_managed_channel is control
        if valid:
            current, state = _remote_desktop_browser_auth_state(active)
            valid = current is not None and current.is_superadmin and state == "ok"
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
            control_channel=control, managed_request_id=managed_request_id,
            renewable=bool(managed_request_id and getattr(active, "native_rdp_managed_renewable", False)),
        )
        async with _LOCK:
            denied = (
                len(_TUNNELS) >= MAX_TUNNELS or client_id in _CLIENT_TUNNELS
                or BROWSERS.get(session_id) is not active
                or CONTROL_AGENTS.get(client_id) is not control
            )
            if not denied:
                _TUNNELS[tunnel.tunnel_id] = tunnel
                _CLIENT_TUNNELS[client_id] = tunnel.tunnel_id
        if denied:
            await _reject(ws, "RDP-kanalen er allerede i brug eller sessionen er lukket", 4409)
            return

        monitor: asyncio.Task | None = None
        try:
            await ws.accept(subprotocol=protocol)
            if tunnel.closed.is_set() or not tunnel.authorized_browser():
                return
            if CONTROL_AGENTS.get(client_id) is not control:
                return
            await _send_agent(control, {
                "type": "native_rdp_open",
                "session_id": session_id,
                "tunnel_id": tunnel.tunnel_id,
                **({"managed_request_id": managed_request_id} if managed_request_id else {}),
            })
            await asyncio.wait_for(tunnel.ready.wait(), timeout=OPEN_TIMEOUT)
            if tunnel.agent is None or tunnel.closed.is_set():
                return
            await _publish_transport(tunnel, ready=True)
            if tunnel.closed.is_set():
                return
            monitor = asyncio.create_task(_watch_traffic(tunnel))
            await _pump(tunnel, ws, browser_side=True)
        except (asyncio.TimeoutError, WebSocketDisconnect, OSError, RuntimeError) as exc:
            logger.info("native_rdp_browser_closed client_id=%s reason=%s", client_id, type(exc).__name__)
        finally:
            if monitor is not None:
                monitor.cancel()
                await asyncio.gather(monitor, return_exceptions=True)
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
            control is None or control is not tunnel.control_channel
            or str(control.credential_id) != str(credential.id)
            or int(control.token_version) != int(credential.token_version)
        ):
            await _reject(ws, "Agent og kontrolkanal har forskellig identitet", 4401)
            return
        tunnel.agent = ws
        tunnel.agent_credential_id = str(credential.id)
        tunnel.agent_token_version = int(credential.token_version)

    try:
        await ws.accept()
        if tunnel.closed.is_set():
            return
        tunnel.ready.set()
        await _pump(tunnel, ws, browser_side=False)
    except (asyncio.TimeoutError, WebSocketDisconnect, OSError, RuntimeError) as exc:
        logger.info("native_rdp_agent_closed client_id=%s reason=%s", client_id, type(exc).__name__)
    finally:
        await _cleanup(tunnel)
