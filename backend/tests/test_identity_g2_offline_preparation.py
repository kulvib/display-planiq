"""Security-negative tests of offline-only PlanIQ Display Identity G2 contract."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import json
from pathlib import Path
import sys

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from identity_integration_prep.contract import (  # noqa: E402
    ApprovedLink,
    IdentityContractRejected,
    LocalAdmin,
    OidcTrust,
    SignedIdentity,
    consume_code_callback,
    prepare_code_flow,
    require_existing_local_admin,
    verify_id_token,
)

ISSUER = "https://identity.example.test/realms/planiq"
CLIENT = "planiq-display-g2"
CALLBACK = "https://display.example.test/identity/callback"
TRUST = OidcTrust(ISSUER, CLIENT, CALLBACK)
SESSION = "random-server-controlled-binding-" + "a" * 48
NOW = datetime.now(timezone.utc)


@pytest.fixture(scope="module")
def keys():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    public.update({"kid": "test-key-1", "alg": "RS256", "use": "sig"})
    wrong = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private, {"keys": [public]}, wrong


def signed(keys, nonce, *, header=None, claims_override=None, missing=None):
    now = int(datetime.now(timezone.utc).timestamp())
    claims = {
        "iss": ISSUER,
        "sub": "external-sub-84",
        "aud": CLIENT,
        "iat": now - 2,
        "exp": now + 180,
        "nonce": nonce,
        "email": "some-admin@example.test",
        "groups": ["superadmin"],
    }
    claims.update(claims_override or {})
    if missing:
        claims.pop(missing, None)
    return jwt.encode(
        claims, keys[0], algorithm="RS256",
        headers=header if header is not None else {"kid": "test-key-1"},
    )


def rejected(fn):
    with pytest.raises(IdentityContractRejected):
        fn()


@pytest.mark.parametrize("issuer", [
    "http://identity.example.test/realms/planiq",
    "https://identity.example.test/realms/planiq?redirect=evil",
    "https://name:password@identity.example.test/realms/planiq",
    "https://identity.example.test/realms/planiq#frag",
    "https://identity.example.test.",
    " HTTPS://identity.example.test/",
])
def test_strict_https_issuer(issuer):
    rejected(lambda: OidcTrust(issuer, CLIENT, CALLBACK))


@pytest.mark.parametrize("uri", [
    "http://display.example.test/identity/callback",
    "https://display.example.test/",
    "https://display.example.test/identity/callback?code=steal",
    "https://attacker@display.example.test/identity/callback",
])
def test_no_unregistered_or_insecure_callback(uri):
    rejected(lambda: OidcTrust(ISSUER, CLIENT, uri))


@pytest.mark.parametrize("client", ["", "*", "with spaces", "x" * 129])
def test_invalid_client_id(client):
    rejected(lambda: OidcTrust(ISSUER, client, CALLBACK))


def test_secure_authorization_code_context_is_random_and_bound():
    a = prepare_code_flow(TRUST, session_binding=SESSION, now=NOW)
    b = prepare_code_flow(TRUST, session_binding=SESSION, now=NOW)
    assert a.state != b.state and a.nonce != b.nonce
    assert a.nonce != a.state and a.verifier != b.verifier
    assert len(a.nonce) >= 32 and len(a.state) >= 32
    assert 43 <= len(a.verifier) <= 128
    challenge = base64.urlsafe_b64encode(hashlib.sha256(
        a.verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    assert a.challenge == challenge
    assert a.session_digest != SESSION
    assert a.redirect_uri == CALLBACK
    rejected(lambda: prepare_code_flow(TRUST, session_binding="user-id-1", now=NOW))


def test_state_is_one_use_and_callback_bound_to_exact_session_and_time():
    tx = prepare_code_flow(TRUST, session_binding=SESSION, now=NOW)
    db = {tx.state: tx}
    def atomic_take(state):
        return db.pop(state, None)
    answer = {"state": tx.state, "code": "authcode_123456789"}
    result = consume_code_callback(
        TRUST, answer, atomic_take=atomic_take,
        session_binding=SESSION, now=NOW)
    assert (result.nonce, result.verifier, result.redirect_uri) == (
        tx.nonce, tx.verifier, tx.redirect_uri)
    assert tx.state not in db
    rejected(lambda: consume_code_callback(
        TRUST, answer, atomic_take=atomic_take, session_binding=SESSION, now=NOW))
    for session, when, trust in (
        ("different-server-binding-" + "b" * 48, NOW, TRUST),
        (SESSION, NOW + timedelta(minutes=5, seconds=1), TRUST),
        (SESSION, NOW - timedelta(seconds=1), TRUST),
        (SESSION, NOW, OidcTrust(ISSUER, CLIENT, "https://display.example.test/other")),
    ):
        db[tx.state] = tx
        rejected(lambda session=session, when=when, trust=trust: consume_code_callback(
            trust, answer, atomic_take=atomic_take, session_binding=session, now=when))
        assert tx.state not in db
    for invalid in (
        {"state": "short", "code": "authcode_123456789"},
        {"state": tx.state, "code": ""},
        {"state": tx.state, "code": "invalid code"},
        {"state": tx.state, "code": "authcode_123456789", "error": "access_denied"},
        {"state": tx.state},
    ):
        rejected(lambda invalid=invalid: consume_code_callback(
            TRUST, invalid, atomic_take=atomic_take, session_binding=SESSION, now=NOW))


def test_signed_identity_requires_exact_issuer_audience_nonce_and_time(keys):
    nonce = "random-challenge-nonce-" + "c" * 48
    token = signed(keys, nonce)
    result = verify_id_token(token, trust=TRUST, nonce=nonce, trusted_jwks=keys[1])
    assert result == SignedIdentity(ISSUER, "external-sub-84", CLIENT)
    cases = [
        {"iss": "https://wrong.example.test/realms/planiq"},
        {"aud": "planiq-flow"},
        {"aud": [CLIENT, "planiq-flow"]},
        {"aud": [CLIENT, "planiq-flow"], "azp": "planiq-flow"},
        {"aud": CLIENT, "azp": "planiq-worklog"},
        {"nonce": "not-the-current-request"},
        {"sub": ""},
        {"sub": "bad\nsubject"},
        {"exp": 1},
        {"exp": "invalid"},
        {"iat": True},
        {"iat": int(datetime.now(timezone.utc).timestamp()) + 1800},
    ]
    for claims in cases:
        rejected(lambda claims=claims: verify_id_token(
            signed(keys, nonce, claims_override=claims),
            trust=TRUST, nonce=nonce, trusted_jwks=keys[1]))
    valid_multi = signed(keys, nonce, claims_override={
        "aud": [CLIENT, "planiq-other"], "azp": CLIENT,
    })
    assert verify_id_token(valid_multi, trust=TRUST, nonce=nonce,
                           trusted_jwks=keys[1]).subject == "external-sub-84"


def test_missing_jwt_required_claims_are_all_rejected(keys):
    nonce = "long-nonce-" + "d" * 48
    for key in ("iss", "sub", "aud", "exp", "iat", "nonce"):
        rejected(lambda key=key: verify_id_token(
            signed(keys, nonce, missing=key),
            trust=TRUST, nonce=nonce, trusted_jwks=keys[1]))


def test_untrusted_jwk_algorithm_key_rotation_and_signature_fail_closed(keys):
    nonce = "long-nonce-" + "e" * 48
    token = signed(keys, nonce)
    other_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(keys[2].public_key()))
    other_jwk.update({"kid": "test-key-1", "alg": "RS256"})
    for jwks in (
        {"keys": []},
        {"keys": [other_jwk]},
        {"keys": keys[1]["keys"] * 2},
        {"keys": [dict(keys[1]["keys"][0], d="private")]},
        {"keys": [dict(keys[1]["keys"][0], alg="HS256")]},
        {"keys": [dict(keys[1]["keys"][0], use="enc")]},
        {"keys": [dict(keys[1]["keys"][0], x5u="https://evil.test/key")]},
    ):
        rejected(lambda jwks=jwks: verify_id_token(
            token, trust=TRUST, nonce=nonce, trusted_jwks=jwks))
    header_from_network = signed(keys, nonce, header={
        "kid": "test-key-1", "jku": "https://evil.test/jwks",
    })
    rejected(lambda: verify_id_token(header_from_network, trust=TRUST,
                                     nonce=nonce, trusted_jwks=keys[1]))
    unknown_kid = signed(keys, nonce, header={"kid": "other-key"})
    rejected(lambda: verify_id_token(unknown_kid, trust=TRUST, nonce=nonce,
                                     trusted_jwks=keys[1]))
    token_without_kid = jwt.encode({"sub": "a"}, keys[0], algorithm="RS256")
    rejected(lambda: verify_id_token(token_without_kid, trust=TRUST,
                                     nonce=nonce, trusted_jwks=keys[1]))
    unsigned = jwt.encode({"sub": "a"}, key="", algorithm="none")
    rejected(lambda: verify_id_token(unsigned, trust=TRUST,
                                     nonce=nonce, trusted_jwks=keys[1]))


def test_existing_verified_subject_link_and_local_admin_gate(keys):
    nonce = "long-nonce-" + "f" * 48
    identity = verify_id_token(signed(keys, nonce), trust=TRUST,
                               nonce=nonce, trusted_jwks=keys[1])
    local = LocalAdmin(id=84, role="admin", organization_id=6,
                       active=True, must_change_password=False)
    link = ApprovedLink(issuer=ISSUER, subject=identity.subject,
                        local_user_id=84, explicitly_verified=True)
    assert require_existing_local_admin(identity, links=[link], users={84: local}) == local
    for links, users in (
        ([], {84: local}),
        ([replace(link, subject="other-sub")], {84: local}),
        ([replace(link, issuer="https://different.example.test")], {84: local}),
        ([replace(link, explicitly_verified=False)], {84: local}),
        ([link, link], {84: local}),
        ([link], {}),
        ([link], {84: replace(local, active=False)}),
        ([link], {84: replace(local, must_change_password=True)}),
        ([link], {84: replace(local, role="viewer")}),
        ([link], {84: replace(local, role="bruger")}),
        ([link], {84: replace(local, role="admin", organization_id=None)}),
        ([link], {84: replace(local, id=85)}),
        ([link], {84: replace(local, role="superadmin", organization_id=6)}),
    ):
        rejected(lambda links=links, users=users: require_existing_local_admin(
            identity, links=links, users=users))
    real_superadmin = replace(local, role="superadmin", organization_id=None)
    assert require_existing_local_admin(
        identity, links=[link], users={84: real_superadmin}) == real_superadmin
    # An IdP group called superadmin grants NOTHING without a matching local link.
    rejected(lambda: require_existing_local_admin(
        identity, links=[], users={84: real_superadmin}))


def test_isolated_package_has_no_legacy_login_or_machine_dependencies():
    assert (ROOT / "backend/identity_integration_prep/contract.py").is_file()
    protected_files = (
        "backend/service1/main.py",
        "backend/service1/auth.py",
        "backend/service1/routers/client_auth_compat.py",
        "backend/service1/routers/remote_desktop_auth.py",
        "backend/service1/routers/terminal_auth.py",
        "frontend/src/auth/AuthProvider.jsx",
    )
    for path in protected_files:
        source = (ROOT / path).read_text(encoding="utf-8")
        assert "identity_integration_prep" not in source, path
        assert "PLANIQ_IDENTITY_G2_ENABLED" not in source, path
    assert not list((ROOT / "backend/migrations/versions").glob("*identity_g2*"))
