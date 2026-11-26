"""Root-only immutable native RDP release entrypoint."""
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
    "clientflow_63d29_persistent_rdp_guard.py": "b1ece1303f524fd81b2ea7d86c4a3131cf26cf1bb343c0e4025ed8e9a84231fa",
    "clientflow_63d30_local_rdp_pilot.py": "3cbe65ead5c1c520eeda6767bf4fae36c96bc74dbc2ac6fd25e8af320f97ee5e",
    "clientflow_native_rdp_browser_pilot.py": "a347e87f013a45f15d125eb7f74f0b6210e1bba302894744f2414ee2290167ff",
    "clientflow_63d49_autologin_broker.py": "eb46d11c76825764e6dd601bb5f8f286ebc5729a4fe2ba3c755c89c0ed9a572c",
    "clientflow_63d53_rdp_proof.py": "9a610abf8c2e7f9eb1d41f6c81add9eaa4d79a1ec15ba4873fea9deba64c9790",
    "clientflow_63d53_rdp_lifecycle.py": "a7aa44dcd016574a8613e498a3410ac2e8e063266018d706513f56b1b18be941",
    "clientflow_63d53_rdp_ipc.py": "17b7145b1236edf4811108b90015cbc6d54fb0e2e7f255431839549b5204ee4a",
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
    client_id = verify_installed_identity(active)
    sys.path.insert(0, str(directory))
    from scripts import clientflow_63d53_rdp_ipc as ipc
    from scripts import clientflow_63d53_rdp_lifecycle as lifecycle
    from scripts import clientflow_63d53_rdp_proof as proof
    proof.EXPECTED_CLIENT_ID = client_id
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
