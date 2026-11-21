"""61B-2G: immutable source/release-candidate readiness without approval."""
from __future__ import annotations

from pathlib import Path
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / 'scripts/clientflow_61b2g_release_source_gate.py'
spec = importlib.util.spec_from_file_location('release_source_gate_61b2g', SCRIPT)
gate = importlib.util.module_from_spec(spec)
assert spec and spec.loader
# Loading a script via spec_from_file_location does not add its directory to
# sys.path, unlike `python scripts/clientflow_61b2g_release_source_gate.py`.
# Make the sibling 63D-6 catalog contract importable for this isolated test.
script_dir = str(SCRIPT.parent)
sys.path.insert(0, script_dir)
try:
    spec.loader.exec_module(gate)
finally:
    sys.path.remove(script_dir)


def _copy_repository(tmp_path: Path) -> Path:
    root = tmp_path / 'repo'
    manifest = (REPO / 'SHA256SUMS.txt').read_text(encoding='utf-8')
    required = {x.split('  ', 1)[1] for x in manifest.splitlines() if x}
    required.update(('SHA256SUMS.txt', 'scripts/build_clientflow_release.py',
                     '.github/workflows/release-build.yml',
                     '.github/workflows/release-approve.yml'))
    for relative in required:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / relative, target)
    return root


def _rehash(root: Path, name: str):
    lines = (root / 'SHA256SUMS.txt').read_text().splitlines()
    replacement = hashlib.sha256((root / name).read_bytes()).hexdigest() + '  ' + name
    lines = [replacement if line.endswith('  ' + name) else line for line in lines]
    (root / 'SHA256SUMS.txt').write_text('\n'.join(lines) + '\n')


def test_pristine_main_source_passes_but_is_not_a_new_candidate():
    report = gate.inspect(REPO)
    assert report['source_verified'] is True
    if report['version'] == '1.3.44' and report['release_sequence'] == 1245:
        assert report['result'] == 'STOP_STABLE_SOURCE_NOT_A_NEW_CANDIDATE'
    else:
        assert report['result'] == 'READY_FOR_UNSIGNED_CANDIDATE_BUILD'
        assert report['candidate_identity_advanced'] is True
    assert report['deployment_authorized'] is False
    assert report['pilot_accepted'] is False
    assert report['signature_verified'] is False
    assert report['fresh_install_concurrency_proven'] is False


def test_cli_is_readonly_and_requires_explicit_candidate_gate():
    paths = [REPO / 'client/VERSION', REPO / 'client/release/release-input.json',
             REPO / 'SHA256SUMS.txt']
    before = [path.read_bytes() for path in paths]
    base = [sys.executable, str(SCRIPT), '--repo-root', str(REPO)]
    normal = subprocess.run(base, capture_output=True, text=True, check=False)
    source = subprocess.run(base + ['--source-only'], capture_output=True, text=True, check=False)
    assert normal.returncode in (0, 2)  # depends only on canonical source version
    assert normal.returncode == (0 if json.loads(normal.stdout)['candidate_identity_advanced'] else 2)
    assert source.returncode == 0
    assert json.loads(normal.stdout)['release_approved'] is False
    assert [path.read_bytes() for path in paths] == before


def test_new_unsigned_source_identity_can_pass_only_build_eligibility(tmp_path):
    root = _copy_repository(tmp_path)
    (root / 'client/VERSION').write_text('1.3.47\n')
    _rehash(root, 'client/VERSION')
    release_input = root / 'client/release/release-input.json'
    record = json.loads(release_input.read_text())
    record['release_sequence'] = 1248
    release_input.write_text(json.dumps(record) + '\n')
    _rehash(root, 'client/release/release-input.json')
    result = gate.inspect(root)
    assert result['source_verified'] is True
    assert result['candidate_identity_advanced'] is True
    assert result['result'] == 'READY_FOR_UNSIGNED_CANDIDATE_BUILD'
    assert result['deployment_authorized'] is False
    assert result['release_approved'] is False
    assert result['signature_verified'] is False
    assert result['pilot_accepted'] is False


