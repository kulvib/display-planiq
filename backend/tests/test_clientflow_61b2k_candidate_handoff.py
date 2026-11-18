"""61B-2K: offline handoff must fail closed, on both sides of manual approval."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import shutil
import sys
from pathlib import Path
import tarfile

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/verify_clientflow_candidate_handoff.py'
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location('clientflow_61b2k_handoff', SCRIPT)
assert spec and spec.loader
handoff_gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handoff_gate)
SHA = 'a' * 40
EPOCH = 1700000000
TRANSPORT = 'b' * 64
RELEASE = 'clientflow-1.3.45-seq-1246'
CANDIDATE = RELEASE + '-candidate.tar'
INSTALLER = 'clientflow-installer-1.3.45.pyz'


def _save(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def _hash(data: bytes):
    return hashlib.sha256(data).hexdigest()


def _add_member(tar: tarfile.TarFile, name: str, data: bytes):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.uid = info.gid = 0
    info.mtime = EPOCH
    info.mode = 0o644
    tar.addfile(info, io.BytesIO(data))


def _reindex(handoff: Path):
    names = {CANDIDATE, INSTALLER, 'clientflow-payload.tar', 'manifest.candidate.json'}
    entries = {n: {'size': (handoff / n).stat().st_size,
                   'sha256': _hash((handoff / n).read_bytes())} for n in sorted(names)}
    (handoff / 'SHA256SUMS').write_text(''.join(f"{entries[n]['sha256']}  {n}\n" for n in sorted(names)))
    record = json.loads((handoff / 'REPRODUCIBILITY.json').read_text())
    record['artifacts'] = {**entries, 'SHA256SUMS': {
        'size': (handoff / 'SHA256SUMS').stat().st_size,
        'sha256': _hash((handoff / 'SHA256SUMS').read_bytes())}}
    _save(handoff / 'REPRODUCIBILITY.json', record)


@pytest.fixture
def scenario(tmp_path: Path):
    repo = tmp_path / 'repo'
    handoff = tmp_path / 'handoff'
    handoff.mkdir()
    (repo / 'client').mkdir(parents=True)
    (repo / 'client/VERSION').write_text('1.3.45\n')
    _save(repo / 'client/release/release-input.json', {
        'release_sequence': 1246, 'runtime_python': '3.13.14',
        'architecture': 'amd64', 'minimum_ubuntu_lts': '26.04'})
    _save(repo / 'client/release/release-build-toolchain.json', {
        'python': '3.13.14', 'pip': '26.1.2', 'setuptools': '83.0.0'})
    for name in (
        'backend/service1/clientflow_release_catalog.json',
        'backend/service1/clientflow_release_catalog_1246_pilot.stage.json',
        'backend/service1/clientflow_pilot_1246_approval.json',
    ):
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, path)
    _save(repo / 'backend/service1/clientflow_1245_fleet_acceptance.json', {
        'physical_pilot_accepted': False})
    payload = b'this-is-a-synthetic-test-payload'
    installer = b'#!/usr/bin/env python3\n'
    (handoff / 'clientflow-payload.tar').write_bytes(payload)
    (handoff / INSTALLER).write_bytes(installer)
    manifest = {
        'version': '1.3.45', 'release_sequence': 1246, 'release_id': RELEASE,
        'source_date_epoch': EPOCH, 'source': {'commit': SHA, 'dirty': False},
        'deployable': False, 'release_approval': {'reference': None, 'candidate_sha256': None},
        'activation': {'automatic': False, 'requires_manual_approval': True},
        'runtime': {'offline_wheelhouse_complete': True, 'python': '3.13.14'},
        'platform': {'architecture': 'amd64', 'minimum_lts': '26.04'},
        'payload': {'file': 'clientflow-payload.tar', 'size': len(payload), 'sha256': _hash(payload)},
        'fresh_installer': {'file': INSTALLER, 'size': len(installer), 'sha256': _hash(installer)},
    }
    _save(handoff / 'manifest.candidate.json', manifest)
    with tarfile.open(handoff / CANDIDATE, 'w', format=tarfile.PAX_FORMAT) as tar:
        _add_member(tar, 'manifest.json', (handoff / 'manifest.candidate.json').read_bytes())
        _add_member(tar, 'clientflow-payload.tar', payload)
        _add_member(tar, INSTALLER, installer)
    _save(handoff / 'REPRODUCIBILITY.json', {
        'schema_version': 1, 'reproducible': True,
        'release_id': RELEASE, 'version': '1.3.45', 'release_sequence': 1246,
        'source_commit': SHA, 'source_date_epoch': EPOCH,
        'runtime_inputs_transport_sha256': TRANSPORT,
        'build_toolchain': {'python': '3.13.14', 'pip': '26.1.2', 'setuptools': '83.0.0'},
        'artifacts': {}})
    _reindex(handoff)
    return repo, handoff


def _verify(scenario):
    repo, handoff = scenario
    return handoff_gate.verify(repo, handoff, source_sha=SHA,
                               candidate_sha256=_hash((handoff / CANDIDATE).read_bytes()),
                               installer_sha256=_hash((handoff / INSTALLER).read_bytes()),
                               runtime_transport_sha256=TRANSPORT)


def test_valid_synthetic_unsigned_handoff_passes_without_approval(scenario):
    result = _verify(scenario)
    assert result['result'] == 'VERIFIED_UNSIGNED_HANDOFF_ONLY'
    assert result['release_id'] == RELEASE
    assert result['release_approved'] is False
    assert result['deployment_authorized'] is False
    assert result['physical_pilot_accepted'] is False


@pytest.mark.parametrize('attack', [
    'extra_file', 'missing_file', 'tampered_payload', 'tampered_manifest',
    'altered_installer', 'wrong_source', 'wrong_transport', 'already_approved',
    'already_deployable', 'auto_activation', 'incomplete_runtime',
    'changed_catalog', 'accepted_pilot', 'duplicate_checksums',
    'symlink_installer', 'rehashed_loose_payload', 'rehashed_manifest_only',
    'embedded_duplicate', 'embedded_symlink', 'unexpected_tar_entry',
    'tampered_reproducibility', 'wrong_epoch', 'wrong_build_toolchain',
])
def test_modified_or_unsafe_handoff_fails_closed(tmp_path, scenario, attack):
    repo, handoff = scenario
    if attack == 'extra_file':
        (handoff / 'extra').write_bytes(b'extra')
    elif attack == 'missing_file':
        (handoff / INSTALLER).unlink()
    elif attack == 'tampered_payload':
        (handoff / 'clientflow-payload.tar').write_bytes(b'changed')
    elif attack == 'altered_installer':
        (handoff / INSTALLER).write_bytes(b'changed')
    elif attack == 'tampered_manifest':
        with (handoff / 'manifest.candidate.json').open('ab') as f: f.write(b' ')
    elif attack == 'wrong_source':
        with pytest.raises(handoff_gate.HandoffError):
            handoff_gate.verify(repo, handoff, source_sha='f' * 40)
        return
    elif attack == 'wrong_transport':
        with pytest.raises(handoff_gate.HandoffError):
            handoff_gate.verify(repo, handoff, source_sha=SHA, runtime_transport_sha256='0'*64)
        return
    elif attack in ('already_approved','already_deployable','auto_activation','incomplete_runtime'):
        path = handoff / 'manifest.candidate.json'
        obj = json.loads(path.read_text())
        if attack == 'already_approved': obj['release_approval']['reference'] = 'test'
        if attack == 'already_deployable': obj['deployable'] = True
        if attack == 'auto_activation': obj['activation']['automatic'] = True
        if attack == 'incomplete_runtime': obj['runtime']['offline_wheelhouse_complete'] = False
        _save(path, obj)
        _reindex(handoff)
    elif attack == 'changed_catalog':
        path = repo / 'backend/service1/clientflow_release_catalog.json'
        obj = json.loads(path.read_text());obj['latest_stable'] = '1.3.45';_save(path,obj)
    elif attack == 'accepted_pilot':
        _save(repo / 'backend/service1/clientflow_1245_fleet_acceptance.json', {'physical_pilot_accepted':True})
    elif attack == 'duplicate_checksums':
        path = handoff / 'SHA256SUMS';path.write_text(path.read_text()+path.read_text().splitlines()[0]+'\n')
        record_path = handoff / 'REPRODUCIBILITY.json'
        record = json.loads(record_path.read_text())
        record['artifacts']['SHA256SUMS'] = {'size': path.stat().st_size, 'sha256': _hash(path.read_bytes())}
        _save(record_path, record)
    elif attack == 'symlink_installer':
        path = handoff / INSTALLER; data = path.read_bytes(); path.unlink(); tmp = tmp_path / 'other';tmp.write_bytes(data); path.symlink_to(tmp)
    elif attack == 'rehashed_loose_payload':
        (handoff / 'clientflow-payload.tar').write_bytes(b'changed and rehashed');_reindex(handoff)
    elif attack == 'rehashed_manifest_only':
        path = handoff / 'manifest.candidate.json';obj=json.loads(path.read_text());obj['release_id']='clientflow-1.3.44-seq-1245';_save(path,obj);_reindex(handoff)
    elif attack in ('embedded_duplicate','embedded_symlink','unexpected_tar_entry'):
        path = handoff / CANDIDATE
        # Append to a valid tar to prove a duplicate/unsafe member cannot be ignored.
        with tarfile.open(path, 'a') as tar:
            if attack == 'embedded_duplicate':
                _add_member(tar, 'manifest.json', b'{}')
            elif attack == 'embedded_symlink':
                info = tarfile.TarInfo('marker'); info.type=tarfile.SYMTYPE;info.linkname='../etc/passwd';tar.addfile(info)
            else:
                _add_member(tar, '../escape', b'bad')
        _reindex(handoff)
    elif attack in ('tampered_reproducibility','wrong_epoch','wrong_build_toolchain'):
        path = handoff / 'REPRODUCIBILITY.json';obj=json.loads(path.read_text())
        if attack=='tampered_reproducibility':obj['reproducible']=False
        if attack=='wrong_epoch':obj['source_date_epoch']+=1
        if attack=='wrong_build_toolchain':obj['build_toolchain']['pip']='1.0'
        _save(path,obj)
    with pytest.raises((handoff_gate.HandoffError, OSError, KeyError, TypeError, ValueError)):
        _verify(scenario)


def test_workflows_run_same_strict_handoff_gate_before_attestation_and_manual_approval():
    build = (ROOT / '.github/workflows/release-build.yml').read_text()
    approve = (ROOT / '.github/workflows/release-approve.yml').read_text()
    assert build.count('python scripts/verify_clientflow_candidate_handoff.py') == 1
    assert approve.count('/usr/bin/python3 scripts/verify_clientflow_candidate_handoff.py') == 1
    assert build.index('Verify complete unapproved candidate handoff') < build.index('Attest reproducible candidate provenance')
    assert approve.index('Reverify exact unapproved candidate handoff') < approve.index('Approve exact candidate with canonical source approval gate')
    for content in (build, approve):
        assert '--expected-source-sha' in content
        assert '--handoff "$RUNNER_TEMP/handoff"' in content
        assert not any(action in content[content.index('verify_clientflow_candidate_handoff.py'):content.index('verify_clientflow_candidate_handoff.py')+150]
                       for action in ('--approve-release', '--publish-release'))
        assert yaml.safe_load(content)['on']['workflow_dispatch']['inputs']


def test_actual_source_catalog_still_disarmed_for_1246_candidate():
    assert (ROOT / 'client/VERSION').read_text().strip() == '1.3.45'
    inputs = json.loads((ROOT / 'client/release/release-input.json').read_text())
    assert inputs['release_sequence'] == 1246
    cat = json.loads((ROOT / 'backend/service1/clientflow_release_catalog.json').read_text())
    assert cat['latest_stable'] == cat['default_install_version'] == '1.3.44'
    assert len(cat['releases']) == 2
    assert cat['releases'][0]['release_id'] == 'clientflow-1.3.44-seq-1245'
    assert cat['releases'][1]['release_id'] == 'clientflow-1.3.45-seq-1246'
    assert cat['releases'][1]['installable'] is False
    fleet = json.loads((ROOT / 'backend/service1/clientflow_1245_fleet_acceptance.json').read_text())
    assert fleet['physical_pilot_accepted'] is False
