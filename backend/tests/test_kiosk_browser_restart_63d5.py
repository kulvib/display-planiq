"""Browser-only restart using the EXISTING 1246 Display stop/start agents.

No running kiosk, Render service, external DB or active deployment is touched.
The stop acknowledgement triggers the next command only in the same DB
transaction and only with a matching/healthy context. No profile clearing.
"""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlmodel import SQLModel, Session, create_engine, select

from service1.client_domain_models import ClientCommand, DisplayDesiredConfiguration
from service1.display_control import apply_display_command_completion, display_command_legacy_action, utcnow
from service1.models import Client
from service1.routers import clients as route


@pytest.fixture
def database(monkeypatch):
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Client(id=777, name="Viborg1-test", organization_id=91, status="approved", state="normal"))
        session.add(DisplayDesiredConfiguration(
            client_id=777, schema_version=1, revision=4,
            kiosk_url="https://example.org/kiosk", browser_refresh_interval_sec=900,
            updated_at=utcnow(), updated_by_user_id=None,
        ))
        session.commit()
        monkeypatch.setattr(route, "_require_client_online", lambda *args, **kwargs: None)
        monkeypatch.setattr(route, "_require_no_active_clientflow_deployment", lambda *args, **kwargs: None)
        monkeypatch.setattr(route, "latest_display_status", lambda *args: SimpleNamespace(
            agent_version="1.3.45", status_payload={"runtime": {"state": "running", "browser_pid": 123}}
        ))
        yield session
    engine.dispose()


def operator(role, org=91):
    return SimpleNamespace(
        role=role, organization_id=org, id=None, is_superadmin=role == "superadmin",
        is_admin=role in {"admin", "superadmin"},
    )


def request_restart(session, user=None):
    return route.set_chrome_command(
        777, {"action": "restart_browser", "source": "actionbutton"},
        session=session, user=user or operator("bruger"),
    )


def get_commands(session):
    return session.exec(select(ClientCommand).where(ClientCommand.client_id == 777).order_by(ClientCommand.requested_at)).all()


@pytest.mark.parametrize("role", ["bruger", "admin", "superadmin"])
def test_operator_roles_queue_single_non_destructive_stop(database, role):
    response = request_restart(database, operator(role))
    assert response["pending_chrome_action"] == "restart_browser"
    commands = get_commands(database)
    assert len(commands) == 1
    assert commands[0].command_type == "stop_browser"
    assert commands[0].payload == {"restart_browser_after_stop": True, "desired_revision": 4}
    assert display_command_legacy_action(commands[0]) == "restart_browser"


@pytest.mark.parametrize("role,org", [
    ("viewer", 91), ("bruger", 22), ("admin", 22), ("guest", 91),
])
def test_forbidden_users_cannot_queue_restart(database, role, org):
    with pytest.raises(HTTPException) as denied:
        request_restart(database, operator(role, org))
    assert denied.value.status_code == 403
    assert get_commands(database) == []


def test_successful_stop_queues_one_start_and_duplicate_callback_is_idempotent(database):
    request_restart(database)
    stop = get_commands(database)[0]
    stop.status = "succeeded"
    stop.result = {"stopped": True, "was_running": True}
    database.add(stop)
    database.flush()
    apply_display_command_completion(database, client_id=777, command_id=stop.id)
    database.commit()
    commands = get_commands(database)
    assert len(commands) == 2
    start = next(c for c in commands if c.command_type == "start_browser")
    assert start.payload == {"restart_browser_followup": True}
    assert display_command_legacy_action(start) == "restart_browser"
    assert all(c.command_type != "reset_browser" for c in commands)
    apply_display_command_completion(database, client_id=777, command_id=stop.id)
    database.commit()
    assert len(get_commands(database)) == 2


@pytest.mark.parametrize("status,result", [
    ("failed", {"stopped": True}),
    ("claimed", {"stopped": True}),
    ("succeeded", {"stopped": False}),
    ("succeeded", {}),
])
def test_failed_or_unverified_stop_cannot_start_browser(database, status, result):
    request_restart(database)
    stop = get_commands(database)[0]
    stop.status, stop.result = status, result
    database.add(stop)
    database.flush()
    apply_display_command_completion(database, client_id=777, command_id=stop.id)
    database.commit()
    assert [c.command_type for c in get_commands(database)] == ["stop_browser"]


