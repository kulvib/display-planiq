"""63D-2 transactional future-cutover proof; no live deployment route is wired."""
from __future__ import annotations

from datetime import datetime, timedelta
from copy import deepcopy
from uuid import uuid4

import pytest
pytest.importorskip("sqlmodel")
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from service1.client_domain_models import ClientDomainCredential, ClientDomainStatus, ClientCommand
from service1.clientflow_release_admin_models import (
    ClientFlowReleaseControl, ClientFlowRolloutWave,
    ClientFlowRolloutTarget, ClientFlowPhysicalAcceptance,
)
from service1.clientflow_release_wave_transactions import (
    WaveTransactionDenied, locked_wave_preconditions,
    consume_locked_wave, create_staged_wave_deployment,
)
from service1.clientflow_update_models import ClientFlowDeployment, ClientFlowDeploymentEvent, ClientFlowUpdateCredential
from service1.models import Client, User

NOW = datetime(2026, 11, 18, 11, 0)
RID = 'clientflow-1.3.45-seq-1246'
SHA = 'a' * 64
RELEASE = {'release_id': RID, 'version': '1.3.45', 'release_sequence': 1246,
           'status': 'stable', 'installable': True, 'update_allowed': True,
           'rollback_allowed': False}
ARTIFACT = {'target_release_id': RID, 'bundle_sha256': SHA,
            'bundle_size': 228000000, 'release_approval_reference': 'signed-evidence-only',
            'release_candidate_sha256': 'b' * 64, 'source_commit': 'c' * 40}


@pytest.fixture
def context(monkeypatch):
    from service1 import clientflow_release_wave_transactions as engine
    monkeypatch.setattr(engine, "resolve_release", lambda version: dict(RELEASE))
    monkeypatch.setattr(engine, "deployment_release_snapshot", lambda release: dict(ARTIFACT))
    monkeypatch.setattr(engine, "_system_now", lambda: NOW)
    engine = create_engine('sqlite://', poolclass=StaticPool,
                           connect_args={'check_same_thread': False})
    SQLModel.metadata.create_all(engine, tables=[
        User.__table__, Client.__table__,
        ClientFlowReleaseControl.__table__, ClientFlowRolloutWave.__table__,
        ClientFlowRolloutTarget.__table__, ClientFlowPhysicalAcceptance.__table__,
        ClientDomainCredential.__table__, ClientDomainStatus.__table__,
        ClientFlowDeployment.__table__, ClientFlowDeploymentEvent.__table__,
        ClientFlowUpdateCredential.__table__, ClientCommand.__table__,
    ])
    with Session(engine) as session:
        session.add(Client(id=3, name='Viborg1', status='approved'))
        session.flush()
        session.add_all([
            User(id=1, username='admin-staged', email='admin-staged@example.invalid',
                 hashed_password='hashed', role='superadmin', is_active=True),
            User(id=2, username='reviewer-staged', email='reviewer-staged@example.invalid',
                 hashed_password='hashed', role='superadmin', is_active=True),
        ])
        session.flush()
        session.add_all([
            ClientFlowReleaseControl(id=1, stable_release_id=RID,
                   stable_bundle_sha256=SHA, cutover_enabled=True, fleet_open=True,
                   fresh_install_open=False, revision=7, updated_at=NOW),
            ClientFlowRolloutWave(id='e7547fa0-ce54-462f-b7a4-c469a8de6d80',
                kind='controlled', state='approved', release_id=RID,
                bundle_sha256=SHA, source_version='1.3.43', reason='test wave',
                created_by_user_id=1, approved_by_user_id=2,
                created_at=NOW-timedelta(hours=1), expires_at=NOW+timedelta(hours=1),
                approved_at=NOW-timedelta(minutes=40), revision=4),
            ClientFlowPhysicalAcceptance(id='924092c8-55e0-41cb-9936-09bbd7a8b57b',
                release_id=RID, bundle_sha256=SHA, client_id=3,
                actor_user_id=2, decision='accepted',
                evidence={'physical_pilot_verified': True, 'recovery_verified': True},
                created_at=NOW-timedelta(minutes=30)),
        ])
        session.flush()
        session.add_all([
            ClientFlowRolloutTarget(id='6c955d19-484e-42af-b0a1-9e73a41f0c65',
                wave_id='e7547fa0-ce54-462f-b7a4-c469a8de6d80',
                client_id=3, state='approved', created_at=NOW-timedelta(hours=1),
                expires_at=NOW+timedelta(hours=1)),
            ClientDomainCredential(id='f6fa28c5-c1d3-423f-9be1-e19328b35c50',
                client_id=3, domain='status', secret_hash='not-a-real-secret',
                created_at=NOW-timedelta(days=1)),
        ])
        session.flush()
        session.add(ClientDomainStatus(
            id='4a080dc2-5022-42b0-95de-c08f34c21455', client_id=3, domain='status',
            credential_id='f6fa28c5-c1d3-423f-9be1-e19328b35c50',
            schema_version=1, observed_state='online', agent_version='1.3.43',
            reported_at=NOW-timedelta(seconds=15),
        ))
        session.commit()
        yield session
    engine.dispose()


