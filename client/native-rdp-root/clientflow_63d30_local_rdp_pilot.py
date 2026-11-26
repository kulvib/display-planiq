#!/usr/bin/env python3
"""63D-30 physical GNOME screen-sharing pilot; not a production RDP gateway.

No Render, backend API, release catalogue, database or ClientFlow agent changes.
Use only with the independently reviewed 63D-29 persistent nftables boot guard.

Security invariants:
- Root + verified canonical client identity; existing user GNOME desktop
- Firewall and root timer active BEFORE any GNOME RDP change
- No RDP secret in argv/env/logs; generated credentials pass via stdin
- On timeout/boot restart: stop RDP, verify no listeners, restore settings;
  only then remove the guard. On doubt, retain guard and retry.
- No public RDP or municipal HTTPS/443 relay is provided by this pilot.
"""
from __future__ import annotations

import argparse
import fcntl
import errno
import pty
import select
import signal
import termios
import hashlib
import json
import math
import os
from pathlib import Path
import pwd
import re
import secrets
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import time

# Avoid generating __pycache__ files in the temporary staged root bundle.
sys.dont_write_bytecode = True
# Both package-style CI imports and standalone root-staged execution must
# resolve the *same adjacent* guard script, never a mutable production release.
if __package__:
    from . import clientflow_63d29_persistent_rdp_guard as guard
else:
    import clientflow_63d29_persistent_rdp_guard as guard

SCHEMA = "org.gnome.desktop.remote-desktop.rdp"
# GNOME Keyring session collection: RAM-only and destroyed on session end.
SESSION_COLLECTION = "/org/freedesktop/secrets/collection/session"
KIOSK = "clientflow-kiosk"
STATE_ROOT = Path("/var/lib/clientflow/rdp-pilot-63d30")
STATE_FILE = STATE_ROOT / "state.json"
STAGE_ROOT = Path("/var/lib/clientflow/rdp-pilot-bundle-63d30")
STAGED_RUNNER = STAGE_ROOT / "clientflow_63d30_local_rdp_pilot.py"
STAGED_GUARD = STAGE_ROOT / "clientflow_63d29_persistent_rdp_guard.py"
TIMER_NAME = "clientflow-63d30-rdp-watchdog.timer"
SERVICE_NAME = "clientflow-63d30-rdp-watchdog.service"
TIMER_PATH = Path("/etc/systemd/system") / TIMER_NAME
SERVICE_PATH = Path("/etc/systemd/system") / SERVICE_NAME
SECRET_ROOT = Path("/run/clientflow-rdp-63d30")
SECRET_FILE = SECRET_ROOT / "credentials"
MAX_SECONDS = 6 * 60
EXPECTED_GUARD_SHA256 = "b1ece1303f524fd81b2ea7d86c4a3131cf26cf1bb343c0e4025ed8e9a84231fa"
LOCK_PATH = Path("/run/clientflow-63d30-pilot.lock")
APPROVAL_MARKER = Path("/run/clientflow/native-rdp-approved")
SESSION_PROOF = Path("/run/clientflow/rdp-session-proof-v1.json")
BASE_KEYS = (
    "port", "negotiate-port", "screen-share-mode", "view-only",
    "enable", "auth-methods", "tls-cert", "tls-key",
)
EXPECTED_BASE = {
    "port": "uint16 3389",
    "negotiate-port": "true",
    "screen-share-mode": "'mirror-primary'",
    "view-only": "true",
    "enable": "false",
    "auth-methods": "['credentials']",
    "tls-cert": "''",
    "tls-key": "''",
}
TIMER = """[Unit]
Description=ClientFlow GNOME RDP physical pilot expiry monitor

[Timer]
OnCalendar=*-*-* *:*:0/10
Persistent=true
AccuracySec=1s
Unit=clientflow-63d30-rdp-watchdog.service

[Install]
WantedBy=timers.target
"""
SERVICE = f"""[Unit]
Description=ClientFlow 63D-30 fail-closed RDP cleanup worker
After=local-fs.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 {STAGED_RUNNER} tick
TimeoutStartSec=50
UMask=0077
"""


def run(*args: str, input: str | None = None, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args), input=input, capture_output=True, text=True,
        timeout=timeout, check=False,
    )


def run_ok(*args: str, input: str | None = None, timeout: int = 15) -> None:
    result = run(*args, input=input, timeout=timeout)
    if result.returncode:
        # Never display stderr/stdout of credential- or key-bearing commands.
        raise RuntimeError("STOP: Kommando mislykkedes: " + args[0])


def _local_kiosk() -> tuple[int, Path]:
    if os.geteuid() != 0:
        raise RuntimeError("RDP_ROOT_REQUIRED")
    entry = pwd.getpwnam(KIOSK)
    runtime = Path("/run/user") / str(entry.pw_uid)
    if not (runtime / "bus").is_socket():
        raise RuntimeError("STOP: kiosk-D-Bus ikke tilgængelig; behold firewall")
    return entry.pw_uid, runtime


def target() -> tuple[int, Path]:
    guard.local_client_id()
    return _local_kiosk()


def kiosk(uid: int, *args: str, input: str | None = None) -> subprocess.CompletedProcess[str]:
    return run(
        "runuser", "-u", KIOSK, "--", "env",
        f"XDG_RUNTIME_DIR=/run/user/{uid}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus",
        "LC_ALL=C", *args, input=input,
    )


