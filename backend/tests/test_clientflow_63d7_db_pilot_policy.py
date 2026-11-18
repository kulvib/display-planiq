"""Strict one-shot database pilot source guard, no database/network needed."""
from __future__ import annotations

from copy import deepcopy
import os

import pytest

from service1.clientflow_pilot_1246_db_authorization import (
    DatabasePilot1246Denied, require_database_pilot_1246,
)
from service1.clientflow_release_pilot_stage_1246 import load_staged_catalog
from service1.clientflow_pilot_1246 import (
    PILOT_FLAG, PILOT_ARM_FLAG, CONFLICTING_FLAGS,
    APPROVED_BUNDLE_SHA256, APPROVED_BUNDLE_SIZE,
    CANDIDATE_SHA256, SOURCE_COMMIT, APPROVAL_REFERENCE, PILOT_RELEASE_ID,
)


def _kwargs():
    catalog = load_staged_catalog()
    return {
        "client_id": 3, "client_name": "Viborg1",
        "current_version": "1.3.43", "expected_current_version": "1.3.43",
        "ubuntu_version": "26.04", "release": deepcopy(catalog["releases"][1]),
        "catalog": catalog, "reason": "Manuelt kontrolleret fysisk pilot",
        "artifact": {
            "target_release_id": PILOT_RELEASE_ID,
            "bundle_sha256": APPROVED_BUNDLE_SHA256,
            "bundle_size": APPROVED_BUNDLE_SIZE,
            "release_approval_reference": APPROVAL_REFERENCE,
            "release_candidate_sha256": CANDIDATE_SHA256,
            "source_commit": SOURCE_COMMIT,
        },
        "policy": {
            "revision": 1, "stable_release_id": "clientflow-1.3.44-seq-1245",
            "stable_bundle_sha256": "28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5",
            "cutover_enabled": False, "fleet_open": False, "fresh_install_open": False,
        },
        "expected_revision": 1,
    }


@pytest.fixture(autouse=True)
def _environment(monkeypatch):
    monkeypatch.setenv('CLIENTFLOW_FRESH_INSTALL_SUSPENDED', '1')
    for name in (PILOT_FLAG, PILOT_ARM_FLAG, *CONFLICTING_FLAGS):
        monkeypatch.delenv(name, raising=False)


def test_exact_1246_from_both_allowed_versions():
    data = _kwargs()
    require_database_pilot_1246(**data)
    data['current_version'] = data['expected_current_version'] = '1.3.44'
    require_database_pilot_1246(**data)


@pytest.mark.parametrize('field,value', [
    ('client_id', 4), ('client_id', True), ('client_name', 'Viborg2'),
    ('current_version', '1.3.42'), ('current_version', '1.3.45'),
    ('expected_current_version', '1.3.44'), ('ubuntu_version', '24.04'),
    ('expected_revision', 2), ('reason', 'short'),
])
def test_denies_non_exact_intent(field, value):
    data = _kwargs(); data[field] = value
    with pytest.raises(DatabasePilot1246Denied):
        require_database_pilot_1246(**data)


@pytest.mark.parametrize('key,value', [
    ('release_id', 'clientflow-1.3.44-seq-1245'),
    ('revision', 'clientflow-1.3.44-seq-1245'),
    ('status', 'stable'), ('installable', True), ('update_allowed', False),
    ('rollback_allowed', True), ('release_sequence', True),
    ('install_modes', ['fresh_install', 'in_place_update']),
    ('max_current_version', '1.3.45'), ('requires_reboot', False),
])
def test_denies_modified_release(key, value):
    data = _kwargs(); data['release'][key] = value
    with pytest.raises(DatabasePilot1246Denied):
        require_database_pilot_1246(**data)


@pytest.mark.parametrize('key,value', [
    ('target_release_id', 'clientflow-1.3.44-seq-1245'),
    ('bundle_sha256', 'f'*64), ('bundle_size', 1), ('bundle_size', True),
    ('release_approval_reference', 'wrong'), ('source_commit', 'f'*40),
    ('release_candidate_sha256', 'f'*64),
])
def test_denies_modified_artifact(key, value):
    data = _kwargs(); data['artifact'][key] = value
    with pytest.raises(DatabasePilot1246Denied):
        require_database_pilot_1246(**data)


@pytest.mark.parametrize('flag', ['cutover_enabled', 'fleet_open', 'fresh_install_open'])
def test_denies_open_db_cutover_or_fleet(flag):
    data = _kwargs(); data['policy'][flag] = True
    with pytest.raises(DatabasePilot1246Denied):
        require_database_pilot_1246(**data)


def test_denies_unreviewed_policy_sha_or_catalog():
    data = _kwargs(); data['policy']['stable_bundle_sha256'] = 'f' * 64
    with pytest.raises(DatabasePilot1246Denied): require_database_pilot_1246(**data)
    data = _kwargs(); data['catalog']['latest_stable'] = '1.3.45'
    with pytest.raises(ValueError): require_database_pilot_1246(**data)


@pytest.mark.parametrize('flag', [PILOT_FLAG, PILOT_ARM_FLAG, *CONFLICTING_FLAGS])
def test_denies_old_environment_authority(monkeypatch, flag):
    monkeypatch.setenv(flag, 'armed')
    with pytest.raises(DatabasePilot1246Denied):
        require_database_pilot_1246(**_kwargs())


def test_missing_maintenance_hold_denied(monkeypatch):
    monkeypatch.delenv('CLIENTFLOW_FRESH_INSTALL_SUSPENDED')
    with pytest.raises(DatabasePilot1246Denied): require_database_pilot_1246(**_kwargs())
