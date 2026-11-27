"""Livestream command agent with a generation-owned local lifecycle."""
from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any

from .command_agent import CommandContext, CommandRejected, QueueAgent
from .config import DomainCredential
from .constants import Domain
from .livestream_paths import BROKER_SOCKET, PRODUCER_STATUS_PATH, UPLOADER_STATUS_PATH
from .net import DomainTransport
from .unix_rpc import RpcError, call


class LivestreamHandler:
    def __init__(self, transport: DomainTransport) -> None:
        self.transport = transport

    def _wait_producer(self, generation_id: str, wanted: set[str], timeout: float = 45.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        last: dict[str, Any] = {}
        observed = ""
        while time.monotonic() < deadline:
            try:
                value = json.loads(PRODUCER_STATUS_PATH.read_text(encoding="utf-8"))
                if isinstance(value, dict):
                    last = value
            except (OSError, json.JSONDecodeError):
                pass
            observed = str(last.get("generation_id") or "")
            state = last.get("state")
            # A blank generation is only meaningful for an acknowledged
            # stop, never for a running/start acknowledgement.
            if state in wanted and (observed == generation_id or (state == "stopped" and not observed)):
                return last
            time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
        if observed == generation_id and last.get("state") == "retrying":
            raise CommandRejected(
                "producer_retrying", "Livestream afventer kontrolleret nyt capture-forsøg", retryable=True,
            )
        raise CommandRejected("producer_timeout", f"Livestreamproducer nåede ikke {sorted(wanted)}", retryable=True)

    def __call__(self, context: CommandContext) -> dict[str, Any]:
        client_id = self.transport.credential.client_id
        try:
            if context.command_type in {"start", "restart", "reset_generation"}:
                generation_id = str(context.payload.get("generation_id") or "")
                if not generation_id:
                    raise CommandRejected("missing_generation", "Livestreamkommandoen mangler generation_id")
                call(BROKER_SOCKET, {"action": context.command_type, "generation_id": generation_id})
                # The producer owns local retry/backoff. A transient failed
                # or retrying snapshot is not the final command outcome.
                # Wait within the existing 45s lease-backed command budget;
                # a fast local retry can finish without a new backend claim.
                status = self._wait_producer(generation_id, {"running"})
                generation = self.transport.json_request(
                    "POST",
                    f"/api/livestream-agent/clients/{client_id}/generations/{generation_id}/started",
                    json_body={},
                )
                return {"generation": generation, "producer": status}
            if context.command_type == "stop":
                desired = call(BROKER_SOCKET, {"action": "stop"})
                generation_id = str(desired.get("generation_id") or "")
                if generation_id:
                    self._wait_producer(generation_id, {"stopped"})
                    generation = self.transport.json_request(
                        "POST",
                        f"/api/livestream-agent/clients/{client_id}/generations/{generation_id}/stopped",
                        json_body={"error_code": None},
                    )
                else:
                    generation = None
                return {"generation": generation, "stopped": True}
        except RpcError as exc:
            raise CommandRejected("livestream_broker_error", str(exc), retryable=True) from exc
        raise CommandRejected("unsupported_livestream_command", "Ukendt livestreamkommando")


def _read_status(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def main() -> int:
    credential = DomainCredential.load(Domain.LIVESTREAM)
    transport = DomainTransport(credential)
    QueueAgent(
        transport,
        LivestreamHandler(transport),
        status_payload=lambda: {
            "producer": _read_status(PRODUCER_STATUS_PATH),
            "uploader": _read_status(UPLOADER_STATUS_PATH),
        },
    ).run_forever()
    return 0