def payload(**changes):
    d = {'client_id': 3, 'current_version':'1.3.43',
         'release': deepcopy(RELEASE), 'artifact': deepcopy(ARTIFACT),
         'expected_policy_revision':7, 'expected_wave_revision':4, 'now':NOW}
    d.update(changes)
    return d


def wave(context):
    return context.get(ClientFlowRolloutWave, 'e7547fa0-ce54-462f-b7a4-c469a8de6d80')


def target(context):
    return context.get(ClientFlowRolloutTarget, '6c955d19-484e-42af-b0a1-9e73a41f0c65')


def physical(context):
    return context.get(ClientFlowPhysicalAcceptance, '924092c8-55e0-41cb-9936-09bbd7a8b57b')


def test_staged_transaction_consumes_target_together_with_immutable_deployment(context):
    legacy_checks = []
    dep = create_staged_wave_deployment(
        context, **payload(), requested_by_user_id=1,
        reason='explicit planned update', legacy_guard=lambda: legacy_checks.append('checked'),
    )
    assert legacy_checks == ['checked']
    assert dep.target_release_id == RID and dep.bundle_sha256 == SHA
    assert dep.release_candidate_sha256 == ARTIFACT['release_candidate_sha256']
    assert target(context).state == 'consumed'
    assert target(context).consumed_deployment_id == dep.id
    assert wave(context).state == 'running' and wave(context).revision == 5
    context.commit()
    assert context.exec(select(ClientFlowDeployment)).one().id == dep.id
    assert context.exec(select(ClientFlowDeploymentEvent)).one().deployment_id == dep.id


def test_staged_transaction_can_rollback_both_deployment_and_consumption(context):
    dep = create_staged_wave_deployment(context, **payload(), requested_by_user_id=1,
         reason='explicit planned update', legacy_guard=lambda: None)
    assert context.get(ClientFlowDeployment, dep.id) is not None
    context.rollback()
    assert context.get(ClientFlowDeployment, dep.id) is None
    assert context.exec(select(ClientFlowDeploymentEvent)).all() == []
    assert target(context).state == 'approved'
    assert target(context).consumed_deployment_id is None
    assert wave(context).state == 'approved' and wave(context).revision == 4


def test_reused_or_consumed_grant_cannot_issue_second_deployment(context):
    first = create_staged_wave_deployment(context, **payload(), requested_by_user_id=1,
                reason='explicit planned update', legacy_guard=lambda: None)
    context.commit()
    with pytest.raises(WaveTransactionDenied, match='no_unique_approved_target'):
        create_staged_wave_deployment(context, **payload(), requested_by_user_id=1,
            reason='explicit planned update', legacy_guard=lambda: None)
    assert context.exec(select(ClientFlowDeployment)).one().id == first.id


@pytest.mark.parametrize('mutate', [
    lambda s: setattr(s.get(ClientFlowReleaseControl, 1), 'cutover_enabled', False),
    lambda s: setattr(s.get(ClientFlowReleaseControl, 1), 'fleet_open', False),
    lambda s: setattr(s.get(ClientFlowReleaseControl, 1), 'revision', 8),
    lambda s: setattr(wave(s), 'revision', 5),
    lambda s: setattr(wave(s), 'state', 'paused'),
    lambda s: setattr(wave(s), 'expires_at', NOW-timedelta(seconds=1)),
    lambda s: setattr(wave(s), 'approved_by_user_id', None),
    lambda s: setattr(target(s), 'expires_at', NOW-timedelta(seconds=1)),
    lambda s: setattr(target(s), 'state', 'revoked'),
    lambda s: setattr(physical(s), 'decision', 'rejected'),
    lambda s: setattr(physical(s), 'actor_user_id', 0),
    lambda s: setattr(physical(s), 'bundle_sha256', 'f'*64),
    lambda s: setattr(physical(s), 'evidence', {'physical_pilot_verified': True}),
    lambda s: setattr(s.get(Client,3), 'status','inactive'),
    lambda s: setattr(s.exec(select(ClientDomainStatus)).one(),'agent_version','1.3.42'),
    lambda s: setattr(s.exec(select(ClientDomainStatus)).one(),'observed_state','offline'),
    lambda s: setattr(s.exec(select(ClientDomainStatus)).one(),'reported_at',NOW-timedelta(seconds=91)),
    lambda s: setattr(s.exec(select(ClientDomainCredential)).one(),'revoked_at',NOW),
])
def test_authorization_denied_before_creating_deployment(context,mutate):
    mutate(context)
    context.flush()
    with pytest.raises(WaveTransactionDenied):
        create_staged_wave_deployment(context, **payload(), requested_by_user_id=1,
           reason='explicit planned update', legacy_guard=lambda: None)
    assert context.exec(select(ClientFlowDeployment)).all() == []


