"""63D-3 staged human governance: SQLite state and audit regression suite.

All tests use disposable local tables, synthetic signatures and synthetic humans.
The production admin and deployment routers never import these mutators.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
pytest.importorskip('sqlmodel')
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from service1 import clientflow_release_governance as govern
from service1.client_domain_models import ClientDomainCredential, ClientDomainStatus
from service1.clientflow_release_admin_models import (
    ClientFlowReleaseControl, ClientFlowRolloutWave,
    ClientFlowRolloutTarget, ClientFlowPhysicalAcceptance,
)
from service1.clientflow_update_models import ClientFlowDeployment
from service1.models import User, Client, AuditLog

NOW = datetime(2026, 11, 18, 11, 0)
RID = 'clientflow-1.3.45-seq-1246'
SHA = 'a'*64
WAVE = '9b16a936-0c82-4996-a6eb-a7076a3de6a3'


def _evidence():
    return {
        'physical_pilot_verified': True, 'recovery_verified': True,
        'pilot_client_id': 3, 'release_id': RID, 'bundle_sha256': SHA,
        'tested_by_user_id': 1, 'observed_version': '1.3.45',
        'pilot_reference': 'pilot-viborg1-20261118',
        'recovery_reference': 'recovery-viborg1-20261118',
    }


@pytest.fixture
def context(monkeypatch):
    monkeypatch.setattr(govern, 'resolve_release', lambda v: {
        'release_id': RID, 'version': '1.3.45', 'release_sequence': 1246,
        'status': 'stable', 'installable': True, 'update_allowed': True, 'rollback_allowed': False,
    })
    monkeypatch.setattr(govern, 'deployment_release_snapshot', lambda r: {
        'target_release_id': RID, 'bundle_sha256': SHA,
        'release_approval_reference': 'ci-synthetic-signed-snapshot',
    })
    engine = create_engine('sqlite://', poolclass=StaticPool,
                           connect_args={'check_same_thread': False})
    SQLModel.metadata.create_all(engine, tables=[
        User.__table__, Client.__table__, AuditLog.__table__,
        ClientFlowReleaseControl.__table__, ClientFlowRolloutWave.__table__,
        ClientFlowRolloutTarget.__table__, ClientFlowPhysicalAcceptance.__table__,
        ClientDomainCredential.__table__, ClientDomainStatus.__table__,
        ClientFlowDeployment.__table__,
    ])
    with Session(engine) as session:
        session.add_all([Client(id=i, name=f'client-{i}', status='approved') for i in (3,4,5)])
        session.flush()
        session.add_all([
            User(id=1, username='creator', email='creator@example.invalid',
                 hashed_password='hashed', role='superadmin', is_active=True),
            User(id=2, username='reviewer', email='reviewer@example.invalid',
                 hashed_password='hashed', role='superadmin', is_active=True),
            User(id=3, username='viewer', email='viewer@example.invalid',
                 hashed_password='hashed', role='viewer', is_active=True),
        ])
        session.flush()
        session.add_all([
            ClientFlowReleaseControl(id=1, stable_release_id=RID,
                stable_bundle_sha256=SHA, cutover_enabled=False, fleet_open=False,
                fresh_install_open=False, revision=7, updated_at=NOW),
            ClientFlowRolloutWave(id=WAVE, kind='controlled', state='draft',
                release_id=RID, bundle_sha256=SHA, source_version='1.3.43',
                reason='CI future rollout plan only', created_by_user_id=1,
                approved_by_user_id=2, approved_at=NOW-timedelta(minutes=30),
                created_at=NOW-timedelta(hours=1),
                expires_at=NOW+timedelta(hours=1), revision=2),
            ClientFlowPhysicalAcceptance(id=str(uuid4()), release_id=RID,
                bundle_sha256=SHA, client_id=3, actor_user_id=2,
                decision='accepted', evidence=_evidence(),
                created_at=NOW-timedelta(minutes=35)),
        ])
        session.flush()
        session.add_all([
            ClientFlowRolloutTarget(id=str(uuid4()),wave_id=WAVE,
                client_id=i,state='draft',created_at=NOW-timedelta(hours=1),
                expires_at=NOW+timedelta(hours=1)) for i in (4,5)
        ])
        session.add(ClientDomainCredential(id='7a5a3e95-765f-46a9-9564-a32da2abec38',
            client_id=3, domain='status', secret_hash='synthetic',
            created_at=NOW-timedelta(days=1)))
        session.flush()
        session.add(ClientDomainStatus(id=str(uuid4()),client_id=3,domain='status',
            credential_id='7a5a3e95-765f-46a9-9564-a32da2abec38',
            schema_version=1,observed_state='online',agent_version='1.3.45',
            reported_at=NOW-timedelta(seconds=15)))
        session.flush()
        for i in (4,5):
            cid=str(uuid4())
            session.add(ClientDomainCredential(id=cid,client_id=i,
                domain='status',secret_hash='synthetic',created_at=NOW-timedelta(days=1)))
            session.flush()
            session.add(ClientDomainStatus(id=str(uuid4()),client_id=i,domain='status',
                credential_id=cid,schema_version=1,observed_state='online',
                agent_version='1.3.43',reported_at=NOW-timedelta(seconds=15)))
        session.commit()
        yield session
    engine.dispose()


def _approve(session, **changes):
    args=dict(wave_id=WAVE,expected_policy_revision=7,
              expected_wave_revision=2, release_id=RID,bundle_sha256=SHA,
              actor_user_id=2, now=NOW)
    args.update(changes)
    return govern.stage_approve_controlled_wave(session,**args)


def _control(session, action, revision, **changes):
    args=dict(action=action,wave_id=WAVE,expected_policy_revision=7,
              expected_wave_revision=revision,release_id=RID,bundle_sha256=SHA,
              actor_user_id=2, reason='CI human release safety control', now=NOW)
    args.update(changes)
    return govern.stage_control_wave(session,**args)


def _targets(session):
    return session.exec(select(ClientFlowRolloutTarget).order_by(
        ClientFlowRolloutTarget.client_id)).all()


def _audit(session):
    return session.exec(select(AuditLog).order_by(AuditLog.id)).all()


def test_real_approval_is_distinct_from_planning_review_and_keeps_flags_closed(context):
    _approve(context)
    assert context.get(ClientFlowRolloutWave,WAVE).state=='approved'
    assert context.get(ClientFlowRolloutWave,WAVE).revision==3
    assert [t.state for t in _targets(context)]==['approved','approved']
    assert len(_audit(context))==1
    assert _audit(context)[0].action=='clientflow_wave_staged_approved'
    assert context.get(ClientFlowReleaseControl,1).cutover_enabled is False
    assert context.get(ClientFlowReleaseControl,1).fleet_open is False
    context.commit()
    assert len(_audit(context))==1


def test_approval_and_audit_rollback_together(context):
    _approve(context)
    context.rollback()
    assert context.get(ClientFlowRolloutWave,WAVE).state=='draft'
    assert [t.state for t in _targets(context)]==['draft','draft']
    assert _audit(context)==[]


@pytest.mark.parametrize('alter', [
    lambda s: setattr(s.get(ClientFlowReleaseControl,1),'revision',8),
    lambda s: setattr(s.get(ClientFlowRolloutWave,WAVE),'revision',3),
    lambda s: setattr(s.get(ClientFlowRolloutWave,WAVE),'kind','pilot'),
    lambda s: setattr(s.get(ClientFlowRolloutWave,WAVE),'created_by_user_id',2),
    lambda s: setattr(s.get(ClientFlowRolloutWave,WAVE),'expires_at',NOW-timedelta(seconds=1)),
    lambda s: setattr(s.get(ClientFlowPhysicalAcceptance,s.exec(select(ClientFlowPhysicalAcceptance.id)).one()),'decision','rejected'),
    lambda s: setattr(s.get(Client,4),'status','inactive'),
])
def test_approval_rejects_drift_without_audit_or_deployment(context,alter):
    alter(context)
    context.flush()
    with pytest.raises(govern.GovernanceDenied):
        _approve(context)
    assert context.get(ClientFlowRolloutWave,WAVE).state=='draft'
    assert _audit(context)==[]
    assert context.exec(select(ClientFlowDeployment)).all()==[]


def test_pause_resume_stop_revoke_unconsumed_targets_and_audit(context):
    _approve(context)
    _control(context,'pause',3)
    assert context.get(ClientFlowRolloutWave,WAVE).state=='paused'
    assert [t.state for t in _targets(context)]==['approved','approved']
    _control(context,'resume',4)
    assert context.get(ClientFlowRolloutWave,WAVE).state=='approved'
    _control(context,'stop',5)
    assert context.get(ClientFlowRolloutWave,WAVE).state=='cancelled'
    assert [t.state for t in _targets(context)]==['revoked','revoked']
    assert len(_audit(context))==4
    with pytest.raises(govern.GovernanceDenied):
        _control(context,'resume',6)
    context.commit()
    assert len(_audit(context))==4


def test_live_approved_but_not_newly_published_release_cannot_be_approved(context,monkeypatch):
    monkeypatch.setattr(govern,'deployment_release_snapshot',lambda r:{
        'target_release_id': RID, 'bundle_sha256': 'b'*64,
        'release_approval_reference':'wrong-artifact',
    })
    with pytest.raises(govern.GovernanceDenied,match='signed_artifact_binding_changed'):
        _approve(context)
    assert _audit(context)==[]


def test_physical_acceptance_requires_current_status_two_actors_and_no_duplicates(context):
    existing=context.exec(select(ClientFlowPhysicalAcceptance)).one()
    context.delete(existing)
    # Pilot success is a separate immutable updater-deployment fact, not
    # operator-written status or a claim in the acceptance JSON.
    context.add(_deployment(context,3,'succeeded'))
    context.commit()
    row=govern.stage_physical_acceptance(context,
        release_id=RID,bundle_sha256=SHA,expected_policy_revision=7,
        pilot_client_id=3,tested_by_user_id=1,reviewer_user_id=2,
        observed_version='1.3.45',pilot_reference='pilot-viborg1-20261118',
        recovery_reference='recovery-viborg1-20261118',now=NOW)
    assert row.evidence['tested_by_user_id']==1
    assert len(_audit(context))==1
    with pytest.raises(govern.GovernanceDenied, match='physical_acceptance_already_recorded'):
        govern.stage_physical_acceptance(context,
            release_id=RID,bundle_sha256=SHA,expected_policy_revision=7,
            pilot_client_id=3,tested_by_user_id=1,reviewer_user_id=2,
            observed_version='1.3.45',pilot_reference='pilot-viborg1-20261118',
            recovery_reference='recovery-viborg1-20261118',now=NOW)
    context.commit()
    assert context.exec(select(ClientFlowPhysicalAcceptance)).one().id==row.id


def test_invalid_physical_acceptance_cannot_create_any_history(context):
    existing=context.exec(select(ClientFlowPhysicalAcceptance)).one()
    context.delete(existing)
    context.commit()
    with pytest.raises(govern.GovernanceDenied):
        govern.stage_physical_acceptance(context,
            release_id=RID,bundle_sha256=SHA,expected_policy_revision=7,
            pilot_client_id=3,tested_by_user_id=2,reviewer_user_id=2,
            observed_version='1.3.45',pilot_reference='pilot-viborg1-20261118',
            recovery_reference='recovery-viborg1-20261118',now=NOW)
    assert context.exec(select(ClientFlowPhysicalAcceptance)).all()==[]
    assert _audit(context)==[]


def _deployment(session, client_id, state, deployment_id=None):
    return ClientFlowDeployment(
        id=deployment_id or str(uuid4()), client_id=client_id,
        target_release_id=RID,target_version='1.3.45',target_release_sequence=1246,
        bundle_sha256=SHA,bundle_size=12345,release_approval_reference='synthetic',
        allow_downgrade=False, requested_by_user_id=2,requested_at=NOW,
        state=state,state_updated_at=NOW,
        completed_at=NOW if state in ('succeeded','failed') else None,
    )


def test_reconcile_needs_all_terminal_success_or_records_failure(context):
    _approve(context)
    targets=_targets(context)
    for i,t in enumerate(targets):
        d=_deployment(context,t.client_id,'succeeded' if i==0 else 'failed')
        context.add(d)
        t.consumed_deployment_id=d.id
        t.state='consumed'
    context.get(ClientFlowRolloutWave,WAVE).state='running'
    context.flush()
    row=govern.stage_reconcile_wave(context,wave_id=WAVE,
        expected_policy_revision=7,expected_wave_revision=3,
        release_id=RID,bundle_sha256=SHA,actor_user_id=2,now=NOW)
    assert row.state=='failed'
    assert _audit(context)[-1].action=='clientflow_wave_staged_reconciled'


def test_reconcile_can_finish_only_fully_succeeded_wave(context):
    _approve(context)
    for t in _targets(context):
        d=_deployment(context,t.client_id,'succeeded')
        context.add(d)
        t.consumed_deployment_id=d.id
        t.state='consumed'
    context.get(ClientFlowRolloutWave,WAVE).state='running'
    context.flush()
    row=govern.stage_reconcile_wave(context,wave_id=WAVE,
        expected_policy_revision=7,expected_wave_revision=3,
        release_id=RID,bundle_sha256=SHA,actor_user_id=2,now=NOW)
    assert row.state=='completed'
    assert len(_audit(context))==2
