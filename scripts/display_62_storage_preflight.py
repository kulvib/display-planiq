#!/usr/bin/env python3
"""62A: read-only PlanIQ Display single-node storage/cutover preflight.

No network, SQL, database commands, secrets, mutation, backup or gate changes.
This is NOT a backup, restore validation or migration authorization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat

RELEASE_ID_RE = re.compile(r"clientflow-\d+\.\d+\.\d+-seq-[1-9]\d*\Z")
SHA_RE = re.compile(r"[a-f0-9]{64}\Z")


def _check_directory(path: Path, results: dict, key: str, *, private: bool = False) -> bool:
    try:
        data = path.lstat()
        valid = stat.S_ISDIR(data.st_mode) and not stat.S_ISLNK(data.st_mode)
        if private:
            valid = valid and not (data.st_mode & 0o077)
        else:
            valid = valid and not (data.st_mode & 0o002)
    except OSError:
        valid = False
    results[key] = bool(valid)
    return bool(valid)


def _check_pg_version(path: Path, results: dict) -> None:
    try:
        data = path.lstat()
        if not stat.S_ISREG(data.st_mode) or stat.S_ISLNK(data.st_mode):
            results["pg_version_18"] = False
            return
        with path.open("rb") as handle:
            results["pg_version_18"] = handle.read(16).strip() == b"18"
    except OSError:
        results["pg_version_18"] = False


def _sha256_verified_file(path: Path, *, expected_sha: str, expected_size: int) -> tuple[bool, int]:
    """Pin an ordinary non-world-writable file descriptor and hash its bytes."""
    handle = None
    try:
        handle = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
        before = os.fstat(handle)
        if (not stat.S_ISREG(before.st_mode) or before.st_mode & 0o022
                or before.st_size <= 0 or (expected_size and before.st_size != expected_size)):
            return False, 0
        digest = hashlib.sha256()
        while True:
            chunk = os.read(handle, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(handle)
        return (digest.hexdigest() == expected_sha
                and (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)), before.st_size
    except OSError:
        return False, 0
    finally:
        if handle is not None:
            os.close(handle)


def storage_preflight(mount: Path, *, release_id: str, expected_sha: str, expected_size: int = 0) -> dict:
    """Only inspect the local disk. Never claim to verify logical data or backup."""
    if not RELEASE_ID_RE.fullmatch(release_id) or not SHA_RE.fullmatch(expected_sha):
        raise ValueError("Invalid immutable release identity or lowercase SHA256")
    if expected_size < 0:
        raise ValueError("Invalid artifact size")
    mount = Path(mount)
    if not mount.is_absolute():
        raise ValueError("Absolute storage mount path required")
    checks: dict[str, bool] = {}
    # Detect a symlink on the requested mount itself or on a parent; do not
    # silently follow a different release authority through a symlink.
    try:
        checks["mount_path_not_redirected"] = mount.resolve(strict=True) == mount
    except (OSError, RuntimeError):
        checks["mount_path_not_redirected"] = False
    _check_directory(mount, checks, "mount_is_directory")
    pg = mount / "postgres" / "data"
    _check_directory(mount / "postgres", checks, "postgres_parent_exists")
    _check_directory(pg, checks, "pgdata_private", private=True)
    _check_pg_version(pg / "PG_VERSION", checks)
    _check_directory(pg / "base", checks, "pg_base_exists")
    _check_directory(pg / "global", checks, "pg_global_exists")
    _check_directory(pg / "pg_wal", checks, "pg_wal_exists")
    control = pg / "global" / "pg_control"
    try:
        meta = control.lstat()
        checks["pg_control_regular"] = stat.S_ISREG(meta.st_mode) and not stat.S_ISLNK(meta.st_mode)
    except OSError:
        checks["pg_control_regular"] = False

    store = mount / "store"
    _check_directory(store, checks, "release_store_exists")
    if checks["release_store_exists"]:
        checks["release_store_restricted"] = not (store.stat().st_mode & 0o022)
    else:
        checks["release_store_restricted"] = False
    file_path = store / f"{release_id}.tar"
    verified, size = _sha256_verified_file(file_path, expected_sha=expected_sha, expected_size=expected_size)
    checks["stable_release_sha256_matches"] = verified

    try:
        volume = os.statvfs(mount)
        free_bytes = volume.f_bavail * volume.f_frsize
    except OSError:
        free_bytes = None
    # Disk free is informational, NOT a storage migration or backup proof.
    return {
        "schema": "planiq-display-62a-storage-preflight-v1",
        "mode": "read_only",
        "checks": checks,
        "checks_passed": sum(bool(v) for v in checks.values()),
        "checks_total": len(checks),
        "storage_preflight_ok": all(checks.values()),
        "stable_release_id": release_id,
        "verified_artifact_bytes": size if verified else 0,
        "volume_free_bytes_observed": free_bytes,
        "backup_verified": False,
        "restore_verified": False,
        "database_cutover_authorized": False,
        "deployment_authorized": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mount", default="/var/data/clientflow-release-artifacts")
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-size", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        result = storage_preflight(Path(args.mount), release_id=args.release_id,
                                   expected_sha=args.expected_sha256, expected_size=args.expected_size)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["storage_preflight_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