@pytest.mark.parametrize('field,value', [
    ('expected_policy_revision',8), ('expected_wave_revision',8),
    ('client_id',4), ('current_version','1.3.42'),
    ('now',NOW+timedelta(hours=2)),
    ('release',dict(RELEASE, status='candidate')),
    ('release',dict(RELEASE, version='1.3.43')),
    ('artifact',dict(ARTIFACT, bundle_sha256='b'*64)),
    ('artifact',dict(ARTIFACT, release_candidate_sha256='wrong')),
])
def test_changed_input_denied(context,field,value):
    with pytest.raises(WaveTransactionDenied):
        locked_wave_preconditions(context, **payload(**{field:value}))
    assert context.exec(select(ClientFlowDeployment)).all()==[]


def test_existing_guard_must_pass_under_lock_before_deployment(context):
    def denied():
        raise WaveTransactionDenied('old_gate_denied')
    with pytest.raises(WaveTransactionDenied, match='old_gate_denied'):
        create_staged_wave_deployment(context, **payload(), requested_by_user_id=1,
            reason='explicit planned update', legacy_guard=denied)
    assert context.exec(select(ClientFlowDeployment)).all() == []
    with pytest.raises(WaveTransactionDenied, match='missing_existing_approval_or_actor'):
        create_staged_wave_deployment(context, **payload(), requested_by_user_id=1,
            reason='explicit planned update', legacy_guard=None)


def test_ambiguous_physical_acceptance_never_grants(context):
    context.add(ClientFlowPhysicalAcceptance(id=str(uuid4()),
        release_id=RID, bundle_sha256=SHA, client_id=3, actor_user_id=2,
        decision='accepted', evidence={'physical_pilot_verified': True, 'recovery_verified': True},
        created_at=NOW-timedelta(minutes=1)))
    context.flush()
    with pytest.raises(WaveTransactionDenied, match='ambiguous_physical_acceptance'):
        locked_wave_preconditions(context, **payload())


def test_draft_never_authorizes_even_if_reviewed(context):
    wave(context).state='draft'
    target(context).state='draft'
    context.flush()
    with pytest.raises(WaveTransactionDenied):
        locked_wave_preconditions(context, **payload())
    assert context.exec(select(ClientFlowDeployment)).all() == []


def test_verified_snapshot_required_even_when_grant_looks_valid(context, monkeypatch):
    from service1 import clientflow_release_wave_transactions as engine
    monkeypatch.setattr(engine, 'deployment_release_snapshot', lambda release: dict(ARTIFACT, bundle_size=10))
    with pytest.raises(WaveTransactionDenied, match='published_artifact_changed'):
        create_staged_wave_deployment(context, **payload(), requested_by_user_id=1,
            reason='explicit planned update', legacy_guard=lambda: None)
    assert context.exec(select(ClientFlowDeployment)).all() == []


def test_wave_expiring_during_legacy_guard_cannot_be_consumed(context, monkeypatch):
    from service1 import clientflow_release_wave_transactions as engine
    def slow_guard():
        monkeypatch.setattr(engine, '_system_now', lambda: NOW+timedelta(hours=2))
    with pytest.raises(WaveTransactionDenied, match='deployment_consumption_binding_mismatch'):
        create_staged_wave_deployment(context, **payload(), requested_by_user_id=1,
            reason='explicit planned update', legacy_guard=slow_guard)
    context.rollback()
    assert context.exec(select(ClientFlowDeployment)).all() == []
    assert target(context).state == 'approved'


def test_concurrent_system_operation_denies_wave_before_deployment(context, monkeypatch):
    from service1 import clientflow_release_wave_transactions as engine
    monkeypatch.setattr(engine, 'active_system_command', lambda session, client_id: object())
    with pytest.raises(WaveTransactionDenied, match='system_command_active'):
        locked_wave_preconditions(context, **payload())
    assert context.exec(select(ClientFlowDeployment)).all() == []


def test_no_http_route_or_prod_cutover_is_wired_to_staging_engine():
    from pathlib import Path
    root=Path(__file__).resolve().parents[2]
    route=(root/'backend/service1/routers/clientflow_deployments.py').read_text()
    admin=(root/'backend/service1/routers/clientflow_release_administration.py').read_text()
    assert 'clientflow_release_wave_transactions' not in route
    assert 'clientflow_release_wave_transactions' not in admin
    assert 'create_staged_wave_deployment' not in route
    assert 'cutover_enabled is not False' in admin
