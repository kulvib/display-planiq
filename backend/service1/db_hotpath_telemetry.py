"""Bounded, credential-free DB counters for agent HTTP and socket revocation.

This is diagnostic attribution only: no database I/O or polling schedule is
introduced. A process-local 15-minute summary is emitted when eligible HTTP
or socket work completes. Labels are fixed, never client IDs or SQL parameters.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
import json
import logging
from threading import Lock
from time import monotonic
from typing import Callable

_LOGGER = logging.getLogger("service1.db_hotpath_telemetry")
WINDOW_SECONDS = 15 * 60
# Fixed names only: credential/client identity is never used as a metric label.
WEBSOCKET_RECHECK_CATEGORIES = frozenset({"terminal_ws_recheck", "remote_desktop_ws_recheck"})


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
    websocket_rechecks: int = 0
    failed_websocket_rechecks: int = 0

    def add(self, *, status_code: int, statements: int, selects: int, checkouts: int, cursor_ms: float) -> None:
        self.requests += 1
        self.failed_http += int(status_code >= 400)
        self.statements += statements
        self.selects += selects
        self.checkouts += checkouts
        self.cursor_ms += cursor_ms
        self.max_statements = max(self.max_statements, statements)

    def add_websocket_recheck(
        self, *, authorized: bool, statements: int, selects: int, checkouts: int, cursor_ms: float
    ) -> None:
        self.websocket_rechecks += 1
        self.failed_websocket_rechecks += int(not authorized)
        self.statements += statements
        self.selects += selects
        self.checkouts += checkouts
        self.cursor_ms += cursor_ms
        self.max_statements = max(self.max_statements, statements)

    def as_dict(self) -> dict[str, int | float]:
        result = {
            "requests": self.requests,
            "failed_http": self.failed_http,
            "statements": self.statements,
            "selects": self.selects,
            "checkouts": self.checkouts,
            "cursor_ms": round(self.cursor_ms, 2),
            "max_statements": self.max_statements,
        }
        if self.websocket_rechecks:
            result["websocket_rechecks"] = self.websocket_rechecks
            result["failed_websocket_rechecks"] = self.failed_websocket_rechecks
        return result


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
        if category is not None:
            self._record(category, status_code=status_code, metrics=metrics)

    def record_websocket_recheck(self, category: str, authorized: bool, metrics: object) -> None:
        # A caller cannot inject dynamic client IDs, paths or credentials into labels.
        if category not in WEBSOCKET_RECHECK_CATEGORIES:
            raise ValueError("Unknown fixed WebSocket recheck category")
        self._record(category, authorized=authorized, metrics=metrics)

    def _record(
        self, category: str, *, metrics: object,
        status_code: int | None = None, authorized: bool | None = None,
    ) -> None:
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
            counts = self._totals.setdefault(category, _Counts())
            fields = {
                "statements": int(getattr(metrics, "statement_count", 0)),
                "selects": int(getattr(metrics, "select_count", 0)),
                "checkouts": int(getattr(metrics, "checkout_count", 0)),
                "cursor_ms": float(getattr(metrics, "duration_ms", 0.0)),
            }
            if authorized is not None:
                counts.add_websocket_recheck(authorized=authorized, **fields)
            else:
                assert status_code is not None
                counts.add(status_code=status_code, **fields)
        # Neither logging nor serialization holds the DB pool or telemetry lock.
        if snapshot is not None:
            self._emit(snapshot)


def instrument_websocket_recheck(category: str):
    """Measure persisted socket revocation checks without changing their cadence.

    The existing SQLAlchemy events account for SQL and pool checkouts, even
    though WebSockets do not pass through HTTP observability middleware.
    Exceptions still propagate, and failed revalidations are counted.
    """
    if category not in WEBSOCKET_RECHECK_CATEGORIES:
        raise ValueError("Unknown fixed WebSocket recheck category")

    def decorate(check):
        @wraps(check)
        def measured(*args, **kwargs):
            # Deferred import avoids a module cycle with db.py.
            from .db import begin_database_request_metrics, reset_database_request_metrics

            metrics, token = begin_database_request_metrics()
            authorized = False
            try:
                authorized = bool(check(*args, **kwargs))
                return authorized
            finally:
                reset_database_request_metrics(token)
                try:
                    hotpath_database_telemetry.record_websocket_recheck(
                        category, authorized=authorized, metrics=metrics
                    )
                except Exception as exc:
                    # Observability must never change revocation decisions.
                    _LOGGER.warning(
                        "db_hotpath_ws_metric_failure error_type=%s", type(exc).__name__
                    )

        return measured

    return decorate


hotpath_database_telemetry = HotpathDatabaseTelemetry()
