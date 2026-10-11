"""The Display desired-state reconciler must not create a lockdown command storm.

Regresses the production pattern where an offline administrator's kiosk agent
repeatedly succeeds at reapplying lockdown but then reports real enforcement
'drifted' again. A new intent or uncompleted repair is never delayed.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlmodel import SQLModel, Session, create_engine, select

from service1.client_domain_models import ClientCommand
from service1.display_control import (
    LOCKDOWN_DRIFT_RETRY_SECONDS,
    reconcile_kiosk_lockdown,
    utcnow,
)
from service1.models import Client


@pytest.fixture
def database():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _client(session: Session, *, completed_ago: float | None, request_after_completion: bool = False) -> Client:
    when = utcnow() - timedelta(seconds=completed_ago) if completed_ago is not None else None
    client = Client(
        id=987,
        name="Lockdown retry budget",
        status="approved",
        desktop_lockdown_enabled=True,
        desktop_lockdown_status="applied",
        desktop_lockdown_last_applied_at=when,
        desktop_lockdown_updated_at=(
            when + timedelta(seconds=1)
            if request_after_completion and when is not None
            else utcnow() - timedelta(days=1)
        ),
    )
    session.add(client)
    session.commit()
    return client


def _drift(*, observed_desired: bool = True) -> dict:
    return {
        "kiosk_lockdown": {
            "schema_version": 1,
            "desired": observed_desired,
            "status": "drifted",
            "message": "launchers; acl; polkit; quick-guard",
        }
    }


def _reconcile(session: Session, client: Client, payload: dict) -> ClientCommand | None:
    return reconcile_kiosk_lockdown(
        session,
        client_id=client.id,
        client=client,
        agent_version="1.3.34",
        status_payload=payload,
    )


def _lockdown_commands(session: Session) -> list[ClientCommand]:
    return list(
        session.exec(
            select(ClientCommand).where(ClientCommand.command_type == "set_kiosk_lockdown")
        ).all()
    )


def test_repeated_drift_after_success_does_not_queue_or_hide_failure(database):
    with Session(database) as session:
        client = _client(session, completed_ago=10)
        for _ in range(80):
            assert _reconcile(session, client, _drift()) is None
            session.commit()
        assert _lockdown_commands(session) == []
        session.refresh(client)
        assert client.desktop_lockdown_status == "drifted"
        assert client.desktop_lockdown_message == "launchers; acl; polkit; quick-guard"
        assert client.desktop_lockdown_enabled is True


def test_expired_drift_cooldown_queues_one_repair(database):
    with Session(database) as session:
        client = _client(session, completed_ago=LOCKDOWN_DRIFT_RETRY_SECONDS + 10)
        command = _reconcile(session, client, _drift())
        assert command is not None
        assert command.command_type == "set_kiosk_lockdown"
        assert command.payload == {"enabled": True}
        session.commit()
        assert len(_lockdown_commands(session)) == 1
        assert client.desktop_lockdown_status == "pending"
        # A queued repair is reused, never duplicated by another report.
        assert _reconcile(session, client, _drift()) is not None
        session.commit()
        assert len(_lockdown_commands(session)) == 1


@pytest.mark.parametrize("observed_desired", [True, False])
def test_no_prior_success_or_new_desired_repairs_immediately(database, observed_desired):
    with Session(database) as session:
        client = _client(session, completed_ago=None if observed_desired else 10)
        command = _reconcile(session, client, _drift(observed_desired=observed_desired))
        assert command is not None
        assert command.payload == {"enabled": True}
        session.commit()
        assert len(_lockdown_commands(session)) == 1


def test_explicit_new_operator_intent_bypasses_cooldown(database):
    with Session(database) as session:
        client = _client(session, completed_ago=10, request_after_completion=True)
        command = _reconcile(session, client, _drift())
        assert command is not None
        assert command.payload == {"enabled": True}
        session.commit()
        assert len(_lockdown_commands(session)) == 1


def test_failed_or_unknown_enforcement_is_not_throttled(database):
    with Session(database) as session:
        client = _client(session, completed_ago=10)
        payload = {"kiosk_lockdown": {"status": "error", "desired": True, "message": "failure"}}
        command = _reconcile(session, client, payload)
        assert command is not None
        session.commit()
        assert len(_lockdown_commands(session)) == 1


def test_matching_applied_lockdown_does_not_queue(database):
    with Session(database) as session:
        client = _client(session, completed_ago=LOCKDOWN_DRIFT_RETRY_SECONDS + 10)
        assert _reconcile(session, client, {"kiosk_lockdown": {"desired": True, "status": "applied"}}) is None
        session.commit()
        assert _lockdown_commands(session) == []