# Fixed, non-sensitive operation labels. Do not include command arguments,
# TLS file locations, credentials, or stderr/stdout in error messages.
SAFE_KIOSK_OPERATIONS = {
    ("grdctl", "rdp", "set-tls-key"): "RDP_SET_TLS_KEY",
    ("grdctl", "rdp", "set-tls-cert"): "RDP_SET_TLS_CERT",
    ("grdctl", "rdp", "set-credentials"): "RDP_SET_CREDENTIALS",
    ("grdctl", "rdp", "disable-port-negotiation"): "RDP_DISABLE_PORT_NEGOTIATION",
    ("grdctl", "rdp", "disable-view-only"): "RDP_DISABLE_VIEW_ONLY",
    ("grdctl", "rdp", "enable"): "RDP_ENABLE",
    ("grdctl", "rdp", "disable"): "RDP_DISABLE",
    ("grdctl", "rdp", "clear-credentials"): "RDP_CLEAR_CREDENTIALS",
    ("systemctl", "--user", "enable"): "USER_RDP_SERVICE_ENABLE",
    ("systemctl", "--user", "disable"): "USER_RDP_SERVICE_DISABLE",
}


def safe_kiosk_operation(args: tuple[str, ...]) -> str:
    if len(args) >= 2 and args[:2] == ("gsettings", "set"):
        return "GSETTINGS_SET"
    if len(args) >= 3:
        return SAFE_KIOSK_OPERATIONS.get(tuple(args[:3]), "OTHER_USER_COMMAND")
    return "OTHER_USER_COMMAND"


def kiosk_ok(uid: int, *args: str, input: str | None = None) -> None:
    result = kiosk(uid, *args, input=input)
    if result.returncode:
        label = safe_kiosk_operation(args)
        # Never log subprocess output or any values, even on diagnostic failure.
        print("GNOME_USER_FAILED_OPERATION=", label, flush=True)
        print("GNOME_USER_COMMAND_FAILED=True", flush=True)
        raise RuntimeError("STOP: GNOME user operation failed: " + label)


def kiosk_set_rdp_credentials_pty(uid: int, username: str, password: str) -> None:
    """Drive GRD's two separate readline prompts through a private PTY.

    Sending both lines together on a pipe can cause the first buffered
    GDataInputStream to consume the second line. The PTY feeds one answer
    only after the relevant prompt. No secret enters argv, env, or logs.
    """
    if not re.fullmatch(r"[a-zA-Z0-9]{8,32}", username):
        raise RuntimeError("STOP: Unsafe generated RDP username")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{32,80}", password):
        raise RuntimeError("STOP: Unsafe generated RDP password")

    master, slave = pty.openpty()
    process = None
    stage = "PTY_PREPARE"
    try:
        attrs = termios.tcgetattr(slave)
        attrs[3] &= ~termios.ECHO
        termios.tcsetattr(slave, termios.TCSANOW, attrs)
        argv = [
            "runuser", "-u", KIOSK, "--", "env",
            f"XDG_RUNTIME_DIR=/run/user/{uid}",
            f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus",
            "LC_ALL=C", "grdctl", "rdp", "set-credentials",
        ]
        process = subprocess.Popen(
            argv, stdin=slave, stdout=slave, stderr=subprocess.DEVNULL,
            close_fds=True, start_new_session=True,
        )
        os.close(slave)
        slave = -1
        stage = "WAIT_USERNAME_PROMPT"
        buffer = b""
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            ready, _, _ = select.select(
                [master], [], [], min(0.5, max(0, deadline - time.monotonic())),
            )
            if ready:
                try:
                    chunk = os.read(master, 4096)
                except OSError as exc:
                    if exc.errno == errno.EIO:
                        chunk = b""
                    else:
                        raise
                if not chunk:
                    break
                # The PTY is private. Never print or log its contents.
                buffer = (buffer + chunk)[-4096:]
                if stage == "WAIT_USERNAME_PROMPT" and b"Username:" in buffer:
                    os.write(master, username.encode("ascii") + b"\n")
                    stage = "WAIT_PASSWORD_PROMPT"
                    buffer = b""
                elif stage == "WAIT_PASSWORD_PROMPT" and b"Password:" in buffer:
                    os.write(master, password.encode("ascii") + b"\n")
                    stage = "WAIT_CREDENTIAL_STORE"
                    buffer = b""
            if process.poll() is not None and not ready:
                break
        if stage != "WAIT_CREDENTIAL_STORE":
            raise RuntimeError("STOP: GNOME credential prompt incomplete")
        if process.poll() is None:
            try:
                process.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("STOP: GNOME credential store timed out") from exc
        if process.returncode != 0:
            raise RuntimeError("STOP: GNOME credential store returned failure")
        print("GNOME_CREDENTIALS_STDIN_PTY=PASS", flush=True)
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        # Only fixed phases are logged; raw PTY output can contain secrets.
        print("GNOME_USER_FAILED_OPERATION= RDP_SET_CREDENTIALS", flush=True)
        print("GNOME_CREDENTIAL_PTY_PHASE=", stage, flush=True)
        raise RuntimeError("STOP: GNOME credential PTY failed") from None
    finally:
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
        os.close(master)
        if slave >= 0:
            os.close(slave)


