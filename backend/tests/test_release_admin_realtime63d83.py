"""Release-admin status is a committed, scoped, payload-free event stream."""
import os
from types import SimpleNamespace

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "ci-only-secret-key-with-at-least-thirty-two-characters")
os.environ.setdefault("FRONTEND_URL", "http://localhost:5173")
os.environ.setdefault("CORS_ALLOW_ORIGINS", "http://localhost:5173")

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel import Session, create_engine

from service1 import db  # register commit/rollback wake hooks
from service1 import ui_realtime, realtime_wakeup


def test_release_admin_capability_denies_non_superadmin_and_client_scope():
    for role in ("viewer", "admin", "bruger"):
        principal = SimpleNamespace(id=9, role=role, is_superadmin=False, organization_id=1)
        with pytest.raises(HTTPException) as exc:
            ui_realtime.issue_ui_realtime_capability(principal, release_admin=True)
        assert exc.value.status_code == 403
    principal = SimpleNamespace(id=1, role="superadmin", is_superadmin=True, organization_id=None)
    with pytest.raises(HTTPException):
        ui_realtime.issue_ui_realtime_capability(principal, client_id=3, release_admin=True)


def test_release_admin_wakes_only_after_commit_not_heartbeat_or_rollback():
    principal = SimpleNamespace(id=1, role="superadmin", is_superadmin=True, organization_id=None)
    issued = ui_realtime.issue_ui_realtime_capability(principal, release_admin=True)
    claims = ui_realtime.verify_ui_realtime_capability(issued["capability"])
    assert claims["release_admin"] is True
    generation = issued["generation"]
    engine = create_engine("sqlite:///:memory:")
    try:
        ui_realtime.notify_ui_state_changed(organization_id=1, client_id=3)
        assert ui_realtime.wait_for_ui_change(claims=claims, after=generation, timeout=0) == generation
        with Session(engine) as session:
            session.execute(text("SELECT 1"))
            realtime_wakeup.queue_release_admin_wakeup(session)
            session.rollback()
        assert ui_realtime.wait_for_ui_change(claims=claims, after=generation, timeout=0) == generation
        with Session(engine) as session:
            session.execute(text("SELECT 1"))
            realtime_wakeup.queue_release_admin_wakeup(session)
            realtime_wakeup.queue_release_admin_wakeup(session)
            assert ui_realtime.wait_for_ui_change(claims=claims, after=generation, timeout=0) == generation
            session.commit()
        assert ui_realtime.wait_for_ui_change(claims=claims, after=generation, timeout=0) == generation + 1
    finally:
        engine.dispose()


def test_committed_status_version_change_wakes_once_without_heartbeat_writes(monkeypatch):
    from collections import OrderedDict

    monkeypatch.setattr(realtime_wakeup, "_RELEASE_VERSION_CACHE", OrderedDict())
    topic = realtime_wakeup.RELEASE_ADMIN_WAKE_DOMAIN
    key = realtime_wakeup.RELEASE_ADMIN_WAKE_KEY
    generation = realtime_wakeup.current_generation(topic, key)
    engine = create_engine("sqlite:///:memory:")
    try:
        def report(version, *, commit=True, credential="test-credential"):
            with Session(engine) as session:
                session.execute(text("SELECT 1"))
                realtime_wakeup.queue_release_version_observation(
                    session, client_id=9001, credential_id=credential, agent_version=version,
                )
                assert realtime_wakeup.current_generation(topic, key) == expected[0]
                if commit:
                    session.commit()
                else:
                    session.rollback()

        expected = [generation]
        report("1.3.47")
        expected[0] += 1
        assert realtime_wakeup.current_generation(topic, key) == expected[0]
        report("1.3.47")
        assert realtime_wakeup.current_generation(topic, key) == expected[0]
        report("1.4.0", commit=False)
        assert realtime_wakeup.current_generation(topic, key) == expected[0]
        report("1.4.0")
        expected[0] += 1
        assert realtime_wakeup.current_generation(topic, key) == expected[0]
        report("1.4.0", credential="new-credential")
        expected[0] += 1
        assert realtime_wakeup.current_generation(topic, key) == expected[0]
    finally:
        engine.dispose()
