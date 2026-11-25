"""Root-only immutable native RDP release entrypoint (Viborg1 gate retained)."""
from __future__ import annotations

import hashlib
import os
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
