"""61B-2J: 1247 successor source must never inherit 1245/1246 approval.

Source-only and filesystem-isolated; no tokens, DB, live network or mutation.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / 'scripts/clientflow_61b2g_release_source_gate.py'
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location('candidate_gate_61b2j', GATE)
gate = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(gate)


def _copy(root: Path) -> Path:
    target = root / 'repo'
    names = {line.split('  ', 1)[1] for line in (ROOT / 'SHA256SUMS.txt').read_text().splitlines()}
    names.update(('SHA256SUMS.txt', 'scripts/build_clientflow_release.py',
                  '.github/workflows/release-build.yml', '.github/workflows/release-approve.yml'))
    for name in names:
        out = target / name
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, out)
    return target


def _rehash(root: Path, name: str) -> None:
    sha = hashlib.sha256((root / name).read_bytes()).hexdigest()
    manifest = root / 'SHA256SUMS.txt'
    lines = manifest.read_text().splitlines()
    assert sum(line.endswith('  ' + name) for line in lines) == 1
    manifest.write_text('\n'.join((sha + '  ' + name) if line.endswith('  ' + name) else line
                                  for line in lines) + '\n')


def test_unsigned_candidate_has_new_source_identity_and_no_approval():
    assert (ROOT / 'client/VERSION').read_text().strip() == '1.3.47'
    assert json.loads((ROOT / 'client/release/release-input.json').read_text())['release_sequence'] == 1248
    result = gate.inspect(ROOT)
    assert result['source_verified'] is True, result['checks']
    assert result['candidate_identity_advanced'] is True
    assert result['result'] == 'READY_FOR_UNSIGNED_CANDIDATE_BUILD'
    assert result['release_approved'] is False
    assert result['deployment_authorized'] is False
    assert result['pilot_accepted'] is False
    assert result['signature_verified'] is False
    assert result['fresh_install_concurrency_proven'] is False
    assert result['checks']['unchanged_approved_stable_catalog_and_disarmed_pilot']['pass'] is True


def test_active_catalog_and_approval_remain_original_1245():
    cat = json.loads((ROOT / 'backend/service1/clientflow_release_catalog.json').read_text())
    fleet = json.loads((ROOT / 'backend/service1/clientflow_1245_fleet_acceptance.json').read_text())
    approval = json.loads((ROOT / 'backend/service1/clientflow_pilot_1245_approval.json').read_text())
    assert cat['latest_stable'] == cat['default_install_version'] == '1.3.44'
    assert cat['catalog_sequence'] == 1247
    assert len(cat['releases']) == 3
    assert cat['releases'][0]['release_id'] == 'clientflow-1.3.44-seq-1245'
    assert approval['release_id'] == fleet['release_id'] == 'clientflow-1.3.44-seq-1245'
    assert fleet['physical_pilot_accepted'] is False
    assert cat['releases'][1]['release_id'] == 'clientflow-1.3.45-seq-1246'
    assert cat['releases'][1]['status'] == 'supported'
    assert cat['releases'][1]['installable'] is False
    assert cat['releases'][2]['release_id'] == 'clientflow-1.3.46-seq-1247'
    assert cat['releases'][2]['installable'] is False


@pytest.mark.parametrize('field,value', [
    ('catalog_sequence', 1248),
    ('latest_stable', '1.3.45'),
    ('default_install_version', '1.3.45'),
])
def test_even_rehashed_catalog_promotion_fails_source_gate(tmp_path, field, value):
    root = _copy(tmp_path)
    path = root / 'backend/service1/clientflow_release_catalog.json'
    record = json.loads(path.read_text())
    record[field] = value
    path.write_text(json.dumps(record))
    _rehash(root, 'backend/service1/clientflow_release_catalog.json')
    report = gate.inspect(root)
    assert report['checks']['complete_sha256_manifest']['pass'] is True
    assert report['checks']['unchanged_approved_stable_catalog_and_disarmed_pilot']['pass'] is False
    assert report['result'] == 'SOURCE_INVALID'


@pytest.mark.parametrize('name,field,value', [
    ('backend/service1/clientflow_1245_fleet_acceptance.json', 'physical_pilot_accepted', True),
    ('backend/service1/clientflow_pilot_1245_approval.json', 'approved_bundle_sha256', '0' * 64),
])
def test_rehashed_approval_or_acceptance_mutation_fails_closed(tmp_path, name, field, value):
    root = _copy(tmp_path)
    path = root / name
    record = json.loads(path.read_text())
    record[field] = value
    path.write_text(json.dumps(record))
    _rehash(root, name)
    report = gate.inspect(root)
    assert report['checks']['complete_sha256_manifest']['pass'] is True
    assert report['checks']['unchanged_approved_stable_catalog_and_disarmed_pilot']['pass'] is False
    assert report['source_verified'] is False


@pytest.mark.parametrize('version,sequence', [
    ('1.3.44', 1245), ('1.3.44', 1246), ('1.3.45', 1245),
    ('1.3.45', 1246), ('1.3.46', 1246), ('1.3.47', 1247), ('1.3.48', 1249), ('1.3.43', 1246),
])
def test_non_candidate_pair_cannot_pass_candidate_build_gate(tmp_path, version, sequence):
    root = _copy(tmp_path)
    path = root / 'client/VERSION'
    path.write_text(version + '\n')
    _rehash(root, 'client/VERSION')
    path = root / 'client/release/release-input.json'
    record = json.loads(path.read_text())
    record['release_sequence'] = sequence
    path.write_text(json.dumps(record))
    _rehash(root, 'client/release/release-input.json')
    report = gate.inspect(root)
    assert report['source_verified'] is True
    assert report['candidate_identity_advanced'] is False
    assert report['deployment_authorized'] is False
    assert report['result'] == 'STOP_STABLE_SOURCE_NOT_A_NEW_CANDIDATE'
