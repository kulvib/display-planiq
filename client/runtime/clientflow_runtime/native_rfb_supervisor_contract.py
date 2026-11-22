"""63D-43: inert root-supervisor *contract*, NOT an installed daemon.

Models the on-demand RFB lease, generation, ownership, absolute expiry,
socket-inode readiness and revocation. Does not start/kill a process, install
RFB packages, write secrets, create sockets or change systemd/GNOME.
Real activation is blocked by THREE independent source constants. A real
root service with crash/reboot/watchdog cleanup must be separately reviewed.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path

from . import native_rfb_local_gate as gate

# Only a future, separately audited source change may change these constants.
CVE_CLEARANCE_APPROVED = False
ROOT_CLEANUP_WATCHDOG_APPROVED = False
PHYSICAL_CLIENT_ACTIVATION_APPROVED = False

MAX_LEASE_SECONDS = 360
MAX_STARTUP_SECONDS = 15


class NativeRfbSupervisorDenied(ValueError):
    """Deliberately contains no credential, socket path or pixel bytes."""


@dataclass(frozen=True)
class Lease:
    client_id: int
    session_id: str
    stream_id: str
    owner_uid: int
    issued_at: float
    deadline: float
    startup_deadline: float
    socket_path: Path


def _time(value: object) -> float:
    if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
        raise NativeRfbSupervisorDenied("invalid monotonic lease timestamp")
    return float(value)


def approvals_present() -> bool:
    return (
        gate.PRODUCER_APPROVED is True
        and CVE_CLEARANCE_APPROVED is True
        and ROOT_CLEANUP_WATCHDOG_APPROVED is True
        and PHYSICAL_CLIENT_ACTIVATION_APPROVED is True
    )


class SupervisorContract:
    """A single-client, single-generation state machine; no OS side effects."""

    def __init__(self) -> None:
        self.lease: Lease | None = None
        self.mode = "idle"
        self._original_socket: gate.VerifiedSocket | None = None
        self.closed_reason: str | None = None

    def request(
        self, *,
        client_id: int,
        owner_uid: int,
        session_id: str,
        stream_id: str,
        now: float,
        requested_seconds: int,
    ) -> Lease:
        if self.mode != "idle" or self.lease is not None:
            raise NativeRfbSupervisorDenied("supervisor generation already used")
        if not approvals_present():
            raise NativeRfbSupervisorDenied("RFB source security gates not approved")
        if (
            type(client_id) is not int or client_id < 1
            or type(owner_uid) is not int or owner_uid <= 0
            or type(requested_seconds) is not int
            or not 1 <= requested_seconds <= MAX_LEASE_SECONDS
        ):
            raise NativeRfbSupervisorDenied("untrusted RFB lease parameters")
        session_id = gate.canonical_session_id(session_id)
        stream_id = gate.canonical_session_id(stream_id)
        if session_id == stream_id:
            raise NativeRfbSupervisorDenied("RFB session and stream generation overlap")
        started = _time(now)
        self.lease = Lease(
            client_id, session_id, stream_id, owner_uid, started,
            started + requested_seconds,
            started + min(MAX_STARTUP_SECONDS, requested_seconds),
            gate.socket_path(session_id),
        )
        self.mode = "awaiting_socket"
        return self.lease

    def _require_time(self, now: float) -> Lease:
        lease = self.lease
        if lease is None or self.mode not in {"awaiting_socket", "active"}:
            raise NativeRfbSupervisorDenied("RFB lease not active")
        instant = _time(now)
        if instant < lease.issued_at or instant >= lease.deadline:
            self.stop("absolute_lease_expired")
            raise NativeRfbSupervisorDenied("RFB lease expired")
        if self.mode == "awaiting_socket" and instant >= lease.startup_deadline:
            self.stop("startup_timeout")
            raise NativeRfbSupervisorDenied("RFB socket not ready before startup deadline")
        return lease

    def socket_ready(self, verified: gate.VerifiedSocket, *, now: float) -> None:
        lease = self._require_time(now)
        if self.mode != "awaiting_socket" or self._original_socket is not None:
            self.stop("duplicate_socket_ready")
            raise NativeRfbSupervisorDenied("RFB socket readiness repeated")
        if (
            type(verified) is not gate.VerifiedSocket
            or verified.path != lease.socket_path
            or verified.owner_uid != lease.owner_uid
            or verified.socket_inode <= 0
            or verified.directory_inode <= 0
            or verified.socket_device != verified.directory_device
        ):
            self.stop("socket_identity_rejected")
            raise NativeRfbSupervisorDenied("RFB private socket generation mismatch")
        self._original_socket = verified
        self.mode = "active"

    def authorise_stream(
        self, *,
        session_id: str,
        stream_id: str,
        client_id: int,
        owner_uid: int,
        now: float,
        current_socket: gate.VerifiedSocket,
    ) -> None:
        lease = self._require_time(now)
        if (
            self.mode != "active"
            or session_id != lease.session_id
            or stream_id != lease.stream_id
            or type(client_id) is not int or client_id != lease.client_id
            or type(owner_uid) is not int or owner_uid != lease.owner_uid
            or type(current_socket) is not gate.VerifiedSocket
            or current_socket != self._original_socket
        ):
            self.stop("session_or_socket_revoked")
            raise NativeRfbSupervisorDenied("RFB browser, owner or socket generation changed")
        if not approvals_present():
            self.stop("source_approval_revoked")
            raise NativeRfbSupervisorDenied("RFB source approval revoked")

    def tick(self, *, now: float, owner_still_authorised: bool) -> bool:
        """False => a REAL supervisor MUST kill children and restore GNOME.

        This pure contract cannot perform or assert cleanup itself.
        """
        if type(owner_still_authorised) is not bool or not owner_still_authorised:
            self.stop("owner_revoked")
            return False
        try:
            self._require_time(now)
        except NativeRfbSupervisorDenied:
            return False
        if not approvals_present():
            self.stop("source_approval_revoked")
            return False
        return True

    def stop(self, reason: str = "explicit_stop") -> None:
        self.mode = "closed"
        self._original_socket = None
        self.closed_reason = reason
        # Clear all lease identity, preventing revival/credential reuse.
        self.lease = None
