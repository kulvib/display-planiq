"""63D-53 source-only, single-owner GNOME RDP lifecycle for physical Viborg1.

This controller wraps the fixed SHA-pinned 63D-29/30 physical implementation.
It does not replace its independent firewall or watchdog. Never install or
enable this experimental controller without the packaging and physical gate.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import time

from . import clientflow_63d53_rdp_proof as proof

SOURCE = Path("/usr/local/libexec/clientflow/native-rdp-pilot/scripts")
STAGE = Path("/var/lib/clientflow/rdp-pilot-bundle-63d30")
LOCK = Path("/run/clientflow/rdp-lifecycle-v1.lock")
IDENTITY = Path("/etc/clientflow/identity.json")
RUNNER = "clientflow_63d30_local_rdp_pilot.py"
GUARD = "clientflow_63d29_persistent_rdp_guard.py"
BROWSER = "clientflow_native_rdp_browser_pilot.py"
PINNED = {
    RUNNER: "78972f7c7173a4894abc22d4518b1fc4d3189c76e30dd463715af03ef069af69",
    GUARD: "709a5d9b1eba3364dfd2ac21f4e24525b0dc3261236456a9127aac7cfd54c000",
    BROWSER: "02c63fc10deb3c0329c5309bdcb19a0edf8fa694c1c0045257cd79c304849e7f",
}


class LifecycleDenied(RuntimeError):
    pass


def safe_directory(path: Path) -> None:
    meta = path.lstat()
    if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != 0 or meta.st_mode & 0o022:
        raise LifecycleDenied("UNTRUSTED_LIFECYCLE_DIRECTORY")


def verified_source(directory: Path, name: str) -> Path:
    safe_directory(directory)
    path = directory / name
    meta = path.lstat()
    if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != 0 or meta.st_mode & 0o022
            or not 0 < meta.st_size <= 128 * 1024
            or hashlib.sha256(path.read_bytes()).hexdigest() != PINNED[name]):
        raise LifecycleDenied("UNTRUSTED_PINNED_SOURCE")
    return path


def present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


class PhysicalOperations:
    """Fixed commands only; no browser-controlled command, path or argument."""

    def preflight(self) -> None:
        if os.geteuid() != 0 or socket.gethostname() != proof.HOST:
            raise LifecycleDenied("WRONG_PHYSICAL_TARGET")
        identity = IDENTITY.lstat()
        if (not stat.S_ISREG(identity.st_mode) or identity.st_uid != 0
                or identity.st_mode & 0o022 or not 0 < identity.st_size <= 2048):
            raise LifecycleDenied("UNTRUSTED_CLIENT_IDENTITY")
        data = json.loads(IDENTITY.read_text())
        if str(data.get("CLIENT_ID", data.get("client_id"))) != "3":
            raise LifecycleDenied("WRONG_CLIENT_ID")
        safe_directory(proof.PROOF.parent)
        for name in PINNED:
            verified_source(SOURCE, name)
        # Never adopt, overwrite or stop a pre-existing operator session.
        if any(present(p) for p in (STAGE, proof.STATE.parent, proof.APPROVAL, proof.PROOF)):
            raise LifecycleDenied("PREEXISTING_RDP_STATE")

    def run(self, name: str, action: str, *, staged: bool = False) -> str:
        allowed = {RUNNER: {"stage", "start", "stop", "unstage"},
                   BROWSER: {"arm", "disarm"}}
        if action not in allowed.get(name, set()) or (staged and name != RUNNER):
            raise LifecycleDenied("UNSUPPORTED_LIFECYCLE_ACTION")
        directory = STAGE if staged else SOURCE
        verified_source(directory, GUARD)
        verified_source(directory, RUNNER)
        source = verified_source(directory, name)
        bootstrap = (
            "import sys,runpy; p=sys.argv[1]; "
            "sys.path.insert(0,p.rsplit('/',1)[0]); "
            "sys.argv=[p,sys.argv[2]]; runpy.run_path(p,run_name='__main__')"
        )
        # The privileged subprocess uses only the checked root-owned directory.
        result = subprocess.run(
            ["/usr/bin/python3", "-I", "-B", "-c", bootstrap, str(source), action],
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
            capture_output=True, text=True, timeout=110, check=False,
        )
        if result.returncode:
            raise LifecycleDenied("PHYSICAL_" + action.upper() + "_FAILED")
        # Raw output may contain local diagnostics; do not relay it to a user.
        return result.stdout

    def stage(self) -> None:
        if "WATCHDOG_STAGED=True" not in self.run(RUNNER, "stage").splitlines():
            raise LifecycleDenied("WATCHDOG_NOT_ATTESTED")

    def start(self) -> None:
        if "RDP_EXISTING_SESSION_PILOT_ACTIVE=True" not in self.run(
                RUNNER, "start", staged=True).splitlines():
            raise LifecycleDenied("GNOME_NOT_ATTESTED")

    def arm(self) -> str:
        lines = self.run(BROWSER, "arm").splitlines()
        matches = [line.removeprefix("GNOME_TLS_SHA256=") for line in lines
                   if line.startswith("GNOME_TLS_SHA256=")]
        if ("NATIVE_RDP_BROWSER_GRANT=ARMED" not in lines or len(matches) != 1
                or not re.fullmatch(r"(?:[0-9A-F]{2}:){31}[0-9A-F]{2}", matches[0])):
            raise LifecycleDenied("BROWSER_GRANT_NOT_ATTESTED")
        return matches[0].replace(":", "").lower()

    def publish(self, session_id: str, fingerprint: str) -> None:
        grant = proof.root_json(proof.APPROVAL, 0o644)
        boot = proof.BOOT.read_text().strip()
        if (grant.get("client_id") != 3 or grant.get("boot_id") != boot
                or grant.get("hostname") != proof.HOST):
            raise LifecycleDenied("WRONG_PHYSICAL_GRANT")
        left = proof.remaining(grant.get("expires_wall"), grant.get("expires_mono"))
        if not 5 < left <= 360:
            raise LifecycleDenied("PHYSICAL_GRANT_EXPIRED")
        left = min(left, proof.MAX_PROOF_SECONDS)
        packet = {
            "schema": 1, "client_id": 3, "boot_id": boot,
            "session_id": session_id, "pid": os.getpid(),
            "process_start": proof.process_start(os.getpid()),
            "expires_wall": time.time() + left,
            "expires_mono": time.monotonic() + left,
            "fingerprint": fingerprint,
        }
        fd = os.open(proof.PROOF, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(packet, stream, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        proof.authorize(session_id)

    def revoke(self) -> None:
        # This path was absent at preflight and reserved by our exclusive lock.
        if present(proof.PROOF):
            meta = proof.PROOF.lstat()
            if not stat.S_ISREG(meta.st_mode) or meta.st_uid != 0:
                raise LifecycleDenied("UNKNOWN_PROOF_STATE")
            proof.PROOF.unlink()
        if present(proof.APPROVAL):
            self.run(BROWSER, "disarm")

    def stop(self) -> None:
        if present(proof.STATE):
            output = self.run(RUNNER, "stop", staged=True).splitlines()
            if not {"RDP_STOPPED_AND_VERIFIED=True", "RDP_CREDENTIALS_AND_TLS_REMOVED=True",
                    "ROOT_WATCHDOG_AND_STAGED_CODE_REMOVED=True"}.issubset(output):
                raise LifecycleDenied("GNOME_CLEANUP_NOT_ATTESTED")
        elif present(STAGE):
            output = self.run(RUNNER, "unstage", staged=True).splitlines()
            if "ROOT_WATCHDOG_AND_STAGED_CODE_REMOVED=True" not in output:
                raise LifecycleDenied("WATCHDOG_CLEANUP_NOT_ATTESTED")
        if any(present(p) for p in (STAGE, proof.STATE.parent, proof.APPROVAL, proof.PROOF)):
            raise LifecycleDenied("LOCAL_RDP_CLEANUP_INCOMPLETE")


def run_owned_session(session_id: str, hold, *, operations=None) -> None:
    """Hold the exclusive physical lease only while the authorized owner lives.

    The caller must tie hold() to the authenticated agent socket and never
    extend the independent six-minute physical watchdog. Failure in cleanup
    propagates; never remove the independent firewall or watchdog ourselves.
    """
    proof.canonical_session(session_id)
    ops = operations if operations is not None else PhysicalOperations()
    safe_directory(LOCK.parent)
    fd = os.open(LOCK, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+b") as lock:
        meta = os.fstat(lock.fileno())
        if not stat.S_ISREG(meta.st_mode) or meta.st_uid != 0 or stat.S_IMODE(meta.st_mode) != 0o600:
            raise LifecycleDenied("UNTRUSTED_LIFECYCLE_LOCK")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise LifecycleDenied("RDP_LIFECYCLE_BUSY") from None
        ops.preflight()
        try:
            ops.stage()
            ops.start()
            fingerprint = ops.arm()
            ops.publish(session_id, fingerprint)
            hold()
        finally:
            # Even if revoking the grant fails, attempt GNOME-first cleanup.
            try:
                ops.revoke()
            finally:
                ops.stop()
