#!/usr/bin/env python3
"""62B: operator-invoked, non-authorizing Display backup staging and hash evidence.

Capture reads the live local database with pg_dump (no database writes) and
copies immutable release TAR files to a private *separate staging directory*.
The output is NOT a verified off-site backup or a restore proof. No Render,
release approval, deployment or database cutover is performed.

Verify only hashes previously captured bytes; a real isolated PostgreSQL
pg_restore is a separate mandatory acceptance gate.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import uuid

from display_62_storage_preflight import storage_preflight

SCHEMA = "planiq-display-62b-backup-staging-v1"
RELEASE_RE = re.compile(r"clientflow-\d+\.\d+\.\d+-seq-[1-9]\d*\.tar\Z")
SHA_RE = re.compile(r"[a-f0-9]{64}\Z")
CHUNK = 1024 * 1024


class BackupEvidenceError(RuntimeError):
    pass


def _safe_dir(path: Path, *, private: bool = False) -> None:
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise BackupEvidenceError("directory_missing_or_redirected")
    meta = path.lstat()
    mode = meta.st_mode
    if private and meta.st_uid != os.geteuid():
        raise BackupEvidenceError("private_stage_owner_mismatch")
    if not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
        raise BackupEvidenceError("directory_not_regular")
    if mode & (0o077 if private else 0o002):
        raise BackupEvidenceError("directory_permissions_unsafe")


def _open_regular(path: Path) -> tuple[int, os.stat_result]:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022:
        os.close(fd)
        raise BackupEvidenceError("source_file_unsafe")
    return fd, info


def _copy_hashed(source: Path, dest: Path) -> tuple[str, int]:
    """No symlink following and no same-file mutation during capture."""
    src_fd, first = _open_regular(source)
    out_fd = None
    try:
        out_fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        digest, size = hashlib.sha256(), 0
        while True:
            block = os.read(src_fd, CHUNK)
            if not block:
                break
            digest.update(block)
            size += len(block)
            view = memoryview(block)
            while view:
                written = os.write(out_fd, view)
                if written <= 0:
                    raise BackupEvidenceError("destination_write_failed")
                view = view[written:]
        os.fsync(out_fd)
        last = os.fstat(src_fd)
        if ((first.st_dev, first.st_ino, first.st_size, first.st_mtime_ns)
                != (last.st_dev, last.st_ino, last.st_size, last.st_mtime_ns)):
            raise BackupEvidenceError("source_changed_during_capture")
        if size != first.st_size:
            raise BackupEvidenceError("capture_truncated")
        return digest.hexdigest(), size
    finally:
        os.close(src_fd)
        if out_fd is not None:
            os.close(out_fd)


def _hash_regular(path: Path) -> tuple[str, int]:
    fd, first = _open_regular(path)
    try:
        h, size = hashlib.sha256(), 0
        while True:
            data = os.read(fd, CHUNK)
            if not data:
                break
            h.update(data)
            size += len(data)
        last = os.fstat(fd)
        if ((first.st_dev, first.st_ino, first.st_size, first.st_mtime_ns)
                != (last.st_dev, last.st_ino, last.st_size, last.st_mtime_ns)):
            raise BackupEvidenceError("file_changed_during_verify")
        return h.hexdigest(), size
    finally:
        os.close(fd)


def _dump_local_database(dest: Path, *, socket: Path) -> tuple[str, int]:
    """Read-only logical dump via the local peer-auth socket, never via TCP."""
    if not socket.is_absolute() or socket != Path('/run/display-postgres'):
        raise BackupEvidenceError("noncanonical_database_socket")
    # Avoid PG* environment overrides that could redirect a privileged export.
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG") and k not in {"DATABASE_URL"}}
    env["PGCONNECT_TIMEOUT"] = "5"
    cmd = ["pg_dump", "--no-password", "--format=custom", "--no-owner", "--no-acl",
           "--host=/run/display-postgres", "--username=display_app", "--dbname=display"]
    if os.geteuid() == 0:
        cmd = ["gosu", "display_app", *cmd]
    out_fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    with os.fdopen(out_fd, 'wb') as output:
        try:
            completed = subprocess.run(
                cmd, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.PIPE,
                env=env, timeout=1800, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BackupEvidenceError("pg_dump_failed_or_timed_out") from exc
        output.flush()
        os.fsync(output.fileno())
    if completed.returncode:
        # Deliberately do not echo pg_dump stderr (could include private DB names).
        raise BackupEvidenceError("pg_dump_nonzero_exit")
    digest, size = _hash_regular(dest)
    if size < 5:
        raise BackupEvidenceError("pg_dump_empty")
    fd, _ = _open_regular(dest)
    try:
        if os.read(fd, 5) != b'PGDMP':
            raise BackupEvidenceError("pg_dump_invalid_header")
    finally:
        os.close(fd)
    return digest, size


def _write_manifest(path: Path, manifest: dict) -> None:
    encoded = (json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        raise


def capture(mount: Path, target_parent: Path, *, release_id: str,
            expected_sha256: str, expected_size: int) -> dict:
    """Stage one consistent logical DB dump and all currently visible release TARs.

    Repository deployment approval, backup off-site acceptance and restore proof
    are *never* set by this script. For formal recovery, verify + isolated
    restore and independent protected offsite copy are required.
    """
    preflight = storage_preflight(mount, release_id=release_id,
                                 expected_sha=expected_sha256, expected_size=expected_size)
    if not preflight['storage_preflight_ok']:
        raise BackupEvidenceError("62a_source_storage_preflight_failed")
    _safe_dir(target_parent, private=True)
    # Stage outside the live persistent mount; also reject paths nested below
    # the source via symlink resolution. Offsite durability is NOT implied.
    if target_parent == mount or mount in target_parent.parents or target_parent in mount.parents:
        raise BackupEvidenceError("backup_stage_must_be_separate")
    _safe_dir(mount)
    releases = []
    store = mount / 'store'
    for item in sorted(store.iterdir()):
        if item.name.endswith('.tar'):
            if not RELEASE_RE.fullmatch(item.name):
                raise BackupEvidenceError("unrecognized_release_tar_in_store")
            releases.append(item)
    if not releases or f'{release_id}.tar' not in {p.name for p in releases}:
        raise BackupEvidenceError("stable_release_not_in_capture")

    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    stage = target_parent / f'planiq-display-62b-{stamp}-{uuid.uuid4().hex[:12]}'
    stage.mkdir(mode=0o700)
    try:
        (stage / 'releases').mkdir(mode=0o700)
        db_sha, db_size = _dump_local_database(stage / 'database.pgdump', socket=Path('/run/display-postgres'))
        entry = []
        for source in releases:
            sha, size = _copy_hashed(source, stage / 'releases' / source.name)
            if source.name == f'{release_id}.tar' and (sha != expected_sha256 or size != expected_size):
                raise BackupEvidenceError("stable_release_changed_since_preflight")
            entry.append({'filename': source.name, 'sha256': sha, 'size': size})
        if {p.name for p in store.iterdir() if p.name.endswith('.tar')} != {p.name for p in releases}:
            raise BackupEvidenceError('release_inventory_changed_during_capture')
        manifest = {
            'schema': SCHEMA,
            'captured_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'db': {'filename': 'database.pgdump', 'format': 'pg_dump_custom',
                   'sha256': db_sha, 'size': db_size},
            'releases': entry,
            'stable_release_id': release_id,
            'stable_sha256': expected_sha256,
            'independent_device_observed': mount.stat().st_dev != target_parent.stat().st_dev,
            'backup_offsite_verified': False,
            'backup_restored_to_isolated_postgres': False,
            'database_cutover_authorized': False,
            'deployment_authorized': False,
        }
        _write_manifest(stage / 'manifest.json', manifest)
        # Ensure directory metadata is durable before operator takes custody.
        dir_fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        return {'stage': str(stage), 'manifest': manifest}
    except BaseException:
        # Only remove a directory created exclusively by this run.
        shutil.rmtree(stage)
        raise


def verify(stage: Path) -> dict:
    """Filesystem-only evidence check. NOT a database restore or backup approval."""
    _safe_dir(stage, private=True)
    manifest_path = stage / 'manifest.json'
    fd, st = _open_regular(manifest_path)
    try:
        if st.st_size > 32768:
            raise BackupEvidenceError('manifest_too_large')
        with os.fdopen(fd, 'rb') as h:
            payload = h.read()
            fd = -1
    finally:
        if fd >= 0:
            os.close(fd)
    try:
        m = json.loads(payload)
    except (ValueError, UnicodeDecodeError) as exc:
        raise BackupEvidenceError('invalid_manifest_json') from exc
    if not isinstance(m, dict) or m.get('schema') != SCHEMA:
        raise BackupEvidenceError('unknown_manifest_schema')
    if any(m.get(k) is not False for k in ('backup_offsite_verified', 'backup_restored_to_isolated_postgres',
               'database_cutover_authorized', 'deployment_authorized')):
        raise BackupEvidenceError('manifest_claims_unearned_authorization')
    db = m.get('db')
    if not isinstance(db, dict) or db.get('filename') != 'database.pgdump' or db.get('format') != 'pg_dump_custom':
        raise BackupEvidenceError('unexpected_database_artifact')
    releases = m.get('releases')
    if not isinstance(releases, list) or not releases or len(releases) > 200 or len(releases) != len({x.get('filename') for x in releases if isinstance(x, dict)}):
        raise BackupEvidenceError('invalid_release_inventory')
    expected_release = m.get('stable_release_id')
    expected_sha = m.get('stable_sha256')
    if not isinstance(expected_release,str) or not RELEASE_RE.fullmatch(expected_release + '.tar') or not isinstance(expected_sha,str) or not SHA_RE.fullmatch(expected_sha):
        raise BackupEvidenceError('invalid_stable_release')
    _safe_dir(stage / 'releases', private=True)
    observed = {'manifest.json', 'database.pgdump', 'releases'}
    if {p.name for p in stage.iterdir()} != observed:
        raise BackupEvidenceError('unexpected_stage_entries')
    checked = []
    for item in [db, *releases]:
        if not isinstance(item, dict) or not isinstance(item.get('sha256'), str) or not SHA_RE.fullmatch(item['sha256']) or type(item.get('size')) is not int or item['size'] <= 0:
            raise BackupEvidenceError('invalid_file_evidence')
        name = item['filename']
        if item is db:
            file_path = stage / 'database.pgdump'
        elif isinstance(name, str) and RELEASE_RE.fullmatch(name):
            file_path = stage / 'releases' / name
        else:
            raise BackupEvidenceError('invalid_release_filename')
        digest, count = _hash_regular(file_path)
        if digest != item['sha256'] or count != item['size']:
            raise BackupEvidenceError('capture_sha256_mismatch')
        checked.append(name)
    if set(p.name for p in (stage/'releases').iterdir()) != set(checked[1:]):
        raise BackupEvidenceError('unexpected_release_files')
    stable = [x for x in releases if x['filename'] == f'{expected_release}.tar']
    if len(stable) != 1 or stable[0]['sha256'] != expected_sha:
        raise BackupEvidenceError('stable_release_identity_mismatch')
    fd, _ = _open_regular(stage / 'database.pgdump')
    try:
        if os.read(fd, 5) != b'PGDMP':
            raise BackupEvidenceError('invalid_database_dump_magic')
    finally:
        os.close(fd)
    return {'schema': SCHEMA, 'stage_bytes_hash_verified': True,
            'verified_file_count': len(checked), 'stable_release_sha256': expected_sha,
            'backup_offsite_verified': False, 'backup_restored_to_isolated_postgres': False,
            'database_cutover_authorized': False, 'deployment_authorized': False}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--verify-stage', type=Path)
    g.add_argument('--capture', action='store_true')
    p.add_argument('--mount', type=Path, default=Path('/var/data/clientflow-release-artifacts'))
    p.add_argument('--stage-parent', type=Path)
    p.add_argument('--release-id', default='clientflow-1.3.44-seq-1245')
    p.add_argument('--expected-sha256', default='28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5')
    p.add_argument('--expected-size', type=int, default=223610880)
    args = p.parse_args(argv)
    try:
        if args.verify_stage:
            result = verify(args.verify_stage)
        else:
            if args.stage_parent is None:
                p.error('--capture requires --stage-parent on a separately controlled private directory')
            result = capture(args.mount, args.stage_parent, release_id=args.release_id,
                             expected_sha256=args.expected_sha256, expected_size=args.expected_size)
    except (BackupEvidenceError, ValueError, OSError) as exc:
        # Never output environment details or SQL errors.
        print('62B STOP: ' + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
