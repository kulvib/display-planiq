"""Bounded, credential-free SQL/checkout counters for always-on agent routes.

This is diagnostic attribution only: no SQL, authentication or client polling
behavior is modified. One process-local summary is emitted per 15-minute window
when an eligible HTTP request subsequently completes. Aggregation is bounded by
static category labels, never raw URLs, IDs, headers, or SQL parameters.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from threading import Lock
from time import monotonic
from typing import Callable

_LOGGER = logging.getLogger("service1.db_hotpath_telemetry")
WINDOW_SECONDS = 15 * 60


def classify_hotpath(path: str) -> str | None:
    """Map a *path*, never a query string, to a fixed-cardinality category."""
    if path == "/api/clientflow-update/token":
        return "updater_token"
    if path.startswith("/api/clientflow-update/"):
        return "updater_other"
    if path == "/api/terminal-auth/token":
        return "terminal_token"
    if path == "/api/remote-desktop-auth/token":
        return "remote_desktop_token"
    if path == "/api/client-auth/token":
        return "shared_token"
    if path.startswith("/api/terminal-agent/clients/"):
        return "terminal_relay" if "/poll" in path else "terminal_agent"
    if path.startswith("/api/remote-desktop-agent/clients/"):
        return "remote_desktop_relay" if "/poll" in path else "remote_desktop_agent"
    if path.startswith("/api/livestream-agent/clients/"):
        if path.endswith("/presence"):
            return "livestream_presence"
        if path.endswith("/status"):
            return "livestream_status"
        return "livestream_other"
    if path.startswith(("/api/status-agent/clients/", "/api/display-agent/clients/", "/api/system-agent/clients/")):
        if path.endswith("/presence"):
            return "shared_presence"
        if path.endswith("/status"):
            return "shared_status"
        return "shared_other"
    return None


@dataclass
class _Counts:
    requests: int = 0
    failed_http: int = 0
    statements: int = 0
    selects: int = 0
    checkouts: int = 0
    cursor_ms: float = 0.0
    max_statements: int = 0

    def add(self, *, status_code: int, statements: int, selects: int, checkouts: int, cursor_ms: float) -> None:
        self.requests += 1
        self.failed_http += int(status_code >= 400)
        self.statements += statements
        self.selects += selects
        self.checkouts += checkouts
        self.cursor_ms += cursor_ms
        self.max_statements = max(self.max_statements, statements)

    def as_dict(self) -> dict[str, int | float]:
        return {
            "requests": self.requests,
            "failed_http": self.failed_http,
            "statements": self.statements,
            "selects": self.selects,
            "checkouts": self.checkouts,
            "cursor_ms": round(self.cursor_ms, 2),
            "max_statements": self.max_statements,
        }


class HotpathDatabaseTelemetry:
    """Constant-space, process-local accounting with no extra DB operations."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = monotonic,
        interval_seconds: int = WINDOW_SECONDS,
        emit: Callable[[str], None] | None = None,
    ) -> None:
        self._clock = clock
        self._interval_seconds = interval_seconds
        self._emit = emit or (lambda message: _LOGGER.info("db_hotpath_summary %s", message))
        self._lock = Lock()
        self._started = clock()
        self._totals: dict[str, _Counts] = {}

    def record(self, path: str, status_code: int, metrics: object) -> None:
        category = classify_hotpath(path)
        if category is None:
            return
        snapshot = None
        now = self._clock()
        with self._lock:
            if now - self._started >= self._interval_seconds:
                if self._totals:
                    snapshot = json.dumps(
                        {
                            "window_seconds": round(max(0.0, now - self._started)),
                            "categories": {key: value.as_dict() for key, value in sorted(self._totals.items())},
                        },
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                self._totals = {}
                self._started = now
            self._totals.setdefault(category, _Counts()).add(
                status_code=status_code,
                statements=int(getattr(metrics, "statement_count", 0)),
                selects=int(getattr(metrics, "select_count", 0)),
                checkouts=int(getattr(metrics, "checkout_count", 0)),
                cursor_ms=float(getattr(metrics, "duration_ms", 0.0)),
            )
        # Logging happens after releasing the lock, never on the DB hot path.
        if snapshot is not None:
            self._emit(snapshot)


hotpath_database_telemetry = HotpathDatabaseTelemetry()
