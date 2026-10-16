"""Bounded, isolated CI fleet rehearsal against real agent HTTP routes.

The test NEVER opens a socket to production: an exact GitHub Actions / local
Postgres contract is required and an independent, throwaway PostgreSQL schema
contains every synthetic client.  It is a correctness and comparative request/
SQL budget test, NOT a claim about 15 real Ubuntu boxes or Neon billing.
"""
from __future__ import annotations

import asyncio
import base64
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from statistics import median
from time import perf_counter
import uuid

import pytest
from fastapi import FastAPI
from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlmodel import SQLModel, Session, create_engine, select

from service1.client_domain_models import (
    ClientCommand,
    ClientDomainCredential,
    ClientDomainStatus,
    DisplayDesiredConfiguration,
)
from service1.clientflow_update_models import ClientFlowDeployment
from service1.livestream_v2 import credential_digest
from service1.livestream_v2_models import (
    LivestreamV2Credential, LivestreamV2AgentStatus, LivestreamV2Command,
    LivestreamV2Generation, LivestreamV2Viewer,
)
from service1.models import Client, EnrollmentToken, Organization, User
from service1.remote_desktop_v2_models import RemoteDesktopClient, RemoteDesktopCredential
from service1.terminal_v2_models import TerminalClient, TerminalCredential
from service1.routers import (
    client_auth_compat, livestream_v2, remote_desktop_auth, shared_domain, terminal_auth,
)

@dataclass(frozen=True)
class _ASGIResponse:
    status_code: int
    content: bytes

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.content)


class _ASGIClient:
    """Concurrent in-process ASGI HTTP, without introducing a new dependency."""

    def __init__(self, app: FastAPI):
        self.app = app

    async def request(self, method: str, path: str, *, json_body=None, headers=None):
        body = b"" if json_body is None else json.dumps(json_body).encode("utf-8")
        header_items = [(b"host", b"testserver")]
        if json_body is not None:
            header_items.extend([
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ])
        header_items.extend([
            (key.lower().encode("latin-1"), value.encode("latin-1"))
            for key, value in (headers or {}).items()
        ])
        request_sent = False
        messages = []

        async def receive():
            nonlocal request_sent
            if not request_sent:
                request_sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message):
            messages.append(message)

        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1", "method": method.upper(),
            "scheme": "http", "path": path, "raw_path": path.encode("ascii"),
            "query_string": b"", "root_path": "", "headers": header_items,
            "client": ("127.0.0.1", 50000), "server": ("testserver", 80),
        }
        await self.app(scope, receive, send)
        starts = [m for m in messages if m["type"] == "http.response.start"]
        assert len(starts) == 1, "Expected exactly one ASGI response"
        payload = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
        return _ASGIResponse(int(starts[0]["status"]), payload)

    async def post(self, path: str, *, json_body=None, headers=None):
        return await self.request("POST", path, json_body=json_body, headers=headers)

    async def put(self, path: str, *, json_body=None, headers=None):
        return await self.request("PUT", path, json_body=json_body, headers=headers)


SIZES = (5, 10, 15)
ROUNDS = 2
DOMAINS = ("status", "display", "system")


def _local_ci_database_url() -> str:
    """Fail closed: never accept Neon, external, or non-CI target URLs."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        pytest.skip("Fleet load uses GitHub CI's disposable local PostgreSQL only")
    if os.environ.get("ENVIRONMENT") != "development":
        raise AssertionError("Fleet load requires ENVIRONMENT=development")
    url = os.environ.get("DATABASE_URL", "")
    parsed = make_url(url)
    if (parsed.get_backend_name() != "postgresql" or
            parsed.host not in ("localhost", "127.0.0.1") or
            parsed.database != "planiq_ci" or parsed.port != 5432):
        raise AssertionError("Fleet load refuses any database other than local CI planiq_ci:5432")
    return url


def _required_tables():
    """Include all FK dependencies; don't clone or migrate the live schema."""
    seeds = [
        Client, EnrollmentToken, Organization, User,
        ClientDomainCredential, ClientDomainStatus, ClientCommand,
        DisplayDesiredConfiguration, ClientFlowDeployment,
        LivestreamV2Credential, LivestreamV2AgentStatus, LivestreamV2Command,
        LivestreamV2Generation, LivestreamV2Viewer,
        TerminalClient, TerminalCredential,
        RemoteDesktopClient, RemoteDesktopCredential,
    ]
    tables = {model.__table__.key: model.__table__ for model in seeds}
    pending = list(tables.values())
    while pending:
        table = pending.pop()
        for foreign_key in table.foreign_keys:
            parent = foreign_key.column.table
            if parent.key not in tables:
                tables[parent.key] = parent
                pending.append(parent)
    return list(tables.values())


