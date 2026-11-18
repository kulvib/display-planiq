"""63D-4 archive preflight: offline only, never publish or activate release."""
from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
path = ROOT / 'scripts/clientflow_63d4_verify_1246_archive.py'
spec = spec_from_file_location('clientflow_63d4_verify_1246_archive', path)
assert spec and spec.loader
mod = module_from_spec(spec)
spec.loader.exec_module(mod)


class FakeHandle:
    def __init__(self): self.closed = False
    def close(self): self.closed = True


def _manifest():
    return {
        'version': '1.3.45', 'release_id': mod.PILOT_RELEASE_ID,
        'release_sequence': 1246, 'deployable': True,
        'source': {'commit': mod.SOURCE_COMMIT, 'dirty': False},
        'release_approval': {'reference': mod.APPROVAL_REFERENCE, 'candidate_sha256': mod.CANDIDATE_SHA256},
        'fresh_installer': {'sha256': mod.INSTALLER_SHA256},
    }


def _setup(monkeypatch, tmp_path, *, manifest=None, size=100, sha=None):
    archive=tmp_path/'bundle.tar';archive.write_bytes(b'x'*100)
    monkeypatch.setattr(mod,'APPROVED_BUNDLE_SIZE',100)
    handle=FakeHandle()
    monkeypatch.setattr(mod,'open_verified_bundle',lambda path,**kw:(
        _manifest() if manifest is None else manifest,None,size,
        sha if sha is not None else mod.APPROVED_BUNDLE_SHA256,handle))
    return archive,handle


def test_synthetic_verified_archive_never_authorizes_deployment(monkeypatch,tmp_path):
    archive,handle=_setup(monkeypatch,tmp_path)
    result=mod.verify_1246_archive(archive)
    assert result['status']=='VERIFIED_OFFLINE_ARCHIVE_ONLY'
    assert result['published_to_render'] is False
    assert result['catalog_promoted'] is False
    assert result['deployment_authorized'] is False
    assert handle.closed


@pytest.mark.parametrize('key,value',[
    ('version','1.3.44'), ('release_id','clientflow-1.3.44-seq-1245'),
    ('release_sequence',1245), ('release_sequence','1246'), ('deployable',False),
    ('source',{'commit':'0'*40,'dirty':False}),
    ('source',{'commit':mod.SOURCE_COMMIT,'dirty':True}),
    ('release_approval',{'reference':'other','candidate_sha256':mod.CANDIDATE_SHA256}),
    ('release_approval',{'reference':mod.APPROVAL_REFERENCE,'candidate_sha256':'0'*64}),
    ('fresh_installer',{'sha256':'0'*64}),
])
def test_archive_provenance_mismatch_denied(monkeypatch,tmp_path,key,value):
    manifest=_manifest();manifest[key]=value
    archive,handle=_setup(monkeypatch,tmp_path,manifest=manifest)
    with pytest.raises(mod.ArchivePreflightDenied):
        mod.verify_1246_archive(archive)
    assert handle.closed


@pytest.mark.parametrize('value', ['0'*64,''])
def test_wrong_archive_checksum_denied(monkeypatch,tmp_path,value):
    archive,handle=_setup(monkeypatch,tmp_path,sha=value)
    with pytest.raises(mod.ArchivePreflightDenied):
        mod.verify_1246_archive(archive)
    assert handle.closed


def test_wrong_file_size_denied_before_bundle_open(monkeypatch,tmp_path):
    archive,handle=_setup(monkeypatch,tmp_path)
    monkeypatch.setattr(mod,'APPROVED_BUNDLE_SIZE',101)
    with pytest.raises(mod.ArchivePreflightDenied):
        mod.verify_1246_archive(archive)
    assert not handle.closed


def test_no_symlink_bundle(monkeypatch,tmp_path):
    archive,handle=_setup(monkeypatch,tmp_path)
    link=tmp_path/'link.tar';link.symlink_to(archive)
    with pytest.raises(mod.ArchivePreflightDenied):
        mod.verify_1246_archive(link)
    assert not handle.closed


def test_missing_bundle_denied(monkeypatch,tmp_path):
    _setup(monkeypatch,tmp_path)
    with pytest.raises(mod.ArchivePreflightDenied):
        mod.verify_1246_archive(tmp_path/'not-found.tar')


def test_signed_bundle_failure_denied(monkeypatch,tmp_path):
    archive,_=_setup(monkeypatch,tmp_path)
    def bad(*args,**kwargs): raise RuntimeError('signature mismatch')
    monkeypatch.setattr(mod,'open_verified_bundle',bad)
    with pytest.raises(mod.ArchivePreflightDenied):
        mod.verify_1246_archive(archive)


def test_no_network_or_mutating_release_calls_present():
    source=path.read_text()
    for symbol in ('requests.get(', 'urllib.request', 'subprocess.', 'publish_clientflow_release',
                   'stage_approve_controlled_wave(', 'os.environ[', 'shutil.copy', 'session.commit('):
        assert symbol not in source
