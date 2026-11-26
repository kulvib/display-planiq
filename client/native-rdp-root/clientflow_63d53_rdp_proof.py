"""63D-53: short-lived root-owned, session-specific physical RDP attestation.

The credential sealer consumes this proof without running systemctl, nftables,
or switching to the kiosk UID. The privileged lifecycle owner creates it only
after the existing GNOME watchdog, firewall and certificate checks succeed.
Canonical release helper; backend session authorization remains separate.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import socket
import stat
import time
import uuid

PROOF = Path("/run/clientflow/rdp-session-proof-v1.json")
BOOT = Path("/proc/sys/kernel/random/boot_id")
APPROVAL = Path("/run/clientflow/native-rdp-approved")
STATE = Path("/var/lib/clientflow/rdp-pilot-63d30/state.json")
from . import clientflow_63d29_persistent_rdp_guard as guard

# Set only by the verified immutable release entrypoint.
EXPECTED_CLIENT_ID: int | None = None
MAX_PROOF_SECONDS = 30
FIELDS = {"schema", "client_id", "boot_id", "session_id", "pid",
          "process_start", "expires_wall", "expires_mono", "fingerprint"}


class ProofDenied(RuntimeError):
    pass


def canonical_session(value: str) -> str:
    try:
        if not isinstance(value, str) or str(uuid.UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError, TypeError):
        raise ProofDenied("INVALID_SESSION") from None
    return value


def root_json(path: Path, mode: int) -> dict:
    """Bounded, non-symlink read with ownership checked on the opened inode."""
    try:
        parent = path.parent.lstat()
        if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0 or parent.st_mode & 0o022:
            raise ProofDenied("UNSAFE_PROOF_DIRECTORY")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            meta = os.fstat(stream.fileno())
            if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != 0
                    or stat.S_IMODE(meta.st_mode) != mode or not 0 < meta.st_size <= 2048):
                raise ProofDenied("UNSAFE_PROOF_FILE")
            raw = stream.read(2049)
        if len(raw) > 2048:
            raise ProofDenied("OVERSIZED_PROOF")
        data = json.loads(raw)
        if type(data) is not dict:
            raise ProofDenied("INVALID_PROOF_SHAPE")
        return data
    except (OSError, ValueError, UnicodeError) as exc:
        raise ProofDenied("PROOF_UNAVAILABLE") from exc


def process_start(pid: int) -> str:
    if type(pid) is not int or pid <= 1:
        raise ProofDenied("INVALID_LIFECYCLE_OWNER")
    try:
        # /proc/PID/stat comm can contain spaces and closing parentheses.
        record = Path(f"/proc/{pid}/stat").read_text()
        fields = record.rsplit(")", 1)[1].split()
        if fields[0] in {"Z", "X", "x"}:
            raise ProofDenied("LIFECYCLE_OWNER_EXITED")
        return fields[19]
    except (OSError, IndexError) as exc:
        raise ProofDenied("LIFECYCLE_OWNER_EXITED") from exc


def remaining(wall, mono) -> float:
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in (wall, mono)):
        raise ProofDenied("INVALID_DEADLINE")
    return min(wall - time.time(), mono - time.monotonic())


def bound_client_id() -> int:
    client_id = guard.local_client_id()
    if type(EXPECTED_CLIENT_ID) is not int or client_id != EXPECTED_CLIENT_ID:
        raise ProofDenied("INSTALLED_CLIENT_BINDING_CHANGED")
    return client_id


def authorize(session_id: str) -> tuple[int, str]:
    """Return an envelope deadline and public fingerprint, never credentials."""
    canonical_session(session_id)
    client_id = bound_client_id()
    proof = root_json(PROOF, 0o600)
    grant = root_json(APPROVAL, 0o644)
    state = root_json(STATE, 0o600)
    boot = BOOT.read_text().strip()
    if (set(proof) != FIELDS or type(proof["schema"]) is not int or proof["schema"] != 1
            or type(proof["client_id"]) is not int or proof["client_id"] != client_id
            or proof["session_id"] != session_id or proof["boot_id"] != boot
            or grant.get("boot_id") != boot or type(grant.get("client_id")) is not int
            or grant["client_id"] != client_id
            or grant.get("hostname") != socket.gethostname() or grant.get("schema") != 1
            or state.get("boot_id") != boot or state.get("phase") != "63D-30"
            or type(state.get("client_id")) is not int or state["client_id"] != client_id
            or state.get("hostname") != socket.gethostname()
            or proof["process_start"] != process_start(proof["pid"])
            or not isinstance(proof["fingerprint"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", proof["fingerprint"])):
        raise ProofDenied("PROOF_BINDING_INVALID")
    left = remaining(proof["expires_wall"], proof["expires_mono"])
    if not 0 < left <= MAX_PROOF_SECONDS:
        raise ProofDenied("PROOF_EXPIRED")
    for record, wall, mono in ((grant, "expires_wall", "expires_mono"),
                               (state, "deadline_wall", "deadline_mono")):
        physical = remaining(record.get(wall), record.get(mono))
        if not 0 < physical <= 360:
            raise ProofDenied("PHYSICAL_LEASE_EXPIRED")
        left = min(left, physical)
    expires = int(time.time() + left)
    if expires <= int(time.time()):
        raise ProofDenied("PROOF_EXPIRED")
    return expires, proof["fingerprint"]
