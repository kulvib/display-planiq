"""63D-37: local native-RFB Unix socket policy; deliberately NOT activated.

This security boundary does not start or install GNOME, FreeRDP, Xvfb or a
VNC server. No environment switch bypasses the unresolved Ubuntu package CVE
gate. Only a separately audited source change may authorise runtime usage.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat
import uuid


RUNTIME_ROOT = Path("/run/clientflow/native-rfb")
# Both x11vnc and TigerVNC scraping server have unresolved Ubuntu 26.04
# security review. Never activate merely because an executable is installed.
PRODUCER_APPROVED = False
MAX_LEASE_SECONDS = 360
SOCKET_MODE = 0o600
DIRECTORY_MODE = 0o700
_SESSION_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


class NativeRfbLocalGateError(RuntimeError):
    """Fail-closed local preflight; never include secrets or paths in errors."""


def canonical_session_id(value: object) -> str:
    if type(value) is not str or _SESSION_RE.fullmatch(value) is None:
        raise NativeRfbLocalGateError("invalid RFB session generation")
    try:
        if str(uuid.UUID(value)) != value:
            raise NativeRfbLocalGateError("noncanonical RFB session generation")
    except ValueError as exc:
        raise NativeRfbLocalGateError("invalid RFB session generation") from exc
    return value


def socket_path(session_id: str, *, runtime_root: Path = RUNTIME_ROOT) -> Path:
    canonical_session_id(session_id)
    if not runtime_root.is_absolute() or ".." in runtime_root.parts:
        raise NativeRfbLocalGateError("untrusted RFB runtime root")
    return runtime_root / ("rfb-" + session_id + ".sock")


@dataclass(frozen=True)
class VerifiedSocket:
    path: Path
    directory_device: int
    directory_inode: int
    directory_mtime_ns: int
    socket_device: int
    socket_inode: int
    socket_ctime_ns: int
    owner_uid: int


def _verified_lstat(path: Path, *, expected_uid: int, directory: bool) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise NativeRfbLocalGateError("RFB path missing or unreadable") from exc
    kind_ok = stat.S_ISDIR(metadata.st_mode) if directory else stat.S_ISSOCK(metadata.st_mode)
    expected_mode = DIRECTORY_MODE if directory else SOCKET_MODE
    if (
        not kind_ok or metadata.st_uid != expected_uid or
        stat.S_IMODE(metadata.st_mode) != expected_mode
    ):
        raise NativeRfbLocalGateError("RFB inode ownership or mode violation")
    return metadata


def inspect_socket(
    session_id: str, *, runtime_root: Path = RUNTIME_ROOT,
    expected_uid: int | None = None,
) -> VerifiedSocket:
    """Read-only inspection; never connect or trust a symlink.

    The whole runtime directory must be owned by the *agent* user and private
    mode 0700, the RFB Unix socket 0600. The root of this path is fixed in the
    deployed app. Tests may supply a temp root to validate negative cases.
    """
    uid = os.geteuid() if expected_uid is None else expected_uid
    if type(uid) is not int or uid <= 0 or os.geteuid() != uid:
        raise NativeRfbLocalGateError("RFB agent privilege boundary mismatch")
    path = socket_path(session_id, runtime_root=runtime_root)
    directory = _verified_lstat(runtime_root, expected_uid=uid, directory=True)
    sock = _verified_lstat(path, expected_uid=uid, directory=False)
    if directory.st_dev != sock.st_dev:
        raise NativeRfbLocalGateError("RFB socket on unexpected device")
    return VerifiedSocket(
        path=path,
        directory_device=directory.st_dev,
        directory_inode=directory.st_ino,
        directory_mtime_ns=directory.st_mtime_ns,
        socket_device=sock.st_dev,
        socket_inode=sock.st_ino,
        socket_ctime_ns=sock.st_ctime_ns,
        owner_uid=uid,
    )


def revalidate_socket(verified: VerifiedSocket) -> None:
    """Detect path replacement between authorization and Unix connection."""
    current = inspect_socket(
        verified.path.name[len("rfb-"):-len(".sock")],
        runtime_root=verified.path.parent,
        expected_uid=verified.owner_uid,
    )
    if current != verified:
        raise NativeRfbLocalGateError("RFB socket generation replaced")


def ensure_source_approved() -> None:
    if not PRODUCER_APPROVED:
        raise NativeRfbLocalGateError(
            "RFB producer is blocked by pending Ubuntu security acceptance"
        )


async def open_approved_socket(
    session_id: str,
    *,
    runtime_root: Path = RUNTIME_ROOT,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Bounded AF_UNIX connection; both original inodes held open by O_PATH.

    A closed/unlinked AF_UNIX inode may be reused immediately by Linux.
    Path-only stat comparisons therefore do NOT prove identity. Holding
    O_PATH descriptors to the original socket and O_DIRECTORY descriptor to
    the original private directory prevents inode reuse until validation
    completes; any replacement on connect is detected and closed.
    """
    ensure_source_approved()
    verified = inspect_socket(session_id, runtime_root=runtime_root)
    try:
        dir_fd = os.open(
            runtime_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
    except OSError as exc:
        raise NativeRfbLocalGateError("RFB private directory changed") from exc
    try:
        try:
            sock_fd = os.open(
                verified.path, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
        except OSError as exc:
            raise NativeRfbLocalGateError("RFB socket changed before connect") from exc
        try:
            original_dir = os.fstat(dir_fd)
            original_sock = os.fstat(sock_fd)
            if (
                original_dir.st_ino != verified.directory_inode or
                original_dir.st_dev != verified.directory_device or
                original_sock.st_ino != verified.socket_inode or
                original_sock.st_dev != verified.socket_device or
                not stat.S_ISSOCK(original_sock.st_mode) or
                original_sock.st_uid != verified.owner_uid or
                stat.S_IMODE(original_sock.st_mode) != SOCKET_MODE
            ):
                raise NativeRfbLocalGateError("RFB socket generation changed")
            revalidate_socket(verified)
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_unix_connection(path=str(verified.path)),
                    timeout=2.0,
                )
            except (OSError, asyncio.TimeoutError) as exc:
                raise NativeRfbLocalGateError("RFB Unix socket not ready") from exc
            try:
                revalidate_socket(verified)
                return reader, writer
            except Exception:
                writer.close()
                try:
                    await asyncio.wait_for(writer.wait_closed(), timeout=2.0)
                except (OSError, asyncio.TimeoutError):
                    pass
                raise
        finally:
            os.close(sock_fd)
    finally:
        os.close(dir_fd)
