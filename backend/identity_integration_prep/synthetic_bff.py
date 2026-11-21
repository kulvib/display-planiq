"""Synthetic-only, persistent Display Identity BFF acceptance harness.

Offline G2 preparation, NOT a production BFF: no server routes, cookies,
network, token endpoint, real IdP discovery or deployment capability.
SQLite is an intentionally disposable test substitute, NOT Display's schema.
Existing auth, ClientFlow, Flow, Events and Worklog remain untouched.

A future approved G2 app must replace the harness with real Postgres
transactions, browser security, maintained IdP integration, logout/revocation,
JWKS rotation and operation-bound passkey step-up. Do NOT import in service1.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import secrets
import sqlite3
from typing import Callable, Iterator, Mapping

from .contract import (
    ApprovedLink,
    AuthorizationTransaction,
    IdentityContractRejected,
    LocalAdmin,
    OidcTrust,
    SignedIdentity,
    consume_code_callback,
    prepare_code_flow,
    require_existing_local_admin,
    verify_id_token,
)

SESSION_ABSOLUTE = timedelta(hours=6)
SESSION_IDLE = timedelta(minutes=30)
_ALLOWED_METHODS = frozenset({"GET", "POST", "PATCH", "PUT", "DELETE"})
_UNSAFE_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})


def _deny() -> None:
    # Never leak external codes, JWTs, secrets, account IDs or existence.
    raise IdentityContractRejected("Synthetic Display Identity BFF rejected")


def _seconds(value: datetime) -> int:
    if not isinstance(value, datetime) or value.tzinfo is None:
        _deny()
    return int(value.astimezone(timezone.utc).timestamp())


def _hash(value: str) -> str:
    if not isinstance(value, str) or not 32 <= len(value) <= 512:
        _deny()
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TestSessionSecrets:
    """Simulated opaque handles; no Set-Cookie, bearer issue or browser route."""

    session: str
    csrf: str


class SyntheticDisplayBff:
    """Offline simulation of a separate, durable BFF store.

    Each operation opens an independent SQLite connection. BEGIN IMMEDIATE
    serializes consume-once callback and concurrent session mutations.
    Construction requires a plainly named disposable test database and
    positive test-only authorization. Neither is a runtime configuration.
    """

    def __init__(
        self, *, trust: OidcTrust, disposable_database: Path,
        synthetic_test_only: bool = False,
    ) -> None:
        if (
            synthetic_test_only is not True
            or not isinstance(trust, OidcTrust)
            or not isinstance(disposable_database, Path)
            or not disposable_database.is_absolute()
            or disposable_database.suffix != ".sqlite3"
            or not disposable_database.name.startswith("synthetic_identity_")
            or not disposable_database.parent.is_dir()
            or disposable_database.is_symlink()
        ):
            _deny()
        self.trust = trust
        self.path = disposable_database
        with self._db(immediate=True) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS pending (
                  state_digest TEXT PRIMARY KEY,
                  state TEXT NOT NULL,
                  nonce TEXT NOT NULL,
                  verifier TEXT NOT NULL,
                  challenge TEXT NOT NULL,
                  session_digest TEXT NOT NULL,
                  redirect_uri TEXT NOT NULL,
                  created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS local_users (
                  local_id INTEGER PRIMARY KEY,
                  role TEXT NOT NULL,
                  org_id INTEGER,
                  active INTEGER NOT NULL,
                  must_change_password INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS explicit_links (
                  issuer TEXT NOT NULL,
                  subject TEXT NOT NULL,
                  local_id INTEGER NOT NULL,
                  verified INTEGER NOT NULL,
                  PRIMARY KEY (issuer, subject),
                  UNIQUE (local_id)
                );
                CREATE TABLE IF NOT EXISTS local_sessions (
                  session_digest TEXT PRIMARY KEY,
                  csrf_digest TEXT NOT NULL,
                  issuer TEXT NOT NULL,
                  subject TEXT NOT NULL,
                  local_id INTEGER NOT NULL,
                  created_at INTEGER NOT NULL,
                  last_seen_at INTEGER NOT NULL,
                  expires_at INTEGER NOT NULL,
                  revoked INTEGER NOT NULL DEFAULT 0
                );
                """
            )

    @contextmanager
    def _db(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(str(self.path), timeout=5, isolation_level=None)
        try:
            db.execute("PRAGMA foreign_keys=ON")
            if immediate:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if immediate:
                db.commit()
        except Exception:
            if immediate:
                db.rollback()
            raise
        finally:
            db.close()

    def seed_local_admin_for_synthetic_test(self, user: LocalAdmin) -> None:
        if not isinstance(user, LocalAdmin) or type(user.id) is not int or user.id < 1:
            _deny()
        with self._db(immediate=True) as db:
            db.execute(
                """INSERT INTO local_users
                   (local_id, role, org_id, active, must_change_password)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(local_id) DO UPDATE SET
                     role=excluded.role,
                     org_id=excluded.org_id,
                     active=excluded.active,
                     must_change_password=excluded.must_change_password""",
                (user.id, user.role, user.organization_id,
                 int(user.active), int(user.must_change_password)),
            )

    def seed_explicit_link_for_synthetic_test(self, link: ApprovedLink) -> None:
        if not isinstance(link, ApprovedLink):
            _deny()
        if (
            link.issuer != self.trust.issuer
            or not isinstance(link.subject, str) or not link.subject
            or type(link.local_user_id) is not int or link.local_user_id < 1
            or link.explicitly_verified is not True
        ):
            _deny()
        # No upsert here: a duplicate issuer+sub or an attempted second
        # subject for one local account must fail instead of relinking.
        try:
            with self._db(immediate=True) as db:
                db.execute(
                    """INSERT INTO explicit_links (issuer,subject,local_id,verified)
                       VALUES (?,?,?,1)""",
                    (link.issuer, link.subject, link.local_user_id),
                )
        except sqlite3.IntegrityError:
            _deny()

    def revoke_link_for_synthetic_test(self, *, issuer: str, subject: str) -> None:
        with self._db(immediate=True) as db:
            db.execute(
                "UPDATE explicit_links SET verified=0 WHERE issuer=? AND subject=?",
                (issuer, subject),
            )

    def start_login(self, *, session_binding: str, now: datetime) -> AuthorizationTransaction:
        tx = prepare_code_flow(self.trust, session_binding=session_binding, now=now)
        with self._db(immediate=True) as db:
            db.execute(
                """INSERT INTO pending
                   (state_digest,state,nonce,verifier,challenge,session_digest,
                    redirect_uri,created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (_hash(tx.state), tx.state, tx.nonce, tx.verifier,
                 tx.challenge, tx.session_digest, tx.redirect_uri,
                 _seconds(tx.created_at)),
            )
        return tx

    def _take_pending(self, state: str) -> AuthorizationTransaction | None:
        # ACID DELETE even if later token exchange, nonce or identity fails.
        with self._db(immediate=True) as db:
            row = db.execute(
                """SELECT state,nonce,verifier,challenge,session_digest,
                          redirect_uri,created_at FROM pending
                   WHERE state_digest=?""",
                (_hash(state),),
            ).fetchone()
            if row is None:
                return None
            db.execute("DELETE FROM pending WHERE state_digest=?", (_hash(state),))
        return AuthorizationTransaction(
            state=row[0], nonce=row[1], verifier=row[2], challenge=row[3],
            session_digest=row[4],
            redirect_uri=row[5],
            created_at=datetime.fromtimestamp(row[6], tz=timezone.utc),
        )

    def _authoritative_local_user(self, identity: SignedIdentity) -> LocalAdmin:
        with self._db() as db:
            linked = db.execute(
                """SELECT issuer,subject,local_id,verified FROM explicit_links
                   WHERE issuer=? AND subject=?""",
                (identity.issuer, identity.subject),
            ).fetchall()
            users: dict[int, LocalAdmin] = {}
            for issuer, subject, local_id, verified in linked:
                row = db.execute(
                    """SELECT local_id,role,org_id,active,must_change_password
                       FROM local_users WHERE local_id=?""",
                    (local_id,),
                ).fetchone()
                if row:
                    users[local_id] = LocalAdmin(
                        id=row[0], role=row[1], organization_id=row[2],
                        active=bool(row[3]), must_change_password=bool(row[4]),
                    )
        return require_existing_local_admin(
            identity,
            links=[
                ApprovedLink(issuer, subject, local_id, bool(verified))
                for issuer, subject, local_id, verified in linked
            ],
            users=users,
        )

    def finish_login(
        self, callback: Mapping[str, str], *, session_binding: str,
        exchange_code_for_id_token: Callable[[str, str, str], str],
        trusted_jwks: Mapping, now: datetime,
    ) -> TestSessionSecrets:
        # No exceptions from external fake IdP are allowed to leak code,
        # verifier, tokens or user info to the caller.
        accepted = consume_code_callback(
            self.trust, callback, atomic_take=self._take_pending,
            session_binding=session_binding, now=now,
        )
        try:
            id_token = exchange_code_for_id_token(
                accepted.code, accepted.verifier, accepted.redirect_uri,
            )
        except Exception:
            _deny()
        identity = verify_id_token(
            id_token, trust=self.trust, nonce=accepted.nonce,
            trusted_jwks=trusted_jwks,
        )
        local = self._authoritative_local_user(identity)
        session = secrets.token_urlsafe(48)
        csrf = secrets.token_urlsafe(32)
        issued_at = _seconds(now)
        with self._db(immediate=True) as db:
            db.execute(
                """INSERT INTO local_sessions
                   (session_digest,csrf_digest,issuer,subject,local_id,
                    created_at,last_seen_at,expires_at,revoked)
                   VALUES (?,?,?,?,?,?,?,?,0)""",
                (_hash(session), _hash(csrf), identity.issuer, identity.subject,
                 local.id, issued_at, issued_at,
                 issued_at + int(SESSION_ABSOLUTE.total_seconds())),
            )
        return TestSessionSecrets(session=session, csrf=csrf)

    def require_local_request(
        self, *, session: str, method: str, now: datetime,
        csrf: str | None = None, origin: str | None = None,
    ) -> LocalAdmin:
        if method not in _ALLOWED_METHODS:
            _deny()
        digest = _hash(session)
        when = _seconds(now)
        with self._db(immediate=True) as db:
            row = db.execute(
                """SELECT csrf_digest,issuer,subject,local_id,created_at,
                          last_seen_at,expires_at,revoked
                   FROM local_sessions WHERE session_digest=?""",
                (digest,),
            ).fetchone()
            if row is None:
                _deny()
            stored_csrf, issuer, subject, user_id, created, seen, end, revoked = row
            if (
                revoked != 0 or when < created or when < seen or when >= end
                or when - seen > int(SESSION_IDLE.total_seconds())
            ):
                _deny()
            if method in _UNSAFE_METHODS:
                # In a real BFF origin is supplied by the trusted HTTP
                # server parser and the CSRF must be sent in a separate
                # header, never inferred from cookie/query/body.
                from urllib.parse import urlsplit
                public = urlsplit(self.trust.redirect_uri)
                expected_origin = public.scheme + "://" + public.netloc
                if (
                    origin != expected_origin
                    or not isinstance(csrf, str)
                    or not secrets.compare_digest(stored_csrf, _hash(csrf))
                ):
                    _deny()
            principal = SignedIdentity(issuer=issuer, subject=subject,
                                       audience=self.trust.client_id)
            user = self._authoritative_local_user(principal)
            if user.id != user_id:
                _deny()
            db.execute(
                "UPDATE local_sessions SET last_seen_at=? WHERE session_digest=?",
                (when, digest),
            )
            return user

    def logout(
        self, *, session: str, csrf: str, origin: str, now: datetime,
    ) -> None:
        self.require_local_request(
            session=session, method="POST", csrf=csrf, origin=origin, now=now,
        )
        with self._db(immediate=True) as db:
            db.execute(
                "UPDATE local_sessions SET revoked=1 WHERE session_digest=?",
                (_hash(session),),
            )
