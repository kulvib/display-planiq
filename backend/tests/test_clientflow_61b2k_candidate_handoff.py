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
    # Keep the historical unsigned-1246 handoff isolated from the active 1247
    # production catalog. This fixture must remain an exact 1246 source state.
    shutil.copy2(
        ROOT / 'backend/service1/clientflow_release_catalog_1246_pilot.stage.json',
        repo / 'backend/service1/clientflow_release_catalog.json',
    )
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


def test_actual_source_catalog_preserves_stable_1245_and_only_update_only_1248():
    assert (ROOT / 'client/VERSION').read_text().strip() == '1.4.1'
    inputs = json.loads((ROOT / 'client/release/release-input.json').read_text())
    assert inputs['release_sequence'] == 1251
    cat = json.loads((ROOT / 'backend/service1/clientflow_release_catalog_1248_pilot.stage.json').read_text())
    assert cat['latest_stable'] == cat['default_install_version'] == '1.3.44'
    assert cat['catalog_sequence'] == 1248
    assert len(cat['releases']) == 3
    assert [entry['release_id'] for entry in cat['releases']] == [
        'clientflow-1.3.44-seq-1245',
        'clientflow-1.3.46-seq-1247',
        'clientflow-1.3.47-seq-1248',
    ]
    assert sum(entry['installable'] is True for entry in cat['releases']) == 1
    assert all(entry['rollback_allowed'] is False for entry in cat['releases'])
    assert cat['releases'][2]['installable'] is False
    assert cat['releases'][2]['install_modes'] == ['in_place_update']
    assert cat['releases'][2]['min_current_version'] == cat['releases'][2]['max_current_version'] == '1.3.46'
    fleet = json.loads((ROOT / 'backend/service1/clientflow_1245_fleet_acceptance.json').read_text())
    assert fleet['physical_pilot_accepted'] is False


def test_current_approved_1248_handoff_accepts_only_exact_pinned_1248_catalog(tmp_path):
    """Regression: exact current 1248 stage may verify 1248 source provenance."""
    repo = tmp_path / "repo"
    paths = [
        'backend/service1/clientflow_release_catalog.json',
        'backend/service1/clientflow_release_catalog_1246_pilot.stage.json',
        'backend/service1/clientflow_pilot_1246_approval.json',
        'backend/service1/clientflow_release_catalog_1247_pilot.stage.json',
        'backend/service1/clientflow_pilot_1247_approval.json',
        'backend/service1/clientflow_release_catalog_1248_pilot.stage.json',
        'backend/service1/clientflow_pilot_1248_approval.json',
    ]
    for name in paths:
        destination = repo / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / (paths[5] if name == paths[0] else name), destination)

    assert handoff_gate._verify_original_catalog(repo, "clientflow-1.3.47-seq-1248", 1248) is None
    active_path = repo / paths[0]
    catalog = json.loads(active_path.read_text())
    catalog['releases'][2]['installable'] = True  # unauthorized promotion
    _save(active_path, catalog)
    with pytest.raises(handoff_gate.HandoffError, match='stable_catalog_changed'):
        handoff_gate._verify_original_catalog(repo, 'clientflow-1.3.47-seq-1248', 1248)

    # A rollback to the valid 1246 pilot catalog is also not a valid base for 1248.
    shutil.copy2(ROOT / paths[1], active_path)
    with pytest.raises(handoff_gate.HandoffError, match='stable_catalog_changed'):
        handoff_gate._verify_original_catalog(repo, 'clientflow-1.3.47-seq-1248', 1248)


def test_full_unsigned_1248_handoff_with_exact_active_1248_catalog(scenario):
    """End-to-end reproduction of the gate reached in 1248 release-build CI."""
    repo, handoff = scenario
    for name in (
        'backend/service1/clientflow_release_catalog.json',
        'backend/service1/clientflow_release_catalog_1247_pilot.stage.json',
        'backend/service1/clientflow_pilot_1247_approval.json',
        'backend/service1/clientflow_release_catalog_1248_pilot.stage.json',
        'backend/service1/clientflow_pilot_1248_approval.json',
    ):
        source = 'backend/service1/clientflow_release_catalog_1248_pilot.stage.json' if name.endswith('/clientflow_release_catalog.json') else name
        shutil.copy2(ROOT / source, repo / name)
    (repo / 'client/VERSION').write_text('1.3.47\n')
    source_inputs = json.loads((repo / 'client/release/release-input.json').read_text())
    source_inputs['release_sequence'] = 1248
    _save(repo / 'client/release/release-input.json', source_inputs)

    release_id = 'clientflow-1.3.47-seq-1248'
    candidate = release_id + '-candidate.tar'
    installer = 'clientflow-installer-1.3.47.pyz'
    (handoff / INSTALLER).rename(handoff / installer)
    (handoff / CANDIDATE).unlink()
    manifest_path = handoff / 'manifest.candidate.json'
    manifest = json.loads(manifest_path.read_text())
    manifest.update(version='1.3.47', release_sequence=1248, release_id=release_id)
    manifest['fresh_installer']['file'] = installer
    _save(manifest_path, manifest)
    with tarfile.open(handoff / candidate, 'w', format=tarfile.PAX_FORMAT) as archive:
        for member, blob in (
            ('manifest.json', manifest_path.read_bytes()),
            ('clientflow-payload.tar', (handoff / 'clientflow-payload.tar').read_bytes()),
            (installer, (handoff / installer).read_bytes()),
        ):
            _add_member(archive, member, blob)

    artifact_names = sorted({candidate, installer, 'clientflow-payload.tar', 'manifest.candidate.json'})
    sums = ''.join(f'{_hash((handoff / name).read_bytes())}  {name}\n' for name in artifact_names)
    (handoff / 'SHA256SUMS').write_text(sums)
    record_path = handoff / 'REPRODUCIBILITY.json'
    record = json.loads(record_path.read_text())
    record.update(version='1.3.47', release_sequence=1248, release_id=release_id)
    record['artifacts'] = {
        name: {'size': (handoff / name).stat().st_size, 'sha256': _hash((handoff / name).read_bytes())}
        for name in artifact_names + ['SHA256SUMS']
    }
    _save(record_path, record)

    verified = handoff_gate.verify(
        repo, handoff, source_sha=SHA,
        candidate_sha256=_hash((handoff / candidate).read_bytes()),
        installer_sha256=_hash((handoff / installer).read_bytes()),
        runtime_transport_sha256=TRANSPORT,
    )
    assert verified['result'] == 'VERIFIED_UNSIGNED_HANDOFF_ONLY'
    assert verified['release_id'] == release_id
    assert verified['release_approved'] is False
    assert verified['deployment_authorized'] is False
