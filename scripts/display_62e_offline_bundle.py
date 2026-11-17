#!/usr/bin/env python3
"""62E: assemble and re-verify a private, self-contained OFFLINE recovery bundle.

Never connects to a database or Render; never performs pg_restore, promotion,
cutover, or authorization. Real isolated restore is a separate operator step.
The bundle is not an encrypted offsite backup and is not a publisher signature.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

from display_62b_backup_evidence import (
    BackupEvidenceError,
    _copy_hashed,
    _hash_regular,
    _open_regular,
    _safe_dir,
    verify as verify_stage,
)
from display_62d_recovery_coverage import (
    PROTECTED_RELEASES,
    RecoveryCoverageStop,
    verify_coverage,
)

SCHEMA = 'planiq-display-62e-offline-recovery-bundle-v1'
MAX_MANIFEST_BYTES = 65536
PROTECTED_ROOTS = (Path('/var/data/clientflow-release-artifacts'),
                   Path('/opt/display'), Path('/run/display-postgres'))


class BundleStop(RuntimeError):
    pass


def _offline_private(path: Path) -> None:
    _safe_dir(path, private=True)
    if any(path == root or root in path.parents for root in PROTECTED_ROOTS):
        raise BundleStop('live_host_path_forbidden')


def _read_json(path: Path, *, maximum: int) -> dict:
    fd, info = _open_regular(path)
    try:
        if info.st_size > maximum or info.st_size <= 0:
            raise BundleStop('manifest_size_invalid')
        with os.fdopen(fd, 'rb') as handle:
            fd = -1
            data = json.load(handle)
    finally:
        if fd >= 0:
            os.close(fd)
    if not isinstance(data, dict):
        raise BundleStop('manifest_not_an_object')
    return data


def _expected_paths(stage: Path, *, protected: tuple[tuple[str, str, int], ...]) -> tuple[set[str], set[str]]:
    manifest = _read_json(stage / 'manifest.json', maximum=32768)
    releases = manifest.get('releases')
    if not isinstance(releases, list):
        raise BundleStop('invalid_stage_manifest')
    staged = {r['filename'] for r in releases}
    paths = {'stage/manifest.json', 'stage/database.pgdump'}
    paths.update('stage/releases/' + name for name in staged)
    missing = {release_id + '.tar' for release_id, _, _ in protected} - staged
    paths.update('archive/' + name for name in missing)
    return paths, missing


def _all_regular_artifacts(bundle: Path) -> set[str]:
    """Reject nested directories, extra files and symlinks at every level."""
    stage = bundle / 'stage'
    archive = bundle / 'archive'
    for folder in (bundle, stage, stage / 'releases', archive):
        _offline_private(folder)
    if {p.name for p in bundle.iterdir()} != {'bundle.json', 'stage', 'archive'}:
        raise BundleStop('unexpected_bundle_top_level_entries')
    if {p.name for p in stage.iterdir()} != {'manifest.json', 'database.pgdump', 'releases'}:
        raise BundleStop('unexpected_staged_files')
    paths = {'stage/manifest.json', 'stage/database.pgdump'}
    paths.update('stage/releases/' + p.name for p in (stage / 'releases').iterdir())
    paths.update('archive/' + p.name for p in archive.iterdir())
    return paths


def verify_bundle(bundle: Path, *, protected: tuple[tuple[str, str, int], ...] = PROTECTED_RELEASES) -> dict:
    """Re-open every bundle artifact; no restore/approval claims."""
    bundle = Path(bundle)
    _offline_private(bundle)
    if not protected or len(protected) > 3:
        raise BundleStop('invalid_protected_release_policy')
    observed = _all_regular_artifacts(bundle)
    expected, _ = _expected_paths(bundle / 'stage', protected=protected)
    if observed != expected:
        raise BundleStop('missing_or_unexpected_bundle_artifact')
    payload = _read_json(bundle / 'bundle.json', maximum=MAX_MANIFEST_BYTES)
    if payload.get('schema') != SCHEMA or payload.get('protected_release_ids') != [r[0] for r in protected]:
        raise BundleStop('bundle_policy_or_schema_drift')
    for key in ('offsite_backup_verified', 'production_isolated_restore_verified',
                'publisher_signature_verified', 'migration_authorized',
                'database_cutover_authorized', 'client_deployment_authorized'):
        if payload.get(key) is not False:
            raise BundleStop('unearned_authorization_or_proof')
    artifacts = payload.get('artifacts')
    if (not isinstance(artifacts, list) or len(artifacts) != len(expected)
            or len(artifacts) > 205):
        raise BundleStop('invalid_artifact_inventory')
    checked: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict) or set(artifact) != {'path', 'sha256', 'size'}:
            raise BundleStop('invalid_artifact_metadata')
        name, sha, size = artifact['path'], artifact['sha256'], artifact['size']
        if (not isinstance(name, str) or name not in expected or name in checked
                or not isinstance(sha, str) or len(sha) != 64
                or any(c not in '0123456789abcdef' for c in sha)
                or type(size) is not int or size <= 0):
            raise BundleStop('invalid_artifact_evidence')
        real_sha, real_size = _hash_regular(bundle / name)
        if (real_sha, real_size) != (sha, size):
            raise BundleStop('bundle_bytes_mismatch')
        checked.add(name)
    if checked != expected:
        raise BundleStop('artifact_list_incomplete')
    if payload.get('stage_manifest_sha256') != _hash_regular(bundle / 'stage' / 'manifest.json')[0]:
        raise BundleStop('stage_manifest_digest_mismatch')

    if verify_stage(bundle / 'stage').get('stage_bytes_hash_verified') is not True:
        raise BundleStop('stage_verification_failed')
    coverage = verify_coverage(bundle / 'stage', bundle / 'archive', protected=protected)
    if coverage.get('protected_release_count') != len(protected):
        raise BundleStop('protected_release_coverage_incomplete')
    manifest_sha, _ = _hash_regular(bundle / 'bundle.json')
    return {
        'schema': SCHEMA, 'status': 'OFFLINE_BYTES_VERIFIED_ONLY',
        'artifact_count': len(checked),
        'protected_release_count': len(protected),
        'bundle_manifest_sha256': manifest_sha,
        'self_contained_recovery_bytes_verified': True,
        'offsite_backup_verified': False,
        'production_isolated_restore_verified': False,
        'publisher_signature_verified': False,
        'migration_authorized': False,
        'database_cutover_authorized': False,
        'client_deployment_authorized': False,
    }


def assemble_bundle(stage: Path, target_parent: Path, archive: Path | None = None,
                    *, protected: tuple[tuple[str, str, int], ...] = PROTECTED_RELEASES) -> dict:
    """Copy only verified offline bytes to a new private bundle; never modify inputs."""
    stage, target_parent = Path(stage), Path(target_parent)
    _offline_private(stage)
    _offline_private(target_parent)
    if target_parent == stage or stage in target_parent.parents:
        raise BundleStop('destination_nested_under_stage')
    if archive is not None:
        archive = Path(archive)
        _offline_private(archive)
        if archive == target_parent or archive in target_parent.parents:
            raise BundleStop('destination_nested_under_archive')
    coverage = verify_coverage(stage, archive, protected=protected)
    if coverage.get('protected_release_count') != len(protected):
        raise BundleStop('source_recovery_coverage_incomplete')
    expected, missing = _expected_paths(stage, protected=protected)
    # Prevent predictable partial 700+ MB release-copies on undersized offline
    # destinations. Include the full source stage, protected historical TARs,
    # and 10% or 16 MiB (whichever is larger) of free-space headroom.
    source_manifest = _read_json(stage / 'manifest.json', maximum=32768)
    estimated_bytes = (source_manifest['db']['size']
                       + sum(r['size'] for r in source_manifest['releases'])
                       + sum(size for release_id, _, size in protected
                             if release_id + '.tar' in missing))
    try:
        volume = os.statvfs(target_parent)
    except OSError as exc:
        raise BundleStop('destination_capacity_unknown') from exc
    required_bytes = estimated_bytes + max(16 * 1024 * 1024, estimated_bytes // 10)
    if volume.f_bavail * volume.f_frsize < required_bytes:
        raise BundleStop('destination_capacity_insufficient')
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    bundle = target_parent / f'planiq-display-62e-{stamp}-{uuid.uuid4().hex[:12]}'
    bundle.mkdir(mode=0o700)
    try:
        (bundle / 'stage').mkdir(mode=0o700)
        (bundle / 'stage' / 'releases').mkdir(mode=0o700)
        (bundle / 'archive').mkdir(mode=0o700)
        records = []
        for name in sorted(expected):
            source = (archive / name.split('/', 1)[1]) if name.startswith('archive/') else (stage / name.split('/', 1)[1])
            sha, size = _copy_hashed(source, bundle / name)
            records.append({'path': name, 'sha256': sha, 'size': size})
        source_manifest_sha, _ = _hash_regular(stage / 'manifest.json')
        manifest = {
            'schema': SCHEMA,
            'created_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'stage_manifest_sha256': source_manifest_sha,
            'protected_release_ids': [r[0] for r in protected],
            'artifacts': records,
            'offsite_backup_verified': False,
            'production_isolated_restore_verified': False,
            'publisher_signature_verified': False,
            'migration_authorized': False,
            'database_cutover_authorized': False,
            'client_deployment_authorized': False,
        }
        path = bundle / 'bundle.json'
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        with os.fdopen(fd, 'wb') as output:
            output.write((json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode('utf-8'))
            output.flush()
            os.fsync(output.fileno())
        for folder in (bundle / 'stage' / 'releases', bundle / 'stage', bundle / 'archive', bundle):
            fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        result = verify_bundle(bundle, protected=protected)
        return {'bundle': str(bundle), 'evidence': result, 'protected_archived_count': len(missing)}
    except BaseException:
        shutil.rmtree(bundle)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--assemble', action='store_true')
    mode.add_argument('--verify-bundle', type=Path)
    parser.add_argument('--verified-stage', type=Path)
    parser.add_argument('--offline-recovery-archive', type=Path)
    parser.add_argument('--destination-parent', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.verify_bundle is not None:
            result = verify_bundle(args.verify_bundle)
        else:
            if args.verified_stage is None or args.destination_parent is None:
                parser.error('--assemble requires --verified-stage and --destination-parent')
            result = assemble_bundle(args.verified_stage, args.destination_parent,
                                     args.offline_recovery_archive)
    except (BackupEvidenceError, RecoveryCoverageStop, BundleStop, OSError,
            ValueError, TypeError, KeyError) as exc:
        if isinstance(exc, BundleStop):
            code = str(exc)
        elif isinstance(exc, RecoveryCoverageStop):
            code = str(exc)
        else:
            code = 'invalid_offline_bundle_evidence'
        print('62E STOP: ' + code, file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
