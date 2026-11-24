"""63D-49: request a one-time sealed GNOME RDP bootstrap from root over AF_UNIX.

The non-privileged agent never receives a plaintext GNOME RDP password.
Only the existing, session-bound superadmin control lane may invoke this.
Fail closed on socket owner, mode, physical guard, expiry and message bounds.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import re
import socket
import stat
import struct
import time
import uuid

from .native_rdp_forwarder import ensure_native_rdp_guard

SOCKET = Path("/run/clientflow/rdp-autologin-v1.sock")
MANAGED_SOCKET = Path("/run/clientflow/rdp-lifecycle-v1.sock")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
B64_RE = re.compile(r"^[A-Za-z0-9_-]+$")
MAX_REPLY = 2048


class AutologinUnavailable(RuntimeError):
    pass


def _validate_binding(value: str) -> None:
    if not isinstance(value, str) or not UUID_RE.fullmatch(value):
        raise AutologinUnavailable("INVALID_SESSION_BINDING")
    try:
        if str(uuid.UUID(value)) != value:
            raise AutologinUnavailable("NONCANONICAL_SESSION_BINDING")
    except ValueError as exc:
        raise AutologinUnavailable("INVALID_SESSION_BINDING") from exc


def _verify_local_socket(path=None) -> None:
    path = SOCKET if path is None else path
    try:
        parent = path.parent.lstat()
        stat_info = path.lstat()
    except OSError as exc:
        raise AutologinUnavailable("RDP_LOGIN_BROKER_OFFLINE") from exc
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0 or
            parent.st_mode & 0o022 or not stat.S_ISSOCK(stat_info.st_mode) or
            stat_info.st_uid != 0 or stat.S_IMODE(stat_info.st_mode) != 0o660):
        raise AutologinUnavailable("RDP_LOGIN_BROKER_UNTRUSTED")


def _validate_envelope(envelope: dict, *, session_id: str, request_id: str) -> None:
    fields = {"schema", "session_id", "request_id", "public_key",
              "salt", "nonce", "ciphertext", "expires_unix"}
    if type(envelope) is not dict or set(envelope) != fields:
        raise AutologinUnavailable("INVALID_SEALED_RDP_ENVELOPE")
    if (type(envelope["schema"]) is not int or envelope["schema"] != 1
            or envelope["session_id"] != session_id or
            envelope["request_id"] != request_id):
        raise AutologinUnavailable("SEALED_RDP_WRONG_SESSION")
    for key, limit in (("public_key", 100), ("salt", 24),
                       ("nonce", 20), ("ciphertext", 1024)):
        value = envelope.get(key)
        if not isinstance(value, str) or not 1 <= len(value) <= limit or not B64_RE.fullmatch(value):
            raise AutologinUnavailable("SEALED_RDP_ENVELOPE_INVALID_ENCODING")
    remaining = envelope["expires_unix"] - int(time.time()) if type(envelope["expires_unix"]) is int else -1
    if not (0 < remaining <= 60):
        raise AutologinUnavailable("SEALED_RDP_ENVELOPE_EXPIRED")


async def request_sealed_native_rdp_login(
    *, client_id: int, session_id: str, request_id: str, public_key: str,
) -> dict:
    if client_id != 3:
        raise AutologinUnavailable("UNSUPPORTED_RDP_CLIENT")
    _validate_binding(session_id)
    _validate_binding(request_id)
    if not isinstance(public_key, str) or not 80 <= len(public_key) <= 92 or not B64_RE.fullmatch(public_key):
        raise AutologinUnavailable("INVALID_BROWSER_PUBLIC_KEY")
    ensure_native_rdp_guard(client_id=client_id)
    _verify_local_socket()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(str(SOCKET)), timeout=2
        )
    except (OSError, asyncio.TimeoutError) as exc:
        raise AutologinUnavailable("RDP_LOGIN_BROKER_UNREACHABLE") from exc
    try:
        request = {
            "schema": 1, "session_id": session_id,
            "request_id": request_id, "public_key": public_key,
        }
        writer.write(json.dumps(request, separators=(",", ":")).encode("ascii") + b"\n")
        await asyncio.wait_for(writer.drain(), timeout=2)
        # Root verifies the kernel guard using a subprocess bounded to 10 s.
        # Keep the response deadline inside Render's 20 s pending challenge.
        frame = await asyncio.wait_for(reader.readline(), timeout=12)
        if not frame or len(frame) > MAX_REPLY or not frame.endswith(b"\n"):
            raise AutologinUnavailable("RDP_LOGIN_BROKER_DENIED")
        envelope = json.loads(frame.decode("ascii"))
        _validate_envelope(envelope, session_id=session_id, request_id=request_id)
        ensure_native_rdp_guard(client_id=client_id)
        return envelope
    except (OSError, UnicodeError, ValueError, asyncio.TimeoutError) as exc:
        raise AutologinUnavailable("RDP_LOGIN_BROKER_PROTOCOL_ERROR") from exc
    finally:
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), timeout=2)
        except (OSError, asyncio.TimeoutError):
            pass


@asynccontextmanager
async def open_managed_native_rdp_login(*, client_id, session_id, request_id, public_key):
    """Keep the guarded physical lease only while this local socket lives."""
    if client_id != 3:
        raise AutologinUnavailable("UNSUPPORTED_RDP_CLIENT")
    _validate_binding(session_id)
    _validate_binding(request_id)
    if not isinstance(public_key, str) or not 80 <= len(public_key) <= 92 or not B64_RE.fullmatch(public_key):
        raise AutologinUnavailable("INVALID_BROWSER_PUBLIC_KEY")
    _verify_local_socket(MANAGED_SOCKET)
    writer = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(str(MANAGED_SOCKET), limit=MAX_REPLY + 1), timeout=3)
        peer = writer.get_extra_info("socket")
        if peer is None or struct.unpack("3i", peer.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1] != 0:
            raise AutologinUnavailable("RDP_LIFECYCLE_UNTRUSTED")
        request = {"schema": 1, "session_id": session_id,
                   "request_id": request_id, "public_key": public_key}
        writer.write(json.dumps(request, separators=(",", ":")).encode("ascii") + b"\n")
        await asyncio.wait_for(writer.drain(), timeout=3)
        frame = await asyncio.wait_for(reader.readline(), timeout=165)
        if not frame or len(frame) > MAX_REPLY or not frame.endswith(b"\n"):
            raise AutologinUnavailable("RDP_LIFECYCLE_DENIED")
        envelope = json.loads(frame.decode("ascii"))
        _validate_envelope(envelope, session_id=session_id, request_id=request_id)
        ensure_native_rdp_guard(client_id=client_id)
        yield envelope, reader
    except (OSError, UnicodeError, ValueError, asyncio.TimeoutError) as exc:
        raise AutologinUnavailable("RDP_LIFECYCLE_UNAVAILABLE") from exc
    finally:
        if writer is not None:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), timeout=2)
            except (OSError, asyncio.TimeoutError):
                pass
