#!/usr/bin/env python3
"""63D-54: time-bounded physical pilot installer, not a release installer.

Root, Viborg1 ID 3, release 1248 only. Pin the entire candidate source set to
the immutable integrated 63D-61D source snapshot. No GNOME start at installation time; no
database, release-store, firewall policy, kiosk display, or Render mutations.
A runtime timer restores the original agent independently of the browser.
The original GNOME watchdog remains responsible for firewall-first protection
and RDP-first cleanup, including after reboot. Never delete foreign state.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import socket
import stat
import subprocess
import sys
import time
import urllib.request

COMMIT = "fb2e7ba677d478b4c466a4c916955d7f17175237"
HOST = "viborg1-NUC14MNK-B2"
RELEASE = "clientflow-1.3.47-seq-1248"
ROOT = Path("/run/clientflow-63d54-operator")
LOCK = Path("/run/clientflow-63d54-install.lock")
INSTALLER = ROOT / "operator.py"
SOURCE = Path("/usr/local/libexec/clientflow/native-rdp-pilot")
SHADOW = ROOT / "shadow"
SYSTEMD = Path("/run/systemd/system")
AGENT = "clientflow-remote-desktop-agent.service"
DROPIN = SYSTEMD / (AGENT + ".d") / "63d54-native-rdp.conf"
PYTHON = "/opt/clientflow/active/runtime/bin/python"
AGENT_USER = "clientflow-remote-desktop-agent"
LIFECYCLE = "clientflow-rdp-lifecycle.socket"
SEALER = "clientflow-rdp-sealer.socket"
TIMER = "clientflow-63d54-rollback.timer"
ROLLBACK = "clientflow-63d54-rollback.service"
STATE = Path("/var/lib/clientflow/rdp-pilot-63d30")
STAGE = Path("/var/lib/clientflow/rdp-pilot-bundle-63d30")
GRANT = Path("/run/clientflow/native-rdp-approved")
PROOF = Path("/run/clientflow/rdp-session-proof-v1.json")
SECRET = Path("/run/clientflow-rdp-63d30")
GUARD = Path("/etc/clientflow/rdp-guard-63d29")
SOCKETS = (Path("/run/clientflow/rdp-lifecycle-v1.sock"),
           Path("/run/clientflow/rdp-sealer-v1.sock"),
           Path("/run/clientflow/rdp-autologin-v1.sock"))
LIMIT = 128 * 1024
PINS = {
    "scripts/clientflow_63d29_persistent_rdp_guard.py": "709a5d9b1eba3364dfd2ac21f4e24525b0dc3261236456a9127aac7cfd54c000",
    "scripts/clientflow_63d30_local_rdp_pilot.py": "78972f7c7173a4894abc22d4518b1fc4d3189c76e30dd463715af03ef069af69",
    "scripts/clientflow_63d30_physical_preflight.py": "40967aa92d658d8ecf1288ad22b5cde8f247835c2d2070f6d2e785b144f40cc4",
    "scripts/clientflow_native_rdp_browser_pilot.py": "02c63fc10deb3c0329c5309bdcb19a0edf8fa694c1c0045257cd79c304849e7f",
    "scripts/clientflow_63d49_autologin_broker.py": "00dc81e3215b3605503cbd03ed8a3ebcc899b8489bb268a0668f5c98c4a7445e",
    "scripts/clientflow_63d53_rdp_ipc.py": "393c971b624ad7805f3cec5c395184200c8831e8d8d8033c309acaed6a0c7b7f",
    "scripts/clientflow_63d53_rdp_lifecycle.py": "5ee6afc5d8bf5a3d4401f77d8f36bb8eda47e1fcaea210466af0755bc9a8e2bb",
    "scripts/clientflow_63d53_rdp_proof.py": "daec30c30191f3dd6d9b0b4b12b773023bf5287ff34379150ef1b14f0df2e4f6",
    "client/runtime/clientflow_runtime/remote_desktop_agent.py": "1fbcfb5667b29c55140d082bc7ec1e65ba81f5b2f407bd5186546597dca4311a",
    "client/runtime/clientflow_runtime/native_rdp_forwarder.py": "1aa5946c8d34ceb1a07082b512e856e532732ab5f417e99372e7cd23d455dcfc",
    "client/runtime/clientflow_runtime/native_rdp_autologin.py": "087822cd2b0928b7d0406be0aa8b646a4b32690105e9f3094bff074cacb0726f",
    "client/runtime/clientflow_runtime/native_rdp_https_peer.py": "a0d3c2bb284967b76860217ec3d38c13b1dc744ef1d620df0888d109bfe90fb0",
    "experiments/63d53-managed-rdp/clientflow-rdp-lifecycle.socket": "9664b1e7c2b2c3627644d200a599018e7e64ebd32ce30b723024c9d91aa289a3",
    "experiments/63d53-managed-rdp/clientflow-rdp-lifecycle@.service": "35f49b92ce587c2496676ce92d9fc011511fabaa3c67e11c65634bfda899cbfc",
    "experiments/63d53-managed-rdp/clientflow-rdp-sealer.socket": "061ed3d0f426445e3b824fc4ab87a389ac10a333737a7e1b08217d7f4afca825",
    "experiments/63d53-managed-rdp/clientflow-rdp-sealer@.service": "99811bcc36e34ad2c16f5a86e9fe0a317fdd3c3f5275869d434af0d7290dc824"
}
MODULES = ("remote_desktop_agent.py", "native_rdp_forwarder.py", "native_rdp_autologin.py",
           "native_rdp_https_peer.py")
DROPIN_BYTES = ("[Service]\nExecStart=\nExecStart=" + PYTHON +
                " -I -B " + str(SHADOW / "entrypoint.py") + "\n").encode("ascii")
HTTPS_DROPIN_BYTES = DROPIN_BYTES + (
    b"Environment=CLIENTFLOW_NATIVE_BINARY_HTTPS_ENABLED=true\n"
    b"Environment=CLIENTFLOW_NATIVE_RDP_TRANSPORT=https\n"
)
WSS_DROPIN_BYTES = DROPIN_BYTES + (
    b"Environment=CLIENTFLOW_NATIVE_BINARY_HTTPS_ENABLED=false\n"
    b"Environment=CLIENTFLOW_NATIVE_RDP_TRANSPORT=wss\n"
)
ENTRY = """import hashlib
import os
from pathlib import Path
import socket
import stat
import sys
root = Path(__file__).resolve().parent
if socket.gethostname() != 'viborg1-NUC14MNK-B2' or Path('/opt/clientflow/active').resolve().name != 'clientflow-1.3.47-seq-1248':
    raise SystemExit('SHADOW_TARGET_INVALID')