def get_setting(uid: int, key: str) -> str:
    if key not in BASE_KEYS:
        raise RuntimeError("STOP: Ukendt GNOME setting")
    response = kiosk(uid, "gsettings", "get", SCHEMA, key)
    if response.returncode != 0:
        raise RuntimeError("STOP: Kunne ikke læse GNOME setting")
    return response.stdout.strip()


def set_setting(uid: int, key: str, value: str) -> None:
    if key not in BASE_KEYS:
        raise RuntimeError("STOP: Ukendt GNOME setting")
    kiosk_ok(uid, "gsettings", "set", SCHEMA, key, value)
    if get_setting(uid, key) != value:
        raise RuntimeError("STOP: GNOME setting ikke bekræftet: " + key)


def rdp_status_section(stdout: str) -> str | None:
    """Return the user-mode RDP block only; ignore VNC Password fields."""
    sections = 0
    inside = False
    captured = []
    for line in stdout.splitlines():
        if line == "RDP:":
            sections += 1
            inside = True
            continue
        if inside and line and not line.startswith((" ", "\t")):
            inside = False
        if inside:
            captured.append(line)
    return "\n".join(captured) if sections == 1 else None

def credentials_empty(uid: int) -> bool:
    """Inspect only GNOME's RDP credential section, not VNC or secret values."""
    response = kiosk(uid, "grdctl", "status")
    if response.returncode:
        raise RuntimeError("STOP: kunne ikke læse credentials status")
    rdp = rdp_status_section(response.stdout)
    if rdp is None:
        return False
    for field in ("Username", "Password"):
        values = re.findall(
            rf"(?m)^[ \t]*{field}:[ \t]*([^\r\n]*)$", rdp
        )
        if len(values) != 1 or values[0].strip(" \t") != "(empty)":
            return False
    return True

def secret_bus(uid: int, *args: str) -> str:
    """Call Secret Service through kiosk D-Bus, never expose raw replies/errors."""
    response = kiosk(uid, "busctl", "--user", *args)
    if response.returncode != 0:
        raise RuntimeError("STOP: Secret Service query or operation failed")
    return response.stdout.strip()


def secret_alias(uid: int, name: str) -> str:
    if name not in {"default", "login"}:
        raise RuntimeError("STOP: Unexpected Secret Service alias")
    raw = secret_bus(
        uid, "call", "org.freedesktop.secrets", "/org/freedesktop/secrets",
        "org.freedesktop.Secret.Service", "ReadAlias", "s", name,
    )
    try:
        parts = shlex.split(raw)
    except ValueError as exc:
        raise RuntimeError("STOP: Unexpected Secret Service alias response") from exc
    if len(parts) != 2 or parts[0] != "o":
        raise RuntimeError("STOP: Unexpected Secret Service alias response")
    if parts[1] not in {"/", SESSION_COLLECTION}:
        raise RuntimeError("STOP: Unexpected existing Secret Service alias")
    return parts[1]


def session_collection_preflight(uid: int) -> None:
    """Only accept the one existing unlocked RAM-only GNOME session collection."""
    raw = secret_bus(
        uid, "get-property", "org.freedesktop.secrets",
        "/org/freedesktop/secrets", "org.freedesktop.Secret.Service", "Collections",
    )
    try:
        values = shlex.split(raw)
    except ValueError as exc:
        raise RuntimeError("STOP: Unexpected Secret Service collection response") from exc
    if values != ["ao", "1", SESSION_COLLECTION]:
        raise RuntimeError("STOP: Only an existing single RAM-only session collection is allowed")
    locked = secret_bus(
        uid, "get-property", "org.freedesktop.secrets",
        SESSION_COLLECTION, "org.freedesktop.Secret.Collection", "Locked",
    )
    if locked != "b false":
        raise RuntimeError("STOP: Session collection is locked or unknown")
    if secret_alias(uid, "default") != "/" or secret_alias(uid, "login") != "/":
        raise RuntimeError("STOP: Existing keyring alias cannot be overwritten")
    print("RAM_ONLY_SESSION_COLLECTION_VERIFIED=True", flush=True)


def set_temporary_default_alias(uid: int) -> None:
    # Called only AFTER the persistent boot firewall and root watchdog are verified.
    session_collection_preflight(uid)
    secret_bus(
        uid, "call", "org.freedesktop.secrets", "/org/freedesktop/secrets",
        "org.freedesktop.Secret.Service", "SetAlias", "so",
        "default", SESSION_COLLECTION,
    )
    if secret_alias(uid, "default") != SESSION_COLLECTION:
        raise RuntimeError("STOP: Temporary default alias was not established")
    print("TEMPORARY_SESSION_ALIAS_ACTIVE=True", flush=True)


def clear_temporary_default_alias(uid: int) -> None:
    # No persistent default keyring ever created. Do not overwrite another alias.
    current = secret_alias(uid, "default")
    if current == SESSION_COLLECTION:
        secret_bus(
            uid, "call", "org.freedesktop.secrets", "/org/freedesktop/secrets",
            "org.freedesktop.Secret.Service", "SetAlias", "so", "default", "/",
        )
    if secret_alias(uid, "default") != "/":
        raise RuntimeError("STOP: Temporary alias not cleared; keep firewall")
    if secret_alias(uid, "login") != "/":
        raise RuntimeError("STOP: Login keyring alias changed; keep firewall")
    print("TEMPORARY_SESSION_ALIAS_CLEARED=True", flush=True)


