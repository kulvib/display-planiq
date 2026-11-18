"""63D-2: real PostgreSQL row locks and atomic wave target consumption.

Only GitHub Actions' disposable local planiq_ci database is allowed. Never
connect to Neon, Render, or a named production database from this test.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import os
from threading import Barrier
from uuid import uuid4

import pytest
pytest.importorskip('sqlmodel')
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlmodel import SQLModel, Session, create_engine, select

from service1 import clientflow_release_wave_transactions as staged
from service1.client_domain_models import ClientCommand, ClientDomainCredential, ClientDomainStatus
from service1.clientflow_release_admin_models import (
    ClientFlowReleaseControl, ClientFlowRolloutWave, ClientFlowRolloutTarget,
    ClientFlowPhysicalAcceptance,
)
from service1.clientflow_update_models import (
    ClientFlowDeployment, ClientFlowDeploymentEvent, ClientFlowUpdateCredential,
)
from service1.models import Client, User

RID = 'clientflow-1.3.45-seq-1246'
SHA = 'a'*64
NOW = datetime(2026,11,18,11,0)
RELEASE = {'release_id':RID, 'version':'1.3.45', 'release_sequence':1246,
           'status':'stable', 'installable':True, 'update_allowed':True,
           'rollback_allowed':False}
ARTIFACT = {'target_release_id':RID, 'bundle_sha256':SHA,
            'bundle_size': 228000000, 'release_approval_reference':'verified-ci-synthetic',
            'release_candidate_sha256':'b'*64, 'source_commit':'c'*40}


def _isolated_local_ci_url():
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        pytest.skip('PostgreSQL row-lock tests run only on GitHub Actions')
    url = os.environ.get('DATABASE_URL', '')
    d = make_url(url)
    if (d.get_backend_name() != 'postgresql' or d.host not in ('127.0.0.1','localhost')
            or d.port != 5432 or d.database != 'planiq_ci'
            or os.environ.get('ENVIRONMENT') != 'development'):
        raise AssertionError('63D2 refuses anything but disposable local CI PostgreSQL')
    return url


def _fk_tables(seed):
    out={m.__table__.key:m.__table__ for m in seed}
    pending=list(out.values())
    while pending:
        t=pending.pop()
        for fk in t.foreign_keys:
            other=fk.column.table
            if other.key not in out:
                out[other.key]=other
                pending.append(other)
    return list(out.values())


@pytest.fixture
def postgres(monkeypatch):
    url=_isolated_local_ci_url()
    schema='release_wave_ci_'+uuid4().hex[:16]
    admin=create_engine(url)
    with admin.begin() as db:
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
    base=create_engine(url, pool_size=5, max_overflow=0, pool_timeout=10,
                       connect_args={'options':f'-csearch_path={schema}'})
    engine=base.execution_options(schema_translate_map={None:schema})
    monkeypatch.setattr(staged,'resolve_release', lambda v: dict(RELEASE))
    monkeypatch.setattr(staged,'deployment_release_snapshot', lambda r: dict(ARTIFACT))
    monkeypatch.setattr(staged,'_system_now', lambda: NOW)
    try:
        tables=_fk_tables([
            User, Client, ClientCommand, ClientDomainCredential, ClientDomainStatus,
            ClientFlowReleaseControl, ClientFlowRolloutWave, ClientFlowRolloutTarget,
            ClientFlowPhysicalAcceptance, ClientFlowDeployment,
            ClientFlowDeploymentEvent, ClientFlowUpdateCredential,
        ])
        SQLModel.metadata.create_all(engine, tables=tables)
        with Session(engine) as session:
            session.add(Client(id=3, name='ci-client3', status='approved'))
            session.flush()
            session.add_all([
                User(id=1, username='release-ci-actor', hashed_password='hash',
                     email='release-ci@example.invalid', role='superadmin', is_active=True),
                User(id=2, username='release-ci-reviewer', hashed_password='hash',
                     email='release-ci-reviewer@example.invalid', role='superadmin', is_active=True),
            ])
            session.flush()
            session.add_all([
                ClientFlowReleaseControl(id=1,stable_release_id=RID,
                    stable_bundle_sha256=SHA,cutover_enabled=True,fleet_open=True,
                    fresh_install_open=False,revision=3,updated_at=NOW),
                ClientFlowRolloutWave(id='95f50b1e-bf33-4d61-8744-92ec8706353d',
                    kind='controlled',state='approved',release_id=RID,
                    bundle_sha256=SHA,source_version='1.3.43',reason='CI-only synthetic',
                    created_by_user_id=1,approved_by_user_id=2,
                    created_at=NOW-timedelta(hours=1),expires_at=NOW+timedelta(hours=1),
                    approved_at=NOW-timedelta(minutes=40),revision=2),
                ClientFlowPhysicalAcceptance(id='28708ed9-6bad-47e6-a85c-55f0a8a35d1c',
                    release_id=RID,bundle_sha256=SHA,client_id=3,actor_user_id=2,
                    decision='accepted',evidence={
                        'physical_pilot_verified': True,'recovery_verified': True,
                    },created_at=NOW-timedelta(minutes=30)),
            ])
            session.flush()
            session.add_all([
                ClientFlowRolloutTarget(id='c40720d0-e041-4c30-89f5-1d9b2e7ca2b1',
                    wave_id='95f50b1e-bf33-4d61-8744-92ec8706353d',
                    client_id=3,state='approved',created_at=NOW-timedelta(hours=1),
                    expires_at=NOW+timedelta(hours=1)),
                ClientDomainCredential(id='89e11ac0-d66c-4de1-9c94-63919425616b',
                    client_id=3, domain='status', secret_hash='ci-only-hash',
                    created_at=NOW-timedelta(days=1)),
            ])
            session.flush()
            session.add(ClientDomainStatus(id='4a3550f5-4f36-4c1e-8b1a-38d6a065ff92',
                client_id=3,domain='status',credential_id='89e11ac0-d66c-4de1-9c94-63919425616b',
                agent_version='1.3.43',observed_state='online',reported_at=NOW-timedelta(seconds=15)))
            session.commit()
        yield engine
    finally:
        base.dispose()
        admin.dispose()
        cleaner=create_engine(url)
        try:
            with cleaner.begin() as db:
                db.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        finally:
            cleaner.dispose()


def test_two_simultaneous_deployment_attempts_only_one_consumes(postgres):
    ready=Barrier(2,timeout=15)
    def attempt():
        with Session(postgres) as session:
            ready.wait()
            try:
                deployment=staged.create_staged_wave_deployment(
                    session,client_id=3,current_version='1.3.43',
                    release=dict(RELEASE),artifact=dict(ARTIFACT),
                    expected_policy_revision=3,expected_wave_revision=2,
                    requested_by_user_id=1,reason='CI concurrent pilot check',
                    now=NOW,legacy_guard=lambda:None)
                session.commit()
                return ('granted',deployment.id)
            except staged.WaveTransactionDenied as exc:
                session.rollback()
                return ('denied',str(exc))
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(attempt)
        b=pool.submit(attempt)
        results=[a.result(timeout=30),b.result(timeout=30)]
    assert sorted(row[0] for row in results)==['denied','granted'],results
    with Session(postgres) as session:
        deployments=session.exec(select(ClientFlowDeployment)).all()
        targets=session.exec(select(ClientFlowRolloutTarget)).all()
        waves=session.exec(select(ClientFlowRolloutWave)).all()
        assert len(deployments)==1
        assert targets[0].state=='consumed'
        assert targets[0].consumed_deployment_id==deployments[0].id
        assert waves[0].state=='running' and waves[0].revision==3
