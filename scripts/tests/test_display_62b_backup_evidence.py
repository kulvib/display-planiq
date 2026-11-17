"""62B operator backup staging; no live DB, secrets, or Render access in tests."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/display_62b_backup_evidence.py'
spec = importlib.util.spec_from_file_location('display_62b_backup_evidence', SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
RELEASE = 'clientflow-1.3.44-seq-1245'
STABLE = b'approved stable immutable TAR fixture'


def _source(base: Path):
    mount, dest = base / 'source', base / 'private-stage'
    (mount/'postgres/data/base').mkdir(parents=True)
    (mount/'postgres/data/global').mkdir()
    (mount/'postgres/data/pg_wal').mkdir()
    (mount/'postgres/data/PG_VERSION').write_text('18\n')
    (mount/'postgres/data/global/pg_control').write_bytes(b'fixture')
    (mount/'store').mkdir()
    (mount/'store'/f'{RELEASE}.tar').write_bytes(STABLE)
    (mount/'store'/'clientflow-1.3.43-seq-1244.tar').write_bytes(b'prior recovery candidate')
    os.chmod(mount/'postgres/data',0o700)
    dest.mkdir(mode=0o700)
    return mount,dest,hashlib.sha256(STABLE).hexdigest()


def _stub_dump(monkeypatch, *, code=0):
    calls=[]
    def run(argv, **kw):
        assert '--host=/run/display-postgres' in argv
        assert '--dbname=display' in argv
        assert '--format=custom' in argv
        assert '--no-owner' in argv and '--no-acl' in argv
        assert kw['stdin'] == subprocess.DEVNULL
        assert 'DATABASE_URL' not in kw['env'] and 'PGPASSWORD' not in kw['env']
        calls.append(argv)
        kw['stdout'].write(b'PGDMP' + b'fake database archive bytes')
        return subprocess.CompletedProcess(argv,code,stderr=b'redacted')
    monkeypatch.setattr(mod.subprocess,'run',run)
    return calls


def test_capture_and_verify_do_not_claim_offsite_backup_or_restore(tmp_path,monkeypatch):
    mount,dest,sha=_source(tmp_path)
    calls=_stub_dump(monkeypatch)
    capture=mod.capture(mount,dest,release_id=RELEASE,expected_sha256=sha,expected_size=len(STABLE))
    assert len(calls)==1
    stage=Path(capture['stage'])
    assert stage.parent == dest
    assert len(capture['manifest']['releases'])==2
    assert (stage/'database.pgdump').stat().st_mode & 0o777 == 0o600
    assert (stage/'manifest.json').stat().st_mode & 0o777 == 0o600
    status=mod.verify(stage)
    assert status['verified_file_count']==3
    assert status['stage_bytes_hash_verified'] is True
    for key in ('backup_offsite_verified','backup_restored_to_isolated_postgres','database_cutover_authorized','deployment_authorized'):
        assert capture['manifest'][key] is False
        assert status[key] is False


def test_corrupt_database_and_release_fail_verification(tmp_path,monkeypatch):
    mount,dest,sha=_source(tmp_path)
    _stub_dump(monkeypatch)
    p=Path(mod.capture(mount,dest,release_id=RELEASE,expected_sha256=sha,expected_size=len(STABLE))['stage'])
    (p/'database.pgdump').write_bytes(b'corrupted database')
    with pytest.raises(mod.BackupEvidenceError,match='capture_sha256_mismatch'):
        mod.verify(p)
    (p/'database.pgdump').write_bytes(b'PGDMPfake database archive bytes')
    (p/'releases'/f'{RELEASE}.tar').write_bytes(b'changed approved stable release')
    with pytest.raises(mod.BackupEvidenceError,match='capture_sha256_mismatch'):
        mod.verify(p)


def test_reject_symlink_tricks_and_additional_files(tmp_path,monkeypatch):
    mount,dest,sha=_source(tmp_path)
    _stub_dump(monkeypatch)
    stage=Path(mod.capture(mount,dest,release_id=RELEASE,expected_sha256=sha,expected_size=len(STABLE))['stage'])
    (stage/'database.pgdump').unlink()
    (stage/'database.pgdump').symlink_to(mount/'store'/f'{RELEASE}.tar')
    with pytest.raises((mod.BackupEvidenceError,OSError)):
        mod.verify(stage)
    (stage/'database.pgdump').unlink()
    (stage/'database.pgdump').write_bytes(b'PGDMPfake database archive bytes')
    (stage/'releases'/'unknown.tar').write_bytes(b'payload')
    with pytest.raises(mod.BackupEvidenceError,match='unexpected_release_files'):
        mod.verify(stage)


def test_error_during_dump_leaves_no_stage(tmp_path,monkeypatch):
    mount,dest,sha=_source(tmp_path)
    _stub_dump(monkeypatch,code=2)
    with pytest.raises(mod.BackupEvidenceError,match='pg_dump_nonzero_exit'):
        mod.capture(mount,dest,release_id=RELEASE,expected_sha256=sha,expected_size=len(STABLE))
    assert list(dest.iterdir()) == []


def test_62a_source_preflight_fail_closed_before_dump(tmp_path,monkeypatch):
    mount,dest,sha=_source(tmp_path)
    _stub_dump(monkeypatch)
    (mount/'store'/f'{RELEASE}.tar').write_bytes(b'tampered')
    with pytest.raises(mod.BackupEvidenceError,match='62a_source_storage_preflight_failed'):
        mod.capture(mount,dest,release_id=RELEASE,expected_sha256=sha,expected_size=len(STABLE))
    assert list(dest.iterdir()) == []


def test_capture_rejects_nested_stage_and_world_accessible_parent(tmp_path,monkeypatch):
    mount,dest,sha=_source(tmp_path)
    _stub_dump(monkeypatch)
    os.chmod(dest,0o755)
    with pytest.raises(mod.BackupEvidenceError,match='directory_permissions_unsafe'):
        mod.capture(mount,dest,release_id=RELEASE,expected_sha256=sha,expected_size=len(STABLE))
    os.chmod(dest,0o700)
    os.chmod(mount/'store',0o700)
    with pytest.raises(mod.BackupEvidenceError,match='backup_stage_must_be_separate'):
        mod.capture(mount,mount/'store',release_id=RELEASE,expected_sha256=sha,expected_size=len(STABLE))


def test_reject_forged_success_and_extra_metadata(tmp_path,monkeypatch):
    mount,dest,sha=_source(tmp_path)
    _stub_dump(monkeypatch)
    stage=Path(mod.capture(mount,dest,release_id=RELEASE,expected_sha256=sha,expected_size=len(STABLE))['stage'])
    manifest=json.loads((stage/'manifest.json').read_text())
    manifest['database_cutover_authorized'] = True
    (stage/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(mod.BackupEvidenceError,match='manifest_claims_unearned_authorization'):
        mod.verify(stage)
    manifest['database_cutover_authorized']=False
    (stage/'manifest.json').write_text(json.dumps(manifest))
    (stage/'hidden-token.txt').write_text('not allowed')
    with pytest.raises(mod.BackupEvidenceError,match='unexpected_stage_entries'):
        mod.verify(stage)


def test_ci_contract_proves_real_isolated_database_restore_not_just_listing():
    workflow=(ROOT/'.github/workflows/single-node-smoke.yml').read_text()
    assert 'pg_dump --no-password --format=custom' in workflow
    assert 'pg_restore --exit-on-error --single-transaction' in workflow
    assert 'display-62b-isolated-restore' in workflow
    assert '--network none' in workflow
    assert 'SELECT id FROM ci_persistence_marker.proof' in workflow
    assert 'SELECT count(*) FROM alembic_version' in workflow
    assert 'DISPLAY_62B_CI_FIXTURE_RESTORE_PASS' in workflow
    assert 'docker rm -f -v display-62b-isolated-restore' in workflow
    assert 'rm -f "$RUNNER_TEMP/display-62b-disposable.pgdump"' in workflow
    assert 'api.display.planiq.dk' not in workflow


def test_script_does_not_support_db_cutover_or_release_promote():
    script=SCRIPT.read_text()
    assert "--host=/run/display-postgres" in script
    assert "--dbname=display" in script
    assert "'database_cutover_authorized': False" in script
    assert "'deployment_authorized': False" in script
    assert 'ALTER SYSTEM' not in script
    assert 'CREATE DATABASE' not in script
    assert '["pg_restore"' not in script


def test_reject_duplicate_release_evidence_and_unexpected_manifest(tmp_path,monkeypatch):
    mount,dest,sha=_source(tmp_path)
    _stub_dump(monkeypatch)
    stage=Path(mod.capture(mount,dest,release_id=RELEASE,expected_sha256=sha,expected_size=len(STABLE))['stage'])
    manifest=json.loads((stage/'manifest.json').read_text())
    manifest['releases'].append(dict(manifest['releases'][0]))
    (stage/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(mod.BackupEvidenceError,match='invalid_release_inventory'):
        mod.verify(stage)


def test_reject_unrecognized_tar_before_dump(tmp_path,monkeypatch):
    mount,dest,sha=_source(tmp_path)
    calls=_stub_dump(monkeypatch)
    (mount/'store'/'unsafe-backup.tar').write_bytes(b'bad')
    with pytest.raises(mod.BackupEvidenceError,match='unrecognized_release_tar_in_store'):
        mod.capture(mount,dest,release_id=RELEASE,expected_sha256=sha,expected_size=len(STABLE))
    assert not calls


def test_no_operator_capture_when_destination_is_redirected(tmp_path,monkeypatch):
    mount,dest,sha=_source(tmp_path)
    calls=_stub_dump(monkeypatch)
    redirect=tmp_path/'stage-symlink'
    redirect.symlink_to(dest, target_is_directory=True)
    with pytest.raises(mod.BackupEvidenceError,match='directory_missing_or_redirected'):
        mod.capture(mount,redirect,release_id=RELEASE,expected_sha256=sha,expected_size=len(STABLE))
    assert not calls


def test_offline_restore_wrapper_requires_isolation_and_closed_release():
    script=(ROOT/'scripts/display_62b_offline_restore.sh').read_text()
    assert '--network none' in script
    assert 'display_62b_backup_evidence.py' in script and '--verify-stage' in script
    assert 'pg_restore --exit-on-error --single-transaction' in script
    assert 'clientflow_release_control' in script
    assert 'NOT fresh_install_open AND NOT fleet_open AND NOT cutover_enabled' in script
    assert 'docker rm --force --volumes' in script
    assert 'DISPLAY_62B_OFFLINE_RESTORE_PASS' in script
    assert '--network host' not in script
    assert 'docker cp' not in script
