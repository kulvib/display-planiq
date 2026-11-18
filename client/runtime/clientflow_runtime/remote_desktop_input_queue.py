"""Bounded, ordered input lane which replaces only adjacent pending mouse moves.

Mouse button transitions, scrolling, keystrokes and session lifecycle events
are never coalesced; capacity applies backpressure instead of silently losing
non-replaceable user actions. No credentials or DB are involved.
"""
from __future__ import annotations

import asyncio
from collections import deque
import json
import time
from typing import Awaitable, Callable


def _replaceable_move(raw: str) -> str | None:
    try:
        message = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if isinstance(message, dict) and message.get("type") == "mouse" and message.get("event") == "move":
        return str(message.get("session_id") or "")
    return None


class InputLaneQueue:
    def __init__(
        self,
        process: Callable[[str], Awaitable[None]],
        *,
        max_pending: int = 96,
        on_dequeue: Callable[[str, float], None] | None = None,
    ) -> None:
        if max_pending < 2:
            raise ValueError("Input queue capacity must be >= 2")
        self.process = process
        self.max_pending = max_pending
        self.on_dequeue = on_dequeue
        self.pending: deque[tuple[str, float]] = deque()
        self.condition = asyncio.Condition()
        self.replaced_moves = 0
        self.high_water_mark = 0
        self.failure: Exception | None = None

    async def put(self, raw: str) -> None:
        if not isinstance(raw, str) or len(raw) > 100_000:
            raise RuntimeError("Input lane message is invalid or too large")
        identity = _replaceable_move(raw)
        async with self.condition:
            if self.failure is not None:
                raise RuntimeError("Input lane consumer failed") from self.failure
            # Only adjacent moves within the same session are replaceable;
            # never jump over down/up, key, scroll or close events.
            if identity and self.pending and _replaceable_move(self.pending[-1][0]) == identity:
                self.pending[-1] = (raw, time.monotonic())
                self.replaced_moves += 1
                return
            while len(self.pending) >= self.max_pending:
                await self.condition.wait()
                if self.failure is not None:
                    raise RuntimeError("Input lane consumer failed") from self.failure
                # A consumer may have created a replaceable tail meanwhile.
                if identity and self.pending and _replaceable_move(self.pending[-1][0]) == identity:
                    self.pending[-1] = (raw, time.monotonic())
                    self.replaced_moves += 1
                    return
            self.pending.append((raw, time.monotonic()))
            self.high_water_mark = max(self.high_water_mark, len(self.pending))
            self.condition.notify_all()

    async def run(self) -> None:
        try:
            while True:
                async with self.condition:
                    while not self.pending:
                        await self.condition.wait()
                    raw, queued_at = self.pending.popleft()
                    self.condition.notify_all()
                if self.on_dequeue:
                    self.on_dequeue(raw, max(0, (time.monotonic() - queued_at) * 1000))
                await self.process(raw)
        except Exception as exc:
            async with self.condition:
                self.failure = exc
                self.condition.notify_all()
            raise
