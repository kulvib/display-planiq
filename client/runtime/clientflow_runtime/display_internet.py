"""Non-blocking, fail-closed internet availability gate for Chrome only.

A validated HTTPS response from either the PlanIQ backend or the kiosk site's
own HTTPS origin proves an external route, DNS resolution, and TLS trust.
Neither the Display control socket nor the local GUI depends on this probe.
"""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, HTTPSHandler
import ssl
import time

BACKEND_PROBE_URL = "https://api.display.planiq.dk/health"
CHECK_INTERVAL_SECONDS = 10.0
LOSS_GRACE_SECONDS = 20.0
RECOVERY_CONFIRM_SECONDS = 10.0
REQUEST_TIMEOUT_SECONDS = 2.5


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _kiosk_origin(kiosk_url: str | None) -> str | None:
    parsed = urlsplit(kiosk_url or "")
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    # Do not probe the kiosk path: it can contain tokens or client identifiers.
    return f"https://{parsed.netloc}/"


def probe_internet(kiosk_url: str | None) -> bool:
    """Never follow redirects or accept plaintext HTTP as evidence of internet."""
    origins = [BACKEND_PROBE_URL]
    kiosk_origin = _kiosk_origin(kiosk_url)
    if kiosk_origin and kiosk_origin not in origins:
        origins.append(kiosk_origin)
    opener = build_opener(_NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    for url in origins:
        try:
            with opener.open(
                Request(url, method="HEAD", headers={"User-Agent": "ClientFlow-Display-Connectivity/1"}),
                timeout=REQUEST_TIMEOUT_SECONDS,
            ) as response:
                if 200 <= int(response.status) < 500:
                    return True
        except HTTPError as exc:
            # 3xx/4xx HTTPS replies (including HEAD-not-allowed) prove that
            # the expected remote origin was reached with a validated TLS cert.
            if 300 <= exc.code < 500 and exc.code != 407:
                exc.close()
                return True
            exc.close()
        except (OSError, URLError, TimeoutError, ssl.SSLError, ValueError):
            continue
    return False


class InternetMonitor:
    """Hysteretic link-independent monitor; only its worker performs I/O."""

    def __init__(self) -> None:
        self.online = False
        self.state = "checking"
        self.last_checked_at: float | None = None
        self._future: Future[bool] | None = None
        self._next_check = 0.0
        self._success_since: float | None = None
        self._failure_since: float | None = None

    def tick(self, executor: ThreadPoolExecutor, kiosk_url: str | None, *, now: float | None = None) -> bool:
        """Return True iff effective online/offline state changed."""
        current = time.monotonic() if now is None else now
        previous = self.state
        if self._future is not None and self._future.done():
            try:
                successful = bool(self._future.result())
            except Exception:
                successful = False
            self._future = None
            self.last_checked_at = time.time()
            if successful:
                self._failure_since = None
                if self._success_since is None:
                    self._success_since = current
                if current - self._success_since >= RECOVERY_CONFIRM_SECONDS:
                    self.online = True
                    self.state = "online"
                elif not self.online:
                    self.state = "checking"
            else:
                self._success_since = None
                if self._failure_since is None:
                    self._failure_since = current
                if not self.online or current - self._failure_since >= LOSS_GRACE_SECONDS:
                    self.online = False
                    self.state = "offline"
        # Never spawn overlapping checks or block the control socket.
        if self._future is None and current >= self._next_check:
            self._future = executor.submit(probe_internet, kiosk_url)
            self._next_check = current + CHECK_INTERVAL_SECONDS
        return previous != self.state
