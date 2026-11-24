#!/usr/bin/env python3
"""Root-only GNOME RDP credential sealer for ClientFlow pilot 63D-49.

The dedicated remote-desktop-agent UID is the only AF_UNIX peer. The helper
only serves inside the already-authorized GNOME six-minute pilot. The result
is ECDH P-256 + HKDF-SHA256 + AES-256-GCM sealed to a one-time browser key.
Render and the unprivileged client agent relay ciphertext, not passwords.

Pilot source only: not installed, not started by production or main release.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import socket
import ssl
import stat
import struct
import subprocess
import time
import uuid

HOST = "viborg1-NUC14MNK-B2"
AGENT_USER = "clientflow-remote-desktop-agent"
SOCKET_PATH = Path("/run/clientflow/rdp-autologin-v1.sock")
APPROVAL = Path("/run/clientflow/native-rdp-approved")
STATE = Path("/var/lib/clientflow/rdp-pilot-63d30/state.json")
CREDENTIALS = Path("/run/clientflow-rdp-63d30/credentials")
BOOT_ID = Path("/proc/sys/kernel/random/boot_id")
GNOME_RUNNER = Path("/var/lib/clientflow/rdp-pilot-bundle-63d30/clientflow_63d30_local_rdp_pilot.py")
GNOME_RUNNER_SHA256 = "78972f7c7173a4894abc22d4518b1fc4d3189c76e30dd463715af03ef069af69"
MAGIC = "planiq-clientflow-rdp-v1"
MAX_REQUEST = 1024


class BrokerDenied(RuntimeError):
    pass


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(raw: str, expected: int) -> bytes:
    if not isinstance(raw, str) or not 1 <= len(raw) <= 200 or not re.fullmatch(r"[A-Za-z0-9_-]+", raw):
        raise BrokerDenied("INVALID_PUBLIC_KEY_ENCODING")
    try:
        value = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except (ValueError, base64.binascii.Error) as exc:
        raise BrokerDenied("INVALID_PUBLIC_KEY_ENCODING") from exc
    if len(value) != expected or _b64(value) != raw:
        raise BrokerDenied("INVALID_PUBLIC_KEY_LENGTH")
    return value


def _root_private(path: Path, *, max_size: int) -> bytes:
    try:
        meta = path.lstat()
        if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != 0 or
                stat.S_IMODE(meta.st_mode) != 0o600 or not 1 <= meta.st_size <= max_size):
            raise BrokerDenied("UNSAFE_PRIVATE_PILOT_FILE")
        with path.open("rb") as file:
            data = file.read(max_size + 1)
        if len(data) > max_size:
            raise BrokerDenied("OVERSIZED_PRIVATE_PILOT_FILE")
        return data
    except OSError as exc:
        raise BrokerDenied("MISSING_PRIVATE_PILOT_FILE") from exc


def _safe_grant() -> int:
    if os.geteuid() != 0 or socket.gethostname() != HOST:
        raise BrokerDenied("WRONG_MACHINE_OR_PRIVILEGE")
    try:
        identity_path = Path("/etc/clientflow/identity.json")
        if identity_path.is_symlink():
            raise BrokerDenied("UNSAFE_CLIENT_IDENTITY")
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
        if str(identity.get("CLIENT_ID", identity.get("client_id"))) != "3":
            raise BrokerDenied("WRONG_CLIENT_ID")
        for file in (APPROVAL, STATE):
            m = file.lstat()
            if not stat.S_ISREG(m.st_mode) or m.st_uid != 0 or m.st_mode & 0o022 or m.st_size > 2048:
                raise BrokerDenied("UNSAFE_PILOT_STATE")
        grant = json.loads(APPROVAL.read_text("ascii"))
        state = json.loads(STATE.read_text("ascii"))
        boot = BOOT_ID.read_text().strip()
        if (grant.get("schema") != 1 or grant.get("client_id") != 3 or
                grant.get("hostname") != HOST or grant.get("boot_id") != boot or
                state.get("boot_id") != boot or state.get("phase") != "63D-30"):
            raise BrokerDenied("INVALID_PILOT_BINDING")
        left = min(
            float(grant["expires_wall"]) - time.time(),
            float(grant["expires_mono"]) - time.monotonic(),
            float(state["deadline_wall"]) - time.time(),
            float(state["deadline_mono"]) - time.monotonic(),
        )
        if not (5 < left <= 360):
            raise BrokerDenied("RDP_PILOT_EXPIRED")
        # These are independently owned by the physical GNOME root watchdog.
        # Never serve merely because a stale JSON marker exists.
        from subprocess import run
        result = run(
            ["/usr/bin/systemctl", "is-active", "clientflow-63d30-rdp-watchdog.timer"],
            capture_output=True, text=True, timeout=3, check=False,
        )
        if result.returncode or result.stdout.strip() != "active":
            raise BrokerDenied("ROOT_WATCHDOG_MISSING")
        return int(time.time() + min(left, 60))
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        raise BrokerDenied("RDP_PILOT_NOT_VERIFIED") from exc


def _verify_physical_firewall() -> None:
    # Reuse independently audited root GNOME kernel guard. A stale JSON marker
    # (or timer alone) must never release GNOME RDP credentials.
    try:
        meta = GNOME_RUNNER.lstat()
        if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != 0 or meta.st_mode & 0o022
                or hashlib.sha256(GNOME_RUNNER.read_bytes()).hexdigest() != GNOME_RUNNER_SHA256):
            raise BrokerDenied("UNTRUSTED_PHYSICAL_GUARD_CODE")
        p = subprocess.run(
            ["/usr/bin/python3", "-I", "-B", str(GNOME_RUNNER), "status"],
            capture_output=True, text=True, timeout=10, check=False,
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BrokerDenied("PHYSICAL_FIREWALL_NOT_VERIFIED") from exc
    expected = (
        "PILOT_STATE_EXISTS= True",
        "GUARD_KERNEL_VERIFIED= True",
        "ROOT_WATCHDOG_VERIFIED= True",
        "GNOME_RDP_SETTING= true",
        "RDP_LISTENERS_3389_3398= [3389]",
        "PILOT_EXPIRED= False",
    )
    if p.returncode or any(line not in p.stdout for line in expected):
        raise BrokerDenied("PHYSICAL_FIREWALL_NOT_VERIFIED")


def _cert_path(uid: int) -> Path:
    return Path(f"/run/user/{uid}/clientflow-rdp-pilot-63d30/tls.crt")


def _seal(request: dict) -> dict:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives import hashes, serialization

    if type(request) is not dict or set(request) != {"schema", "session_id", "request_id", "public_key"}:
        raise BrokerDenied("BAD_REQUEST_SHAPE")
    if type(request["schema"]) is not int or request["schema"] != 1:
        raise BrokerDenied("BAD_REQUEST_VERSION")
    try:
        session = str(uuid.UUID(request["session_id"]))
        challenge = str(uuid.UUID(request["request_id"]))
    except (ValueError, TypeError, AttributeError) as exc:
        raise BrokerDenied("INVALID_REQUEST_BINDING") from exc
    if request["session_id"] != session or request["request_id"] != challenge:
        raise BrokerDenied("NONCANONICAL_REQUEST_BINDING")
    point = _unb64(request["public_key"], 65)
    if point[0] != 4:
        raise BrokerDenied("UNSUPPORTED_PUBLIC_KEY")
    try:
        peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), point)
    except ValueError as exc:
        raise BrokerDenied("INVALID_ECDH_PUBLIC_KEY") from exc

    expires = _safe_grant()
    _verify_physical_firewall()
    lines = _root_private(CREDENTIALS, max_size=512).decode("ascii").splitlines()
    if (len(lines) != 2 or not re.fullmatch(r"cfpilot[0-9a-f]{8}", lines[0]) or
            not re.fullmatch(r"[A-Za-z0-9_-]{40,80}", lines[1])):
        raise BrokerDenied("INVALID_GNOME_RDP_CREDENTIALS")
    uid = pwd.getpwnam("clientflow-kiosk").pw_uid
    cert = _cert_path(uid)
    if cert.is_symlink() or not cert.is_file() or cert.stat().st_size > 32768:
        raise BrokerDenied("UNSAFE_GNOME_CERTIFICATE")
    try:
        fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert.read_text("ascii"))).hexdigest()
    except (ValueError, OSError, UnicodeError) as exc:
        raise BrokerDenied("BAD_GNOME_CERTIFICATE") from exc

    own_key = ec.generate_private_key(ec.SECP256R1())
    shared = own_key.exchange(ec.ECDH(), peer)
    salt, iv = os.urandom(16), os.urandom(12)
    info = f"{MAGIC}|{session}|{challenge}".encode("ascii")
    aad = f"{MAGIC}|3|{session}|{challenge}".encode("ascii")
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info).derive(shared)
    plaintext = json.dumps({
        "username": lines[0], "password": lines[1], "fingerprint": fingerprint,
        "expires_unix": expires,
    }, separators=(",", ":")).encode("ascii")
    ciphertext = AESGCM(key).encrypt(iv, plaintext, aad)
    public = own_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return {
        "schema": 1, "session_id": session, "request_id": challenge,
        "public_key": _b64(public), "salt": _b64(salt), "nonce": _b64(iv),
        "ciphertext": _b64(ciphertext), "expires_unix": expires,
    }


def serve() -> None:
    _safe_grant()
    # Fail closed when audited crypto is absent from the privileged runtime.
    from cryptography.hazmat.primitives.asymmetric import ec  # noqa: F401
    agent = pwd.getpwnam(AGENT_USER)
    folder = SOCKET_PATH.parent
    meta = folder.lstat()
    if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != 0 or meta.st_mode & 0o022:
        raise BrokerDenied("UNSAFE_BROKER_DIRECTORY")
    if SOCKET_PATH.exists() or SOCKET_PATH.is_symlink():
        raise BrokerDenied("EXISTING_BROKER_SOCKET")

    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.settimeout(1.0)
    seen: set[str] = set()
    try:
        listener.bind(str(SOCKET_PATH))
        os.chown(SOCKET_PATH, 0, agent.pw_gid)
        os.chmod(SOCKET_PATH, 0o660)
        listener.listen(4)
        print("RDP_AUTOLOGIN_BROKER=READY", flush=True)
        while True:
            try:
                _safe_grant()
            except BrokerDenied:
                break
            try:
                conn, _ = listener.accept()
            except socket.timeout:
                continue
            with conn:
                conn.settimeout(3.0)
                try:
                    creds = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
                    _, uid, _ = struct.unpack("3i", creds)
                    if uid != agent.pw_uid:
                        raise BrokerDenied("UNAUTHORIZED_LOCAL_PEER")
                    frame = bytearray()
                    while not frame.endswith(b"\n") and len(frame) <= MAX_REQUEST:
                        piece = conn.recv(min(512, MAX_REQUEST + 1 - len(frame)))
                        if not piece:
                            break
                        frame.extend(piece)
                    if len(frame) > MAX_REQUEST or not frame.endswith(b"\n"):
                        raise BrokerDenied("INVALID_REQUEST_FRAME")
                    req = json.loads(bytes(frame).decode("ascii"))
                    binding = str(req.get("session_id", ""))
                    if binding in seen:
                        raise BrokerDenied("SESSION_ALREADY_ISSUED")
                    packet = _seal(req)
                    seen.add(binding)
                    conn.sendall(json.dumps(packet, separators=(",", ":")).encode("ascii") + b"\n")
                except (BrokerDenied, ValueError, TypeError, UnicodeError, OSError):
                    # Never echo contents, passwords or socket requests.
                    pass
    finally:
        listener.close()
        try:
            meta = SOCKET_PATH.lstat()
            if stat.S_ISSOCK(meta.st_mode) and meta.st_uid == 0:
                SOCKET_PATH.unlink()
        except FileNotFoundError:
            pass
        print("RDP_AUTOLOGIN_BROKER=STOPPED", flush=True)


if __name__ == "__main__":
    try:
        serve()
    except (BrokerDenied, OSError, ValueError, ImportError):
        print("RDP_AUTOLOGIN_BROKER=STOP", flush=True)
        raise SystemExit(2) from None