def read_baseline(uid: int) -> dict[str, str]:
    result = {key: get_setting(uid, key) for key in BASE_KEYS}
    if result != EXPECTED_BASE:
        raise RuntimeError("STOP: GNOME har ændret indstillinger; afbryd uden overskrivning")
    if not credentials_empty(uid):
        raise RuntimeError("STOP: eksisterende RDP-credentials må ikke overskrives")
    guard.ensure_rdp_off(str(uid))
    return result


def write_private(path: Path, text: str, mode: int = 0o600) -> None:
    with path.open("x", encoding="utf-8") as file:
        os.fchmod(file.fileno(), mode)
        file.write(text)
        file.flush()
        os.fsync(file.fileno())


def cleanup_state() -> dict | None:
    """Only local root-owned evidence may authorize shutdown of owned state.

    Enrollment changes cannot prevent safety cleanup. This evidence is never
    sufficient to start, renew or seal an RDP session.
    """
    if os.geteuid() != 0:
        raise RuntimeError("RDP_ROOT_REQUIRED")
    try:
        STATE_FILE.lstat()
    except FileNotFoundError:
        return None
    data = guard.read_private_json(STATE_FILE)
    if (data.get("phase") != "63D-30"
            or type(data.get("client_id")) is not int or data["client_id"] <= 0
            or type(data.get("kiosk_uid")) is not int or data["kiosk_uid"] <= 0
            or not isinstance(data.get("hostname"), str) or not data["hostname"]
            or not isinstance(data.get("boot_id"), str) or not data["boot_id"]
            or data.get("baseline") != EXPECTED_BASE):
        raise RuntimeError("STOP: Ukendt RDP recovery-state; behold firewall")
    return data


def identity_matches(data: dict) -> bool:
    try:
        return (data["client_id"] == guard.local_client_id()
                and data["hostname"] == socket.gethostname()
                and data["kiosk_uid"] == pwd.getpwnam(KIOSK).pw_uid)
    except (RuntimeError, OSError, ValueError, KeyError):
        return False


def state_load() -> dict | None:
    data = cleanup_state()
    if data is not None and not identity_matches(data):
        raise RuntimeError("STOP: Klientidentiteten er ændret; kun sikker oprydning tilladt")
    return data


def _remove_owned_attestation(path: Path, data: dict, mode: int, *, hostname: bool) -> None:
    """Remove only an exact root-owned grant/proof for this recovery record."""
    try:
        meta = path.lstat()
    except FileNotFoundError:
        return
    parent = path.parent.lstat()
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0 or parent.st_mode & 0o022
            or not stat.S_ISREG(meta.st_mode) or meta.st_uid != 0
            or stat.S_IMODE(meta.st_mode) != mode or not 0 < meta.st_size <= 2048):
        raise RuntimeError("STOP: Ukendt RDP attestation; behold firewall")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (meta.st_dev, meta.st_ino):
            raise RuntimeError("STOP: RDP attestation ændret")
        raw = stream.read(2049)
    value = json.loads(raw)
    if (len(raw) > 2048 or type(value) is not dict or type(value.get("schema")) is not int
            or value["schema"] != 1 or type(value.get("client_id")) is not int
            or value["client_id"] != data["client_id"] or value.get("boot_id") != data["boot_id"]
            or (hostname and value.get("hostname") != data["hostname"])):
        raise RuntimeError("STOP: Fremmed RDP attestation; behold firewall")
    current = path.lstat()
    if (current.st_dev, current.st_ino) != (meta.st_dev, meta.st_ino):
        raise RuntimeError("STOP: RDP attestation ændret")
    path.unlink()


def boot_id() -> str:
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def deadline_expired(data: dict) -> bool:
    if data.get("boot_id") != boot_id():
        return True
    wall, mono = data.get("deadline_wall"), data.get("deadline_mono")
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in (wall, mono)):
        return True
    return (time.time() >= wall or time.monotonic() >= mono
            or wall - time.time() > MAX_SECONDS or mono - time.monotonic() > MAX_SECONDS)


def watchdog_verified() -> bool:
    enabled = run("systemctl", "is-enabled", TIMER_NAME)
    active = run("systemctl", "is-active", TIMER_NAME)
    files = (
        SERVICE_PATH.is_file() and not SERVICE_PATH.is_symlink()
        and TIMER_PATH.is_file() and not TIMER_PATH.is_symlink()
        and SERVICE_PATH.read_text() == SERVICE
        and TIMER_PATH.read_text() == TIMER
    )
    return (
        files and enabled.stdout.strip() == "enabled"
        and active.stdout.strip() == "active"
    )


