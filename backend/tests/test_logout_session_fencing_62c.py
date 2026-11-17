"""62C: signed stale-tab logout must not revoke the new refresh cookie."""
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response

os.environ.setdefault("SECRET_KEY", "ci-only-secret-key-with-at-least-thirty-two-characters")
os.environ.setdefault("DATABASE_URL", "postgresql://ci:ci@127.0.0.1:5432/planiq_ci")
os.environ.setdefault("ENVIRONMENT", "development")

from service1 import auth
from service1.models import RefreshToken


# These tests call the route function directly, without FastAPI dependency
# injection. Explicit body=None reproduces an HTTP request with no JSON body;
# otherwise Python passes FastAPI's Body(...) declaration object as body.


class _RowResult:
    def __init__(self, row):
        self.row = row

    def first(self):
        return self.row


class _Session:
    def __init__(self, row, fail_commit=False):
        self.row = row
        self.committed = False
        self.rolled_back = False
        self.fail_commit = fail_commit

    def exec(self, _query):
        return _RowResult(self.row)

    def add(self, _row):
        pass

    def commit(self):
        if self.fail_commit:
            raise RuntimeError("simulated database outage - no credentials")
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def _row(session_id, token="refresh-cookie-new", user_id=7):
    now = datetime.now(timezone.utc)
    return RefreshToken(
        id=123, user_id=user_id, session_id=session_id,
        token_hash=auth._hash_refresh_token(token),
        expires_at=(now + timedelta(hours=2)).replace(tzinfo=None),
        session_expires_at=(now + timedelta(hours=2)).replace(tzinfo=None),
    )


def _request(session_id, token="refresh-cookie-new", user_id=7, *, bearer=True):
    headers = {}
    if bearer:
        signed = auth.create_access_token(data={
            "sub": "test-user", "uid": user_id, "sid": session_id, "role": "admin",
        })
        headers["authorization"] = "Bearer " + signed
    return SimpleNamespace(headers=headers, cookies={auth.REFRESH_COOKIE_NAME: token})


def test_stale_tab_cannot_revoke_or_clear_new_session_cookie():
    session = _Session(_row("b" * 32))
    response = Response()
    with pytest.raises(HTTPException) as error:
        auth.logout(response, _request("a" * 32), body=None, session=session)
    assert error.value.status_code == 409
    assert session.row.revoked_at is None
    assert not session.committed
    assert "set-cookie" not in response.headers


def test_matching_signed_session_revokes_then_clears_cookie():
    session = _Session(_row("a" * 32))
    response = Response()
    assert auth.logout(response, _request("a" * 32), body=None, session=session) == {"ok": True}
    assert session.committed
    assert session.row.revoked_at is not None
    assert any(key.lower() == b"set-cookie" and b"refresh_token=" in value for key, value in response.raw_headers)
    assert response.headers["cache-control"].startswith("no-store")


def test_revocation_failure_is_503_without_cookie_clearing():
    session = _Session(_row("a" * 32), fail_commit=True)
    response = Response()
    with pytest.raises(HTTPException) as error:
        auth.logout(response, _request("a" * 32), body=None, session=session)
    assert error.value.status_code == 503
    assert session.rolled_back
    assert "set-cookie" not in response.headers


def test_invalid_bearer_is_rejected_without_mutation():
    session = _Session(_row("a" * 32))
    response = Response()
    request = _request("a" * 32)
    request.headers["authorization"] = "Bearer invalid"
    with pytest.raises(HTTPException) as error:
        auth.logout(response, request, body=None, session=session)
    assert error.value.status_code == 401
    assert not session.committed
    assert "set-cookie" not in response.headers


def test_cookie_only_legacy_logout_remains_compatible():
    session = _Session(_row("a" * 32))
    response = Response()
    assert auth.logout(response, _request("a" * 32, bearer=False), body=None, session=session) == {"ok": True}
    assert session.committed
