#!/usr/bin/env python3
"""62D: OFFLINE, read-only recovery coverage of a verified 62B stage and historical release archives.

Never connects to production, executes SQL, uploads data, changes release gates,
performs an actual restore, or claims migration / offsite authorization.
Prior releases may be outside 62B's *active store* inventory: do not silently
pretend a database+stable-TAR backup includes the recovery baseline.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from display_62b_backup_evidence import (
    BackupEvidenceError,
    _hash_regular,
    _open_regular,
    _safe_dir,
    verify as verify_62b_stage,
)

SCHEMA = 'planiq-display-62d-recovery-coverage-v1'
# Source-locked identities; SHA256 alone verifies bytes, NOT publisher signature.
# Update only after a separately reviewed release policy/retention transition.
PROTECTED_RELEASES = (
    ('clientflow-1.3.42-seq-1243', 'ee35cc6caa9304bbc7ee4b1c763ecdeaf03d9d58a6c73cee943805251d8d6914', 223610880),
    ('clientflow-1.3.43-seq-1244', 'd3fdae8fb2a93f74431780f4aadde21625d10917e99cfbe6095ff2394e1e856b', 223610880),
    ('clientflow-1.3.44-seq-1245', '28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5', 223610880),
)
STABLE_RELEASE = PROTECTED_RELEASES[-1]


class RecoveryCoverageStop(RuntimeError):
    pass


def verify_coverage(
    stage: Path,
    archive_dir: Path | None = None,
    *,
    protected: tuple[tuple[str, str, int], ...] = PROTECTED_RELEASES,
) -> dict:
    """Hash all protected bytes from a 62B stage or a separately copied offline archive.

    `protected` is injected only by tests; the CLI always uses pinned source
    identities. This never returns any authorization or offsite-restore claim.
    """
    stage = Path(stage)
    _safe_dir(stage, private=True)
    # 62B verification also checks every dump+TAR SHA, staging permissions,
    # the stable artifact identity and rejects unexpected staging files.
    evidence = verify_62b_stage(stage)
    if evidence.get('stage_bytes_hash_verified') is not True:
        raise RecoveryCoverageStop('62b_stage_not_verified')
    # Reopen the verified manifest without following a swapped symlink.
    manifest_fd, stat_result = _open_regular(stage / 'manifest.json')
    try:
        if stat_result.st_size > 32768:
            raise RecoveryCoverageStop('manifest_too_large')
        with os.fdopen(manifest_fd, 'rb') as handle:
            manifest_fd = -1
            manifest = json.loads(handle.read())
    finally:
        if manifest_fd >= 0:
            os.close(manifest_fd)
    if not protected or len(protected) > 3:
        raise RecoveryCoverageStop('invalid_protected_release_count')
    ids = [r[0] for r in protected]
    if len(set(ids)) != len(ids) or protected[-1][0] != manifest.get('stable_release_id'):
        raise RecoveryCoverageStop('protected_release_policy_drift')
    stable_id, stable_sha, stable_size = protected[-1]
    if manifest.get('stable_sha256') != stable_sha:
        raise RecoveryCoverageStop('stable_identity_drift')
    if not any(r.get('filename') == stable_id + '.tar' and r.get('sha256') == stable_sha
               and r.get('size') == stable_size for r in manifest['releases']):
        raise RecoveryCoverageStop('stable_size_or_digest_drift')

    if archive_dir is not None:
        archive_dir = Path(archive_dir)
        # Only an explicitly supplied, private OFFLINE archive is accepted.
        # A path under the production mount or inside the stage is not recovery.
        if (str(archive_dir).startswith('/var/data/clientflow-release-artifacts')
                or archive_dir == stage or stage in archive_dir.parents
                or archive_dir in stage.parents):
            raise RecoveryCoverageStop('archive_not_an_independent_offline_source')
        _safe_dir(archive_dir, private=True)

    stage_releases = {r['filename']: r for r in manifest['releases']}
    checked = []
    for release_id, sha, size in protected:
        filename = release_id + '.tar'
        expected = stage_releases.get(filename)
        if expected is not None:
            # Stage bytes were independently re-hashed by 62B.verify(); also
            # require the identity to equal the immutable source-locked record.
            if expected['sha256'] != sha or expected['size'] != size:
                raise RecoveryCoverageStop('protected_stage_tar_mismatch')
            origin = 'stage'
        else:
            if archive_dir is None:
                raise RecoveryCoverageStop('protected_archive_missing')
            source = archive_dir / filename
            digest, actual_size = _hash_regular(source)  # no symlink following
            if (digest, actual_size) != (sha, size):
                raise RecoveryCoverageStop('protected_archive_digest_or_size_mismatch')
            origin = 'offline_archive'
        checked.append({'release_id': release_id, 'sha256': sha, 'size': size, 'evidence_source': origin})

    return {
        'schema': SCHEMA,
        'status': 'RELEASE_BYTES_VERIFIED_ONLY',
        'protected_release_count': len(checked),
        'protected_releases': checked,
        'database_dump_bytes_hash_verified': True,
        'release_bytes_sha256_verified': True,
        'publisher_signatures_verified': False,
        'offsite_backup_verified': False,
        'production_database_isolated_restore_verified': False,
        'rpo_rto_verified': False,
        'migration_authorized': False,
        'database_cutover_authorized': False,
        'client_deployment_authorized': False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verified-stage', type=Path, required=True)
    parser.add_argument('--offline-recovery-archive', type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify_coverage(args.verified_stage, args.offline_recovery_archive)
    except (RecoveryCoverageStop, BackupEvidenceError, OSError, ValueError, TypeError, KeyError) as exc:
        # No production paths, DB rows, login credentials or SQL in diagnostics.
        code = str(exc) if isinstance(exc, RecoveryCoverageStop) else 'offline_evidence_invalid'
        print('62D STOP: ' + code, file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
