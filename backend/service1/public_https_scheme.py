"""Restore the public HTTPS scheme for a pinned external API hostname.

Render terminates TLS and connects to the single-node Uvicorn process over
HTTP. The single-node instance intentionally does not trust arbitrary forwarded
headers: a forwarded-allow-ips='*' setting would let non-proxy peers spoof
client addresses and schemes. Instead, when explicitly configured at startup,
we pin the HTTPS scheme only for the *exact* public API Host served by Render.

This restores the request URL used by Starlette redirects and the existing
strict ClientFlow DPoP `htu` validator. It never reads X-Forwarded-* headers.
"""
from __future__ import annotations

import re
from typing import Any, Awaitable, Callable


_PUBLIC_DNS_HOST = re.compile(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?\Z")


class PinnedPublicHttpsScheme:
    def __init__(self, app: Callable[..., Awaitable[Any]], *, public_hostname: str) -> None:
        host = public_hostname.strip().lower()
        if (
            not host
            or len(host) > 253
            or not _PUBLIC_DNS_HOST.fullmatch(host)
            or ".." in host
            or host.startswith(".")
            or host.endswith(".")
        ):
            raise ValueError("DISPLAY_PUBLIC_HTTPS_HOST must be one DNS hostname without scheme or port")
        self.app = app
        self.public_hostname = host

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        # Reject ambiguous/forged Host values for the scheme override.  Do not
        # use the untrusted X-Forwarded-Host or X-Forwarded-Proto headers.
        hosts = [value for name, value in scope.get("headers", []) if name.lower() == b"host"]
        if len(hosts) == 1:
            host = hosts[0].decode("latin-1").lower()
            if host in {self.public_hostname, f"{self.public_hostname}:443"}:
                expected = "https" if scope["type"] == "http" else "wss"
                if scope.get("scheme") != expected:
                    scope = {**scope, "scheme": expected}

        await self.app(scope, receive, send)
