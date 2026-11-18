"""Fase 63D-4: signed GitHub-approved 1246 pilot, never automatic deployment."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from service1 import clientflow_pilot_1246 as pilot
from service1 import clientflow_release_pilot_stage_1246 as stage

ROOT = Path(__file__).resolve().parents[2]


def _stage_release():
    return deepcopy(json.loads(stage.STAGED_CATALOG_PATH.read_text())['releases'][1])


def _args(**overrides):
    return dict({
        'client_id': 3, 'current_version': '1.3.43', 'release': _stage_release(),
        'reason': 'Kun kontrollen Viborg1-pilot efter separate gates',
        'pre_first_activation_repair': False, 'confirm_downgrade': False,
    }, **overrides)


@pytest.fixture
def flags(monkeypatch):
    monkeypatch.setenv(pilot.PILOT_FLAG, '3')
    monkeypatch.setenv(pilot.PILOT_ARM_FLAG, pilot.APPROVAL_REFERENCE)
    for name in pilot.CONFLICTING_FLAGS:
        monkeypatch.delenv(name, raising=False)


def _artifact():
    return {
        'target_release_id': pilot.PILOT_RELEASE_ID,
        'bundle_sha256': pilot.APPROVED_BUNDLE_SHA256,
        'bundle_size': pilot.APPROVED_BUNDLE_SIZE,
        'release_approval_reference': pilot.APPROVAL_REFERENCE,
        'release_candidate_sha256': pilot.CANDIDATE_SHA256,
        'source_commit': pilot.SOURCE_COMMIT,
    }


def test_approved_source_record_is_exact_not_deployment():
    locked = pilot.approval_lock()
    assert locked['approved_bundle_sha256'] == 'e37de3250d58d313d57ad7bcbf59682cee342f2727c6ad5b188c8782342d4c78'
    assert locked['approved_bundle_size'] == 223682560
    assert locked['source_commit'] == pilot.SOURCE_COMMIT
    assert locked['approval_reference'] == pilot.APPROVAL_REFERENCE
    assert '1245' in json.dumps(json.loads((ROOT/'backend/service1/clientflow_release_catalog.json').read_text()))
    assert [x['release_sequence'] for x in json.loads((ROOT/'backend/service1/clientflow_release_catalog.json').read_text())['releases']] == [1245, 1246]


@pytest.mark.parametrize('name', [pilot.PILOT_FLAG, pilot.PILOT_ARM_FLAG])
def test_missing_pilot_operator_flag_denied(flags, monkeypatch, name):
    monkeypatch.delenv(name)
    with pytest.raises(pilot.ClientFlowPilot1246Denied):
        pilot.require_pilot_1246(**_args())


@pytest.mark.parametrize('value', ['3 ', '03', '2', '4', 'true', '*', '', '1,3'])
def test_exact_client_flag(flags, monkeypatch, value):
    monkeypatch.setenv(pilot.PILOT_FLAG, value)
    with pytest.raises(pilot.ClientFlowPilot1246Denied):
        pilot.require_pilot_1246(**_args())


@pytest.mark.parametrize('value', ['', '1', 'true', '*', 'CF-1.3.44-1245-20261114-0685710-ffe58332-R2'])
def test_exact_operator_arm(flags, monkeypatch, value):
    monkeypatch.setenv(pilot.PILOT_ARM_FLAG, value)
    with pytest.raises(pilot.ClientFlowPilot1246Denied):
        pilot.require_pilot_1246(**_args())


@pytest.mark.parametrize('name', pilot.CONFLICTING_FLAGS)
def test_conflicting_old_pilot_or_fleet_denied(flags, monkeypatch, name):
    monkeypatch.setenv(name, '1')
    with pytest.raises(pilot.ClientFlowPilot1246Denied):
        pilot.require_pilot_1246(**_args())


@pytest.mark.parametrize('client_id', [True, '3', None, 0, 1, 2, 4, 100, 1001])
def test_no_other_client_even_with_operator_flags(flags, client_id):
    with pytest.raises(pilot.ClientFlowPilot1246Denied):
        pilot.require_pilot_1246(**_args(client_id=client_id))


@pytest.mark.parametrize('version', ['1.3.42','1.3.45','v1.3.43',None,'',True])
def test_no_unknown_source_version(flags, version):
    with pytest.raises(pilot.ClientFlowPilot1246Denied):
        pilot.require_pilot_1246(**_args(current_version=version))


@pytest.mark.parametrize('version', ['1.3.43','1.3.44'])
def test_exact_source_versions_possible_only_under_explicit_pilot(flags, version):
    pilot.require_pilot_1246(**_args(current_version=version))
    pilot.require_pilot_1246(**_args(current_version=version, artifact=_artifact()))


@pytest.mark.parametrize('field,value', [
    ('version','1.3.44'), ('client_version','1.3.44'),
    ('release_sequence',1245), ('release_sequence','1246'),
    ('release_id','clientflow-1.3.44-seq-1245'), ('revision','old'),
    ('status','stable'), ('status','deprecated'), ('installable',True),
    ('update_allowed',False), ('rollback_allowed',True), ('requires_reboot',False),
    ('requires_explicit_downgrade',True), ('install_modes',['fresh_install','in_place_update']),
    ('min_current_version','1.3.42'), ('max_current_version','1.3.45'),
    ('artifact_type','other'),
])
def test_catalog_drift_denied(flags, field, value):
    rel=_stage_release();rel[field]=value
    with pytest.raises(pilot.ClientFlowPilot1246Denied):
        pilot.require_pilot_1246(**_args(release=rel))


@pytest.mark.parametrize('key', list(_artifact()))
def test_signed_store_artifact_tampering_denied(flags, key):
    asset=_artifact();asset[key]='0'*64 if 'sha256' in key else 0
    with pytest.raises(pilot.ClientFlowPilot1246Denied):
        pilot.require_pilot_1246(**_args(artifact=asset))


@pytest.mark.parametrize('overrides', [
    {'pre_first_activation_repair':True}, {'confirm_downgrade':True},
    {'reason':None}, {'reason':'kort'}, {'reason':''},
])
def test_no_repair_rollback_or_empty_reason(flags, overrides):
    with pytest.raises(pilot.ClientFlowPilot1246Denied):
        pilot.require_pilot_1246(**_args(**overrides))


@pytest.mark.parametrize('field,value', [
    ('approved',False), ('approved','true'), ('approved_bundle_sha256','0'*64),
    ('approved_bundle_size',1), ('approved_bundle_size',True),
    ('source_commit','0'*40), ('installer_sha256','0'*64),
    ('candidate_sha256','0'*64), ('approval_reference','wrong'),
    ('release_id','clientflow-1.3.44-seq-1245'), ('schema_version',True),
])
def test_lock_modified_denied(flags, monkeypatch, tmp_path, field, value):
    lock=pilot.approval_lock();lock[field]=value
    path=tmp_path/'approval.json';path.write_text(json.dumps(lock))
    monkeypatch.setattr(pilot,'APPROVAL_LOCK_PATH',path)
    with pytest.raises(pilot.ClientFlowPilot1246Denied):
        pilot.require_pilot_1246(**_args())


def test_lock_missing_or_symlink_denied(flags, monkeypatch, tmp_path):
    path=tmp_path/'missing.json';monkeypatch.setattr(pilot,'APPROVAL_LOCK_PATH',path)
    with pytest.raises(pilot.ClientFlowPilot1246Denied):
        pilot.require_pilot_1246(**_args())
    path.symlink_to(ROOT/'backend/service1/clientflow_pilot_1246_approval.json')
    with pytest.raises(pilot.ClientFlowPilot1246Denied):
        pilot.require_pilot_1246(**_args())


@pytest.mark.parametrize('field,value', [
    ('catalog_sequence',1245), ('catalog_sequence',True),
    ('latest_stable','1.3.45'), ('default_install_version','1.3.45'),
    ('releases',[]), ('releases',None),
    ('retention_policy',{'max_selectable_versions':10}),
])
def test_staged_catalog_drift_denied(monkeypatch,tmp_path,field,value):
    content=stage.load_staged_catalog();content[field]=value
    p=tmp_path/'stage.json';p.write_text(json.dumps(content));monkeypatch.setattr(stage,'STAGED_CATALOG_PATH',p)
    with pytest.raises(stage.PilotStageDenied):
        stage.load_staged_catalog()


def test_stage_catalog_mismatched_release_denied(monkeypatch,tmp_path):
    content=stage.load_staged_catalog();content['releases'][1]['release_id']='clientflow-1.3.46-seq-1247'
    p=tmp_path/'stage.json';p.write_text(json.dumps(content));monkeypatch.setattr(stage,'STAGED_CATALOG_PATH',p)
    with pytest.raises(stage.PilotStageDenied):
        stage.load_staged_catalog()


def test_admin_stage_never_proves_render_or_pilot():
    active=json.loads((ROOT/'backend/service1/clientflow_release_catalog.json').read_text())
    info=stage.staged_pilot_summary(active_catalog=active)
    assert info['github_artifact_approval_pinned'] is True
    assert info['active_catalog_promoted'] is True
    for field in ('render_store_publication_verified','physical_pilot_accepted','deployment_authorized','fleet_authorized','fresh_install_authorized','database_cutover_authorized'):
        assert info[field] is False
    mutated=deepcopy(active);mutated['latest_stable']='1.3.45'
    with pytest.raises(stage.PilotStageDenied):
        stage.staged_pilot_summary(active_catalog=mutated)


def test_router_exclusively_checks_1246_before_fleet_fallback_and_after_lock():
    source=(ROOT/'backend/service1/routers/clientflow_deployments.py').read_text()
    selector=source.split('def _require_exact_scoped_pilot(',1)[1].split('class ClientFlowDeploymentCreate',1)[0]
    assert selector.index('require_pilot_1246(')<selector.index('require_stable_rollout(')
    create=source.split('def create_clientflow_deployment(',1)[1].split('@router.get(',1)[0]
    assert create.count('_require_exact_scoped_pilot(')==2
    assert create.index('lock_system_client(')<create.rindex('_require_exact_scoped_pilot(')<create.index('create_authorized_deployment(')


def test_all_main_authority_files_are_unchanged_from_baseline_manifest():
    source=(ROOT/'backend/service1/clientflow_release_catalog.json').read_text()
    assert 'clientflow-1.3.45-seq-1246' in source
    assert 'clientflow-1.3.44-seq-1245' in source
    control=(ROOT/'backend/service1/routers/clientflow_release_administration.py').read_text()
    assert '_BUNDLE_SHA256 = "28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5"' in control
    assert 'row.cutover_enabled is not False' in control
    assert 'row.fleet_open is not False' in control
    assert 'row.fresh_install_open is not False' in control


def test_staged_1246_catalog_passes_existing_canonical_validator_and_both_source_versions(monkeypatch):
    from service1 import clientflow_releases as releases
    path = stage.STAGED_CATALOG_PATH
    with monkeypatch.context() as local:
        local.setattr(releases, 'CATALOG_PATH', path)
        releases.load_catalog.cache_clear()
        try:
            catalog = releases.load_catalog()
            assert catalog['latest_stable'] == catalog['default_install_version'] == '1.3.44'
            assert releases.resolve_fresh_install_release()['release_id'] == 'clientflow-1.3.44-seq-1245'
            entry = releases.resolve_release('1.3.45')
            assert entry['installable'] is False and entry['install_modes'] == ['in_place_update']
            for version in ('1.3.43','1.3.44'):
                releases.validate_release_compatibility(entry, current_version=version, ubuntu_version='26.04')
        finally:
            releases.load_catalog.cache_clear()


@pytest.mark.parametrize('field,value', [
    ('status','stable'),('installable',True),
    ('install_modes',['fresh_install','in_place_update']),
    ('max_current_version','1.3.45'),('min_current_version','1.3.42'),
])
def test_stage_never_allows_1246_as_fresh_install_or_wrong_source(monkeypatch,tmp_path,field,value):
    from service1 import clientflow_releases as releases
    content=stage.load_staged_catalog()
    content['releases'][1][field]=value
    path=tmp_path/'catalog.json'
    path.write_text(json.dumps(content))
    with monkeypatch.context() as local:
        local.setattr(releases,'CATALOG_PATH',path)
        releases.load_catalog.cache_clear()
        try:
            with pytest.raises(releases.ClientFlowCatalogError):
                releases.load_catalog()
        finally:
            releases.load_catalog.cache_clear()


def test_staged_catalog_never_changes_existing_1245_stable_record(monkeypatch,tmp_path):
    content=stage.load_staged_catalog()
    content['releases'][0]['notes']=['Unreviewed change']
    path=tmp_path/'catalog.json';path.write_text(json.dumps(content))
    monkeypatch.setattr(stage,'STAGED_CATALOG_PATH',path)
    active=json.loads((ROOT/'backend/service1/clientflow_release_catalog.json').read_text())
    with pytest.raises(stage.PilotStageDenied):
        stage.staged_pilot_summary(active_catalog=active)