def stage() -> None:
    uid, _ = target()
    guard.ensure_rdp_off(str(uid))
    # Fail before creating any watchdog files if the RAM-only keyring is absent.
    session_collection_preflight(uid)
    if STAGE_ROOT.exists() or TIMER_PATH.exists() or SERVICE_PATH.exists():
        raise RuntimeError("STOP: Pilotfiler findes allerede")
    if STATE_ROOT.exists() or SECRET_ROOT.exists():
        raise RuntimeError("STOP: Pilot-state findes allerede")
    source = Path(__file__).resolve()
    other = source.parent / "clientflow_63d29_persistent_rdp_guard.py"
    if not other.is_file():
        raise RuntimeError("STOP: 63D-29 guard-kilden mangler i samme mappe")
    # Source is to be checksum-pinned by the user before any physical stage.
    if source.is_symlink() or other.is_symlink():
        raise RuntimeError("STOP: Symlink til kilde er ikke tilladt")
    if hashlib.sha256(other.read_bytes()).hexdigest() != EXPECTED_GUARD_SHA256:
        raise RuntimeError("STOP: 63D-29 firewall-kilde matcher ikke fysisk recovery-kilde")
    STAGE_ROOT.mkdir(mode=0o700, parents=False)
    write_private(STAGED_RUNNER, source.read_text(encoding="utf-8"), 0o700)
    write_private(STAGED_GUARD, other.read_text(encoding="utf-8"), 0o600)
    write_private(SERVICE_PATH, SERVICE, 0o644)
    write_private(TIMER_PATH, TIMER, 0o644)
    run_ok("systemctl", "daemon-reload")
    run_ok("systemctl", "enable", "--now", TIMER_NAME)
    if not watchdog_verified():
        raise RuntimeError("STOP: Persistent root watchdog ikke verificeret")
    print("WATCHDOG_STAGED=True")
    print("RDP_ENABLED=False")
    print("FIREWALL_INSTALLED=False")



def unstage(uid: int) -> None:
    """Remove only the owned root timer and staged files after proven cleanup."""
    if state_load() is not None:
        raise RuntimeError("STOP: Piloten er stadig aktiv; stop RDP først")
    guard.ensure_rdp_off(str(uid))
    if guard.guard_exists() or guard.DIRECTORY.exists():
        raise RuntimeError("STOP: Firewall-guard eksisterer stadig")
    if not TIMER_PATH.is_file() or TIMER_PATH.is_symlink():
        raise RuntimeError("STOP: Root timer mangler/er symlink")
    if not SERVICE_PATH.is_file() or SERVICE_PATH.is_symlink():
        raise RuntimeError("STOP: Root service mangler/er symlink")
    if TIMER_PATH.read_text() != TIMER or SERVICE_PATH.read_text() != SERVICE:
        raise RuntimeError("STOP: Ukendt watchdog unit indhold")
    if STAGED_RUNNER.is_symlink() or STAGED_GUARD.is_symlink():
        raise RuntimeError("STOP: Staged kilde er symlink")
    if hashlib.sha256(STAGED_GUARD.read_bytes()).hexdigest() != EXPECTED_GUARD_SHA256:
        raise RuntimeError("STOP: Staged guard-kilde er ændret")
    run_ok("systemctl", "disable", "--now", TIMER_NAME)
    TIMER_PATH.unlink()
    SERVICE_PATH.unlink()
    run_ok("systemctl", "daemon-reload")
    STAGED_GUARD.unlink()
    STAGED_RUNNER.unlink()
    STAGE_ROOT.rmdir()
    print("ROOT_WATCHDOG_AND_STAGED_CODE_REMOVED=True", flush=True)


def tls_directory(uid: int) -> Path:
    return Path("/run/user") / str(uid) / "clientflow-rdp-pilot-63d30"


def stage_tls(uid: int) -> tuple[Path, Path]:
    directory = tls_directory(uid)
    directory.mkdir(mode=0o700, exist_ok=False)
    os.chown(directory, uid, pwd.getpwnam(KIOSK).pw_gid)
    cert = directory / "tls.crt"
    key = directory / "tls.key"
    # OpenSSL creates a one-day self-signed certificate with 3072-bit RSA.
    run_ok(
        "openssl", "req", "-new", "-newkey", "rsa:3072",
        "-sha256", "-nodes", "-x509", "-days", "1",
        "-subj", "/CN=clientflow-63d30-local",
        "-keyout", str(key), "-out", str(cert), timeout=30,
    )
    for p in (cert, key):
        if p.is_symlink() or not p.is_file():
            raise RuntimeError("STOP: TLS-fil mangler eller er symlink")
        os.chmod(p, 0o600)
        os.chown(p, uid, pwd.getpwnam(KIOSK).pw_gid)
    return cert, key


def listeners() -> list[int]:
    ports = set()
    for arguments in (("ss", "-H", "-ltn"), ("ss", "-H", "-lun")):
        result = run(*arguments)
        if result.returncode:
            raise RuntimeError("STOP: Kan ikke undersøge RDP listeners")
        for row in result.stdout.splitlines():
            fields = row.split()
            if len(fields) >= 5 and ":" in fields[3]:
                field = fields[3].rsplit(":", 1)[1]
                if field.isdecimal() and 3389 <= int(field) <= 3398:
                    ports.add(int(field))
    return sorted(ports)


