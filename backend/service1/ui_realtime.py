"""DB-free browser wake channel for Control Room live state.

A short-lived capability is issued after normal application authentication. The
capability carries only scope metadata and lets the browser block on a process-
local generation without holding a PostgreSQL session. The wake carries no
client data; authoritative snapshots are still fetched through normal protected
HTTP endpoints after a change.
"""
from __future__ import annotations

from collections import defaultdict
import asyncio
from datetime import datetime, timedelta, timezone
import os
import threading
import time
import uuid
from typing import Any

import jwt
from fastapi import HTTPException, status

from .auth import SECRET_KEY
from .realtime_wakeup import (
    RELEASE_ADMIN_WAKE_DOMAIN, RELEASE_ADMIN_WAKE_KEY,
    current_generation as wake_generation, wait_for_change, wait_for_change_async,
)

ISSUER = "clientflow-ui-realtime"
AUDIENCE = "clientflow-ui-realtime"
TTL_SECONDS = min(max(120, int(os.getenv("CLIENTFLOW_UI_REALTIME_CAPABILITY_TTL_SECONDS", "300"))), 900)
_CONDITION = threading.Condition()
_GLOBAL_GENERATION = 0
_ORG_GENERATIONS: dict[int, int] = defaultdict(int)
_CLIENT_GENERATIONS: dict[int, int] = defaultdict(int)
_UI_ASYNC_WAITERS: dict[
    tuple[str, int], set[tuple[asyncio.AbstractEventLoop, asyncio.Future[None]]]
] = defaultdict(set)


def _wake_scope(*, global_scope: bool, organization_id: int | None, client_id: int | None) -> tuple[str, int]:
    if client_id is not None:
        return ("client", int(client_id))
    if global_scope:
        return ("global", 0)
    if organization_id is None:
        raise ValueError("organization_id kræves for organisationsscope")
    return ("organization", int(organization_id))


def _take_ui_waiters(scopes: set[tuple[str, int]]):
    # Caller holds the same condition lock used by generation snapshots.
    return tuple(listener for scope in scopes for listener in _UI_ASYNC_WAITERS.pop(scope, ()))


def _resolve_ui_waiter(waiter: asyncio.Future[None]) -> None:
    if not waiter.done():
        waiter.set_result(None)


def _publish_ui_waiters(listeners) -> None:
    for loop, waiter in listeners:
        try:
            loop.call_soon_threadsafe(_resolve_ui_waiter, waiter)
        except RuntimeError:
            # Closed event loop; reconciliation remains authoritative.
            pass


def _scope_for_principal(principal: object) -> tuple[bool, int | None]:
    is_global = bool(getattr(principal, "is_superadmin", False) or getattr(principal, "role", None) == "viewer")
    organization_id = getattr(principal, "organization_id", None)
    if not is_global and organization_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Realtime-scope mangler organisation")
    return is_global, int(organization_id) if organization_id is not None else None


def current_generation(
    *, global_scope: bool, organization_id: int | None, client_id: int | None = None
) -> int:
    with _CONDITION:
        if client_id is not None:
            return int(_CLIENT_GENERATIONS[int(client_id)])
        if global_scope:
            return int(_GLOBAL_GENERATION)
        if organization_id is None:
            raise ValueError("organization_id kræves for organisationsscope")
        return int(_ORG_GENERATIONS[int(organization_id)])


def notify_ui_state_changed(
    *, organization_id: int | None, client_id: int | None = None
) -> int:
    global _GLOBAL_GENERATION
    with _CONDITION:
        _GLOBAL_GENERATION += 1
        scopes = {("global", 0)}
        if client_id is not None:
            _CLIENT_GENERATIONS[int(client_id)] += 1
            scopes.add(("client", int(client_id)))
        if organization_id is not None:
            _ORG_GENERATIONS[int(organization_id)] += 1
            scopes.add(("organization", int(organization_id)))
            generation = int(_ORG_GENERATIONS[int(organization_id)])
        else:
            generation = int(_GLOBAL_GENERATION)
        listeners = _take_ui_waiters(scopes)
        _CONDITION.notify_all()
    _publish_ui_waiters(listeners)
    return generation


def notify_ui_fleet_order_changed(organization_ids: set[int]) -> int:
    """One fleet invalidation after commit, including organization-scoped lists.

    Ordering is global for superadmins, but organization admins read their own
    authorized Control Room projection. Wake all affected scopes without one
    notification (or database request) per client.
    """
    global _GLOBAL_GENERATION
    with _CONDITION:
        _GLOBAL_GENERATION += 1
        for organization_id in organization_ids:
            _ORG_GENERATIONS[int(organization_id)] += 1
        generation = int(_GLOBAL_GENERATION)
        listeners = _take_ui_waiters({("global", 0)} | {("organization", int(oid)) for oid in organization_ids})
        _CONDITION.notify_all()
    _publish_ui_waiters(listeners)
    return generation


