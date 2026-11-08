#!/usr/bin/env python3
"""No-replace, verified, NON-DESTRUCTIVE backup of an approved ClientFlow TAR.

The operator must independently export the verified archive outside Render
before authorizing any later retention cleanup. This command NEVER deletes a
source release or authorizes a pilot/deployment/catalog change.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import os
from pathlib import Path
import re
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "client" / "release" / "lib"))

from scripts.audit_clientflow_release_retention import inspect_store  # noqa: E402
from scripts.publish_clientflow_release import _open_published_file, _open_secure_directory  # noqa: E402

RELEASE_RE = re.compile(r"^clientflow-\d+\.\d+\.\d+-seq-[1-9]\d*$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
MIN_FREE_BYTES = 64 * 1024 * 1024


class ArchiveDenied(RuntimeError):
    pass


def _hash_fd(fd: int) -> tuple[int, str]:
    os.lseek(fd, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    length = 0
    while data := os.read(fd, 1024 * 1024):
        length += len(data)
        digest.update(data)
    return length, digest.hexdigest()


def verified_archive(
    source_store: Path,
    archive_dir: Path,
    *,
    release_id: str,
    expected_sha256: str,
    make_archive: bool = False,
) -> dict:
    if not RELEASE_RE.fullmatch(release_id):
        raise ArchiveDenied("Exact canonical release ID required")
    if not SHA_RE.fullmatch(expected_sha256):
        raise ArchiveDenied("Exact approved 64-digit lowercase SHA-256 required")
    if not source_store.is_absolute() or not archive_dir.is_absolute():
        raise ArchiveDenied("Source and archive paths must both be absolute")
    # Use canonical physical location checks to forbid archiving into the live
    # release-store (which would break its approved TAR inventory).
    if source_store.resolve() == archive_dir.resolve() or source_store.resolve() in archive_dir.resolve().parents:
        raise ArchiveDenied("Archive destination must be outside the active release store")
    source_fd = _open_secure_directory(source_store)
    dest_fd = None
    try:
        # A verified snapshot validates every existing approved release before
        # this tool may copy anything. Approved count above retention limit is
        # permitted in read-only audit, but never implicitly authorizes pruning.
        snapshot = inspect_store(source_store)
        records = snapshot["protected_latest"] + snapshot["older_review_only"]
        matching = [row for row in records if row["release_id"] == release_id]
        if len(matching) != 1 or matching[0]["sha256"] != expected_sha256:
            raise ArchiveDenied("Requested release is not an exact verified store artifact")
        size = matching[0]["size_bytes"]
        source_name = release_id + ".tar"
        source_file_fd = _open_published_file(source_fd, source_name)
        try:
            actual_size, actual_sha = _hash_fd(source_file_fd)
            if (actual_size, actual_sha) != (size, expected_sha256):
                raise ArchiveDenied("Verified source changed after store audit")
            result = {
                "release_id": release_id,
                "approved_sha256": expected_sha256,
                "approved_size": size,
                "source_store_unchanged": True,
                "archive_directory": str(archive_dir),
                "operator_offsite_backup_still_required": True,
            }
            if not make_archive:
                return {**result, "mode": "read_only_archive_preflight", "archived": False}

            dest_fd = _open_secure_directory(archive_dir)
            if os.fstat(source_fd).st_dev != os.fstat(dest_fd).st_dev:
                # Cross-device backups are also valid, but don't pretend we
                # can fsync the remote mount's durability semantics.
                pass
            fcntl.flock(dest_fd, fcntl.LOCK_EX)
            destination = source_name
            try:
                old_fd = _open_published_file(dest_fd, destination)
            except FileNotFoundError:
                old_fd = None
            if old_fd is not None:
                try:
                    if _hash_fd(old_fd) != (size, expected_sha256):
                        raise ArchiveDenied("Archive filename exists with different bytes")
                finally:
                    os.close(old_fd)
                return {**result, "mode": "already_archived_verified", "archived": True}

            available = os.fstatvfs(dest_fd)
            if available.f_bavail * available.f_frsize < size + MIN_FREE_BYTES:
                raise ArchiveDenied("Insufficient space for verified archive and 64 MiB reserve")
            temporary_name = f".{release_id}.{secrets.token_hex(12)}.archive"
            temp_fd = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600, dir_fd=dest_fd,
            )
            try:
                os.lseek(source_file_fd, 0, os.SEEK_SET)
                output_hash = hashlib.sha256()
                copied = 0
                with os.fdopen(temp_fd, "wb") as destination_file:
                    temp_fd = -1
                    while data := os.read(source_file_fd, 1024 * 1024):
                        destination_file.write(data)
                        output_hash.update(data)
                        copied += len(data)
                    destination_file.flush()
                    os.fsync(destination_file.fileno())
                if (copied, output_hash.hexdigest()) != (size, expected_sha256):
                    raise ArchiveDenied("Archive copy checksum does not match approved bytes")
                if _hash_fd(source_file_fd) != (size, expected_sha256):
                    raise ArchiveDenied("Original approved source changed while archiving")
                try:
                    os.link(temporary_name, destination, src_dir_fd=dest_fd, dst_dir_fd=dest_fd, follow_symlinks=False)
                except FileExistsError:
                    # Never replace an existing archive, even if a concurrent
                    # process raced. Re-read to verify exact bytes.
                    existing_fd = _open_published_file(dest_fd, destination)
                    try:
                        if _hash_fd(existing_fd) != (size, expected_sha256):
                            raise ArchiveDenied("Concurrent archive has incompatible bytes")
                    finally:
                        os.close(existing_fd)
                os.fsync(dest_fd)
            finally:
                if temp_fd >= 0:
                    os.close(temp_fd)
                try:
                    os.unlink(temporary_name, dir_fd=dest_fd)
                except FileNotFoundError:
                    pass
            final_fd = _open_published_file(dest_fd, destination)
            try:
                if _hash_fd(final_fd) != (size, expected_sha256):
                    raise ArchiveDenied("Postflight archive checksum mismatch")
            finally:
                os.close(final_fd)
            return {**result, "mode": "verified_non_destructive_archive", "archived": True}
        finally:
            os.close(source_file_fd)
    finally:
        if dest_fd is not None:
            os.close(dest_fd)
        os.close(source_fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-store", required=True, type=Path)
    parser.add_argument("--archive-dir", required=True, type=Path)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--create-verified-archive", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = verified_archive(
            args.source_store, args.archive_dir,
            release_id=args.release_id, expected_sha256=args.expected_sha256,
            make_archive=args.create_verified_archive,
        )
    except (ArchiveDenied, OSError, RuntimeError, ValueError) as exc:
        print(f"CLIENTFLOW_ARCHIVE=BLOCKED: {exc}", file=sys.stderr)
        return 1
    import json
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    print("CLIENTFLOW_ARCHIVE=" + ("VERIFIED" if result["archived"] else "READ_ONLY_PASS"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