def start() -> None:
    uid, _ = target()
    if Path(__file__).resolve() != STAGED_RUNNER:
        raise RuntimeError("STOP: kør kun root-staged kilde")
    if state_load() is not None:
        raise RuntimeError("STOP: eksisterende eller uafsluttet RDP-pilot")
    if not watchdog_verified():
        raise RuntimeError("STOP: Boot-watchdog ikke aktiv")
    baseline = read_baseline(uid)
    session_collection_preflight(uid)
    if guard.guard_exists():
        raise RuntimeError("STOP: ukendt eksisterende firewall-guard")
    STATE_ROOT.mkdir(mode=0o700, parents=True, exist_ok=False)
    data = {
        "phase": "63D-30",
        "client_id": guard.local_client_id(),
        "hostname": socket.gethostname(),
        "kiosk_uid": uid,
        "baseline": baseline,
        "temporary_session_alias": True,
        "boot_id": boot_id(),
        "deadline_wall": time.time() + MAX_SECONDS,
        "deadline_mono": time.monotonic() + MAX_SECONDS,
    }
    write_private(STATE_FILE, json.dumps(data), 0o600)
    try:
        guard.install_guard(str(uid))
        if not guard.guard_verified():
            raise RuntimeError("STOP: Firewall ikke verificeret")
        print("RDP_FIREWALL_VERIFIED=True", flush=True)
        # The timer has been armed before any GNOME mutation.
        if not watchdog_verified():
            raise RuntimeError("STOP: Watchdog ikke aktiv")
        set_temporary_default_alias(uid)
        cert, key = stage_tls(uid)
        SECRET_ROOT.mkdir(mode=0o700, exist_ok=False)
        username = "cfpilot" + secrets.token_hex(4)
        password = secrets.token_urlsafe(36)
        write_private(SECRET_FILE, username + "\n" + password + "\n")
        kiosk_ok(uid, "grdctl", "rdp", "set-tls-key", str(key))
        kiosk_ok(uid, "grdctl", "rdp", "set-tls-cert", str(cert))
        kiosk_set_rdp_credentials_pty(uid, username, password)
        # Avoid service moving to another RDP port while only one is tested.
        kiosk_ok(uid, "grdctl", "rdp", "disable-port-negotiation")
        kiosk_ok(uid, "grdctl", "rdp", "disable-view-only")
        if get_setting(uid, "screen-share-mode") != "'mirror-primary'":
            raise RuntimeError("STOP: Ikke eksisterende primary GNOME session")
        if get_setting(uid, "port") != "uint16 3389":
            raise RuntimeError("STOP: RDP port ændret")
        kiosk_ok(uid, "grdctl", "rdp", "enable")
        kiosk_ok(uid, "systemctl", "--user", "enable", "--now",
                 "gnome-remote-desktop.service")
        for _ in range(15):
            if 3389 in listeners():
                break
            time.sleep(1)
        if listeners() != [3389]:
            raise RuntimeError("STOP: RDP listener ikke entydigt TCP/UDP 3389")
        if not guard.guard_verified():
            raise RuntimeError("STOP: Firewall ændret under start")
        print("RDP_EXISTING_SESSION_PILOT_ACTIVE=True")
        print("RDP_LOCAL_PORT=3389")
        print("REMOTE_LOGIN_MODE_USED=False")
        print("CREDENTIALS_ONLY_IN_ROOT_TMPFS=True")
        print("TIMEOUT_MINUTES=6")
        print("AUTHENTICATED_RDP_DESKTOP_TESTED=False")
        print("HTTPS_443_RELAY_TESTED=False")
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        print("START_FAILED=TRUE; ATTEMPTING_RDP_FIRST_ROLLBACK", flush=True)
        try:
            stop()
        except (RuntimeError, OSError, subprocess.TimeoutExpired):
            print("ROLLBACK_UNCERTAIN=TRUE; KEEP_GUARD_AND_WATCHDOG", flush=True)
        raise


def stop() -> None:
    data = cleanup_state()
    if data is None:
        raise RuntimeError("STOP: Intet pilot-state; manuel audit før sletning")
    uid, _ = _local_kiosk()
    if uid != data["kiosk_uid"]:
        raise RuntimeError("STOP: Kiosk UID ændret; behold firewall")
    original = data.get("baseline")
    if original != EXPECTED_BASE:
        raise RuntimeError("STOP: Ukendt baseline; behold firewall")
    # Disarm GNOME access first, before any guard changes.
    # All GNOME commands run only in clientflow-kiosk's user session.
    kiosk_ok(uid, "gsettings", "set", SCHEMA, "enable", "false")
    kiosk_ok(uid, "grdctl", "rdp", "disable")
    kiosk_ok(uid, "systemctl", "--user", "disable", "--now",
             "gnome-remote-desktop.service")
    for _ in range(8):
        if not listeners():
            break
        time.sleep(1)
    if listeners():
        raise RuntimeError("STOP: RDP listener eksisterer; behold firewall")
    kiosk_ok(uid, "grdctl", "rdp", "clear-credentials")
    # Restore all original GNOME RDP settings without echoing TLS paths.
    for key in BASE_KEYS:
        set_setting(uid, key, original[key])
    if not credentials_empty(uid):
        raise RuntimeError("STOP: GNOME RDP credentials blev ikke slettet")
    if data.get("temporary_session_alias") is True:
        clear_temporary_default_alias(uid)
    guard.ensure_rdp_off(str(uid))
    # Watchdog cleanup must also revoke orphaned grants after a killed owner.
    # Unknown files are never removed and network protection remains on doubt.
    _remove_owned_attestation(SESSION_PROOF, data, 0o600, hostname=False)
    _remove_owned_attestation(APPROVAL_MARKER, data, 0o644, hostname=True)
    if guard.guard_exists():
        guard.remove_guard(str(uid))
    elif guard.DIRECTORY.exists() or guard.UNIT_PATH.exists() or guard.DROPIN_PATH.exists():
        raise RuntimeError("STOP: Delvist guard-state kræver manuel audit")
    # Only now remove private pilot artifacts.
    for file in (SECRET_FILE,):
        if file.exists():
            if file.is_symlink():
                raise RuntimeError("STOP: Credential-sti er symlink")
            file.unlink()
    if SECRET_ROOT.exists():
        SECRET_ROOT.rmdir()
    directory = tls_directory(uid)
    if directory.exists():
        for file in (directory / "tls.key", directory / "tls.crt"):
            if file.exists():
                if file.is_symlink():
                    raise RuntimeError("STOP: TLS-sti er symlink")
                file.unlink()
        directory.rmdir()
    STATE_FILE.unlink()
    STATE_ROOT.rmdir()
    print("RDP_STOPPED_AND_VERIFIED=True", flush=True)
    print("RDP_ORIGINAL_GSETTINGS_RESTORED=True", flush=True)
    print("RDP_CREDENTIALS_AND_TLS_REMOVED=True", flush=True)
    print("FIREWALL_GUARD_REMOVED=True", flush=True)
    # If cleanup is complete, retire the periodic root timer and pilot code.
    # All state and firewall checks above have already passed.
    unstage(uid)