@pytest.mark.parametrize("change", ["configuration_changed", "client_inactive", "deleted", "sleep", "os_update"])
def test_changed_state_after_stop_suppresses_followup(database, change):
    request_restart(database)
    stop = get_commands(database)[0]
    stop.status, stop.result = "succeeded", {"stopped": True}
    database.add(stop)
    client = database.get(Client, 777)
    config = database.get(DisplayDesiredConfiguration, 777)
    if change == "configuration_changed":
        config.revision = 5
        database.add(config)
    elif change == "client_inactive":
        client.status = "pending"
        database.add(client)
    elif change == "deleted":
        client.deleted_at = utcnow()
        database.add(client)
    elif change == "sleep":
        client.state = "sleep"
        database.add(client)
    elif change == "os_update":
        client.pending_os_update = True
        database.add(client)
    database.flush()
    apply_display_command_completion(database, client_id=777, command_id=stop.id)
    database.commit()
    assert [c.command_type for c in get_commands(database)] == ["stop_browser"]


def test_active_system_command_blocks_followup(database):
    request_restart(database)
    stop = get_commands(database)[0]
    stop.status, stop.result = "succeeded", {"stopped": True}
    database.add(stop)
    system = ClientCommand(
        id="test-system-1", client_id=777, domain="system", command_type="reboot", schema_version=1,
        payload={}, idempotency_key="test-system-reboot", requested_at=utcnow(),
        available_at=utcnow(), expires_at=utcnow()+timedelta(minutes=3), status="queued", max_attempts=3,
    )
    database.add(system)
    database.flush()
    apply_display_command_completion(database, client_id=777, command_id=stop.id)
    database.commit()
    assert len([c for c in get_commands(database) if c.domain == "display"]) == 1


def test_pending_restart_cannot_be_overwritten_by_concurrent_stop(database):
    request_restart(database)
    with pytest.raises(HTTPException) as blocked:
        route.set_chrome_command(777, {"action": "stop", "source": "actionbutton"},
                                 session=database, user=operator("admin"))
    assert blocked.value.status_code == 409
    assert len(get_commands(database)) == 1

@pytest.mark.parametrize("runtime", [
    {"state": "stopped", "browser_pid": None},
    {"state": "waiting_internet", "browser_pid": None},
    {"state": "running", "browser_pid": None},
    {"state": "starting", "browser_pid": 43},
    {"state": "running", "browser_pid": "43"},
])
def test_restart_refuses_non_running_or_untrusted_display_status(database, monkeypatch, runtime):
    monkeypatch.setattr(route, "latest_display_status", lambda *a: SimpleNamespace(
        agent_version="1.3.45", status_payload={"runtime": runtime},
        reported_at=utcnow(),
    ))
    with pytest.raises(HTTPException) as refused:
        request_restart(database)
    assert refused.value.status_code == 409
    assert get_commands(database) == []


def test_restart_refuses_stale_display_report(database, monkeypatch):
    monkeypatch.setattr(route, "latest_display_status", lambda *a: SimpleNamespace(
        agent_version="1.3.45",
        status_payload={"runtime": {"state": "running", "browser_pid": 123}},
        reported_at=utcnow() - timedelta(minutes=3),
    ))
    with pytest.raises(HTTPException) as refused:
        request_restart(database)
    assert refused.value.status_code == 409
    assert get_commands(database) == []


@pytest.mark.parametrize("state", ["sleep", "shutdown", "rebooting", "updating"])
def test_restart_refuses_sleeping_or_system_transition(database, state):
    client = database.get(Client, 777)
    client.state = state
    database.add(client)
    database.commit()
    with pytest.raises(HTTPException) as refused:
        request_restart(database)
    assert refused.value.status_code == 409
    assert get_commands(database) == []


def test_restart_refuses_active_system_command_before_stopping(database):
    database.add(ClientCommand(
        id="system-active-1", client_id=777, domain="system", command_type="reboot", schema_version=1,
        payload={}, idempotency_key="system-active-1", requested_at=utcnow(), available_at=utcnow(),
        expires_at=utcnow()+timedelta(minutes=4), status="queued", max_attempts=3,
    ))
    database.commit()
    with pytest.raises(HTTPException) as refused:
        request_restart(database)
    assert refused.value.status_code == 409
    assert [c for c in get_commands(database) if c.domain == "display"] == []


@pytest.mark.parametrize("change", ["rebooting", "shutdown", "pending_reboot", "pending_shutdown"])
def test_reboot_or_shutdown_during_stop_cancels_followup(database, change):
    request_restart(database)
    stop = get_commands(database)[0]
    stop.status, stop.result = "succeeded", {"stopped": True}
    client = database.get(Client, 777)
    if change.startswith("pending_"):
        setattr(client, change, True)
    else:
        client.state = change
    database.add(stop)
    database.add(client)
    database.flush()
    apply_display_command_completion(database, client_id=777, command_id=stop.id)
    database.commit()
    assert [c.command_type for c in get_commands(database)] == ["stop_browser"]