@contextmanager
def _isolated_ci_postgres(monkeypatch):
    url = _local_ci_database_url()
    # DB role is superuser in the disposable CI service. The unique schema is
    # the ONLY object this test creates/drops. Never truncate public tables.
    schema = "fleet_ci_" + uuid.uuid4().hex[:18]
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    # Domain secrets are CI-only, never production credentials.
    monkeypatch.setenv("LIVESTREAM_V2_CREDENTIAL_PEPPER", "fleet-ci-pepper-not-a-production-secret-0000")
    # Separate isolated signing keys are mandatory for Terminal and RD.
    monkeypatch.setenv(
        "CLIENTFLOW_TERMINAL_AUTH_KEY_B64",
        base64.urlsafe_b64encode(b"t" * 32).decode("ascii"),
    )
    monkeypatch.setenv(
        "CLIENTFLOW_REMOTE_DESKTOP_AUTH_KEY_B64",
        base64.urlsafe_b64encode(b"r" * 32).decode("ascii"),
    )
    base = create_engine(
        url,
        # Match the application's documented default pool budget (5+2).
        pool_size=5,
        max_overflow=2,
        pool_timeout=20,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    engine = base.execution_options(schema_translate_map={None: schema})
    try:
        SQLModel.metadata.create_all(engine, tables=_required_tables())
        for module in (client_auth_compat, livestream_v2, remote_desktop_auth, shared_domain, terminal_auth):
            monkeypatch.setattr(module, "engine", engine)
        app = FastAPI()
        for module in (client_auth_compat, livestream_v2, remote_desktop_auth, shared_domain, terminal_auth):
            app.include_router(module.router, prefix="/api")
        yield engine, app
    finally:
        base.dispose()
        # Remove nothing outside the unique schema created by this test.
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@dataclass(frozen=True)
class Agent:
    client_id: int
    secrets: dict[str, str]
    credentials: dict[str, str]
    tokens: dict[str, str]


def _make_agents(engine, count: int) -> list[Agent]:
    from passlib.hash import bcrypt
    from service1.models import utcnow

    agents: list[Agent] = []
    with Session(engine) as session:
        for i in range(count):
            row = Client(name=f"CI-fleet-{i:02d}", status="approved")
            session.add(row)
            session.flush()
            ident = int(row.id)
            now = utcnow()
            credentials: dict[str, str] = {}
            secrets: dict[str, str] = {}
            for domain in (*DOMAINS, "livestream", "terminal", "remote_desktop"):
                credential_id = str(uuid.uuid4())
                # Hash once per independent client/domain. Cheap bcrypt *only*
                # in this throwaway fixture; the real verifier remains intact.
                secret = f"ci-only-fleet-{ident}-{domain}-{uuid.uuid4().hex}"
                hashed = bcrypt.using(rounds=4).hash(secret)
                credentials[domain] = credential_id
                secrets[domain] = secret
                if domain in DOMAINS:
                    session.add(ClientDomainCredential(
                        id=credential_id, client_id=ident, domain=domain,
                        secret_hash=hashed, token_version=0, created_at=now,
                    ))
                elif domain == "livestream":
                    session.add(LivestreamV2Credential(
                        id=credential_id, client_id=ident, domain=domain,
                        secret_digest=credential_digest(secret), token_version=1,
                        created_at=now,
                    ))
                elif domain == "terminal":
                    session.add(TerminalClient(id=ident, status="approved", created_at=now))
                    session.add(TerminalCredential(
                        id=credential_id, client_id=ident, secret_hash=hashed,
                        token_version=0, created_at=now,
                    ))
                else:
                    session.add(RemoteDesktopClient(id=ident, status="approved", created_at=now))
                    session.add(RemoteDesktopCredential(
                        id=credential_id, client_id=ident, secret_hash=hashed,
                        token_version=0, created_at=now,
                    ))
            agents.append(Agent(ident, secrets, credentials, {}))
        session.commit()
    return agents


async def _get_tokens(app: FastAPI, agents: list[Agent]):
    http = _ASGIClient(app)
    for agent in agents:
        for domain in (*DOMAINS, "livestream", "terminal", "remote_desktop"):
            path = (
                "/api/client-auth/token" if domain in (*DOMAINS, "livestream")
                else f"/api/{domain.replace('_', '-')}-auth/token"
            )
            response = await http.post(path, json_body={
                "client_id": agent.client_id,
                "credential_id": agent.credentials[domain],
                "client_secret": agent.secrets[domain],
                "domain": domain,
            })
            assert response.status_code == 200, (domain, response.status_code, response.text[:160])
            payload = response.json()
            assert payload["client_id"] == agent.client_id
            assert payload["domain"] == domain
            agent.tokens[domain] = payload["access_token"]

@dataclass
class StageResult:
    clients: int
    requests: int
    errors: int
    p50_ms: float
    p95_ms: float
    sql_statements: int
    select_statements: int
    sql_checkouts: int
    statuses: dict[str, int]


def _percentile(samples: list[float], p: float) -> float:
    ordered = sorted(samples)
    position = (len(ordered) - 1) * p
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


async def _run_stage(app: FastAPI, engine, agents: list[Agent]) -> StageResult:
    counters = Counter()
    timings: list[float] = []
    errors: list[tuple[int, str, int]] = []
    sql = Counter()

    def _sql_listener(_conn, _cursor, statement, _parameters, _context, _executemany):
        sql["statements"] += 1
        if statement.lstrip().upper().startswith("SELECT"):
            sql["selects"] += 1

    def _checkout_listener(_dbapi_connection, _connection_record, _connection_proxy):
        sql["checkouts"] += 1

    event.listen(engine, "before_cursor_execute", _sql_listener)
    event.listen(engine, "checkout", _checkout_listener)
    start = perf_counter()

    async def run_agent(agent: Agent):
        headers = {domain: {"Authorization": f"Bearer {agent.tokens[domain]}"} for domain in (*DOMAINS, "livestream")}
        http = _ASGIClient(app)
        for _round in range(ROUNDS):
            status = {
                "schema_version": 1,
                "observed_state": "online",
                "status_payload": {"fleet_ci": True},
                "agent_version": "fleet-ci",  # no unsolicited configuration/power changes
                "boot_id": f"fleet-ci-{agent.client_id}",
            }
            calls = [
                ("POST", f"/api/{domain}-agent/clients/{agent.client_id}/presence", None, headers[domain])
                for domain in DOMAINS
            ]
            calls += [
                ("PUT", f"/api/{domain}-agent/clients/{agent.client_id}/status", status, headers[domain])
                for domain in DOMAINS
            ]
            calls += [
                ("POST", f"/api/{domain}-agent/clients/{agent.client_id}/commands/claim", {"lease_seconds": 60}, headers[domain])
                for domain in ("display", "system")
            ]
            calls.extend([
                ("POST", f"/api/livestream-agent/clients/{agent.client_id}/presence", None, headers["livestream"]),
                ("PUT", f"/api/livestream-agent/clients/{agent.client_id}/status", status, headers["livestream"]),
                ("POST", f"/api/livestream-agent/clients/{agent.client_id}/commands/claim", {"lease_seconds": 60}, headers["livestream"]),
            ])
            for method, path, body, auth in calls:
                t0 = perf_counter()
                response = await http.request(method, path, json_body=body, headers=auth)
                timings.append((perf_counter() - t0) * 1000)
                counters[str(response.status_code)] += 1
                if response.status_code != 200:
                    errors.append((agent.client_id, path, response.status_code))
                elif path.endswith("/commands/claim"):
                    assert response.json()["claimed"] is None  # no fake commands
                elif not path.endswith("/livestream-agent/clients/" + str(agent.client_id) + "/status"):
                    assert response.json()["client_id"] == agent.client_id
            # Allow other simulated clients to progress on the event loop.
            await asyncio.sleep(0)
    try:
        # Independent requests actually overlap via FastAPI's worker threadpool.
        await asyncio.gather(*(run_agent(a) for a in agents))
    finally:
        elapsed_s = perf_counter() - start
        event.remove(engine, "before_cursor_execute", _sql_listener)
        event.remove(engine, "checkout", _checkout_listener)

    assert not errors, f"Fleet HTTP errors: {errors[:6]}"
    result = StageResult(
        clients=len(agents), requests=sum(counters.values()), errors=len(errors),
        p50_ms=median(timings), p95_ms=_percentile(timings, .95),
        sql_statements=sql["statements"], select_statements=sql["selects"],
        sql_checkouts=sql["checkouts"], statuses=dict(counters),
    )
    # Diagnostic output, not a flaky wall-clock acceptance threshold.
    print("FLEET_CI_RESULT " + json.dumps({
        "clients": result.clients, "rounds": ROUNDS,
        "requests": result.requests, "errors": result.errors,
        "p50_ms": round(result.p50_ms, 2), "p95_ms": round(result.p95_ms, 2),
        "sql_statements": result.sql_statements,
        "select_statements": result.select_statements,
        "sql_checkouts": result.sql_checkouts,
        "elapsed_seconds": round(elapsed_s, 3),
    }, sort_keys=True))
    return result


def test_fleet_load_5_10_15_isolated_ci_postgres(monkeypatch):
    with _isolated_ci_postgres(monkeypatch) as (engine, app):
        agents = _make_agents(engine, max(SIZES))
        asyncio.run(_get_tokens(app, agents))

        # Negative authentication: one client's valid token cannot read another
        # client's state. The verifier remains exercised, not mocked out.
        async def negative_auth():
            http = _ASGIClient(app)
            response = await http.put(
                f"/api/status-agent/clients/{agents[1].client_id}/status",
                headers={"Authorization": f"Bearer {agents[0].tokens['status']}"},
                json_body={"schema_version": 1, "observed_state": "online", "status_payload": {}},
            )
            assert response.status_code in (401, 403)
            # A Terminal credential must not mint a shared Status bearer token.
            cross_domain = await http.post(
                "/api/client-auth/token",
                json_body={
                    "client_id": agents[0].client_id,
                    "credential_id": agents[0].credentials["terminal"],
                    "client_secret": agents[0].secrets["terminal"],
                    "domain": "status",
                },
            )
            assert cross_domain.status_code in (401, 403)
        asyncio.run(negative_auth())

        results = [asyncio.run(_run_stage(app, engine, agents[:n])) for n in SIZES]
        for n, result in zip(SIZES, results):
            assert result.clients == n
            assert result.requests == n * ROUNDS * 11
            assert result.errors == 0
            assert result.statuses == {"200": result.requests}
            assert result.sql_statements >= result.select_statements > 0
            assert result.sql_checkouts > 0
        # Credential revocation remains authoritative after tokens were minted.
        from service1.models import utcnow
        with Session(engine) as session:
            credential = session.get(ClientDomainCredential, agents[0].credentials["system"])
            assert credential is not None
            credential.revoked_at = utcnow()
            session.add(credential)
            session.commit()

        async def revoked_auth():
            http = _ASGIClient(app)
            response = await http.post(
                f"/api/system-agent/clients/{agents[0].client_id}/commands/claim",
                json_body={"lease_seconds": 60},
                headers={"Authorization": f"Bearer {agents[0].tokens['system']}"},
            )
            assert response.status_code in (401, 403)
        asyncio.run(revoked_auth())

        with Session(engine) as session:
            # The synthetic fleet has its own status rows, and no real clients.
            assert session.exec(select(ClientDomainStatus)).all()
            assert len(session.exec(select(Client)).all()) == 15
            assert session.exec(select(ClientCommand)).all() == []
