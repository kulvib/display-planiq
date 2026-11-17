"""62E: no production, Docker, credentials or networking; disposable offline fixtures."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import display_62b_backup_evidence as backup  # noqa: E402
import display_62e_offline_bundle as bundle  # noqa: E402


def sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


@pytest.fixture
def source(tmp_path, monkeypatch):
    mount = tmp_path / 'sample-local-mount'
    (mount / 'postgres/data/base').mkdir(parents=True)
    (mount / 'postgres/data/global').mkdir()
    (mount / 'postgres/data/pg_wal').mkdir()
    (mount / 'postgres/data/PG_VERSION').write_text('18\n')
    (mount / 'postgres/data/global/pg_control').write_bytes(b'fake control file')
    os.chmod(mount / 'postgres/data', 0o700)
    (mount / 'store').mkdir()
    filenames = [f'clientflow-1.3.{version}-seq-{sequence}.tar' for version, sequence in
                 [(42, 1243), (43, 1244), (44, 1245)]]
    blobs = [b'older recovery fixture 1243', b'previous recovery fixture 1244',
             b'current stable fixture 1245']
    (mount / 'store' / filenames[2]).write_bytes(blobs[2])
    archive = tmp_path / 'offline-history'
    archive.mkdir(mode=0o700)
    (archive / filenames[0]).write_bytes(blobs[0])
    (archive / filenames[1]).write_bytes(blobs[1])
    parent = tmp_path / 'private-stage-parent'
    parent.mkdir(mode=0o700)
    dest = tmp_path / 'private-bundles'
    dest.mkdir(mode=0o700)

    def fake_dump(path, **kwargs):
        path.write_bytes(b'PGDMP' + b'private synthetic fixture only')
        os.chmod(path, 0o600)
        return sha(path.read_bytes()), path.stat().st_size

    monkeypatch.setattr(backup, '_dump_local_database', fake_dump)
    stage = Path(backup.capture(mount, parent, release_id=filenames[2][:-4],
                                expected_sha256=sha(blobs[2]),
                                expected_size=len(blobs[2]))['stage'])
    protected = tuple((name[:-4], sha(data), len(data)) for name, data in zip(filenames, blobs))
    return stage, archive, dest, protected


def test_assembles_complete_self_contained_bundle_from_separate_archive(source):
    stage, archive, dest, protected = source
    result = bundle.assemble_bundle(stage, dest, archive, protected=protected)
    target = Path(result['bundle'])
    evidence = result['evidence']
    assert result['protected_archived_count'] == 2
    assert evidence['status'] == 'OFFLINE_BYTES_VERIFIED_ONLY'
    assert evidence['artifact_count'] == 5
    assert evidence['protected_release_count'] == 3
    assert len(evidence['bundle_manifest_sha256']) == 64
    assert (target / 'archive' / (protected[0][0] + '.tar')).is_file()
    assert (target / 'archive' / (protected[1][0] + '.tar')).is_file()
    assert bundle.verify_bundle(target, protected=protected) == evidence
    assert bundle.verify_bundle(target, protected=protected)['self_contained_recovery_bytes_verified'] is True
    for name in ('offsite_backup_verified', 'production_isolated_restore_verified',
                 'publisher_signature_verified', 'migration_authorized',
                 'database_cutover_authorized', 'client_deployment_authorized'):
        assert evidence[name] is False
    # Inputs were not modified or removed.
    assert stage.is_dir() and archive.is_dir()


def test_low_destination_capacity_stops_before_copy(source, monkeypatch):
    stage, archive, dest, protected = source
    class TinyVolume:
        f_bavail = 1
        f_frsize = 4096
    monkeypatch.setattr(bundle.os, 'statvfs', lambda _: TinyVolume())
    with pytest.raises(bundle.BundleStop, match='destination_capacity_insufficient'):
        bundle.assemble_bundle(stage, dest, archive, protected=protected)
    assert list(dest.iterdir()) == []


def test_missing_protected_archive_fails_without_creating_bundle(source):
    stage, archive, dest, protected = source
    (archive / (protected[0][0] + '.tar')).unlink()
    with pytest.raises(FileNotFoundError):
        bundle.assemble_bundle(stage, dest, archive, protected=protected)
    assert list(dest.iterdir()) == []


def test_corrupt_archive_stops_before_any_copy(source):
    stage, archive, dest, protected = source
    (archive / (protected[0][0] + '.tar')).write_bytes(b'changed bytes')
    with pytest.raises(bundle.RecoveryCoverageStop, match='protected_archive_digest_or_size_mismatch'):
        bundle.assemble_bundle(stage, dest, archive, protected=protected)
    assert list(dest.iterdir()) == []


def test_mutated_database_dump_after_assembly_rejected(source):
    stage, archive, dest, protected = source
    target = Path(bundle.assemble_bundle(stage, dest, archive, protected=protected)['bundle'])
    (target / 'stage/database.pgdump').write_bytes(b'PGDMPcorrupted')
    with pytest.raises(bundle.BundleStop, match='bundle_bytes_mismatch'):
        bundle.verify_bundle(target, protected=protected)


def test_mutated_historical_release_after_assembly_rejected(source):
    stage, archive, dest, protected = source
    target = Path(bundle.assemble_bundle(stage, dest, archive, protected=protected)['bundle'])
    (target / 'archive' / (protected[0][0] + '.tar')).write_bytes(b'fake')
    with pytest.raises(bundle.BundleStop, match='bundle_bytes_mismatch'):
        bundle.verify_bundle(target, protected=protected)


def test_missing_or_extra_files_fail_closed(source):
    stage, archive, dest, protected = source
    target = Path(bundle.assemble_bundle(stage, dest, archive, protected=protected)['bundle'])
    (target / 'archive/extra.tar').write_bytes(b'unexpected file')
    with pytest.raises(bundle.BundleStop, match='missing_or_unexpected_bundle_artifact'):
        bundle.verify_bundle(target, protected=protected)
    (target / 'archive/extra.tar').unlink()
    (target / 'archive' / (protected[1][0] + '.tar')).unlink()
    with pytest.raises(bundle.BundleStop, match='missing_or_unexpected_bundle_artifact'):
        bundle.verify_bundle(target, protected=protected)


def test_forged_approval_is_rejected_even_when_artifact_bytes_match(source):
    stage, archive, dest, protected = source
    target = Path(bundle.assemble_bundle(stage, dest, archive, protected=protected)['bundle'])
    m = json.loads((target / 'bundle.json').read_text())
    m['migration_authorized'] = True
    (target / 'bundle.json').write_text(json.dumps(m))
    with pytest.raises(bundle.BundleStop, match='unearned_authorization_or_proof'):
        bundle.verify_bundle(target, protected=protected)


def test_symlinked_history_rejected_without_following(source, tmp_path):
    stage, archive, dest, protected = source
    target = Path(bundle.assemble_bundle(stage, dest, archive, protected=protected)['bundle'])
    release = target / 'archive' / (protected[0][0] + '.tar')
    release.unlink()
    release.symlink_to(archive / (protected[0][0] + '.tar'))
    with pytest.raises(OSError):
        bundle.verify_bundle(target, protected=protected)


def test_rejects_unsafe_bundle_parent_and_nested_destination(source):
    stage, archive, dest, protected = source
    with pytest.raises(bundle.BundleStop, match='destination_nested_under_stage'):
        bundle.assemble_bundle(stage, stage, archive, protected=protected)
    with pytest.raises(bundle.BundleStop, match='destination_nested_under_archive'):
        bundle.assemble_bundle(stage, archive, archive, protected=protected)
    os.chmod(dest, 0o755)
    with pytest.raises(bundle.BackupEvidenceError, match='directory_permissions_unsafe'):
        bundle.assemble_bundle(stage, dest, archive, protected=protected)
    os.chmod(dest, 0o700)


def test_bundle_manifest_swapped_or_policy_drift_rejected(source):
    stage, archive, dest, protected = source
    target = Path(bundle.assemble_bundle(stage, dest, archive, protected=protected)['bundle'])
    m = json.loads((target / 'bundle.json').read_text())
    m['protected_release_ids'].pop()
    (target / 'bundle.json').write_text(json.dumps(m))
    with pytest.raises(bundle.BundleStop, match='bundle_policy_or_schema_drift'):
        bundle.verify_bundle(target, protected=protected)


def test_complete_stage_does_not_require_separate_archive(source):
    stage, archive, dest, protected = source
    # Build another valid 62B stage by changing the synthetic source manifest
    # before assembly; verification still runs and checks the actual hashes.
    sm = json.loads((stage / 'manifest.json').read_text())
    for release_id, digest, size in protected[:-1]:
        name = release_id + '.tar'
        (stage / 'releases' / name).write_bytes((archive / name).read_bytes())
        os.chmod(stage / 'releases' / name, 0o600)
        sm['releases'].append({'filename': name, 'sha256': digest, 'size': size})
    (stage / 'manifest.json').write_text(json.dumps(sm))
    result = bundle.assemble_bundle(stage, dest, protected=protected)
    assert result['protected_archived_count'] == 0
    assert bundle.verify_bundle(Path(result['bundle']), protected=protected)['protected_release_count'] == 3


def test_offline_drill_requires_real_restore_after_bytes_validation():
    script = (ROOT / 'scripts/display_62e_offline_drill.sh').read_text()
    assert '--verify-bundle "$bundle"' in script
    assert 'display_62b_offline_restore.sh' in script
    assert '"$bundle/stage"' in script
    assert '--network' not in script  # network isolation is in the existing 62B restore
    assert 'DISPLAY_62E_OFFLINE_DRILL_PASS' in script
    assert 'DISPLAY_62E_OFFLINE_DRILL_PASS' not in (ROOT / 'scripts/display_62e_offline_bundle.py').read_text()
    assert 'set -Eeuo pipefail' in script
    subprocess.run(['bash', '-n', str(ROOT / 'scripts/display_62e_offline_drill.sh')], check=True)


def test_62e_cli_verify_no_production_access_and_no_write_mode():
    script = (ROOT / 'scripts/display_62e_offline_bundle.py').read_text()
    assert 'import subprocess' not in script and 'subprocess.run(' not in script
    assert 'pg_dump(' not in script and 'pg_restore(' not in script
    assert 'requests.' not in script and 'httpx.' not in script
    assert "'database_cutover_authorized': False" in script
    assert "'client_deployment_authorized': False" in script
    assert '--verify-bundle' in script