def tick() -> None:
    data = cleanup_state()
    if data is None:
        return
    expired = not identity_matches(data) or deadline_expired(data)
    # A transient disappearance of nftables drops is treated as a potential
    # security incident: attempt GNOME-first shutdown immediately, instead of
    # keeping RDP enabled for the remainder of the six-minute pilot.
    try:
        protected = guard.guard_verified()
    except (OSError, subprocess.TimeoutExpired):
        protected = False
    if expired or not protected:
        print("PILOT_TIMEOUT_OR_GUARD_LOSS=TRUE", flush=True)
        stop()
    else:
        print("WATCHDOG=ARMED_AND_FIREWALL_PRESENT", flush=True)



def local_rdp_negotiation() -> bool:
    """Prove only TCP loopback X.224 RDP negotiation, not authentication/video."""
    packet = bytes.fromhex("030000130ee000000000000100080003000000")
    try:
        with socket.create_connection(("127.0.0.1", 3389), timeout=3) as connection:
            connection.settimeout(3)
            connection.sendall(packet)
            response = connection.recv(64)
    except (OSError, TimeoutError):
        return False
    return (
        len(response) >= 11 and response[0:2] == bytes((3, 0))
        and response[5] == 0xD0
    )


def probe() -> None:
    uid, _ = target()
    if state_load() is None or not watchdog_verified():
        raise RuntimeError("STOP: Pilot eller watchdog ikke aktiv")
    if not guard.guard_verified():
        raise RuntimeError("STOP: Firewall ikke verificeret")
    if get_setting(uid, "enable") != "true":
        raise RuntimeError("STOP: GNOME RDP er ikke aktiv")
    if listeners() != [3389]:
        raise RuntimeError("STOP: RDP port afviger")
    result = local_rdp_negotiation()
    print("LOCAL_RDP_X224_NEGOTIATION=", "PASS" if result else "FAIL")
    print("RDP_AUTHENTICATION_TESTED=False")
    print("DESKTOP_PIXELS_TESTED=False")
    if not result:
        raise RuntimeError("STOP: Local RDP X.224 negotiation fejlede")



def auth_probe() -> None:
    """Authenticate locally with FreeRDP, without an exposed socket or argv secrets.

    +auth-only performs authentication, NOT a full pixel/input quality test.
    The test client runs under a disposable virtual X display on this host.
    """
    uid, _ = target()
    data = state_load()
    if data is None or deadline_expired(data):
        raise RuntimeError("STOP: Ingen aktiv, ikke-udløbet RDP-pilot")
    if not watchdog_verified() or not guard.guard_verified():
        raise RuntimeError("STOP: Root-watchdog eller kernel-firewall ikke verificeret")
    if get_setting(uid, "enable") != "true" or listeners() != [3389]:
        raise RuntimeError("STOP: RDP-port og konfiguration ikke verificeret")
    if SECRET_FILE.is_symlink() or not SECRET_FILE.is_file():
        raise RuntimeError("STOP: Lokal test-credentialfil mangler/er symlink")
    st = SECRET_FILE.stat()
    if st.st_uid != 0 or (st.st_mode & 0o777) != 0o600:
        raise RuntimeError("STOP: Forkerte root-only credential-rettigheder")
    credentials = SECRET_FILE.read_text(encoding="utf-8").splitlines()
    if len(credentials) != 2:
        raise RuntimeError("STOP: Uventet credential-filformat")
    username, password = credentials
    if not re.fullmatch(r"cfpilot[0-9a-f]{8}", username):
        raise RuntimeError("STOP: Uventet pilotbrugernavn")
    if len(password) < 40 or any(c in password for c in "\r\n"):
        raise RuntimeError("STOP: Uventet pilotadgangskode")

    client = shutil.which("xfreerdp") or shutil.which("xfreerdp3")
    xvfb = shutil.which("xvfb-run")
    if client is None or xvfb is None:
        raise RuntimeError("STOP: freerdp-x11 og xvfb skal installeres særskilt")
    cert = tls_directory(uid) / "tls.crt"
    if cert.is_symlink() or not cert.is_file():
        raise RuntimeError("STOP: Midlertidigt TLS-certifikat mangler")
    # Pin this one-time certificate by DER SHA256. Never use /cert:ignore.
    # openssl output is DER cert (public), not the private key.
    result = subprocess.run(
        ["openssl", "x509", "-in", str(cert), "-outform", "DER"],
        capture_output=True, timeout=5, check=False,
    )
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError("STOP: TLS-fingerprint kunne ikke beregnes")
    fingerprint = hashlib.sha256(result.stdout).hexdigest().upper()
    arguments = [
        "/v:127.0.0.1:3389", "/u:" + username, "/p:" + password,
        "+auth-only", "/cert:fingerprint:sha256:" + fingerprint,
        "/log-level:ERROR",
    ]
    # /args-from:stdin accepts exactly one argument per line. The shell,
    # process table, environment and user-facing output see no credentials.
    # xvfb-run connects to the virtual display; it does not replace kiosk.
    response = subprocess.run(
        [xvfb, "-a", client, "/args-from:stdin"],
        input="\n".join(arguments) + "\n",
        capture_output=True, text=True, timeout=25, check=False,
    )
    # Do NOT print stdout or stderr; FreeRDP may contain sensitive diagnostics.
    print("FREERDP_LOCAL_AUTH_ONLY=", "PASS" if response.returncode == 0 else "FAIL")
    print("TESTED_ENDPOINT=127.0.0.1:3389")
    print("SECRETS_IN_COMMANDLINE=False")
    print("SECRETS_PRINTED=False")
    print("PIXELS_AND_MOUSE_TESTED=False")
    if response.returncode != 0:
        raise RuntimeError("STOP: FreeRDP localhost-auth mislykkedes")



