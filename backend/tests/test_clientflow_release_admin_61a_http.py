"""Isolated default-closed release-administration HTTP + transaction tests.

No production database, Render flags, binary releases or client agents are used.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

import pytest

pytest.importorskip("sqlmodel")
from fastapi import FastAPI
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from service1.clientflow_release_admin_models import (
    ClientFlowReleaseControl, ClientFlowRolloutTarget, ClientFlowRolloutWave,
)
from service1.db import get_session
from service1.auth import get_current_superadmin_user
from service1.models import User, Client, AuditLog
from service1.routers import clientflow_release_administration as route

SHA = "28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5"
RELEASE_ID = "clientflow-1.3.44-seq-1245"


# Match the repository's dependency-free ASGI HTTP integration test pattern.
class _ASGIResponse:
    def __init__(self, status_code: int, body: bytes):
        self.status_code = status_code
        self._body = body

    @property
    def text(self) -> str:
        return self._body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self._body.decode("utf-8"))


class _ASGITestClient:
    """Minimal in-process ASGI client using only the runtime's existing stack."""

    def __init__(self, app: FastAPI):
        self.app = app

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: Any | None = None,
    ) -> _ASGIResponse:
        body = b"" if json_body is None else json.dumps(json_body).encode("utf-8")
        header_items = [(b"host", b"testserver")]
        if json_body is not None:
            header_items.extend(
                [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ]
            )
        if headers:
            header_items.extend(
                (name.lower().encode("latin-1"), value.encode("latin-1"))
                for name, value in headers.items()
            )

        async def invoke() -> _ASGIResponse:
            messages: list[dict[str, Any]] = []
            request_sent = False

            async def receive() -> dict[str, Any]:
                nonlocal request_sent
                if not request_sent:
                    request_sent = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return {"type": "http.disconnect"}

            async def send(message: dict[str, Any]) -> None:
                messages.append(message)

            scope = {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.3"},
                "http_version": "1.1",
                "method": method.upper(),
                "scheme": "http",
                "path": path,
                "raw_path": path.encode("ascii"),
                "query_string": b"",
                "root_path": "",
                "headers": header_items,
                "client": ("127.0.0.1", 50000),
                "server": ("testserver", 80),
            }
            await self.app(scope, receive, send)
            starts = [message for message in messages if message["type"] == "http.response.start"]
            assert len(starts) == 1, messages
            response_body = b"".join(
                message.get("body", b"")
                for message in messages
                if message["type"] == "http.response.body"
            )
            return _ASGIResponse(int(starts[0]["status"]), response_body)

        return asyncio.run(invoke())

    def get(self, path: str, *, headers: dict[str, str] | None = None) -> _ASGIResponse:
        return self.request("GET", path, headers=headers)

    def post(
        self,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any | None = None,
    ) -> _ASGIResponse:
        return self.request("POST", path, headers=headers, json_body=json)

    def put(
        self,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any | None = None,
    ) -> _ASGIResponse:
        return self.request("PUT", path, headers=headers, json_body=json)



@pytest.fixture()
def environment(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine, tables=[
        User.__table__, Client.__table__, AuditLog.__table__,
        ClientFlowReleaseControl.__table__, ClientFlowRolloutWave.__table__, ClientFlowRolloutTarget.__table__,
    ])
    with Session(engine) as session:
        admin = User(id=1, username="admin-test", email="admin@example.com", hashed_password="stored", role="superadmin", is_active=True)
        client = Client(id=3, name="Viborg1", status="approved", ubuntu_version="26.04")
        control = ClientFlowReleaseControl(id=1, stable_release_id=RELEASE_ID, stable_bundle_sha256=SHA,
                                           fresh_install_open=False, fleet_open=False, cutover_enabled=False,
                                           revision=1, updated_at=datetime(2026, 11, 15, 12, 0))
        session.add(admin)
        session.add(client)
        session.add(control)
        session.commit()
        session.refresh(admin)

        monkeypatch.setattr(route, "verify_password", lambda password, hashed: password == "correct-password")
        monkeypatch.setattr(route, "_approved_lock", lambda: {"approved_bundle_sha256": SHA})
        monkeypatch.setattr(route, "load_catalog", lambda: {
            "latest_stable": "1.3.44", "default_install_version": "1.3.44",
            "releases": [{"release_id": RELEASE_ID, "status": "stable", "install_modes": ["fresh_install", "in_place_update"],
                           "rollback_allowed": False}],
        })

        app = FastAPI()
        app.include_router(route.router, prefix="/api")
        app.dependency_overrides[get_current_superadmin_user] = lambda: admin
        app.dependency_overrides[get_session] = lambda: session
        yield _ASGITestClient(app), session