for name, expected in PINS.items():
    path = root / name
    meta = path.lstat()
    if not stat.S_ISREG(meta.st_mode) or meta.st_uid != 0 or meta.st_mode & 0o022:
        raise SystemExit('SHADOW_SOURCE_UNSAFE')
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise SystemExit('SHADOW_SOURCE_MISMATCH')
import clientflow_runtime
clientflow_runtime.__path__ = [str(root), *clientflow_runtime.__path__]
from clientflow_runtime import native_rdp_autologin, native_rdp_forwarder, native_rdp_https_peer, remote_desktop_agent
for module in (native_rdp_autologin, native_rdp_forwarder, native_rdp_https_peer, remote_desktop_agent):
    if Path(module.__file__).resolve().parent != root:
        raise SystemExit('SHADOW_MODULE_MISMATCH')
if sys.argv[1:] == ['--check']:
    print('MANAGED_AGENT_IMPORT=PASS')
    raise SystemExit(0)
if sys.argv[1:]:
    raise SystemExit('SHADOW_ARGUMENTS_INVALID')
raise SystemExit(remote_desktop_agent.main())
"""
ENTRY_BYTES = ("PINS = " + repr({name: PINS["client/runtime/clientflow_runtime/" + name]
                                for name in MODULES}) + "\n" + ENTRY).encode("ascii")


class Stop(RuntimeError):
    pass


def present(path):
    return path.exists() or path.is_symlink()


def safe_dir(path):
    meta = path.lstat()
    if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != 0 or meta.st_mode & 0o022:
        raise Stop("UNSAFE_DIRECTORY")


def read_regular(path, limit=LIMIT):
    safe_dir(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        meta = os.fstat(stream.fileno())
        if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != 0 or meta.st_mode & 0o022
                or not 0 < meta.st_size <= limit):
            raise Stop("UNSAFE_FILE")
        data = stream.read(limit + 1)
    if not 0 < len(data) <= limit:
        raise Stop("INVALID_FILE_SIZE")
    return data


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require_pin(path, data):
    if not 0 < len(data) <= LIMIT or digest(data) != PINS[path]:
        raise Stop("SOURCE_SHA_MISMATCH")
    return data


def mkdir(path, mode=0o755):
    safe_dir(path.parent)
    path.mkdir(mode=mode, exist_ok=False)
    path.chmod(mode)
    safe_dir(path)


def write_new(path, data, mode=0o644):
    safe_dir(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "wb") as stream:
        os.fchmod(stream.fileno(), mode)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def command(label, *argv, timeout=30, **kwargs):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, check=False,
                                timeout=timeout, **kwargs)
    except (OSError, subprocess.TimeoutExpired):
        raise Stop(label + "_UNAVAILABLE") from None
    if result.returncode:
        raise Stop(label + "_FAILED")
    return result.stdout


def active(unit):
    result = subprocess.run(("/usr/bin/systemctl", "is-active", unit),
                            capture_output=True, text=True, timeout=10, check=False)
    return result.returncode == 0 and result.stdout.strip() == "active"


def systemctl(label, *args, timeout=30):
    return command(label, "/usr/bin/systemctl", *args, timeout=timeout)


def target():
    if os.geteuid() != 0 or socket.gethostname() != HOST:
        raise Stop("WRONG_PHYSICAL_HOST")
    data = json.loads(read_regular(Path("/etc/clientflow/identity.json"), 2048))
    if str(data.get("CLIENT_ID", data.get("client_id"))) != "3":
        raise Stop("WRONG_CLIENT_ID")
    if Path("/opt/clientflow/active").resolve().name != RELEASE:
        raise Stop("WRONG_ACTIVE_RELEASE")


def original_agent():
    if not active(AGENT):
        raise Stop("ORIGINAL_AGENT_INACTIVE")
    value = systemctl("AGENT_EXEC", "show", "--property=ExecStart", "--value", AGENT)
    if PYTHON in value or "/opt/clientflow/active/runtime/bin/clientflow-remote-desktop-agent" not in value:
        raise Stop("ORIGINAL_AGENT_EXEC_MISMATCH")
    if "/run/clientflow-native-rdp" in value or str(ROOT) in value:
        raise Stop("FOREIGN_AGENT_OVERRIDE")


def unit_paths():
    return {SYSTEMD / Path(path).name: path for path in PINS if path.startswith("experiments/")}


def physical_paths():
    return (STATE, STAGE, GRANT, PROOF, SECRET, GUARD)


def verify_clean():
    original_agent()
    for path in (ROOT, SOURCE, DROPIN, *physical_paths(), *SOCKETS, *unit_paths()):
        if present(path):
            raise Stop("PREEXISTING_PILOT_STATE")
    for prefix in (Path("/run/systemd/system"), Path("/etc/systemd/system")):
        directory = prefix / (AGENT + ".d")
        if present(directory):
            safe_dir(directory)
            if any(directory.glob("*native-rdp*.conf")):
                raise Stop("FOREIGN_AGENT_OVERRIDE")
        for name in (p.name for p in unit_paths()):
            if present(prefix / name):
                raise Stop("FOREIGN_MANAGED_UNIT")
    if active(TIMER) or active(LIFECYCLE) or active(SEALER):
        raise Stop("FOREIGN_ACTIVE_UNIT")


def download_all():
    result = {}
    for path in PINS:
        request = urllib.request.Request(
            "https://raw.githubusercontent.com/kulvib/display-planiq/" + COMMIT + "/" + path,
            headers={"User-Agent": "PlanIQ-63D54-Physical-Pilot"})
        with urllib.request.urlopen(request, timeout=25) as response:
            data = response.read(LIMIT + 1)
        result[path] = require_pin(path, data)
    return result


def physical_preflight(path):
    output = command("PHYSICAL_PREFLIGHT", "/usr/bin/python3", "-I", "-B", str(path), timeout=100)
    if not any(line in {"PHYSICAL_PREFLIGHT=PASS", "PHYSICAL_PREFLIGHT= PASS"}
               for line in output.splitlines()):
        raise Stop("PHYSICAL_PREFLIGHT_NOT_ATTESTED")


def crypto_preflight():
    command("SYSTEM_CRYPTO", "/usr/bin/python3", "-I", "-B", "-c",
            "from cryptography.hazmat.primitives.asymmetric import ec; "
            "from cryptography.hazmat.primitives.ciphers.aead import AESGCM; "
            "ec.generate_private_key(ec.SECP256R1()); AESGCM.generate_key(256)")


def owned_bytes(path, expected):
    if read_regular(path) != expected:
        raise Stop("FOREIGN_FILE_CONTENT")


def installed_sources():
    result = {}
    for path, expected in PINS.items():
        if path.startswith("scripts/"):
            result[SOURCE / path] = expected
        elif path.startswith("client/runtime/"):
            result[SHADOW / Path(path).name] = expected
    return result


def verify_owned_installation():
    # Validate everything that exists before any stop or unlink. Partial installs
    # may omit files but must never contain unrecognized replacements.
    safe_dir(ROOT)
    for folder in (SOURCE, SOURCE / "scripts", SHADOW):
        if present(folder):
            safe_dir(folder)
    for path, expected in installed_sources().items():
        if present(path) and digest(read_regular(path)) != expected:
            raise Stop("FOREIGN_SOURCE_CONTENT")
    for path, source in unit_paths().items():
        if present(path) and digest(read_regular(path)) != PINS[source]:
            raise Stop("FOREIGN_UNIT_CONTENT")
    if present(DROPIN):
        if read_regular(DROPIN) not in (WSS_DROPIN_BYTES, HTTPS_DROPIN_BYTES):
            raise Stop("FOREIGN_FILE_CONTENT")
    if present(SHADOW / "entrypoint.py"):
        owned_bytes(SHADOW / "entrypoint.py", ENTRY_BYTES)


def active_instances():
    result = systemctl("MANAGED_INSTANCES", "list-units", "--all", "--plain",
                       "--no-legend", "clientflow-rdp-lifecycle@*.service",
                       "clientflow-rdp-sealer@*.service")
    for line in result.splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[2] not in {"inactive", "failed"}:
            return True
    return False


def rollback():
    target()
    verify_owned_installation()
    # Block new starts before closing the agent's lease. Keep the separate
    # sealer and original watchdog available until root cleanup has completed.
    if present(SYSTEMD / LIFECYCLE):
        systemctl("STOP_NEW_LEASES", "stop", LIFECYCLE)
    if present(DROPIN):
        DROPIN.unlink()
        systemctl("RESTORE_UNIT", "daemon-reload")
        systemctl("RESTORE_AGENT", "restart", AGENT, timeout=45)
    else:
        # If a previous rollback was interrupted after unlink but before reload,
        # compare the actual loaded ExecStart and complete the restoration.
        value = systemctl("ROLLBACK_EXEC", "show", "--property=ExecStart", "--value", AGENT)
        if str(SHADOW / "entrypoint.py") in value or not active(AGENT):
            systemctl("RESTORE_UNIT", "daemon-reload")
            systemctl("RESTORE_AGENT", "restart", AGENT, timeout=45)
    original_agent()
    # A running privileged cleanup must never be killed just to remove files.
    # On timeout leave the independent physical watchdog, sources and timer.
    deadline = time.monotonic() + 150
    while active_instances() or any(present(path) for path in physical_paths()):
        if time.monotonic() >= deadline:
            raise Stop("PHYSICAL_CLEANUP_PENDING_KEEP_WATCHDOG")
        time.sleep(2)
    if present(SYSTEMD / SEALER):
        systemctl("STOP_SEALER", "stop", SEALER)
    if any(present(path) for path in SOCKETS):
        raise Stop("SOCKET_CLEANUP_NOT_PROVEN")
    verify_owned_installation()
    for path in (*unit_paths(), *installed_sources(), SHADOW / "entrypoint.py"):
        if present(path):
            path.unlink()
    for directory in (SOURCE / "scripts", SOURCE, SHADOW):
        if present(directory):
            directory.rmdir()
    systemctl("ROLLBACK_RELOAD", "daemon-reload")
    # Leave the root-owned operator and its audit log until reboot. The
    # transient timer has no persistent enablement.
    if active(TIMER):
        systemctl("STOP_ROLLBACK_TIMER", "stop", TIMER)
    print("63D54_ROLLBACK=PASS", flush=True)


def stage(sources):
    # Only the root-owned source package is persistent; all service definitions
    # and the agent override live under /run. No GNOME change here.
    if not present(SOURCE.parent):
        mkdir(SOURCE.parent)
    safe_dir(SOURCE.parent)
    mkdir(SOURCE)
    mkdir(SOURCE / "scripts")
    mkdir(SHADOW)
    for path, data in sources.items():
        if path.startswith("scripts/"):
            write_new(SOURCE / path, data)
        elif path.startswith("client/runtime/"):
            write_new(SHADOW / Path(path).name, data)
    write_new(SHADOW / "entrypoint.py", ENTRY_BYTES)
    compile(ENTRY_BYTES, str(SHADOW / "entrypoint.py"), "exec")
    for path, expected in installed_sources().items():
        if digest(read_regular(path)) != expected:
            raise Stop("STAGED_SOURCE_MISMATCH")
    user = pwd.getpwnam(AGENT_USER)
    result = command("AGENT_IMPORT", PYTHON, "-I", "-B", str(SHADOW / "entrypoint.py"),
                     "--check", user=user.pw_uid, group=user.pw_gid,
                     extra_groups=[], timeout=40)
    if "MANAGED_AGENT_IMPORT=PASS" not in result.splitlines():
        raise Stop("AGENT_IMPORT_NOT_ATTESTED")


def install(transport="wss"):
    if transport not in {"wss", "https"}:
        raise Stop("INVALID_PILOT_TRANSPORT")
    target()
    verify_clean()
    crypto_preflight()
    # Fetch everything before mutating service state. Every byte is pinned.
    sources = download_all()
    mkdir(ROOT)
    write_new(INSTALLER, read_regular(Path(__file__).resolve()), 0o700)
    preflight = ROOT / "physical-preflight.py"
    write_new(preflight, sources["scripts/clientflow_63d30_physical_preflight.py"], 0o600)
    physical_preflight(preflight)
    # Independent rollback timer is mandatory BEFORE the first installed unit
    # or agent override. No enable or persistent changes to ClientFlow units.
    command("ARM_ROLLBACK", "/usr/bin/systemd-run", "--unit=clientflow-63d54-rollback",
            "--on-active=20m", "--property=Restart=on-failure", "--property=RestartSec=20s",
            "--property=TimeoutStartSec=240", "/usr/bin/python3", "-I", "-B",
            str(INSTALLER), "rollback", timeout=30)
    if not active(TIMER):
        raise Stop("ROLLBACK_TIMER_NOT_ACTIVE")
    try:
        stage(sources)
        for path, source in unit_paths().items():
            write_new(path, sources[source])
        command("SYSTEMD_VERIFY", "/usr/bin/systemd-analyze", "verify",
                *(str(path) for path in unit_paths()), timeout=45)
        systemctl("LOAD_RUNTIME_UNITS", "daemon-reload")
        systemctl("START_LOCAL_SOCKETS", "start", SEALER, LIFECYCLE)
        if not active(SEALER) or not active(LIFECYCLE):
            raise Stop("LOCAL_SOCKETS_NOT_ACTIVE")
        agent_group = pwd.getpwnam(AGENT_USER).pw_gid
        for path, gid, mode in ((SOCKETS[0], agent_group, 0o660), (SOCKETS[1], 0, 0o600)):
            meta = path.lstat()
            if (not stat.S_ISSOCK(meta.st_mode) or meta.st_uid != 0 or meta.st_gid != gid
                    or stat.S_IMODE(meta.st_mode) != mode):
                raise Stop("LOCAL_SOCKET_PERMISSIONS_INVALID")
        if not present(DROPIN.parent):
            mkdir(DROPIN.parent)
        write_new(DROPIN, HTTPS_DROPIN_BYTES if transport == "https" else WSS_DROPIN_BYTES)
        systemctl("RELOAD_AGENT", "daemon-reload")
        systemctl("START_CANDIDATE_AGENT", "restart", AGENT, timeout=45)
        value = systemctl("CANDIDATE_EXEC", "show", "--property=ExecStart", "--value", AGENT)
        if not active(AGENT) or str(SHADOW / "entrypoint.py") not in value or not active(TIMER):
            raise Stop("CANDIDATE_AGENT_NOT_VERIFIED")
        if any(present(path) for path in physical_paths()):
            raise Stop("UNEXPECTED_PHYSICAL_RDP_START")
        print("63D54_MANAGED_PILOT=READY", flush=True)
        print("GNOME_RDP_NOT_STARTED=PASS", flush=True)
        print("CLIENTFLOW_RELEASE_UNCHANGED=1248", flush=True)
        print("AGENT_ROLLBACK_TIMER_MINUTES=20", flush=True)
        print("PHYSICAL_SESSION_RENEWABLE=TRUE", flush=True)
        print("PILOT_TRANSPORT=" + transport, flush=True)
        print("NO_CREDENTIALS_PRINTED=True", flush=True)
    except Exception:
        try:
            rollback()
        except Exception:
            print("ROLLBACK_INCOMPLETE_KEEP_WATCHDOG_AND_TIMER", flush=True)
        raise


def status():
    target()
    print("CANDIDATE_AGENT_ACTIVE=" + str(active(AGENT)))
    print("ROLLBACK_TIMER_ACTIVE=" + str(active(TIMER)))
    print("LIFECYCLE_SOCKET_ACTIVE=" + str(active(LIFECYCLE)))
    print("SEALER_SOCKET_ACTIVE=" + str(active(SEALER)))
    print("PHYSICAL_STATE_PRESENT=" + str(present(STATE)))
    print("PHYSICAL_GRANT_PRESENT=" + str(present(GRANT)))
    print("NO_CREDENTIALS_PRINTED=True")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("install", "install-https", "rollback", "status"))
    args = parser.parse_args()
    try:
        target()
        fd = os.open(LOCK, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "r+b") as lock:
            meta = os.fstat(lock.fileno())
            if not stat.S_ISREG(meta.st_mode) or meta.st_uid != 0 or stat.S_IMODE(meta.st_mode) != 0o600:
                raise Stop("UNSAFE_OPERATOR_LOCK")
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            {"install": install, "install-https": lambda: install("https"),
             "rollback": rollback, "status": status}[args.action]()
        return 0
    except Exception as exc:
        # Only our fixed internal codes; raw errors may contain local data.
        code = str(exc) if isinstance(exc, Stop) else type(exc).__name__
        print("63D54_STOP=" + code, flush=True)
        return 2


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
