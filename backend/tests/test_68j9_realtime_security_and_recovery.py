"""Offline regression: wake-only authorization, expiry, process restart and roles."""
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

from service1 import ui_realtime, shared_domain
from service1.models import Client, User
from service1.routers import clients, shared_domain as shared_routes, livestream_v2 as live_routes


class FakeSocket:
    def __init__(self, fail_on=None):
        self.headers = {"authorization": "Bearer test"}
        self.sent = []
        self.closed = []
        self.fail_on = fail_on

    async def accept(self):
        if self.fail_on == "accept":
            raise OSError("peer disconnected")

    async def send_json(self, message):
        if self.fail_on == "send":
            raise OSError("peer disconnected")
        self.sent.append(message)

    async def close(self, *, code, reason):
        self.closed.append(code)


def test_shared_signed_wake_token_is_client_and_domain_scoped():
    credential = SimpleNamespace(domain="display", client_id=3, id="test-credential", token_version=1)
    token, _ = shared_domain.create_shared_domain_token(credential)
    authorization = "Bearer " + token
    assert shared_domain.verify_shared_agent_wake_token(authorization, client_id=3, domain="display")["client_id"] == 3
    for client_id, domain in [(4, "display"), (3, "system")]:
        with pytest.raises(HTTPException):
            shared_domain.verify_shared_agent_wake_token(authorization, client_id=client_id, domain=domain)


def test_shared_wake_socket_expiry_closes_before_sending_command(monkeypatch):
    socket = FakeSocket()
    checks = []

    def verify(*args, **kwargs):
        checks.append(kwargs)
        if len(checks) > 1:
            raise HTTPException(401, "expired")
        return {"exp": 102}

    async def wait(domain, client_id, generation, timeout):
        assert timeout == 2
        return generation + 1

    monkeypatch.setattr(shared_routes, "verify_shared_agent_wake_token", verify)
    monkeypatch.setattr(shared_routes, "time", SimpleNamespace(time=lambda: 100))
    monkeypatch.setattr(shared_routes, "wait_for_change_async", wait)
    asyncio.run(shared_routes._wake_ws(socket, domain="system", client_id=3))
    assert len(checks) == 2
    assert [message["type"] for message in socket.sent] == ["wake_ready"]
    assert socket.closed == [4401]


def test_shared_long_poll_checks_token_after_wait(monkeypatch):
    checks = []

    def verify(*args, **kwargs):
        checks.append(kwargs)
        if len(checks) > 1:
            raise HTTPException(401, "expired")
        return {"exp": 102}

    async def wait(domain, client_id, generation, timeout):
        assert timeout == 2
        return generation + 1

    monkeypatch.setattr(shared_routes, "verify_shared_agent_wake_token", verify)
    monkeypatch.setattr(shared_routes, "time", SimpleNamespace(time=lambda: 100))
    monkeypatch.setattr(shared_routes, "wait_for_change_async", wait)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(shared_routes._wake_wait("display", 3, 0, 25, "Bearer test"))
    assert exc.value.status_code == 401
    assert len(checks) == 2


def test_livestream_continuous_wake_does_not_starve_recheck(monkeypatch):
    socket = FakeSocket()
    clock = [0.0]
    checks = []

    def verify(*args, **kwargs):
        checks.append(clock[0])
        if len(checks) > 1:
            raise HTTPException(401, "revoked")

    async def wait(domain, client_id, generation, timeout):
        assert 0 <= timeout <= 15
        clock[0] += 5
        # Always a newer generation: the old elif branch never rechecked.
        return generation + 1

    monkeypatch.setattr(live_routes, "asyncio", SimpleNamespace(
        get_running_loop=lambda: SimpleNamespace(time=lambda: clock[0])
    ))
    monkeypatch.setattr(live_routes, "_require_livestream_wake_token", verify)
    monkeypatch.setattr(live_routes, "wait_for_wake_change_async", wait)
    asyncio.run(live_routes.livestream_command_wake_ws(socket, 3))
    assert checks == [0.0, 15.0]
    assert [message["type"] for message in socket.sent] == [
        "wake_ready", "command_available", "command_available"
    ]
    assert socket.closed == [4401]


@pytest.mark.parametrize("fail_on", ["accept", "send"])
def test_wake_handshake_disconnect_is_not_an_unhandled_server_error(monkeypatch, fail_on):
    monkeypatch.setattr(shared_routes, "verify_shared_agent_wake_token", lambda *a, **k: {"exp": 102})
    monkeypatch.setattr(live_routes, "_require_livestream_wake_token", lambda *a, **k: None)
    asyncio.run(shared_routes._wake_ws(FakeSocket(fail_on), domain="system", client_id=3))
    asyncio.run(live_routes.livestream_command_wake_ws(FakeSocket(fail_on), 3))


def test_browser_wait_rejects_expiry_during_wait(monkeypatch):
    principal = SimpleNamespace(id=1, role="superadmin", is_superadmin=True, organization_id=None)
    issued = ui_realtime.issue_ui_realtime_capability(principal)
    claims = ui_realtime.verify_ui_realtime_capability(issued["capability"])
    clock = [claims["exp"] - 2]
    monkeypatch.setattr(ui_realtime, "time", SimpleNamespace(time=lambda: clock[0]))

    async def wait(**kwargs):
        assert kwargs["timeout"] == 2
        clock[0] = claims["exp"]
        return kwargs["after"] + 1

    monkeypatch.setattr(clients, "wait_for_ui_change_async", wait)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(clients.wait_control_room_realtime(
            after=0, timeout_seconds=25, authorization="Bearer " + issued["capability"]
        ))
    assert exc.value.status_code == 401


def _user(role, org):
    return User(id=17, username="test", hashed_password="unused", email="test@example.invalid",
                role=role, organization_id=org)


@pytest.mark.parametrize("role,org,read,admin,reboot,operator", [
    ("superadmin", None, True, True, True, True),
    ("admin", 10, True, True, True, True),
    ("admin", 20, False, False, False, False),
    ("admin", None, False, False, False, False),
    ("bruger", 10, True, False, False, True),
    ("bruger", 20, False, False, False, False),
    ("viewer", None, True, False, False, False),
])
def test_existing_control_room_role_boundary(role, org, read, admin, reboot, operator):
    client = Client(id=3, name="Test client", organization_id=10, status="approved")
    principal = _user(role, org)
    for allowed, action in [
        (read, lambda: clients._require_client_read_access(principal, client)),
        (admin, lambda: clients._require_admin_client_access(principal, client)),
        (reboot, lambda: clients._require_system_action_access(principal, client, "reboot")),
        (operator, lambda: clients._require_client_operator_access(principal, client, "start")),
        (role == "superadmin", lambda: clients._require_system_action_access(principal, client, "shutdown")),
    ]:
        if allowed:
            action()
        else:
            with pytest.raises(HTTPException) as exc:
                action()
            assert exc.value.status_code == 403


def test_client_token_cannot_act_as_another_client_or_human_operator():
    principal = Client(id=3, name="Agent", status="approved")
    other = Client(id=4, name="Other", status="approved")
    clients._require_client_read_access(principal, principal)
    clients._require_client_status_write_access(principal, principal)
    for action in [
        lambda: clients._require_client_read_access(principal, other),
        lambda: clients._require_client_status_write_access(principal, other),
        lambda: clients._require_system_action_access(principal, principal, "reboot"),
        lambda: clients._require_client_operator_access(principal, principal, "start"),
    ]:
        with pytest.raises(HTTPException) as exc:
            action()
        assert exc.value.status_code == 403