def _payload(**overrides):
    data = {
        "kind": "pilot", "client_ids": [3], "source_version": "1.3.43",
        "reason": "Physical pilot Viborg1", "expires_in_hours": 24,
        "expected_revision": 1, "password": "correct-password",
    }
    data.update(overrides)
    return data


def test_default_closed_status_and_draft_does_not_create_deployment(environment):
    http, session = environment
    before = http.get("/api/clientflow/release-administration")
    assert before.status_code == 200, before.text
    policy = before.json()
    assert policy["phase"] == "additive_draft_only"
    assert policy["authorization_active"] is False
    assert policy["fleet_open"] is False
    assert policy["fresh_install_open"] is False
    assert policy["physical_pilot_accepted"] is False
    assert policy["stable_release_id"] == RELEASE_ID
    created = http.post("/api/clientflow/release-administration/drafts", json=_payload())
    assert created.status_code == 201, created.text
    row = created.json()
    assert row["state"] == "draft" and row["client_ids"] == [3]
    assert len(session.exec(select(ClientFlowRolloutTarget)).all()) == 1
    assert session.exec(select(ClientFlowRolloutTarget)).one().state == "draft"
    assert len(session.exec(select(AuditLog).where(AuditLog.action == "clientflow_rollout_draft_created")).all()) == 1
    assert http.get("/api/clientflow/release-administration").json()["waves"][0]["state"] == "draft"
    assert http.post("/api/clientflow/release-administration/drafts/invalid/approve").status_code == 404
    assert session.get(ClientFlowReleaseControl, 1).cutover_enabled is False


def test_pilot_mismatch_and_wrong_password_do_not_create_draft(environment):
    http, session = environment
    assert http.post("/api/clientflow/release-administration/drafts", json=_payload(client_ids=[4])).status_code == 409
    assert http.post("/api/clientflow/release-administration/drafts", json=_payload(password="wrong-password")).status_code == 403
    assert http.post("/api/clientflow/release-administration/drafts", json=_payload(expected_revision=3)).status_code == 409
    assert http.post("/api/clientflow/release-administration/drafts", json=_payload(client_ids=[3, 3])).status_code == 422
    assert len(session.exec(select(ClientFlowRolloutWave)).all()) == 0
    assert session.get(ClientFlowReleaseControl, 1).fleet_open is False


def test_cancel_draft_is_audited_and_cannot_be_reused(environment):
    http, session = environment
    response = http.post("/api/clientflow/release-administration/drafts", json=_payload())
    assert response.status_code == 201, response.text
    wave_id = response.json()["id"]
    url = f"/api/clientflow/release-administration/drafts/{wave_id}/cancel"
    assert http.post(url, json={"password": "correct-password", "expected_revision": 1}).status_code == 200
    assert session.get(ClientFlowRolloutWave, wave_id).state == "cancelled"
    assert session.exec(select(ClientFlowRolloutTarget)).one().state == "revoked"
    assert http.post(url, json={"password": "correct-password", "expected_revision": 1}).status_code == 409
    assert len(session.exec(select(AuditLog).where(AuditLog.action == "clientflow_rollout_draft_cancelled")).all()) == 1


def test_control_drift_fails_closed(environment):
    http, session = environment
    control = session.get(ClientFlowReleaseControl, 1)
    control.fresh_install_open = True
    session.add(control)
    session.commit()
    res = http.get("/api/clientflow/release-administration")
    assert res.status_code == 503
    assert http.post("/api/clientflow/release-administration/drafts", json=_payload()).status_code == 503
    assert not session.exec(select(ClientFlowRolloutWave)).all()