def issue_ui_realtime_capability(
    principal: object, *, client_id: int | None = None, release_admin: bool = False
) -> dict[str, Any]:
    if release_admin and (not getattr(principal, "is_superadmin", False) or client_id is not None):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Releaseadministration kræver superadministrator")
    global_scope, organization_id = _scope_for_principal(principal)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=TTL_SECONDS)
    principal_id = getattr(principal, "id", None)
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": f"ui-realtime:{principal_id}",
        "purpose": "ui_realtime_wait",
        "principal_id": str(principal_id),
        "global_scope": global_scope,
        "organization_id": organization_id,
        # Server-side authorization for a client scope is required at issuance.
        # The wait endpoint intentionally needs no database session.
        "client_id": client_id,
        "release_admin": release_admin,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(claims, SECRET_KEY, algorithm="HS256")
    return {
        "capability": token,
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        "ttl_seconds": TTL_SECONDS,
        "generation": (
            wake_generation(RELEASE_ADMIN_WAKE_DOMAIN, RELEASE_ADMIN_WAKE_KEY)
            if release_admin else current_generation(
                global_scope=global_scope, organization_id=organization_id, client_id=client_id
            )
        ),
    }


def verify_ui_realtime_capability(token: str | None) -> dict[str, Any]:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Realtime-capability mangler")
    try:
        claims = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=["HS256"],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "nbf", "jti", "sub", "purpose", "principal_id"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ugyldig realtime-capability") from exc
    if claims.get("purpose") != "ui_realtime_wait":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forkert realtime-capability")
    if not bool(claims.get("global_scope")) and claims.get("organization_id") is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Realtime-capability mangler scope")
    scoped_client = claims.get("client_id")
    if scoped_client is not None and (type(scoped_client) is not int or scoped_client <= 0):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ugyldigt realtime-klientscope")
    if claims.get("release_admin") is True and (not claims.get("global_scope") or scoped_client is not None):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ugyldigt releaseadministrationsscope")
    return claims


def wait_for_ui_change(*, claims: dict[str, Any], after: int, timeout: float) -> int:
    if claims.get("release_admin") is True:
        return wait_for_change(RELEASE_ADMIN_WAKE_DOMAIN, RELEASE_ADMIN_WAKE_KEY, after, timeout)
    global_scope = bool(claims.get("global_scope"))
    organization_id = claims.get("organization_id")
    organization_id = int(organization_id) if organization_id is not None else None
    client_id = claims.get("client_id")
    deadline = time.monotonic() + min(max(float(timeout), 0.0), 30.0)
    with _CONDITION:
        while (
            current_generation(
                global_scope=global_scope, organization_id=organization_id, client_id=client_id
            )
            <= int(after)
        ):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            _CONDITION.wait(timeout=remaining)
        return current_generation(
            global_scope=global_scope, organization_id=organization_id, client_id=client_id
        )


async def wait_for_ui_change_async(*, claims: dict[str, Any], after: int, timeout: float) -> int:
    """Scoped, DB-free long poll without reserving a request worker thread.

    Register atomically with the generation snapshot. Wake only the affected
    scopes, release waiters on timeout/cancellation, and keep the existing
    capability and generation protocol unchanged.
    """
    bounded_timeout = min(max(float(timeout), 0.0), 30.0)
    if claims.get("release_admin") is True:
        return await wait_for_change_async(RELEASE_ADMIN_WAKE_DOMAIN, RELEASE_ADMIN_WAKE_KEY, after, bounded_timeout)

    global_scope = bool(claims.get("global_scope"))
    organization_id = claims.get("organization_id")
    organization_id = int(organization_id) if organization_id is not None else None
    client_id = claims.get("client_id")
    scope = _wake_scope(global_scope=global_scope, organization_id=organization_id, client_id=client_id)

    def generation() -> int:
        return current_generation(global_scope=global_scope, organization_id=organization_id, client_id=client_id)

    loop = asyncio.get_running_loop()
    waiter: asyncio.Future[None] = loop.create_future()
    subscription = (loop, waiter)
    with _CONDITION:
        observed = generation()
        if observed > int(after) or bounded_timeout <= 0:
            return observed
        _UI_ASYNC_WAITERS[scope].add(subscription)
    try:
        try:
            await asyncio.wait_for(waiter, timeout=bounded_timeout)
        except asyncio.TimeoutError:
            pass
    finally:
        with _CONDITION:
            subscribers = _UI_ASYNC_WAITERS.get(scope)
            if subscribers is not None:
                subscribers.discard(subscription)
                if not subscribers:
                    _UI_ASYNC_WAITERS.pop(scope, None)
    return generation()
