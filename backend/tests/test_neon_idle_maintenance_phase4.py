"""Phase 4: idle Neon wakeups and atomic refresh-token retention.

The cleanup tests exercise the production function against real SQLAlchemy/
SQLModel SQLite statements, including transaction rollback and request counts.
No PostgreSQL service or production credentials are required.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from unittest.mock import patch

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("SECRET_KEY", "ci-only-secret-key-with-at-least-thirty-two-characters")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("FRONTEND_URL", "http://localhost:5173")
os.environ.setdefault("CORS_ALLOW_ORIGINS", "http://localhost:5173")

from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine, select

from service1 import main
from service1.models import RefreshToken


def _test_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    RefreshToken.__table__.create(engine)
    return engine


def _row(*, key: str, expires_days: int = 2, session_days: int | None = None,
         revoked_days: int | None = None) -> RefreshToken:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return RefreshToken(
        user_id=1,
        token_hash=key * 64,
        expires_at=now + timedelta(days=expires_days),
        session_expires_at=None if session_days is None else now + timedelta(days=session_days),
        revoked_at=None if revoked_days is None else now + timedelta(days=revoked_days),
    )


def test_refresh_cleanup_single_statement_preserves_all_retention_predicates() -> None:
    engine = _test_engine()
    tokens = [
        _row(key="a", expires_days=-9),
        _row(key="b", session_days=-9),
        _row(key="c", revoked_days=-9),
        _row(key="d", expires_days=-9, session_days=-10, revoked_days=-11),
        _row(key="e", expires_days=-6),
        _row(key="f", revoked_days=-6),
        _row(key="g", session_days=-6),
        _row(key="h"),
    ]
    with Session(engine) as session:
        session.add_all(tokens)
        session.commit()

    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with patch.object(main, "engine", engine), patch.object(main, "REFRESH_TOKEN_RETENTION_DAYS", 7):
            assert main.cleanup_expired_refresh_tokens_once() == 4
            assert len(statements) == 1
            assert statements[0].lstrip().upper().startswith("DELETE FROM REFRESH_TOKENS")
            assert "RETURNING" in statements[0].upper()
            statements.clear()
            assert main.cleanup_expired_refresh_tokens_once() == 0
            assert len(statements) == 1
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    with Session(engine) as session:
        surviving_hashes = {token.token_hash for token in session.exec(select(RefreshToken)).all()}
    assert surviving_hashes == {key * 64 for key in ("e", "f", "g", "h")}
    engine.dispose()


def test_refresh_cleanup_failed_commit_rolls_back_deletion() -> None:
    engine = _test_engine()
    with Session(engine) as session:
        session.add(_row(key="x", expires_days=-9))
        session.commit()

    class FailedCommitSession(Session):
        def commit(self):
            raise RuntimeError("simulated commit failure")

    with (
        patch.object(main, "engine", engine),
        patch.object(main, "Session", FailedCommitSession),
        patch.object(main, "REFRESH_TOKEN_RETENTION_DAYS", 7),
    ):
        assert main.cleanup_expired_refresh_tokens_once() == 0

    with Session(engine) as session:
        assert len(session.exec(select(RefreshToken)).all()) == 1
    engine.dispose()
