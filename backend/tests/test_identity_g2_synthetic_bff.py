"""Isolated synthetic OIDC BFF acceptance tests, never production routes."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import json
from pathlib import Path
import secrets
import sys

from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from identity_integration_prep.contract import (  # noqa: E402
    ApprovedLink, IdentityContractRejected, LocalAdmin, OidcTrust,
)
from identity_integration_prep.synthetic_bff import (  # noqa: E402
    SESSION_ABSOLUTE, SESSION_IDLE, SyntheticDisplayBff,
)

ISSUER = "https://identity.example.test/realms/neutral"
TRUST = OidcTrust(
    ISSUER, "display-g2-synthetic",
    "https://display.example.test/identity/callback",
)
ORIGIN = "https://display.example.test"
BINDING = "random-server-only-binding-" + "R" * 54
USER_ID = 84
SUBJECT = "opaque-external-subject-84"


class SyntheticProvider:
    """No HTTP, external IdP, credential, real email or session cookie."""

    def __init__(self):
        self.private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048,
        )
        key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(
            self.private_key.public_key()))
        key.update({"kid": "pinned-kid-1", "use": "sig", "alg": "RS256"})
        self.jwks = {"keys": [key]}
        self.codes = {}
        self.claims_override = {}
        self.redeemed = 0

    def authorize(self, transaction) -> str:
        code = "oidc-" + secrets.token_urlsafe(28)
        self.codes[code] = transaction
        return code

    def exchange(self, code: str, verifier: str, redirect_uri: str) -> str:
        tx = self.codes.pop(code)
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        if expected != tx.challenge or redirect_uri != tx.redirect_uri:
            raise ValueError("synthetic PKCE/redirect mismatch")
        self.redeemed += 1
        now = int(datetime.now(timezone.utc).timestamp())
        claims = {
            "iss": ISSUER, "sub": SUBJECT, "aud": TRUST.client_id,
            "nonce": tx.nonce, "iat": now - 2, "exp": now + 180,
            "email": "irrelevant@example.test",
            "groups": ["superadmin", "any-org"],
        }
        claims.update(self.claims_override)
        return jwt.encode(
            claims, self.private_key, algorithm="RS256",
            headers={"kid": "pinned-kid-1"},
        )


@pytest.fixture
def setup(tmp_path):
    path = tmp_path / "synthetic_identity_g2.sqlite3"
    store = SyntheticDisplayBff(
        trust=TRUST, disposable_database=path, synthetic_test_only=True)
    local = LocalAdmin(
        id=USER_ID, role="admin", organization_id=7,
        active=True, must_change_password=False,
    )
    link = ApprovedLink(
        issuer=ISSUER, subject=SUBJECT, local_user_id=USER_ID,
        explicitly_verified=True,
    )
    store.seed_local_admin_for_synthetic_test(local)
    store.seed_explicit_link_for_synthetic_test(link)
    return store, SyntheticProvider(), path, local, link


def rejected(action):
    with pytest.raises(IdentityContractRejected):
        action()


def login(store, provider, *, binding=BINDING, now=None):
    now = now or datetime.now(timezone.utc)
    pending = store.start_login(session_binding=binding, now=now)
    code = provider.authorize(pending)
    callback = {"code": code, "state": pending.state}
    return store.finish_login(
        callback, session_binding=binding,
        exchange_code_for_id_token=provider.exchange,
        trusted_jwks=provider.jwks, now=now,
    )


def test_test_only_gate_requires_explicit_disposable_database(tmp_path):
    db = tmp_path / "synthetic_identity_g2.sqlite3"
    rejected(lambda: SyntheticDisplayBff(trust=TRUST, disposable_database=db))
    for bad in (
        tmp_path / "normal.sqlite3",
        tmp_path / "synthetic_identity.db",
        Path("synthetic_identity_g2.sqlite3"),
    ):
        rejected(lambda bad=bad: SyntheticDisplayBff(
            trust=TRUST, disposable_database=bad, synthetic_test_only=True))
    source = (ROOT / "backend/identity_integration_prep/synthetic_bff.py").read_text()
    for forbidden in (
        "requests.", "urllib.request", "sqlmodel", "fastapi.",
        "os.getenv(", "os.environ", "jwt.encode(", "send_email(",
    ):
        assert forbidden not in source


def test_signed_pkce_login_and_local_session_only(setup):
    store, provider, _, local, _ = setup
    secrets_out = login(store, provider)
    assert secrets_out.session != secrets_out.csrf
    assert len(secrets_out.session) > 32
    assert len(secrets_out.csrf) > 32
    now = datetime.now(timezone.utc)
    assert store.require_local_request(
        session=secrets_out.session, method="GET", now=now) == local
    assert store.require_local_request(
        session=secrets_out.session, method="POST", now=now,
        csrf=secrets_out.csrf, origin=ORIGIN) == local
    # The remote synthetic provider has no input into subsequent local access.
    assert provider.redeemed == 1


def test_session_is_not_a_bypass_for_csrf_or_request_origin(setup):
    store, provider, _, _, _ = setup
    tokens = login(store, provider)
    now = datetime.now(timezone.utc)
    for csrf, origin, method in (
        (None, ORIGIN, "POST"),
        ("x" * 64, ORIGIN, "POST"),
        (tokens.csrf, "https://evil.example.test", "POST"),
        (tokens.csrf, None, "DELETE"),
        (tokens.csrf, "http://display.example.test", "PATCH"),
        (tokens.csrf, ORIGIN + ".evil.test", "PUT"),
    ):
        rejected(lambda csrf=csrf, origin=origin, method=method:
                 store.require_local_request(
                     session=tokens.session, method=method, now=now,
                     csrf=csrf, origin=origin))
    rejected(lambda: store.require_local_request(
        session="x" * 64, method="GET", now=now))
    rejected(lambda: store.require_local_request(
        session=tokens.csrf, method="GET", now=now))
    rejected(lambda: store.require_local_request(
        session=tokens.session, method="UNKNOWN", now=now))


def test_callback_replay_and_stolen_browser_binding_fail_closed(setup):
    store, provider, _, _, _ = setup
    now = datetime.now(timezone.utc)
    tx = store.start_login(session_binding=BINDING, now=now)
    code = provider.authorize(tx)
    callback = {"code": code, "state": tx.state}
    rejected(lambda: store.finish_login(
        callback, session_binding="stolen-binding-" + "Z" * 48,
        exchange_code_for_id_token=provider.exchange,
        trusted_jwks=provider.jwks, now=now))
    assert provider.redeemed == 0
    # Callback state is burned even when the wrong browser attempts to use it.
    rejected(lambda: store.finish_login(
        callback, session_binding=BINDING,
        exchange_code_for_id_token=provider.exchange,
        trusted_jwks=provider.jwks, now=now))
    tx2 = store.start_login(session_binding=BINDING, now=now)
    code2 = provider.authorize(tx2)
    callback2 = {"code": code2, "state": tx2.state}
    store.finish_login(
        callback2, session_binding=BINDING,
        exchange_code_for_id_token=provider.exchange,
        trusted_jwks=provider.jwks, now=now)
    rejected(lambda: store.finish_login(
        callback2, session_binding=BINDING,
        exchange_code_for_id_token=provider.exchange,
        trusted_jwks=provider.jwks, now=now))
    assert provider.redeemed == 1


def test_expired_and_future_callback_never_consume_to_a_session(setup):
    store, provider, _, _, _ = setup
    now = datetime.now(timezone.utc)
    for expired in (now + timedelta(minutes=6), now - timedelta(seconds=1)):
        tx = store.start_login(session_binding=BINDING, now=now)
        code = provider.authorize(tx)
        rejected(lambda expired=expired, code=code, tx=tx:
                 store.finish_login(
                     {"state": tx.state, "code": code},
                     session_binding=BINDING,
                     exchange_code_for_id_token=provider.exchange,
                     trusted_jwks=provider.jwks, now=expired))
    assert provider.redeemed == 0


def test_invalid_token_or_unlinked_subject_cannot_create_display_session(setup):
    store, provider, _, _, _ = setup
    for mutation in (
        {"sub": "other-sub-no-local-link"},
        {"iss": "https://evil.example.test"},
        {"aud": "flow"},
        {"nonce": "unrelated-nonce"},
        {"azp": "worklog"},
        {"exp": 1},
    ):
        provider.claims_override = mutation
        rejected(lambda: login(store, provider))
    provider.claims_override = {}
    # A signed provider 'superadmin' group still grants no local role.
    valid = login(store, provider)
    assert store.require_local_request(
        session=valid.session, method="GET",
        now=datetime.now(timezone.utc)).role == "admin"


def test_duplicate_issuer_subject_and_two_links_for_same_local_user_are_denied(setup):
    store, _, _, _, link = setup
    rejected(lambda: store.seed_explicit_link_for_synthetic_test(link))
    rejected(lambda: store.seed_explicit_link_for_synthetic_test(
        replace(link, subject="new-subject")))
    rejected(lambda: store.seed_explicit_link_for_synthetic_test(
        replace(link, issuer="https://evil.test")))
    rejected(lambda: store.seed_explicit_link_for_synthetic_test(
        replace(link, explicitly_verified=False)))


def test_local_role_org_and_account_revocation_cut_off_existing_sessions(setup):
    store, provider, _, local, link = setup
    now = datetime.now(timezone.utc)
    tokens = login(store, provider, now=now)
    for changed in (
        replace(local, active=False),
        replace(local, must_change_password=True),
        replace(local, role="viewer"),
        replace(local, role="bruger"),
        replace(local, organization_id=None),
        replace(local, role="superadmin", organization_id=7),
    ):
        store.seed_local_admin_for_synthetic_test(changed)
        rejected(lambda: store.require_local_request(
            session=tokens.session, method="GET", now=now))
    store.seed_local_admin_for_synthetic_test(local)
    assert store.require_local_request(
        session=tokens.session, method="GET", now=now) == local
    store.revoke_link_for_synthetic_test(
        issuer=link.issuer, subject=link.subject)
    rejected(lambda: store.require_local_request(
        session=tokens.session, method="GET", now=now))


def test_local_sessions_expire_independently_and_logout_rejects_replay(setup):
    store, provider, _, _, _ = setup
    now = datetime.now(timezone.utc)
    token = login(store, provider, now=now)
    store.require_local_request(
        session=token.session, method="GET",
        now=now + SESSION_IDLE - timedelta(seconds=1))
    rejected(lambda: store.require_local_request(
        session=token.session, method="GET",
        now=now + SESSION_ABSOLUTE))
    another = login(store, provider, now=now)
    rejected(lambda: store.require_local_request(
        session=another.session, method="GET",
        now=now + SESSION_IDLE + timedelta(seconds=1)))
    last = login(store, provider)
    rejected(lambda: store.logout(
        session=last.session, csrf="z" * 64,
        origin=ORIGIN, now=datetime.now(timezone.utc)))
    rejected(lambda: store.logout(
        session=last.session, csrf=last.csrf,
        origin="https://evil.test", now=datetime.now(timezone.utc)))
    store.logout(session=last.session, csrf=last.csrf,
                 origin=ORIGIN, now=datetime.now(timezone.utc))
    rejected(lambda: store.require_local_request(
        session=last.session, method="GET", now=datetime.now(timezone.utc)))
    rejected(lambda: store.logout(
        session=last.session, csrf=last.csrf,
        origin=ORIGIN, now=datetime.now(timezone.utc)))


def test_concurrent_callback_is_atomic_across_independent_db_connections(setup):
    store, provider, path, _, _ = setup
    now = datetime.now(timezone.utc)
    pending = store.start_login(session_binding=BINDING, now=now)
    code = provider.authorize(pending)
    callback = {"state": pending.state, "code": code}
    second_worker = SyntheticDisplayBff(
        trust=TRUST, disposable_database=path, synthetic_test_only=True)

    def attempt(worker):
        try:
            return worker.finish_login(
                callback, session_binding=BINDING, now=now,
                exchange_code_for_id_token=provider.exchange,
                trusted_jwks=provider.jwks,
            )
        except IdentityContractRejected:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, (store, second_worker)))
    assert sum(value is not None for value in outcomes) == 1
    assert provider.redeemed == 1


def test_session_survives_disposable_store_restart_but_not_revocation(setup):
    store, provider, path, _, _ = setup
    now = datetime.now(timezone.utc)
    handle = login(store, provider, now=now)
    restarted = SyntheticDisplayBff(
        trust=TRUST, disposable_database=path, synthetic_test_only=True)
    assert restarted.require_local_request(
        session=handle.session, method="GET", now=now).id == USER_ID
    restarted.logout(
        session=handle.session, csrf=handle.csrf, origin=ORIGIN, now=now)
    rejected(lambda: store.require_local_request(
        session=handle.session, method="GET", now=now))


def test_no_runtime_mount_or_machine_client_dependency():
    package_dir = ROOT / "backend/identity_integration_prep"
    assert (package_dir / "synthetic_bff.py").exists()
    for path in (
        "backend/service1/main.py",
        "backend/service1/auth.py",
        "backend/service1/routers/client_auth_compat.py",
        "backend/service1/routers/remote_desktop_auth.py",
        "backend/service1/routers/terminal_auth.py",
        "frontend/src/auth/AuthProvider.jsx",
        "client/runtime/clientflow_runtime/kiosk_session_policy.py",
    ):
        content = (ROOT / path).read_text(encoding="utf-8")
        assert "identity_integration_prep" not in content, path
        assert "synthetic_bff" not in content, path
    assert not list((ROOT / "backend/migrations/versions").glob("*identity_g2*"))
