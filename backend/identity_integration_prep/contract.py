"""Offline Display G2 OIDC trust-boundary preparation.

NOT imported by any running Display application, machine endpoint, frontend,
migration, or ClientFlow. No network, cloud, database, routes or login UI.
This is an offline foundation for a later, separately approved G2 clone.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import re
import secrets
from typing import Callable, Mapping, Sequence
from urllib.parse import urlsplit

import jwt
from jwt import InvalidTokenError


class IdentityContractRejected(ValueError):
    """Fail closed without including secrets or identity claims."""


def _stop() -> None:
    raise IdentityContractRejected("Identity G2 contract rejected")


_IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_SUBJECT = re.compile(r"[^\s\x00-\x1f\x7f]{1,255}\Z")
_CODE = re.compile(r"[A-Za-z0-9_.~+/=-]{8,2048}\Z")
MAX_TRANSACTION_AGE = timedelta(minutes=5)


def _https(value: str) -> bool:
    if not isinstance(value, str) or not value or value.strip() != value or "\\" in value:
        return False
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme == "https" and bool(parsed.hostname)
            and parsed.username is None and parsed.password is None
            and not parsed.query and not parsed.fragment
            and not parsed.hostname.endswith(".")
            and not parsed.hostname.startswith(".")
        )
    except ValueError:
        return False


def _utc(now: datetime) -> datetime:
    if not isinstance(now, datetime) or now.tzinfo is None:
        _stop()
    return now.astimezone(timezone.utc)


def _session_digest(binding: str) -> str:
    # Caller must use a random, server-controlled handle, not email/user ID.
    if not isinstance(binding, str) or len(binding) < 32:
        _stop()
    return hashlib.sha256(binding.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class OidcTrust:
    issuer: str
    client_id: str
    redirect_uri: str

    def __post_init__(self) -> None:
        if (
            not _https(self.issuer) or not _https(self.redirect_uri)
            or not isinstance(self.client_id, str)
            or not _IDENTIFIER.fullmatch(self.client_id)
            or urlsplit(self.redirect_uri).path in ("", "/")
            or self.issuer == self.redirect_uri
        ):
            _stop()


@dataclass(frozen=True)
class AuthorizationTransaction:
    state: str
    nonce: str
    verifier: str
    challenge: str
    session_digest: str
    created_at: datetime
    redirect_uri: str


@dataclass(frozen=True)
class AuthorizedCode:
    code: str
    nonce: str
    verifier: str
    redirect_uri: str


@dataclass(frozen=True)
class SignedIdentity:
    issuer: str
    subject: str
    audience: str


@dataclass(frozen=True)
class ApprovedLink:
    issuer: str
    subject: str
    local_user_id: int
    explicitly_verified: bool


@dataclass(frozen=True)
class LocalAdmin:
    id: int
    role: str
    organization_id: int | None
    active: bool
    must_change_password: bool


def prepare_code_flow(
    trust: OidcTrust, *, session_binding: str, now: datetime
) -> AuthorizationTransaction:
    """Generate one-time state and nonce with RFC7636 S256 PKCE."""
    digest = _session_digest(session_binding)
    timestamp = _utc(now)
    verifier = secrets.token_urlsafe(48)
    if not 43 <= len(verifier) <= 128:
        _stop()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    return AuthorizationTransaction(
        state=secrets.token_urlsafe(32),
        nonce=secrets.token_urlsafe(32),
        verifier=verifier,
        challenge=challenge,
        session_digest=digest,
        created_at=timestamp,
        redirect_uri=trust.redirect_uri,
    )


def consume_code_callback(
    trust: OidcTrust, callback: Mapping[str, str], *,
    atomic_take: Callable[[str], AuthorizationTransaction | None],
    session_binding: str, now: datetime,
) -> AuthorizedCode:
    """Caller must atomically DELETE state in a durable store, also on failure.

    No in-memory storage, session persistence, token exchange, or FastAPI route
    is provided here. Concurrent G2 workers must prove atomic one-time use.
    """
    current = _utc(now)
    digest = _session_digest(session_binding)
    if not isinstance(callback, Mapping) or set(callback) != {"state", "code"}:
        _stop()
    state, code = callback.get("state"), callback.get("code")
    if (
        not isinstance(state, str) or not 32 <= len(state) <= 256
        or not isinstance(code, str) or not _CODE.fullmatch(code)
    ):
        _stop()
    tx = atomic_take(state)
    if not isinstance(tx, AuthorizationTransaction):
        _stop()
    if (
        not secrets.compare_digest(tx.state, state)
        or not secrets.compare_digest(tx.session_digest, digest)
        or tx.redirect_uri != trust.redirect_uri
        or not timedelta(0) <= current - _utc(tx.created_at) <= MAX_TRANSACTION_AGE
    ):
        _stop()
    return AuthorizedCode(code, tx.nonce, tx.verifier, tx.redirect_uri)


def _trusted_rsa_key(token: str, jwks: Mapping) -> object:
    """Never follow remote keys or trust JWT-supplied alg, jku, jwk, or x5u."""
    try:
        header = jwt.get_unverified_header(token)
    except (InvalidTokenError, TypeError, ValueError):
        _stop()
    if (
        not isinstance(header, dict)
        or set(header) - {"kid", "alg", "typ"}
        or header.get("alg") != "RS256"
        or header.get("typ") not in (None, "JWT")
        or not isinstance(header.get("kid"), str)
        or not _IDENTIFIER.fullmatch(header["kid"])
    ):
        _stop()
    if not isinstance(jwks, Mapping):
        _stop()
    keys = jwks.get("keys")
    if not isinstance(keys, list) or not 1 <= len(keys) <= 16:
        _stop()
    known = set()
    selected = []
    for key in keys:
        if not isinstance(key, dict) or not isinstance(key.get("kid"), str):
            _stop()
        kid = key["kid"]
        if kid in known or not _IDENTIFIER.fullmatch(kid):
            _stop()
        known.add(kid)
        if kid == header["kid"]:
            if (
                key.get("kty") != "RSA"
                or key.get("alg", "RS256") != "RS256"
                or key.get("use", "sig") != "sig"
                or key.get("key_ops", ["verify"]) != ["verify"]
                or not isinstance(key.get("n"), str)
                or not isinstance(key.get("e"), str)
                or any(part in key for part in
                       ("d", "p", "q", "dp", "dq", "qi", "oth", "x5u"))
            ):
                _stop()
            selected.append(key)
    if len(selected) != 1:
        _stop()
    try:
        return jwt.algorithms.RSAAlgorithm.from_jwk(selected[0])
    except (TypeError, ValueError, InvalidTokenError):
        _stop()


def verify_id_token(
    token: str, *, trust: OidcTrust, nonce: str, trusted_jwks: Mapping,
) -> SignedIdentity:
    """Validate an ID token from pretrusted issuer-bound JWKS, NOT an access token.

    A future G2 backend must separately implement trusted JWKS acquisition,
    rotation, code redemption, signed state storage, session and CSRF handling.
    """
    if not isinstance(token, str) or not 0 < len(token) <= 16384:
        _stop()
    if not isinstance(nonce, str) or len(nonce) < 32:
        _stop()
    key = _trusted_rsa_key(token, trusted_jwks)
    try:
        claims = jwt.decode(
            token, key, algorithms=["RS256"],
            issuer=trust.issuer, audience=trust.client_id,
            options={"require": ["iss", "sub", "aud", "exp", "iat", "nonce"]},
            leeway=0,
        )
    except (InvalidTokenError, TypeError, ValueError):
        _stop()
    if not isinstance(claims, dict):
        _stop()
    aud = claims.get("aud")
    azp = claims.get("azp")
    sub = claims.get("sub")
    if (
        not isinstance(sub, str) or not _SUBJECT.fullmatch(sub)
        or type(claims.get("iat")) is not int
        or type(claims.get("exp")) is not int
        or ("nbf" in claims and type(claims["nbf"]) is not int)
        or not isinstance(claims.get("nonce"), str)
        or not secrets.compare_digest(claims["nonce"], nonce)
        or (azp is not None and azp != trust.client_id)
        or not isinstance(aud, (str, list))
        or (isinstance(aud, list) and (
            any(not isinstance(item, str) for item in aud)
            or (len(aud) > 1 and azp != trust.client_id)
        ))
    ):
        _stop()
    # Signed email, external roles and IdP groups are never local grants.
    return SignedIdentity(trust.issuer, sub, trust.client_id)


def require_existing_local_admin(
    identity: SignedIdentity, *,
    links: Sequence[ApprovedLink], users: Mapping[int, LocalAdmin],
) -> LocalAdmin:
    """No JIT provisioning, email-only link, product role or org inheritance."""
    if (
        not isinstance(identity, SignedIdentity)
        or not isinstance(links, Sequence)
        or not isinstance(users, Mapping)
    ):
        _stop()
    matches = [
        link for link in links
        if isinstance(link, ApprovedLink)
        and link.issuer == identity.issuer
        and link.subject == identity.subject
    ]
    if len(matches) != 1 or matches[0].explicitly_verified is not True:
        _stop()
    user = users.get(matches[0].local_user_id)
    if (
        not isinstance(user, LocalAdmin)
        or type(user.id) is not int or user.id < 1
        or user.id != matches[0].local_user_id
        or user.active is not True
        or user.must_change_password is not False
        or user.role not in ("superadmin", "admin")
        or (user.role == "superadmin" and user.organization_id is not None)
        or (user.role == "admin"
            and (type(user.organization_id) is not int or user.organization_id < 1))
    ):
        _stop()
    return user
