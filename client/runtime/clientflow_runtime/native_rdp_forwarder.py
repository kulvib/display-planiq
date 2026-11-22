"""Viborg1 GNOME Desktop Sharing -> PlanIQ authenticated binary WSS tunnel.

No RDP listener, no bridge-side RDP credentials, no public RDP port.
The optional pilot is disabled until a root-owned, boot-ephemeral guard marker
has been installed AFTER firewall/watchdog and GNOME Desktop Sharing checks.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import socket
import stat
import uuid

import websockets

from .remote_desktop_net import DomainTransport

GNOME_RDP_HOST = "127.0.0.1"
GNOME_RDP_PORT = 3389
GUARD_MARKER = Path("/run/clientflow/native-rdp-approved")
MAX_PDU_CHUNK = 16 * 1024
MAX_WSS_MESSAGE = 64 * 1024


class NativeRdpNotApproved(RuntimeError):
    pass


def ensure_native_rdp_guard(*, client_id: int) -> None:
    """A reboot drops the marker; root must re-approve the physical firewall.

    This is a human-controlled pilot latch, not a replacement for nftables.
    """
    try:
        info = GUARD_MARKER.lstat()
        if (
            not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) != 0o644
            or GUARD_MARKER.read_text(encoding="ascii") != f"{socket.gethostname()}:{client_id}\n"
        ):
            raise NativeRdpNotApproved("GNOME RDP mangler fysisk firewallgodkendelse")
    except (OSError, UnicodeError) as exc:
        raise NativeRdpNotApproved("GNOME RDP er ikke aktiveret til browserpilot") from exc


async def forward_native_rdp(
    *, transport: DomainTransport, client_id: int, session_id: str,
    tunnel_id: str, ssl_context,
) -> None:
    # Exact generation and client binding. No arbitrary host/port parameter.
    uuid.UUID(session_id)
    uuid.UUID(tunnel_id)
    ensure_native_rdp_guard(client_id=client_id)
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(GNOME_RDP_HOST, GNOME_RDP_PORT), timeout=4.0
    )
    try:
        path = (
            f"/api/remote-desktop-agent/clients/{client_id}/native-rdp/"
            f"{session_id}/{tunnel_id}/ws"
        )
        async with websockets.connect(
            transport.websocket_url(path),
            extra_headers=transport.websocket_headers(),
            ssl=ssl_context,
            max_size=MAX_WSS_MESSAGE,
            open_timeout=12,
            close_timeout=3,
            ping_interval=15,
            ping_timeout=15,
            max_queue=4,
        ) as websocket:

            async def send_local_bytes() -> None:
                async for packet in websocket:
                    if not isinstance(packet, bytes) or not (0 < len(packet) <= MAX_WSS_MESSAGE):
                        raise ConnectionError("Ugyldig binær RDP-pakke")
                    writer.write(packet)
                    await writer.drain()

            async def send_remote_bytes() -> None:
                while True:
                    ensure_native_rdp_guard(client_id=client_id)
                    packet = await reader.read(MAX_PDU_CHUNK)
                    if not packet:
                        return
                    await websocket.send(packet)

            tasks = [
                asyncio.create_task(send_local_bytes()),
                asyncio.create_task(send_remote_bytes()),
            ]
            try:
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), timeout=3)
        except (OSError, asyncio.TimeoutError):
            pass
