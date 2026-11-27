"""Release-admin status is a committed, scoped, payload-free event stream."""
import asyncio
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


def test_async_ui_waiters_scale_and_wake_only_the_authorized_scope():
    async def scenario():
        def claims(client=None, org=None, global_scope=False):
            return {"client_id": client, "organization_id": org, "global_scope": global_scope}

        def generation(scope):
            return ui_realtime.current_generation(
                global_scope=scope["global_scope"], organization_id=scope["organization_id"], client_id=scope["client_id"]
            )

        scopes = [claims(client=83000 + i) for i in range(100)]
        scopes += [claims(org=83001), claims(org=83002), claims(global_scope=True)]
        before = [generation(scope) for scope in scopes]
        tasks = [asyncio.create_task(ui_realtime.wait_for_ui_change_async(claims=scope, after=seen, timeout=10))
                 for scope, seen in zip(scopes, before)]
        try:
            await asyncio.sleep(0)
            assert sum(map(len, ui_realtime._UI_ASYNC_WAITERS.values())) == 103
            await asyncio.to_thread(ui_realtime.notify_ui_state_changed, organization_id=83001, client_id=83003)
            for index in (3, 100, 102):
                assert await asyncio.wait_for(tasks[index], 1) == before[index] + 1
            assert all(not task.done() for i, task in enumerate(tasks) if i not in (3, 100, 102))
            await asyncio.to_thread(ui_realtime.notify_ui_fleet_order_changed, {83002})
            assert await asyncio.wait_for(tasks[101], 1) == before[101] + 1
            assert not tasks[4].done()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        assert not ui_realtime._UI_ASYNC_WAITERS
        scope = claims(client=83099)
        before_timeout = generation(scope)
        assert await ui_realtime.wait_for_ui_change_async(claims=scope, after=before_timeout, timeout=0.001) == before_timeout
        assert not ui_realtime._UI_ASYNC_WAITERS
    asyncio.run(scenario())


def test_async_release_wait_keeps_commit_scope_and_never_uses_ui_client_waiters():
    async def scenario():
        claims = {"release_admin": True, "global_scope": True, "client_id": None, "organization_id": None}
        topic = realtime_wakeup.RELEASE_ADMIN_WAKE_DOMAIN
        key = realtime_wakeup.RELEASE_ADMIN_WAKE_KEY
        before = realtime_wakeup.current_generation(topic, key)
        task = asyncio.create_task(ui_realtime.wait_for_ui_change_async(claims=claims, after=before, timeout=10))
        try:
            await asyncio.sleep(0)
            ui_realtime.notify_ui_state_changed(organization_id=83001, client_id=83003)
            await asyncio.sleep(0)
            assert not task.done()
            await asyncio.to_thread(realtime_wakeup.notify_command_available, topic, key)
            assert await asyncio.wait_for(task, 1) == before + 1
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


def test_ui_capability_from_previous_process_requires_fresh_authorization(monkeypatch):
    principal = SimpleNamespace(id=1, role="superadmin", is_superadmin=True, organization_id=None)
    issued = ui_realtime.issue_ui_realtime_capability(principal, release_admin=True)
    claims = ui_realtime.verify_ui_realtime_capability(issued["capability"])
    assert claims["process_epoch"] == ui_realtime._PROCESS_EPOCH
    monkeypatch.setattr(ui_realtime, "_PROCESS_EPOCH", "replacement-process")
    with pytest.raises(HTTPException) as exc:
        ui_realtime.verify_ui_realtime_capability(issued["capability"])
    assert exc.value.status_code == 401
    fresh = ui_realtime.issue_ui_realtime_capability(principal, release_admin=True)
    assert ui_realtime.verify_ui_realtime_capability(fresh["capability"])["process_epoch"] == "replacement-process"


def test_ui_capability_wait_never_exceeds_signed_expiry(monkeypatch):
    monkeypatch.setattr(ui_realtime.time, "time", lambda: 100.25)
    assert ui_realtime.capability_wait_timeout({"exp": 102}, 25) == 1.75
    assert ui_realtime.capability_wait_timeout({"exp": 200}, 25) == 25
    with pytest.raises(HTTPException) as exc:
        ui_realtime.capability_wait_timeout({"exp": 100}, 25)
    assert exc.value.status_code == 401
