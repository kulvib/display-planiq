"""Best-effort Display countdown transition reporting without tick-by-tick requests.

The Display runtime updates its local JSON file every second, even while the
Display command agent is blocked in a synchronous runtime RPC. This watcher
observes that file, not the database, and emits *at most* one status at the
start and one when the runtime leaves a countdown. Durable periodic reporting
remains the authority if either edge is missed or the network is unavailable.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from pathlib import Path
from typing import Any, Callable


POLL_SECONDS = 0.5
MAX_COUNTDOWN_SECONDS = 10


def _countdown_token(runtime: dict[str, Any], *, now: float) -> str | None:
    if str(runtime.get("state") or "").lower() != "countdown":
        return None
    try:
        started = float(runtime["countdown_started_at"])
        total = runtime["countdown_total_seconds"]
        remaining = runtime["countdown_remaining"]
        updated = float(runtime["updated_at"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if type(total) is not int or type(remaining) is not int:
        return None
    if not (1 <= total <= MAX_COUNTDOWN_SECONDS and 1 <= remaining <= total):
        return None
    if not all(math.isfinite(value) for value in (started, updated)):
        return None
    # Fail closed for stale/future local state (including across service restarts).
    if started > now + 1 or started + total < now - 1:
        return None
    if updated > now + 1 or updated < started or updated > started + total + 1:
        return None
    return str(started)


def _read_runtime(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


class CountdownStatusBridge:
    """Track transition identity; never report 10 separate countdown ticks."""

    def __init__(
        self,
        status_path: Path,
        notify: Callable[[str, str], None],
        *,
        logger: logging.Logger,
        now: Callable[[], float] = time.time,
        poll_seconds: float = POLL_SECONDS,
    ) -> None:
        self.status_path = status_path
        self.notify = notify
        self.logger = logger
        self.now = now
        self.poll_seconds = max(0.2, poll_seconds)
        self._active: str | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="display-countdown-bridge")

    def inspect_once(self) -> None:
        runtime = _read_runtime(self.status_path)
        if runtime is None:
            # A partially written/unavailable file is not evidence of completion.
            return
        token = _countdown_token(runtime, now=self.now())
        if token is not None:
            if token != self._active:
                self._active = token  # Record before sending; failed sends never cause a request storm.
                self._notify("started", token)
        elif self._active is not None and str(runtime.get("state") or "").lower() != "countdown":
            completed_token = self._active
            self._active = None
            self._notify("finished", completed_token)

    def _notify(self, phase: str, token: str) -> None:
        try:
            self.notify(phase, token)
        except Exception as exc:
            # Edge notifications are best effort; normal agent reporting heals.
            self.logger.warning("countdown_edge_report_failed: %s", type(exc).__name__)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.inspect_once()
            self._stop.wait(self.poll_seconds)

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
