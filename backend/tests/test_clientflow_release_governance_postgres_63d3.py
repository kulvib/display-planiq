"""63D-3 PostgreSQL competing human approvals; DISPOSABLE GitHub CI DB ONLY.

No Neon or Render credentials are used. This test refuses to run outside the
local ephemeral PostgreSQL 18.4 CI service and creates a random schema.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier
from uuid import uuid4
import os

import pytest
pytest.importorskip('sqlmodel')
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlmodel import SQLModel, Session, create_engine, select

from service1 import clientflow_release_governance as governance
from service1.client_domain_models import ClientDomainCredential, ClientDomainStatus
from service1.clientflow_release_admin_models import (
    ClientFlowReleaseControl, ClientFlowRolloutWave, ClientFlowRolloutTarget,
    ClientFlowPhysicalAcceptance,
)
from service1.models import User, Client, AuditLog

RID='clientflow-1.3.45-seq-1246'
SHA='a'*64
NOW=datetime(2026, 11, 18, 11, 0)
WAVE='06ed54b3-295f-4dba-b20d-1c49e22f5a5d'


def _disposable_local_ci_url():
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        pytest.skip('Only the disposable local GitHub CI PostgreSQL service is allowed')
    raw=os.environ.get('DATABASE_URL', '')
    url=make_url(raw)
    if (url.get_backend_name() != 'postgresql'
            or url.host not in ('127.0.0.1','localhost')
            or url.port != 5432 or url.database != 'planiq_ci'
            or os.environ.get('ENVIRONMENT') != 'development'):
        raise AssertionError('63D3 refuses production or non-CI PostgreSQL')
    return raw


def _fk_tables(seeds):
    tables={m.__table__.key:m.__table__ for m in seeds}
    pending=list(tables.values())
    while pending:
        for fk in pending.pop().foreign_keys:
            parent=fk.column.table
            if parent.key not in tables:
                tables[parent.key]=parent
                pending.append(parent)
    return list(tables.values())


@pytest.fixture
def postgres(monkeypatch):
    url=_disposable_local_ci_url()
    schema='governance_ci_'+uuid4().hex[:16]
    root=create_engine(url)
    with root.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    base=create_engine(url,pool_size=4,max_overflow=0,pool_timeout=10,
                       connect_args={'options':f'-csearch_path={schema}'})
    engine=base.execution_options(schema_translate_map={None:schema})
    monkeypatch.setattr(governance,'resolve_release',lambda version: {
        'release_id':RID,'version':'1.3.45','release_sequence':1246,
        'status':'stable','installable':True,'update_allowed':True,'rollback_allowed':False,
    })
    monkeypatch.setattr(governance,'deployment_release_snapshot',lambda release: {
        'target_release_id':RID,'bundle_sha256':SHA,
        'release_approval_reference':'ci-synthetic-signed-release',
    })
    try:
        SQLModel.metadata.create_all(engine,tables=_fk_tables([
            User, Client, AuditLog, ClientFlowReleaseControl,
            ClientFlowRolloutWave, ClientFlowRolloutTarget, ClientFlowPhysicalAcceptance,
            ClientDomainCredential, ClientDomainStatus,
        ]))
        with Session(engine) as session:
            session.add_all([Client(id=i,name=f'ci-{i}',status='approved') for i in (3,4,5)])
            session.flush()
            session.add_all([
                User(id=1, username='creator',hashed_password='hash',
                     email='creator@example.invalid',role='superadmin',is_active=True),
                User(id=2,username='reviewer',hashed_password='hash',
                     email='reviewer@example.invalid',role='superadmin',is_active=True),
            ])
            session.flush()
            session.add_all([
                ClientFlowReleaseControl(id=1,stable_release_id=RID,
                    stable_bundle_sha256=SHA,cutover_enabled=False,fleet_open=False,
                    revision=7,updated_at=NOW),
                ClientFlowRolloutWave(id=WAVE,kind='controlled',state='draft',
                    release_id=RID,bundle_sha256=SHA,source_version='1.3.43',
                    reason='CI-only draft, not authorized',created_by_user_id=1,
                    approved_by_user_id=2,approved_at=NOW-timedelta(minutes=30),
                    created_at=NOW-timedelta(hours=1),expires_at=NOW+timedelta(hours=1),
                    revision=2),
                ClientFlowPhysicalAcceptance(id=str(uuid4()),release_id=RID,
                    bundle_sha256=SHA,client_id=3,actor_user_id=2,decision='accepted',
                    evidence={'physical_pilot_verified':True,'recovery_verified':True,
                        'pilot_client_id':3,'release_id':RID,'bundle_sha256':SHA,
                        'tested_by_user_id':1,'pilot_reference':'pilot-viborg1-20261118',
                        'recovery_reference':'recovery-viborg1-20261118'},
                    created_at=NOW-timedelta(minutes=35)),
            ])
            session.flush()
            for cid in (4,5):
                session.add(ClientFlowRolloutTarget(id=str(uuid4()),wave_id=WAVE,
                    client_id=cid,state='draft',created_at=NOW-timedelta(hours=1),
                    expires_at=NOW+timedelta(hours=1)))
                credential=str(uuid4())
                session.add(ClientDomainCredential(id=credential,client_id=cid,
                    domain='status',secret_hash='synthetic',created_at=NOW-timedelta(days=1)))
                session.flush()
                session.add(ClientDomainStatus(id=str(uuid4()),client_id=cid,
                    domain='status',credential_id=credential,
                    agent_version='1.3.43',observed_state='online',
                    reported_at=NOW-timedelta(seconds=15)))
            session.commit()
        yield engine
    finally:
        base.dispose()
        root.dispose()
        cleanup=create_engine(url)
        try:
            with cleanup.begin() as c:
                c.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        finally:
            cleanup.dispose()


def test_concurrent_wave_approval_exactly_one_succeeds_and_audits_once(postgres):
    barrier=Barrier(2,timeout=15)
    def attempt():
        with Session(postgres) as session:
            barrier.wait()
            try:
                result=governance.stage_approve_controlled_wave(
                    session, wave_id=WAVE,expected_policy_revision=7,
                    expected_wave_revision=2,release_id=RID,bundle_sha256=SHA,
                    actor_user_id=2,now=NOW)
                session.commit()
                return ('approved', result.id)
            except governance.GovernanceDenied as exc:
                session.rollback()
                return ('denied',str(exc))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=[pool.submit(attempt) for _ in range(2)]
        outcomes=[f.result(timeout=30) for f in results]
    assert sorted(x[0] for x in outcomes)==['approved','denied'],outcomes
    with Session(postgres) as session:
        wave=session.get(ClientFlowRolloutWave,WAVE)
        assert wave.state=='approved' and wave.revision==3
        assert sorted(t.state for t in session.exec(select(ClientFlowRolloutTarget)).all())==['approved','approved']
        assert len(session.exec(select(AuditLog)).all())==1
        control=session.get(ClientFlowReleaseControl,1)
        assert control.cutover_enabled is False and control.fleet_open is False
