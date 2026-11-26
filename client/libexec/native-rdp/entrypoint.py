"""Root-only immutable native RDP release entrypoint (Viborg1 gate retained)."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import stat
import sys

PINS = {
    "clientflow_63d29_persistent_rdp_guard.py": "709a5d9b1eba3364dfd2ac21f4e24525b0dc3261236456a9127aac7cfd54c000",
    "clientflow_63d30_local_rdp_pilot.py": "78972f7c7173a4894abc22d4518b1fc4d3189c76e30dd463715af03ef069af69",
    "clientflow_native_rdp_browser_pilot.py": "02c63fc10deb3c0329c5309bdcb19a0edf8fa694c1c0045257cd79c304849e7f",
    "clientflow_63d49_autologin_broker.py": "00dc81e3215b3605503cbd03ed8a3ebcc899b8489bb268a0668f5c98c4a7445e",
    "clientflow_63d53_rdp_proof.py": "daec30c30191f3dd6d9b0b4b12b773023bf5287ff34379150ef1b14f0df2e4f6",
    "clientflow_63d53_rdp_lifecycle.py": "5ee6afc5d8bf5a3d4401f77d8f36bb8eda47e1fcaea210466af0755bc9a8e2bb",
    "clientflow_63d53_rdp_ipc.py": "393c971b624ad7805f3cec5c395184200c8831e8d8d8033c309acaed6a0c7b7f",
    "__init__.py": "2ecd4ea28f445c6a1f4cf7d8ebecc07cee9ff55ee138cd945f3fb2defcb2676d"
}
ACTIVE = Path("/opt/clientflow/active")
RELEASES = Path("/opt/clientflow/releases")


def verify_sources(directory: Path) -> None:
    for folder in (directory, directory / "scripts"):
        meta = folder.lstat()
        if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != 0 or meta.st_mode & 0o022:
            raise RuntimeError("RDP_SOURCE_DIRECTORY_UNSAFE")
    for name, expected in PINS.items():
        path = directory / "scripts" / name
        meta = path.lstat()
        if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != 0 or meta.st_mode & 0o022
                or not 0 < meta.st_size <= 128 * 1024
                or hashlib.sha256(path.read_bytes()).hexdigest() != expected):
            raise RuntimeError("RDP_SOURCE_MISMATCH")


def _trusted_directory(path: Path) -> None:
    meta = path.lstat()
    if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != os.geteuid() or meta.st_mode & 0o022:
        raise RuntimeError("RDP_INSTALLATION_DIRECTORY_UNSAFE")


def _trusted_json(path: Path, *, limit: int, private: bool = True) -> dict:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as stream:
        meta = os.fstat(stream.fileno())
        forbidden = 0o077 if private else 0o022
        if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.geteuid()
                or meta.st_mode & forbidden or not 0 < meta.st_size <= limit):
            raise RuntimeError("RDP_INSTALLATION_FILE_UNSAFE")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError("RDP_INSTALLATION_FILE_TOO_LARGE")
    value = json.loads(data)
    if type(value) is not dict:
        raise RuntimeError("RDP_INSTALLATION_FILE_INVALID")
    return value


def verify_installed_identity(active: Path, *, root: Path = Path("/")) -> int:
    """Host-local admission for a committed, bundle-bound canonical release.

    This is not a backend or browser authorization and does not open any
    network endpoint. The root-owned transaction lock is read, never created.
    """
    if root == Path("/") and os.geteuid() != 0:
        raise RuntimeError("RDP_INSTALLATION_ROOT_REQUIRED")
    install = root / "opt/clientflow"
    state_dir = root / "var/lib/clientflow/release"
    identity_dir = root / "etc/clientflow"
    for folder in (root / "opt", install, install / "releases", active,
                   root / "var", root / "var/lib", state_dir.parent, state_dir,
                   root / "etc", identity_dir):
        _trusted_directory(folder)
    link = install / "active"
    link_meta = link.lstat()
    if (not stat.S_ISLNK(link_meta.st_mode) or link_meta.st_uid != os.geteuid()
            or link.resolve(strict=True) != active or active.parent != install / "releases"):
        raise RuntimeError("RDP_INSTALLATION_ACTIVE_MISMATCH")
    match = re.fullmatch(r"clientflow-([0-9]+\.[0-9]+\.[0-9]+)-seq-([1-9][0-9]*)", active.name)
    if not match:
        raise RuntimeError("RDP_INSTALLATION_RELEASE_INVALID")
    version, sequence_text = match.groups()
    sequence = int(sequence_text)
    if sequence < 1250 or tuple(map(int, version.split("."))) < (1, 4, 0):
        raise RuntimeError("RDP_INSTALLATION_RELEASE_TOO_OLD")
    fd = os.open(state_dir / "transaction.lock", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        meta = os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.geteuid() or meta.st_mode & 0o077:
            raise RuntimeError("RDP_INSTALLATION_LOCK_UNSAFE")
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        lock_meta = (state_dir / "transaction.lock").lstat()
        if (meta.st_dev, meta.st_ino) != (lock_meta.st_dev, lock_meta.st_ino):
            raise RuntimeError("RDP_INSTALLATION_LOCK_CHANGED")
        identity = _trusted_json(identity_dir / "identity.json", limit=64 * 1024)
        client_id = identity.get("client_id")
        if (type(identity.get("schema_version")) is not int or identity["schema_version"] != 1
                or type(client_id) is not int or client_id <= 0
                or ("CLIENT_ID" in identity and str(identity["CLIENT_ID"]) != str(client_id))
                or identity.get("kiosk_user") != "clientflow-kiosk"):
            raise RuntimeError("RDP_INSTALLATION_IDENTITY_INVALID")
        journal = _trusted_json(state_dir / "state.json", limit=8 * 1024 * 1024)
        installed = journal.get("installed")
        record = installed.get(active.name) if isinstance(installed, dict) else None
        if (type(journal.get("schema_version")) is not int or journal["schema_version"] != 2
                or journal.get("active_release_id") != active.name
                or journal.get("activation_intent") is not None
                or journal.get("staged_release_id") is not None
                or type(journal.get("highest_release_sequence")) is not int
                or journal["highest_release_sequence"] < sequence
                or not isinstance(record, dict)
                or record.get("version") != version
                or type(record.get("release_sequence")) is not int or record["release_sequence"] != sequence
                or not isinstance(record.get("activated_at"), str) or not record["activated_at"]):
            raise RuntimeError("RDP_INSTALLATION_NOT_COMMITTED")
        manifest = _trusted_json(active / "release-manifest.json", limit=8 * 1024 * 1024, private=False)
        ready = _trusted_json(active / "release-ready.json", limit=64 * 1024, private=False)
        for value in (manifest, ready):
            if (value.get("release_id") != active.name or value.get("version") != version
                    or type(value.get("release_sequence")) is not int or value["release_sequence"] != sequence):
                raise RuntimeError("RDP_INSTALLATION_RELEASE_MISMATCH")
        approval = manifest.get("release_approval")
        source = manifest.get("source")
        if (not isinstance(approval, dict) or not isinstance(source, dict)
                or not isinstance(approval.get("reference"), str) or not approval["reference"]
                or record.get("release_approval_reference") != approval["reference"]
                or record.get("release_candidate_sha256") != approval.get("candidate_sha256")
                or record.get("source_commit") != source.get("commit")
                or not re.fullmatch(r"[a-f0-9]{64}", str(record.get("bundle_sha256") or ""))
                or not re.fullmatch(r"[a-f0-9]{64}", str(record.get("release_candidate_sha256") or ""))
                or not re.fullmatch(r"[a-f0-9]{40}", str(record.get("source_commit") or ""))
                or type(record.get("bundle_size")) is not int or record["bundle_size"] <= 0
                or record.get("manifest_sha256") != hashlib.sha256(
                    json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()):
            raise RuntimeError("RDP_INSTALLATION_PROVENANCE_MISMATCH")
        coordinator = state_dir.parent / "install-coordinator"
        if coordinator.exists() or coordinator.is_symlink():
            _trusted_directory(coordinator)
            marker = coordinator / "state.json"
            if marker.exists() or marker.is_symlink():
                raise RuntimeError("RDP_INSTALLATION_MAINTENANCE_ACTIVE")
        if link.resolve(strict=True) != active:
            raise RuntimeError("RDP_INSTALLATION_ACTIVE_CHANGED")
        return client_id
    finally:
        os.close(fd)


def main() -> None:
    if os.geteuid() != 0 or len(sys.argv) != 2 or sys.argv[1] not in {"lifecycle", "sealer"}:
        raise RuntimeError("RDP_ENTRYPOINT_DENIED")
    active = ACTIVE.resolve(strict=True)
    directory = Path(__file__).resolve(strict=True).parent
    if active.parent != RELEASES or directory != active / "client-runtime/libexec/native-rdp":
        raise RuntimeError("RDP_ACTIVE_SOURCE_MISMATCH")
    for parent in (RELEASES, active, active / "client-runtime", active / "client-runtime/libexec"):
        meta = parent.lstat()
        if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != 0 or meta.st_mode & 0o022:
            raise RuntimeError("RDP_ACTIVE_RELEASE_UNSAFE")
    verify_sources(directory)
    verify_installed_identity(active)
    sys.path.insert(0, str(directory))
    from scripts import clientflow_63d53_rdp_ipc as ipc
    from scripts import clientflow_63d53_rdp_lifecycle as lifecycle
    lifecycle.SOURCE = directory / "scripts"
    if sys.argv[1] == "lifecycle":
        ipc.lifecycle_main()
    else:
        ipc.sealer_main()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, ImportError):
        raise SystemExit("RDP_RELEASE_ENTRYPOINT_STOP") from None