def exercise_auth() -> None:
    """One command, bounded RDP authentication drill, always RDP-first rollback."""
    # Requires previously staged, checksum-verified root bundle and FreeRDP.
    uid, _ = target()
    if Path(__file__).resolve() != STAGED_RUNNER:
        raise RuntimeError("STOP: Kør kun fysisk staged pilotkilde")
    if state_load() is not None:
        raise RuntimeError("STOP: Tidligere eller igangværende pilot-state")
    if not watchdog_verified():
        raise RuntimeError("STOP: Root-watchdog ikke staged")
    if not (shutil.which("xfreerdp") or shutil.which("xfreerdp3")) or not shutil.which("xvfb-run"):
        raise RuntimeError("STOP: FreeRDP/Xvfb mangler; ingen RDP ændret")
    try:
        start()
        auth_probe()
    finally:
        # If start itself failed but already rolled back successfully,
        # stop() must not rerun and fail on missing state. If anything
        # remains, stop() takes precedence over the authentication result.
        if state_load() is not None:
            stop()
    # Report PASS only AFTER RDP-off and complete cleanup succeeded.
    print("RDP_AUTH_AND_ROLLBACK_DRILL=PASS", flush=True)


def status() -> None:
    uid, _ = target()
    data = state_load()
    print("PILOT_STATE_EXISTS=", data is not None)
    print("GUARD_KERNEL_VERIFIED=", guard.guard_verified())
    print("ROOT_WATCHDOG_VERIFIED=", watchdog_verified())
    print("GNOME_RDP_SETTING=", get_setting(uid, "enable"))
    print("RDP_LISTENERS_3389_3398=", listeners())
    if data is not None:
        print("PILOT_EXPIRED=", deadline_expired(data))
    print("NO_CREDENTIALS_PRINTED=True")


def main() -> int:
    parser = argparse.ArgumentParser(description="63D-30 local GNOME screen-sharing pilot")
    parser.add_argument("action", choices=["stage", "start", "stop", "tick", "status", "unstage", "probe", "auth-probe", "exercise-auth"])
    args = parser.parse_args()
    print("===== CLIENTFLOW 63D-30 · LOCAL GNOME RDP PILOT =====", flush=True)
    try:
        # A concurrently expiring watchdog cannot remove network protection
        # while the pilot is still starting.
        if os.geteuid() != 0:
            raise RuntimeError("RDP_ROOT_REQUIRED")
        if args.action not in {"stop", "tick", "unstage"}:
            guard.local_client_id()
        parent = LOCK_PATH.parent.lstat()
        if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0 or parent.st_mode & 0o022:
            raise RuntimeError("STOP: Ubetroet watchdog-låsekatalog")
        fd = os.open(LOCK_PATH, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o600)
        with os.fdopen(fd, "r+b") as lock:
            meta = os.fstat(lock.fileno())
            if not stat.S_ISREG(meta.st_mode) or meta.st_uid != 0 or stat.S_IMODE(meta.st_mode) != 0o600:
                raise RuntimeError("STOP: Ubetroet watchdog-lås")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("STOP: Anden pilotoperation kører allerede") from exc
            {"stage": stage, "start": start, "stop": stop,
             "tick": tick, "status": status,
             "unstage": lambda: unstage(_local_kiosk()[0]),
             "probe": probe,
             "auth-probe": auth_probe,
             "exercise-auth": exercise_auth}[args.action]()
        return 0
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print("PILOT=STOP", type(exc).__name__, str(exc), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
