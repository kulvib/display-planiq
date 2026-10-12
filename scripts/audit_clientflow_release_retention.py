#!/usr/bin/env python3
"""Read-only Render release-store audit for a three-approved-release retention plan.

Never deletes artifacts, updates the release catalog, or authorizes rollback.
Run *inside* the backend runtime, where Render's persistent disk is mounted.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from clientflow_release_format.bundle import (  # noqa: E402
    BundleFormatError,
    open_verified_bundle_structure,
)

RELEASE_FILE = re.compile(r"^clientflow-(\d+\.\d+\.\d+)-seq-([1-9]\d*)\.tar$")
KEEP_LATEST_APPROVED = 3
# Minimum free space to leave on the 1-GB disk while staging a new artifact.
# The artifact itself also needs temporary space during immutable publication.
RESERVED_FREE_BYTES = 64 * 1024 * 1024


class StoreAuditError(RuntimeError):
    pass


def _check_directory(directory: Path) -> None:
    if not directory.is_absolute():
        raise StoreAuditError("Release-store path must be absolute")
    try:
        st = directory.lstat()
    except FileNotFoundError as exc:
        raise StoreAuditError("Release-store directory does not exist") from exc
    if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode):
        raise StoreAuditError("Release-store must be a real directory, not a symlink")
    if st.st_mode & 0o022 or st.st_uid not in {0, os.geteuid()}:
        raise StoreAuditError("Release-store has insecure permissions or owner")


def inspect_store(directory: Path, *, require_three: bool = False) -> dict:
    """Inventory immutable approved artifacts; never mutate the store.

    A corrupt or unapproved artifact *cannot* count toward the protected three.
    If *any* artifact is untrusted, fail closed rather than suggest pruning.
    """
    _check_directory(directory)
    artifacts = []
    seen_versions = set()
    seen_sequences = set()
    invalid = []

    with os.scandir(directory) as entries:
        for entry in entries:
            name = entry.name
            # The store can contain publication temp files. They are not
            # approved releases and are never candidates for automatic removal.
            if not name.startswith("clientflow-") or not name.endswith(".tar"):
                continue
            match = RELEASE_FILE.fullmatch(name)
            if match is None:
                invalid.append({"file": name, "reason": "noncanonical artifact filename"})
                continue
            try:
                meta = entry.stat(follow_symlinks=False)
                if not stat.S_ISREG(meta.st_mode) or meta.st_mode & 0o022:
                    raise StoreAuditError("not a secure regular file")
                if meta.st_uid not in {0, os.geteuid()}:
                    raise StoreAuditError("unexpected file owner")
                # The format library opens the artifact with O_NOFOLLOW and
                # verifies archive, payload, installer, approval and byte hash.
                manifest, _payload, size, sha, handle = open_verified_bundle_structure(
                    directory / name, require_deployable=True,
                )
                try:
                    fd_stat = os.fstat(handle.fileno())
                    if not stat.S_ISREG(fd_stat.st_mode) or fd_stat.st_mode & 0o022:
                        raise StoreAuditError("open artifact has insecure permissions")
                    if fd_stat.st_uid not in {0, os.geteuid()}:
                        raise StoreAuditError("open artifact has unexpected owner")
                    if (fd_stat.st_dev, fd_stat.st_ino) != (meta.st_dev, meta.st_ino):
                        raise StoreAuditError("artifact was replaced while auditing")
                finally:
                    handle.close()
                version, sequence = match.group(1), int(match.group(2))
                if (
                    manifest.get("release_id") != name[:-4]
                    or manifest.get("version") != version
                    or manifest.get("release_sequence") != sequence
                ):
                    raise StoreAuditError("filename and approved manifest disagree")
                if version in seen_versions or sequence in seen_sequences:
                    raise StoreAuditError("duplicate version or release sequence")
                seen_versions.add(version)
                seen_sequences.add(sequence)
                artifacts.append({
                    "release_id": name[:-4],
                    "release_sequence": sequence,
                    "version": version,
                    "size_bytes": size,
                    "sha256": sha,
                    "approval_reference": manifest["release_approval"]["reference"],
                    "source_commit": manifest["source"]["commit"],
                })
            except (BundleFormatError, StoreAuditError, OSError, ValueError, KeyError) as exc:
                invalid.append({"file": name, "reason": str(exc)})

    artifacts.sort(key=lambda item: item["release_sequence"], reverse=True)
    protected = artifacts[:KEEP_LATEST_APPROVED]
    older = artifacts[KEEP_LATEST_APPROVED:]
    vfs = os.statvfs(directory)
    available = vfs.f_bavail * vfs.f_frsize
    result = {
        "mode": "read_only",
        "retention_target": KEEP_LATEST_APPROVED,
        "approved_count": len(artifacts),
        "retention_ready": len(protected) == KEEP_LATEST_APPROVED and not invalid,
        "protected_latest": protected,
        "older_review_only": older,
        "invalid_artifacts": invalid,
        "disk_available_bytes": available,
        "disk_total_bytes": vfs.f_blocks * vfs.f_frsize,
        # Publishing writes a same-filesystem temporary copy. Any extra
        # release first needs at least this much real free space.
        "max_new_bundle_bytes_with_reserve": max(0, available - RESERVED_FREE_BYTES),
        "automatic_deletion_enabled": False,
        "rollback_enabled": False,
    }
    if invalid:
        raise StoreAuditError("Unsafe release store: " + json.dumps(result, ensure_ascii=False))
    if require_three and not result["retention_ready"]:
        raise StoreAuditError("Fewer than three verified approved releases: " + json.dumps(result, ensure_ascii=False))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--require-three", action="store_true",
                        help="fail if fewer than three verified approved bundles exist")
    args = parser.parse_args(argv)
    try:
        directory = args.artifact_dir
        if directory is None:
            configured = os.getenv("CLIENTFLOW_RELEASE_ARTIFACT_DIR")
            if not configured:
                raise StoreAuditError("Set CLIENTFLOW_RELEASE_ARTIFACT_DIR or --artifact-dir")
            directory = Path(configured)
        result = inspect_store(directory, require_three=args.require_three)
    except (StoreAuditError, OSError) as exc:
        print(f"RELEASE_STORE_AUDIT=FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    print("RELEASE_STORE_AUDIT=PASS")
    print("RELEASE_RETENTION_READY=" + ("YES" if result["retention_ready"] else "NO"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
