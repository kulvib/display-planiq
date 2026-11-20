"""Fail-closed, read-only local recovery evidence for the exact stuck 1247 pilot."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.phase63d13_viborg1_recovery_preflight import (
    DEPLOYMENT_ID, OLD, NEW, APPROVAL, SHA, SOURCE, inspect,
)


def _write(path: Path, body: dict, *, public=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body), encoding='utf-8')
    path.chmod(0o644 if public else 0o600)


def fixture(tmp_path):
    root = tmp_path
    installed = root / 'opt/clientflow/releases'
    (installed / OLD).mkdir(parents=True)
    (installed / NEW).mkdir(parents=True)
    active = root / 'opt/clientflow/active'
    active.symlink_to('releases/' + OLD)
    _write(root / 'var/lib/clientflow/install-coordinator/state.json', {
        'schema_version': 1, 'owner': 'update_clientflow', 'operation_id': DEPLOYMENT_ID,
    })
    _write(root / 'var/lib/clientflow/update-controller/state.json', {
        'phase': 'activation_authorized', 'deployment': {
            'deployment_id': DEPLOYMENT_ID, 'target_release_id': NEW,
            'bundle_sha256': SHA, 'release_approval_reference': APPROVAL,
        },
    })
    _write(root / 'var/lib/clientflow/release/state.json', {
        'active_release_id': OLD, 'staged_release_id': NEW,
        'activation_intent': None, 'installed': {NEW: {
            'bundle_sha256': SHA, 'release_approval_reference': APPROVAL,
            'source_commit': SOURCE,
        }},
    })
    _write(root / 'var/lib/clientflow/release-status/state.json', {
        'deployment_id': DEPLOYMENT_ID, 'target_release_id': NEW,
        'phase': 'activating',
    }, public=True)
    _write(installed / NEW / 'release-manifest.json', {
        'release_id': NEW, 'version': '1.3.46', 'release_sequence': 1247,
        'release_approval': {'reference': APPROVAL}, 'source': {'commit': SOURCE},
    }, public=True)
    return root


def test_exact_local_evidence_passes_but_no_backend_or_activation_authority(tmp_path):
    root = fixture(tmp_path)
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    result = inspect(root, check_services=False)
    assert result['local_evidence_pass'] is True
    assert result['backend_state_independently_verified'] is False
    assert result['recovery_approved'] is False
    assert result['recovery_performed'] is False
    after = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    assert after == before


@pytest.mark.parametrize('relative,key,value', [
    ('var/lib/clientflow/install-coordinator/state.json', 'owner', 'update_os'),
    ('var/lib/clientflow/install-coordinator/state.json', 'operation_id', '00000000-0000-4000-8000-000000000000'),
    ('var/lib/clientflow/update-controller/state.json', 'phase', 'observed'),
    ('var/lib/clientflow/release/state.json', 'active_release_id', NEW),
    ('var/lib/clientflow/release/state.json', 'activation_intent', {'release_id': NEW}),
    ('var/lib/clientflow/release-status/state.json', 'phase', 'completed'),
    ('opt/clientflow/releases/' + NEW + '/release-manifest.json', 'release_sequence', 1248),
])
def test_wrong_state_is_denied(tmp_path, relative, key, value):
    root = fixture(tmp_path)
    path = root / relative
    data = json.loads(path.read_text())
    data[key] = value
    path.write_text(json.dumps(data))
    assert inspect(root, check_services=False)['local_evidence_pass'] is False


def test_wrong_active_symlink_denied(tmp_path):
    root = fixture(tmp_path)
    active = root / 'opt/clientflow/active'
    active.unlink()
    active.symlink_to('releases/' + NEW)
    assert inspect(root, check_services=False)['local_evidence_pass'] is False


def test_symlinked_privileged_state_refused(tmp_path):
    root = fixture(tmp_path)
    state = root / 'var/lib/clientflow/release/state.json'
    state.rename(state.with_suffix('.saved'))
    state.symlink_to(state.with_suffix('.saved'))
    with pytest.raises(ValueError, match='Untrusted journal'):
        inspect(root, check_services=False)


def test_world_readable_privileged_state_refused(tmp_path):
    root = fixture(tmp_path)
    state = root / 'var/lib/clientflow/release/state.json'
    state.chmod(0o644)
    with pytest.raises(ValueError, match='Untrusted journal'):
        inspect(root, check_services=False)
