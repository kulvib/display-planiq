"""62D: offline recovery completeness and observed outage windows, no live data."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import display_62b_backup_evidence as backup  # noqa: E402
import display_62d_deploy_gap_report as gaps  # noqa: E402
import display_62d_recovery_coverage as recovery  # noqa: E402


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def offline_evidence(tmp_path, monkeypatch):
    mount = tmp_path / 'live-volume-fixture'
    pg = mount/'postgres'/'data'
    (pg/'base').mkdir(parents=True)
    (pg/'global').mkdir()
    (pg/'pg_wal').mkdir()
    (pg/'PG_VERSION').write_text('18\n')
    (pg/'global'/'pg_control').write_bytes(b'fake')
    os.chmod(pg, 0o700)
    (mount/'store').mkdir()
    current = b'current signed TAR example only'
    previous = b'older approved TAR example only'
    current_id = 'clientflow-1.3.44-seq-1245'
    older_id = 'clientflow-1.3.43-seq-1244'
    (mount/'store'/f'{current_id}.tar').write_bytes(current)
    target = tmp_path/'private-offline-stage-parent'
    target.mkdir(mode=0o700)
    archive = tmp_path/'private-offline-archive'
    archive.mkdir(mode=0o700)
    (archive/f'{older_id}.tar').write_bytes(previous)
    def fake_dump(dest, **kw):
        dest.write_bytes(b'PGDMP' + b'fake database archive')
        os.chmod(dest, 0o600)
        return sha(dest.read_bytes()), dest.stat().st_size
    monkeypatch.setattr(backup, '_dump_local_database', fake_dump)
    stage = Path(backup.capture(mount, target, release_id=current_id,
                                expected_sha256=sha(current), expected_size=len(current))['stage'])
    protected = ((older_id, sha(previous), len(previous)),
                 (current_id, sha(current), len(current)))
    return stage, archive, protected


def test_62d_offline_stage_and_archived_1244_are_verified_together(offline_evidence):
    stage, archive, protected = offline_evidence
    status = recovery.verify_coverage(stage, archive, protected=protected)
    assert status['status'] == 'RELEASE_BYTES_VERIFIED_ONLY'
    assert status['protected_release_count'] == 2
    assert status['protected_releases'][0]['evidence_source'] == 'offline_archive'
    assert status['protected_releases'][1]['evidence_source'] == 'stage'
    assert status['database_dump_bytes_hash_verified'] is True
    for k in ('publisher_signatures_verified','offsite_backup_verified',
              'production_database_isolated_restore_verified', 'rpo_rto_verified',
              'migration_authorized', 'database_cutover_authorized', 'client_deployment_authorized'):
        assert status[k] is False


def test_62d_missing_archive_fails_closed(offline_evidence):
    stage, archive, protected = offline_evidence
    with pytest.raises(recovery.RecoveryCoverageStop, match='protected_archive_missing'):
        recovery.verify_coverage(stage, protected=protected)


def test_62d_corrupt_archive_fails_closed(offline_evidence):
    stage, archive, protected = offline_evidence
    (archive/(protected[0][0] + '.tar')).write_bytes(b'tampered')
    with pytest.raises(recovery.RecoveryCoverageStop, match='protected_archive_digest_or_size_mismatch'):
        recovery.verify_coverage(stage, archive, protected=protected)


def test_62d_symlink_archive_and_world_accessible_archive_fail_closed(offline_evidence, tmp_path):
    stage, archive, protected = offline_evidence
    alt = tmp_path / 'redirect'
    alt.symlink_to(archive, target_is_directory=True)
    with pytest.raises(backup.BackupEvidenceError, match='directory_missing_or_redirected'):
        recovery.verify_coverage(stage, alt, protected=protected)
    os.chmod(archive,0o755)
    with pytest.raises(backup.BackupEvidenceError, match='directory_permissions_unsafe'):
        recovery.verify_coverage(stage, archive, protected=protected)
    os.chmod(archive,0o700)
    target = archive/(protected[0][0]+'.tar')
    target.unlink()
    target.symlink_to(stage/'releases'/(protected[1][0]+'.tar'))
    with pytest.raises((OSError, backup.BackupEvidenceError)):
        recovery.verify_coverage(stage, archive, protected=protected)


def test_62d_refuses_forged_or_modified_db_stage(offline_evidence):
    stage, archive, protected = offline_evidence
    (stage/'database.pgdump').write_bytes(b'FAKEdump')
    with pytest.raises(backup.BackupEvidenceError, match='capture_sha256_mismatch'):
        recovery.verify_coverage(stage, archive, protected=protected)


def test_62d_rejects_stable_mismatch_or_incomplete_policy(offline_evidence):
    stage, archive, protected = offline_evidence
    mismatched = (protected[0], (protected[1][0], sha(b'wrong'), protected[1][2]))
    with pytest.raises(recovery.RecoveryCoverageStop, match='stable_identity_drift'):
        recovery.verify_coverage(stage, archive, protected=mismatched)
    with pytest.raises(recovery.RecoveryCoverageStop, match='invalid_protected_release_count'):
        recovery.verify_coverage(stage, archive, protected=())
    with pytest.raises(recovery.RecoveryCoverageStop, match='protected_release_policy_drift'):
        recovery.verify_coverage(stage, archive, protected=(protected[1],protected[0]))


def test_62d_stored_history_can_be_verified_without_separate_archive(offline_evidence, monkeypatch):
    stage, archive, protected = offline_evidence
    # The stage already exists: construct a second full stage by adding the
    # older source *before* capture, so 62B signed its inventory correctly.
    # This test verifies the source preference without changing 62B staging.
    entry = (stage/'releases'/(protected[0][0]+'.tar'))
    entry.write_bytes((archive/(protected[0][0]+'.tar')).read_bytes())
    os.chmod(entry,0o600)
    manifest_path=stage/'manifest.json'
    manifest=json.loads(manifest_path.read_text())
    manifest['releases'].append({'filename':entry.name,'sha256':protected[0][1],'size':protected[0][2]})
    manifest_path.write_text(json.dumps(manifest))
    assert recovery.verify_coverage(stage, protected=protected)['protected_release_count'] == 2


def test_62d_all_three_last_historical_identities_must_be_covered(offline_evidence):
    stage, archive, pair = offline_evidence
    earlier = ('clientflow-1.3.42-seq-1243', sha(b'old approved fixture 1243'), len(b'old approved fixture 1243'))
    (archive / (earlier[0] + '.tar')).write_bytes(b'old approved fixture 1243')
    triple = (earlier, *pair)
    result = recovery.verify_coverage(stage, archive, protected=triple)
    assert result['protected_release_count'] == 3
    assert result['protected_releases'][0]['evidence_source'] == 'offline_archive'
    (archive / (earlier[0] + '.tar')).unlink()
    with pytest.raises(FileNotFoundError):
        recovery.verify_coverage(stage, archive, protected=triple)


def test_62d_refuses_archive_inside_live_persistent_mount(offline_evidence):
    stage, archive, pair = offline_evidence
    with pytest.raises(recovery.RecoveryCoverageStop, match='archive_not_an_independent_offline_source'):
        recovery.verify_coverage(stage, Path('/var/data/clientflow-release-artifacts/recovery-archive'), protected=pair)


def test_62d_pinned_1243_1244_and_1245_have_expected_id_size_sha():
    earliest, prior, current = recovery.PROTECTED_RELEASES
    assert earliest == ('clientflow-1.3.42-seq-1243',
        'ee35cc6caa9304bbc7ee4b1c763ecdeaf03d9d58a6c73cee943805251d8d6914',223610880)
    assert prior == ('clientflow-1.3.43-seq-1244',
        'd3fdae8fb2a93f74431780f4aadde21625d10917e99cfbe6095ff2394e1e856b',223610880)
    assert current == ('clientflow-1.3.44-seq-1245',
        '28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5',223610880)
    assert '--capture' not in (ROOT/'scripts/display_62d_recovery_coverage.py').read_text()


def test_deploy_gap_report_redacts_urls_ips_and_marks_partial_evidence():
    lines = [
        '2026-11-17T12:53:20.123Z clientIP="123.4.5.6" requestID="sensitive" statusCode=502 path="/api/private?secret=123"',
        '2026-11-17T12:53:31.000Z INFO: 10.2.0.1:1234 - "HEAD /health HTTP/1.1" 502 Bad Gateway',
        '2026-11-17T12:54:02Z INFO: 10.2.0.1:1234 - "HEAD /health HTTP/1.1" 200 OK',
        '2026-11-17T12:54:20Z INFO: 10.2.0.1:1234 - "GET /api/calendar/seasons HTTP/1.1" 401 Unauthorized',
        '2026-11-17T12:54:50Z clientIP="123.4.5.6" statusCode=503 path="/api/secret"',
    ]
    result = gaps.analyze_lines(lines)
    assert result['http_502_count'] == 2
    assert result['http_503_count'] == 1
    assert result['http_200_count'] == 1
    assert result['http_401_count'] == 1
    assert len(result['observed_502_503_windows']) == 2
    assert result['observed_502_503_windows'][0]['observed_span_seconds'] == 11
    assert result['complete_log_evidence'] is False
    payload=json.dumps(result)
    assert all(v not in payload for v in ('123.4.5.6','secret=123','/api/private','sensitive'))


def test_deploy_gap_report_counts_405_but_not_real_uptime():
    lines = ['2026-11-17T11:15:08Z INFO - "HEAD /health HTTP/1.1" 405 Method Not Allowed']
    x=gaps.analyze_lines(lines)
    assert x['http_405_count'] == 1 and x['measured_service_uptime'] is False
    assert x['observed_502_503_windows']==[]


def test_deploy_gap_report_rejects_excess_lines():
    with pytest.raises(gaps.GapReportStop, match='log_too_large'):
        gaps.analyze_lines('a\n' for _ in range(gaps.MAX_LINES+1))


def test_deploy_gap_source_never_contacts_network_or_writes_to_repo():
    s=(ROOT/'scripts/display_62d_deploy_gap_report.py').read_text()
    assert 'requests.' not in s and 'httpx.' not in s and 'urllib.' not in s
    assert "open('w'" not in s and "'client_deployment_authorized': False" in s
