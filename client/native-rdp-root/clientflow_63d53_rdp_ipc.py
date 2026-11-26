"""Canonical socket adapters for a bounded, authenticated local RDP session."""
from __future__ import annotations

import json
import os
import pwd
import socket
import struct
import time
import uuid

from . import clientflow_63d49_autologin_broker as broker
from . import clientflow_63d53_rdp_lifecycle as lifecycle
from . import clientflow_63d53_rdp_proof as proof

SEAL_SOCKET = "/run/clientflow/rdp-sealer-v1.sock"
MAX_REQUEST = 1024
MAX_REPLY = 2048


class IpcDenied(RuntimeError):
    pass


def peer_uid(conn):
    return struct.unpack("3i", conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]


def read_frame(conn, limit, timeout=5):
    deadline = time.monotonic() + timeout
    frame = bytearray()
    while len(frame) <= limit:
        left = deadline - time.monotonic()
        if left <= 0:
            raise IpcDenied("FRAME_TIMEOUT")
        conn.settimeout(left)
        part = conn.recv(min(512, limit + 1 - len(frame)))
        if not part:
            raise IpcDenied("FRAME_TRUNCATED")
        frame.extend(part)
        if b"\n" in frame:
            if len(frame) > limit or frame.count(b"\n") != 1 or not frame.endswith(b"\n"):
                raise IpcDenied("FRAME_INVALID")
            obj = json.loads(frame.decode("ascii"))
            if type(obj) is not dict:
                raise IpcDenied("FRAME_INVALID")
            return obj
    raise IpcDenied("FRAME_TOO_LARGE")


def send_frame(conn, payload, limit):
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("ascii") + b"\n"
    if len(data) > limit:
        raise IpcDenied("FRAME_TOO_LARGE")
    conn.settimeout(3)
    conn.sendall(data)


def validate_request(request):
    from cryptography.hazmat.primitives.asymmetric import ec

    if (type(request) is not dict or set(request) != {"schema", "session_id", "request_id", "public_key"}
            or type(request["schema"]) is not int or request["schema"] != 1):
        raise IpcDenied("REQUEST_INVALID")
    session = proof.canonical_session(request["session_id"])
    challenge = proof.canonical_session(request["request_id"])
    if uuid.UUID(session).version != 4 or uuid.UUID(challenge).version != 4:
        raise IpcDenied("REQUEST_INVALID")
    point = broker._unb64(request["public_key"], 65)
    if point[0] != 4:
        raise IpcDenied("PUBLIC_KEY_INVALID")
    ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), point)
    return session


def require_open(conn):
    previous = conn.gettimeout()
    try:
        conn.setblocking(False)
        try:
            value = conn.recv(1, socket.MSG_PEEK)
        except BlockingIOError:
            return
        raise IpcDenied("AGENT_CLOSED" if not value else "UNEXPECTED_AGENT_DATA")
    finally:
        conn.settimeout(previous)


def request_seal(request):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(4)
        conn.connect(SEAL_SOCKET)
        if peer_uid(conn) != 0:
            raise IpcDenied("SEALER_UNTRUSTED")
        send_frame(conn, request, MAX_REQUEST)
        result = read_frame(conn, MAX_REPLY)
        if (result.get("session_id") != request["session_id"]
                or result.get("request_id") != request["request_id"]
                or set(result) != {"schema", "session_id", "request_id", "public_key",
                                   "salt", "nonce", "ciphertext", "expires_unix"}):
            raise IpcDenied("SEALED_REPLY_INVALID")
        return result


def validate_renewal(message, request, previous):
    if (set(message) != {"type", "session_id", "request_id", "sequence"}
            or message["type"] != "renew"
            or message["session_id"] != request["session_id"]
            or message["request_id"] != request["request_id"]
            or type(message["sequence"]) is not int
            or message["sequence"] != previous + 1):
        raise IpcDenied("INVALID_RENEWAL")
    return message["sequence"]


def serve_lifecycle(conn):
    if peer_uid(conn) != pwd.getpwnam(broker.AGENT_USER).pw_uid:
        raise IpcDenied("UNAUTHORIZED_AGENT")
    request = read_frame(conn, MAX_REQUEST)
    session = validate_request(request)
    require_open(conn)

    class PeerBoundOperations(lifecycle.PhysicalOperations):
        def stage(self):
            require_open(conn)
            super().stage()

        def start(self):
            require_open(conn)
            super().start()

        def arm(self):
            require_open(conn)
            return super().arm()

        def publish(self, session_id, fingerprint):
            require_open(conn)
            super().publish(session_id, fingerprint)

    ops = PeerBoundOperations()

    def hold():
        require_open(conn)
        packet = request_seal(request)
        require_open(conn)
        send_frame(conn, {"envelope": packet, "lease_protocol": 2}, MAX_REPLY)
        sequence = 0
        while True:
            grant = proof.root_json(proof.APPROVAL, 0o644)
            left = proof.remaining(grant.get("expires_wall"), grant.get("expires_mono"))
            if not 0 < left <= 360:
                return
            conn.settimeout(min(1, left))
            try:
                data = conn.recv(1, socket.MSG_PEEK)
            except TimeoutError:
                continue
            if not data:
                return
            renewal = read_frame(conn, MAX_REQUEST, timeout=3)
            sequence = validate_renewal(renewal, request, sequence)
            # A failed or busy physical validation never extends the lease.
            try:
                ops.renew(session)
            except lifecycle.LifecycleDenied as exc:
                if str(exc) not in {"WATCHDOG_BUSY", "PHYSICAL_STATUS_FAILED"}:
                    raise

    lifecycle.run_owned_session(session, hold, operations=ops)


def serve_sealer(conn):
    if peer_uid(conn) != 0:
        raise IpcDenied("UNAUTHORIZED_LIFECYCLE")
    request = read_frame(conn, MAX_REQUEST)
    validate_request(request)
    # No fallback to the legacy privileged probe.
    packet = broker._seal(request, authorize=proof.authorize)
    send_frame(conn, packet, MAX_REPLY)


def _main(handler):
    try:
        if os.geteuid() != 0:
            raise IpcDenied("ROOT_REQUIRED")
        with socket.fromfd(0, socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            handler(conn)
    except (RuntimeError, OSError, ValueError, TypeError, KeyError, ImportError):
        raise SystemExit("RDP_LOCAL_SESSION_STOP") from None


def lifecycle_main():
    _main(serve_lifecycle)


def sealer_main():
    _main(serve_sealer)
