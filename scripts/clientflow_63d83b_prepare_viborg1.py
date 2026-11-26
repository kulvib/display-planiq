#!/usr/bin/env python3
"""Explicit, one-time Viborg1 1248 -> 1250 preparation; never invoked by updater.

Run only after candidate build/approval and after closing Remote Desktop and
explicitly stopping Livestream. No download, no release activation, no reboot.
Use the known 83A rollback helpers; never delete foreign pilot files.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import tempfile

HOST = "viborg1-NUC14MNK-B2"
RELEASE = "clientflow-1.3.47-seq-1248"
ACTIVE = Path("/opt/clientflow/active")
RDP = Path("/run/clientflow-63d54-operator")
HLS = Path("/run/clientflow-63d77-hls")
RDP_SOURCE = Path("/usr/local/libexec/clientflow/native-rdp-pilot")
CONFIG = Path("/etc/clientflow/livestream.json")
BACKUP_DIR = Path("/var/lib/clientflow/63d83b-preparation")
BACKUP = BACKUP_DIR / "livestream-before.json"
COORD = Path("/var/lib/clientflow/install-coordinator")
RDP_PIN = "8e4b95a5545178afca66d5b65e13e2ad20433c7ce42ed6f2f79e29874fa19bd8"
HLS_ROLLBACK_PIN = "2baa2b32e42e2809a9b02e3c1adf22fc9572566c33e09cb13713148e1cbd4d5b"
HLS_ENTRY_PIN = "fe3305abeb5ecdeed4e55205377e2c284c279feb24a6d7e396857505b857b6c2"
HLS_UPLOADER_PIN = "70116003a27cbbeeccdb0ca736b1f9a62625ac55e7450f696b50445f03ff58fa"
AGENT = "clientflow-remote-desktop-agent.service"
PRODUCER = "clientflow-livestream-producer.service"
UPLOADER = "clientflow-livestream-uploader.service"
SERVICES = (AGENT, PRODUCER, UPLOADER)
TIMERS = ("clientflow-63d54-rollback.timer", "clientflow-63d77-hls-rollback.timer")
UNITS = ("clientflow-rdp-lifecycle.socket", "clientflow-rdp-sealer.socket",
         "clientflow-rdp-lifecycle@.service", "clientflow-rdp-sealer@.service")
SYSTEMD = Path("/run/systemd/system")
DROPINS = {
    AGENT: SYSTEMD / (AGENT + ".d/63d54-native-rdp.conf"),
    PRODUCER: SYSTEMD / (PRODUCER + ".d/63d77-hls.conf"),
    UPLOADER: SYSTEMD / (UPLOADER + ".d/63d77-hls.conf"),
}


def require(ok, code):
    if not ok:
        raise RuntimeError(code)


def present(path):
    return os.path.lexists(path)


def safe_dir(path, private=False):
    meta = path.lstat()
    require(stat.S_ISDIR(meta.st_mode) and meta.st_uid == 0
            and not meta.st_mode & (0o077 if private else 0o022), "UNSAFE_DIRECTORY")


def read_regular(path, *, private=False):
    safe_dir(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        meta = os.fstat(stream.fileno())
        require(stat.S_ISREG(meta.st_mode) and meta.st_uid == 0
                and not meta.st_mode & (0o077 if private else 0o022)
                and 0 < meta.st_size <= 2 * 1024 * 1024, "UNSAFE_FILE")
        return stream.read(), meta


def pinned(path, expected):
    require(hashlib.sha256(read_regular(path)[0]).hexdigest() == expected, "PILOT_SHA_MISMATCH")


def run(*args, timeout=40):
    result = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                            text=True, timeout=timeout, check=False)
    require(result.returncode == 0, "COMMAND_FAILED:" + Path(args[0]).name)
    return result.stdout.strip()


def prop(unit, key):
    return run("/usr/bin/systemctl", "show", unit, "--property=" + key, "--value")


def target():
    require(os.geteuid() == 0 and socket.gethostname() == HOST, "WRONG_HOST")
    identity = json.loads(read_regular(Path("/etc/clientflow/identity.json"))[0])
    require(str(identity.get("CLIENT_ID", identity.get("client_id"))) == "3", "WRONG_CLIENT")
    require(ACTIVE.resolve(strict=True).name == RELEASE, "WRONG_RELEASE")


def migrated_config(raw):
    value = json.loads(raw)
    require(isinstance(value, dict) and value.get("schema_version") == 1, "INVALID_CONFIG_SCHEMA")
    require(value.get("capture_backend", "wayland_mutter") == "wayland_mutter", "INVALID_CAPTURE_BACKEND")
    if type(value.get("segment_seconds")) is int and value["segment_seconds"] == 1 and value.get("continuous_wss") is False:
        return raw
    value["segment_seconds"] = 1
    value["continuous_wss"] = False
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def installation_guard():
    # Serialize with the existing coordinator without claiming a fictitious
    # update deployment or altering its durable operation binding.
    safe_dir(COORD.parent)
    COORD.mkdir(mode=0o700, exist_ok=True)
    safe_dir(COORD, private=True)
    fd = os.open(COORD / "coordinate.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        meta = os.fstat(fd)
        require(stat.S_ISREG(meta.st_mode) and meta.st_uid == 0
                and not meta.st_mode & 0o077, "UNSAFE_COORDINATOR_LOCK")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(not present(COORD / "state.json"), "INSTALLATION_IN_PROGRESS_OR_IN_DOUBT")
        yield
    finally:
        os.close(fd)


def state_stopped():
    base = Path("/var/lib/clientflow/livestream")
    desired = json.loads((base / "desired-state.json").read_text())
    producer = json.loads((base / "producer-status.json").read_text())
    require(desired.get("desired") == "stopped" and producer.get("state") == "stopped",
            "STOP_LIVESTREAM_FIRST")


def pilot_state():
    require(not any(present(Path(p)) for p in ("/run/clientflow-63d76-livestream", "/run/clientflow-63d72f-hls")),
            "FOREIGN_LIVESTREAM_PILOT")
    for timer in TIMERS:
        require(prop(timer, "ActiveState") == "inactive"
                and prop(timer.removesuffix(".timer") + ".service", "ActiveState") == "inactive",
                "ROLLBACK_ACTIVE")
    rdp = present(RDP / "shadow")
    hls = present(HLS)
    if rdp:
        pinned(RDP / "operator.py", RDP_PIN)
        require(present(RDP_SOURCE), "RDP_SOURCE_MISSING")
    else:
        require(not present(RDP_SOURCE) and not any(present(SYSTEMD / name) for name in UNITS),
                "ORPHANED_RDP_SOURCE_OR_UNIT")
    if hls:
        pinned(HLS / "rollback.py", HLS_ROLLBACK_PIN)
        pinned(HLS / "entrypoint.py", HLS_ENTRY_PIN)
        pinned(HLS / "livestream_uploader.py", HLS_UPLOADER_PIN)
    for service in SERVICES:
        expected = rdp if service == AGENT else hls
        require(prop(service, "ActiveState") == "active", "MEDIA_SERVICE_INACTIVE")
        loaded = prop(service, "DropInPaths").split()
        require(loaded == ([str(DROPINS[service])] if expected else []), "UNKNOWN_MEDIA_OVERRIDE")
        require(present(DROPINS[service]) == expected, "MEDIA_OVERRIDE_MISMATCH")
        execution = prop(service, "ExecStart")
        expected_exec = (str(RDP / "shadow/entrypoint.py") if service == AGENT and rdp
                         else str(HLS / "entrypoint.py") if service == UPLOADER and hls
                         else "/opt/clientflow/active/runtime/bin/" + service.removesuffix(".service"))
        require(expected_exec in execution, "UNEXPECTED_MEDIA_EXEC")
    return rdp, hls


def backup_config(raw):
    safe_dir(BACKUP_DIR.parent)
    BACKUP_DIR.mkdir(mode=0o700, exist_ok=True)
    safe_dir(BACKUP_DIR, private=True)
    if present(BACKUP):
        original = read_regular(BACKUP, private=True)[0]
        require(raw in (original, migrated_config(original)), "CONFIG_CHANGED_SINCE_BACKUP")
        return original
    fd = os.open(BACKUP, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    sync_dir(BACKUP_DIR)
    return raw


def replace_config(old, new):
    current, meta = read_regular(CONFIG)
    require(current == old, "CONFIG_CHANGED_DURING_PREPARATION")
    if old == new:
        return
    fd, name = tempfile.mkstemp(prefix=".livestream-63d83b-", dir=CONFIG.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchown(stream.fileno(), 0, meta.st_gid)
            os.fchmod(stream.fileno(), stat.S_IMODE(meta.st_mode))
            stream.write(new)
            stream.flush()
            os.fsync(stream.fileno())
        require(read_regular(CONFIG)[0] == old, "CONFIG_CHANGED_BEFORE_COMMIT")
        os.replace(name, CONFIG)
        sync_dir(CONFIG.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    require(read_regular(CONFIG)[0] == new, "CONFIG_COMMIT_NOT_VERIFIED")


def prepare():
    state_stopped()
    rdp, hls = pilot_state()
    raw = read_regular(CONFIG)[0]
    migrated_config(raw)  # validate both pilots and configuration before mutation
    original = backup_config(raw)
    if hls:
        pinned(HLS / "rollback.py", HLS_ROLLBACK_PIN)
        output = run("/usr/bin/python3", "-I", "-B", str(HLS / "rollback.py"), timeout=240)
        require("63D83A_HLS_ROLLBACK=PASS" in output.splitlines(), "HLS_ROLLBACK_NOT_ATTESTED")
        print("HLS_PILOT_RETIRED=PASS", flush=True)
    if rdp:
        pinned(RDP / "operator.py", RDP_PIN)
        output = run("/usr/bin/python3", "-I", "-B", str(RDP / "operator.py"), "rollback", timeout=300)
        require("63D54_ROLLBACK=PASS" in output.splitlines(), "RDP_ROLLBACK_NOT_ATTESTED")
        print("RDP_PILOT_RETIRED=PASS", flush=True)
    require(pilot_state() == (False, False), "PILOT_REMAINS")
    state_stopped()
    replace_config(raw, migrated_config(original))
    target()
    print("LIVESTREAM_SEGMENT_SECONDS=1\nLIVESTREAM_CONTINUOUS_WSS=False")
    print("CONFIG_BACKUP_VERIFIED=PASS\nACTIVE_RELEASE_UNCHANGED=1248")
    print("VIBORG1_1250_PREPARED=PASS")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "prepare", "restore-config"))
    args = parser.parse_args()
    try:
        target()
        if args.action == "check":
            require(not present(COORD / "state.json"), "INSTALLATION_IN_PROGRESS_OR_IN_DOUBT")
            state_stopped()
            rdp, hls = pilot_state()
            migrated_config(read_regular(CONFIG)[0])
            print(f"RDP_PILOT={rdp}\nHLS_PILOT={hls}\nVIBORG1_PREPARATION_CHECK=PASS")
        else:
            with installation_guard():
                if args.action == "prepare":
                    prepare()
                else:
                    state_stopped()
                    require(pilot_state() == (False, False), "PILOT_REMAINS")
                    safe_dir(BACKUP_DIR, private=True)
                    original = read_regular(BACKUP, private=True)[0]
                    current = read_regular(CONFIG)[0]
                    require(current in (original, migrated_config(original)), "CONFIG_CHANGED_SINCE_BACKUP")
                    replace_config(current, original)
                    print("ORIGINAL_CONFIG_RESTORED=PASS")
        return 0
    except Exception as exc:
        # Fixed code or exception class only; do not dump configuration or credentials.
        code = str(exc) if type(exc) is RuntimeError else type(exc).__name__
        print("63D83B_PREPARATION_STOP=" + code, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