@pytest.mark.parametrize('version,sequence', [('1.3.44', 1246), ('1.3.45', 1245), ('1.3.45', 1246), ('1.3.46', 1246), ('1.3.43', 1246), ('1.3.47', 1247), ('1.3.48', 1249)])
def test_version_and_sequence_both_must_advance(tmp_path, version, sequence):
    root = _copy_repository(tmp_path)
    (root / 'client/VERSION').write_text(version + '\n')
    _rehash(root, 'client/VERSION')
    target = root / 'client/release/release-input.json'
    record = json.loads(target.read_text())
    record['release_sequence'] = sequence
    target.write_text(json.dumps(record) + '\n')
    _rehash(root, 'client/release/release-input.json')
    report = gate.inspect(root)
    assert report['source_verified'] is True
    assert report['candidate_identity_advanced'] is False
    assert report['result'] == 'STOP_STABLE_SOURCE_NOT_A_NEW_CANDIDATE'


def test_tampering_with_a_source_file_fails_closed(tmp_path):
    root = _copy_repository(tmp_path)
    (root / 'client/libexec/update-maintenance-screen').write_text('untrusted new screen')
    report = gate.inspect(root)
    assert report['source_verified'] is False
    assert report['checks']['complete_sha256_manifest']['pass'] is False
    assert report['result'] == 'SOURCE_INVALID'


def test_duplicate_manifest_entry_fails_closed(tmp_path):
    root = _copy_repository(tmp_path)
    manifest = root / 'SHA256SUMS.txt'
    first = manifest.read_text().splitlines()[0]
    manifest.write_text(manifest.read_text() + first + '\n')
    assert not gate.inspect(root)['checks']['complete_sha256_manifest']['pass']


def test_manifest_path_traversal_fails_closed(tmp_path):
    root = _copy_repository(tmp_path)
    manifest = root / 'SHA256SUMS.txt'
    manifest.write_text(manifest.read_text() + '0' * 64 + '  ../escape\n')
    assert not gate.inspect(root)['checks']['complete_sha256_manifest']['pass']


def test_contract_changed_even_if_manifest_is_rehashed_fails_closed(tmp_path):
    root = _copy_repository(tmp_path)
    file = root / 'client/stable-systemd/planiq-display-maintenance.service'
    file.write_text(file.read_text().replace('NoNewPrivileges=yes', 'NoNewPrivileges=no'))
    _rehash(root, 'client/stable-systemd/planiq-display-maintenance.service')
    report = gate.inspect(root)
    assert report['checks']['complete_sha256_manifest']['pass'] is True
    assert report['checks']['installation_and_maintenance_source_contracts']['pass'] is False
    assert report['result'] == 'SOURCE_INVALID'


def test_approval_workflow_cannot_silently_weaken(tmp_path):
    root = _copy_repository(tmp_path)
    file = root / '.github/workflows/release-approve.yml'
    file.write_text(file.read_text().replace('test "$APPROVE_RELEASE" = "true"', 'test "$APPROVE_RELEASE" = "false"'))
    report = gate.inspect(root)
    assert report['checks']['release_provenance_and_manual_approval_contracts']['pass'] is False
    assert report['result'] == 'SOURCE_INVALID'


def test_source_root_must_be_absolute(tmp_path):
    with pytest.raises(ValueError, match='absolute'):
        gate.inspect(Path('relative'))


def test_preclaim_host_apt_lock_is_mandatory_even_with_updated_source_hashes(tmp_path):
    root = _copy_repository(tmp_path)
    target = root / 'client/release/lib/clientflow_release/cli.py'
    original = target.read_text(encoding='utf-8')
    assert 'with install_coordinator.preclaim_host_guard(' in original
    target.write_text(original.replace('with install_coordinator.preclaim_host_guard(',
                                       'with install_coordinator.DISABLED_preclaim_host_guard('), encoding='utf-8')
    _rehash(root, 'client/release/lib/clientflow_release/cli.py')
    report = gate.inspect(root)
    assert report['checks']['complete_sha256_manifest']['pass'] is True
    assert report['checks']['installation_and_maintenance_source_contracts']['pass'] is False
    assert report['source_verified'] is False
    assert report['result'] == 'SOURCE_INVALID'
