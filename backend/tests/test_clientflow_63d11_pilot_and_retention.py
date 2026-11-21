"""63D-11: exact 1247 approval, fail-closed staged catalog, DB pilot and safe retention."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import shutil
import pytest

from service1.clientflow_pilot_1247 import (
    APPROVED_BUNDLE_SHA256, APPROVED_BUNDLE_SIZE, APPROVAL_REFERENCE,
    CANDIDATE_SHA256, SOURCE_COMMIT, PILOT_RELEASE_ID,
    ClientFlowPilot1247Denied, approval_lock_1247,
)
from service1.clientflow_release_pilot_stage_1247 import (
    PilotStage1247Denied, load_staged_catalog_1247, validated_catalog_mode_1247,
)
from service1.clientflow_pilot_1247_db_authorization import (
    DatabasePilot1247Denied, require_database_pilot_1247,
)

ROOT = Path(__file__).resolve().parents[2]
SVC = ROOT / 'backend/service1'


def payload():
    stage = load_staged_catalog_1247()
    return {
        'client_id': 3, 'client_name': 'Viborg1',
        'current_version': '1.3.45', 'expected_current_version': '1.3.45',
        'ubuntu_version': '26.04', 'release': copy.deepcopy(stage['releases'][2]),
        'artifact': {
            'target_release_id': PILOT_RELEASE_ID,
            'bundle_sha256': APPROVED_BUNDLE_SHA256,
            'bundle_size': APPROVED_BUNDLE_SIZE,
            'release_approval_reference': APPROVAL_REFERENCE,
            'release_candidate_sha256': CANDIDATE_SHA256,
            'source_commit': SOURCE_COMMIT,
        },
        'catalog': stage, 'reason': 'Måling af Viborg1 transport og input-latency',
        'policy': {
            'revision': 5, 'stable_release_id': 'clientflow-1.3.44-seq-1245',
            'stable_bundle_sha256': '28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5',
            'cutover_enabled': False, 'fleet_open': False, 'fresh_install_open': False,
        },
        'expected_revision': 5,
    }


def test_source_approval_is_exactly_hashed_and_1247_promoted_update_only():
    approval = approval_lock_1247()
    assert approval['approval_run_id'] == 44609878344
    assert approval['approved_bundle_sha256'] == APPROVED_BUNDLE_SHA256
    assert approval['approved_bundle_size'] == 223692800
    stage = load_staged_catalog_1247()
    assert [r['release_sequence'] for r in stage['releases']] == [1245, 1246, 1247]
    assert stage['default_install_version'] == stage['latest_stable'] == '1.3.44'
    assert stage['releases'][2]['install_modes'] == ['in_place_update']
    assert stage['releases'][2]['installable'] is False
    assert stage['releases'][2]['rollback_allowed'] is False
    live = json.loads((SVC / 'clientflow_release_catalog.json').read_text())
    assert live['catalog_sequence'] == 1248
    from service1.clientflow_release_pilot_stage_1248 import (
        load_staged_catalog_1248, validated_catalog_mode_1248,
    )
    assert live == load_staged_catalog_1248()
    assert validated_catalog_mode_1248(active_catalog=live) == 'update_only_1248_pilot_catalog'
    assert validated_catalog_mode_1247(active_catalog=stage) == 'update_only_1247_pilot_catalog'
    assert live['releases'][0]['status'] == 'stable'
    assert [r['installable'] for r in live['releases']] == [True, False, False]
    assert all(r['rollback_allowed'] is False for r in live['releases'])


def test_approval_digest_tampering_refused(monkeypatch, tmp_path):
    from service1 import clientflow_pilot_1247 as pilot
    value = approval_lock_1247()
    value['approved_bundle_size'] += 1
    replacement = tmp_path / 'approval.json'
    replacement.write_text(json.dumps(value))
    monkeypatch.setattr(pilot, 'APPROVAL_LOCK_PATH', replacement)
    with pytest.raises(ClientFlowPilot1247Denied):
        pilot.approval_lock_1247()


def test_stage_content_tampering_refused(monkeypatch, tmp_path):
    from service1 import clientflow_release_pilot_stage_1247 as stage
    doc = load_staged_catalog_1247()
    doc['releases'][2]['installable'] = True
    path = tmp_path / 'stage.json'
    path.write_text(json.dumps(doc))
    monkeypatch.setattr(stage, 'STAGED_CATALOG_PATH', path)
    with pytest.raises(PilotStage1247Denied):
        stage.load_staged_catalog_1247()


def test_database_single_client_pilot_accepts_exact_source_when_gates_closed(monkeypatch):
    monkeypatch.setenv('CLIENTFLOW_FRESH_INSTALL_SUSPENDED', '1')
    from service1.clientflow_pilot_1247_db_authorization import CONFLICTING_FLAGS
    for flag in CONFLICTING_FLAGS:
        monkeypatch.delenv(flag, raising=False)
    require_database_pilot_1247(**payload())


@pytest.mark.parametrize('field,value', [
    ('client_id', 4), ('client_id', True), ('client_name', 'Other'),
    ('current_version', '1.3.44'), ('expected_current_version', '1.3.44'),
    ('ubuntu_version', '24.04'), ('expected_revision', 6),
    ('reason', 'short'),
])
def test_database_pilot_rejects_invalid_inputs(monkeypatch, field, value):
    monkeypatch.setenv('CLIENTFLOW_FRESH_INSTALL_SUSPENDED', '1')
    from service1.clientflow_pilot_1247_db_authorization import CONFLICTING_FLAGS
    for flag in CONFLICTING_FLAGS:
        monkeypatch.delenv(flag, raising=False)
    args = payload(); args[field] = value
    with pytest.raises(DatabasePilot1247Denied):
        require_database_pilot_1247(**args)


@pytest.mark.parametrize('field,value', [
    ('bundle_sha256', '0'*64), ('bundle_size', 42), ('source_commit', '0'*40),
    ('release_candidate_sha256', '0'*64),
    ('release_approval_reference', 'wrong'),
])
def test_database_pilot_rejects_mismatched_tar(monkeypatch,field,value):
    monkeypatch.setenv('CLIENTFLOW_FRESH_INSTALL_SUSPENDED', '1')
    from service1.clientflow_pilot_1247_db_authorization import CONFLICTING_FLAGS
    for flag in CONFLICTING_FLAGS: monkeypatch.delenv(flag, raising=False)
    args=payload(); args['artifact'][field]=value
    with pytest.raises(DatabasePilot1247Denied):
        require_database_pilot_1247(**args)


@pytest.mark.parametrize('field,value', [
    ('installable', True), ('update_allowed', False), ('rollback_allowed', True),
    ('min_current_version', '1.3.43'), ('max_current_version', '1.3.46'),
    ('install_modes',['fresh_install']), ('release_sequence', 1246),
])
def test_database_pilot_rejects_target_drift(monkeypatch,field,value):
    monkeypatch.setenv('CLIENTFLOW_FRESH_INSTALL_SUSPENDED', '1')
    from service1.clientflow_pilot_1247_db_authorization import CONFLICTING_FLAGS
    for flag in CONFLICTING_FLAGS: monkeypatch.delenv(flag, raising=False)
    args=payload(); args['release'][field]=value
    with pytest.raises(DatabasePilot1247Denied):
        require_database_pilot_1247(**args)


def test_database_pilot_rejects_active_legacy_flags(monkeypatch):
    monkeypatch.setenv('CLIENTFLOW_FRESH_INSTALL_SUSPENDED', '1')
    from service1.clientflow_pilot_1247_db_authorization import CONFLICTING_FLAGS
    for flag in CONFLICTING_FLAGS:
        monkeypatch.setenv(flag, '1')
        with pytest.raises(DatabasePilot1247Denied):
            require_database_pilot_1247(**payload())
        monkeypatch.delenv(flag)


def test_database_pilot_rejects_fresh_install_open_and_fleet_open(monkeypatch):
    monkeypatch.setenv('CLIENTFLOW_FRESH_INSTALL_SUSPENDED', '1')
    for flag in ('cutover_enabled','fleet_open','fresh_install_open'):
        args=payload();args['policy'][flag]=True
        with pytest.raises(DatabasePilot1247Denied):
            require_database_pilot_1247(**args)
    monkeypatch.delenv('CLIENTFLOW_FRESH_INSTALL_SUSPENDED')
    with pytest.raises(DatabasePilot1247Denied):
        require_database_pilot_1247(**payload())


def test_database_pilot_rejects_non_active_catalog(monkeypatch):
    monkeypatch.setenv('CLIENTFLOW_FRESH_INSTALL_SUSPENDED', '1')
    args=payload(); args['catalog']=json.loads((SVC/'clientflow_release_catalog_1246_pilot.stage.json').read_text())
    with pytest.raises(PilotStage1247Denied):
        require_database_pilot_1247(**args)


def test_historical_1244_retention_gate_not_applied_to_normal_three(monkeypatch,tmp_path):
    from scripts import prune_clientflow_release_retention as retention
    monkeypatch.setenv('CLIENTFLOW_FRESH_INSTALL_SUSPENDED', '1')
    for f in ('CLIENTFLOW_1241_PILOT_CLIENT_ID','CLIENTFLOW_1242_PILOT_CLIENT_ID','CLIENTFLOW_1243_PILOT_CLIENT_ID'):
        monkeypatch.delenv(f,raising=False)
    releases=[
        {'release_id':f'clientflow-1.3.{n-1201}-seq-{n}', 'release_sequence':n, 'sha256':str(n)*16}
        for n in (1246,1245,1244)
    ]
    # Real canonical IDs matter for the historical 1244 path.
    releases[0]['release_id']='clientflow-1.3.45-seq-1246'
    releases[1]['release_id']='clientflow-1.3.44-seq-1245'
    releases[2]['release_id']='clientflow-1.3.43-seq-1244'
    monkeypatch.setattr(retention,'inspect_store',lambda path: {
        'approved_count':3,'protected_latest':releases,'older_review_only':[],
        'retention_target':3,'automatic_deletion_enabled':False,'rollback_enabled':False,
    })
    plan=retention.plan_cleanup(tmp_path)
    assert plan['prune_candidate']['release_id']=='clientflow-1.3.43-seq-1244'
    assert plan['catalog_pin_blocks_cleanup'] is False
    assert plan['deleted'] is False
    assert plan['dependency_review_required'] is True
    assert plan['approved_count_after']==2


def test_four_release_1244_historical_reset_still_fails_closed(monkeypatch,tmp_path):
    from scripts import prune_clientflow_release_retention as retention
    monkeypatch.setenv('CLIENTFLOW_FRESH_INSTALL_SUSPENDED','1')
    monkeypatch.setattr(retention,'inspect_store', lambda _: {
        'approved_count':4, 'protected_latest':[
            {'release_id':'clientflow-1.3.45-seq-1246'},
            {'release_id':'clientflow-1.3.44-seq-1245'},
            {'release_id':'clientflow-1.3.43-seq-1244'},
        ],'older_review_only':[{'release_id':'clientflow-1.3.42-seq-1243'}],
        'retention_target':3,'automatic_deletion_enabled':False,'rollback_enabled':False,
    })
    with pytest.raises(Exception):
        retention.plan_cleanup(tmp_path)


def test_source_wiring_is_reauth_and_database_only():
    route = (SVC/'routers/clientflow_release_pilot_63d11.py').read_text()
    assert '_reauth(request, session, user, body.password)' in route
    assert 'lock_system_client(session, 3)' in route
    assert 'control = _bound_control(session, lock=True)' in route
    assert 'create_authorized_deployment(' in route
    assert route.index('deployment_release_snapshot(release)') < route.index('require_database_pilot_1247(')
    assert route.index('require_database_pilot_1247(') < route.index('create_authorized_deployment(')
    assert 'confirmed_single_pilot is not True' in route
    assert 'version != "1.3.45"' in route
    assert "prior is not None" in route
    assert 'release-pilot-1247' in route
    assert 'clientflow_release_pilot_63d11.router' in (SVC/'main.py').read_text()


def test_duplicate_1247_build_rejected_for_new_main(tmp_path):
    from scripts.clientflow_63d11_prevent_duplicate_build import verify
    # The current unsigned source is 1248. Prove the 1247 anti-rebuild gate
    # against a pinned historical identity, not against today's VERSION.
    fixture = tmp_path / 'approved-1247'
    (fixture / 'client/release').mkdir(parents=True)
    (fixture / 'backend/service1').mkdir(parents=True)
    (fixture / 'client/VERSION').write_text('1.3.46\n')
    (fixture / 'client/release/release-input.json').write_text("""{\"schema_version\":1,\"release_sequence\":1247}""")
    shutil.copy2(ROOT / 'backend/service1/clientflow_pilot_1247_approval.json',
                 fixture / 'backend/service1/clientflow_pilot_1247_approval.json')
    with pytest.raises(ValueError, match='already approved'):
        verify('f' * 40, root=fixture)
    verify(SOURCE_COMMIT, root=fixture)  # exact historical signed source
    # The newly signed 1248 source is equally immutable.
    with pytest.raises(ValueError, match='1248 is already approved'):
        verify('f' * 40)
    verify('c0d5a092efe0c4e8638866ad98621481d6f5d0e8')
    workflow = (ROOT / '.github/workflows/release-build.yml').read_text()
    assert 'clientflow_63d11_prevent_duplicate_build.py' in workflow
    assert '--expected-source-sha "$EXPECTED_SOURCE_SHA"' in workflow
