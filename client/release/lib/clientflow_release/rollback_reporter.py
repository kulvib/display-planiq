"""Explicit, retry-safe authenticated reporting of a completed local rollback.

The reporting CLI is deliberately separate from the privileged activation.
Failure or loss of connectivity can never undo a successfully committed local
rollback. Audit remains pending on the backend until authenticated reporting.
"""
from __future__ import annotations

from pathlib import Path
import uuid

from .transaction import Layout, TransactionError, TransactionLock, load_state
from .updater_config import UpdaterConfig
from .updater_transport import UpdaterTransport


def report_completed_rollback(permit_id: str, *, layout: Layout = Layout(), transport=None) -> dict:
    try:
        permit_id = str(uuid.UUID(str(permit_id)))
    except ValueError as exc:
        raise TransactionError("Rollback permit-ID er ugyldigt") from exc
    with TransactionLock(layout):
        state = load_state(layout)
        complete = next((entry for entry in reversed(state.get("history", []))
                         if entry.get("event") == "manual_rollback"
                         and entry.get("permit_id") == permit_id), None)
        if complete is None:
            raise TransactionError("Rollback-permit har ikke en afsluttet lokal transaktion")
        if state.get("used_rollback_permits", {}).get(permit_id) != complete.get("to_release_id"):
            raise TransactionError("Rollback-permit matcher ikke lokal forbrugsjournal")
        # This is an observation. The backend will independently compare its
        # current Status version and authenticated Update credential.
        occurred_at = complete.get("at")
        target = complete.get("to_release_id")
    config = UpdaterConfig.from_paths(
        credential_file=layout.path("/etc/clientflow/update/credential.json"),
        private_key=layout.path("/etc/clientflow/update/private-key.pem"),
        state_root=layout.path("/var/lib/clientflow/updater"),
    ) if transport is None else None
    sender = transport or UpdaterTransport(config)
    access_token = sender.issue_access_token()
    event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "planiq-clientflow-rollback-succeeded:" + permit_id))
    response = sender._json_request(
        method="POST",
        path=f"/api/clientflow-update/rollback-permits/{permit_id}/events",
        access_token=access_token,
        payload={"event_id": event_id, "outcome": "succeeded", "occurred_at": occurred_at},
    )
    if not isinstance(response, dict) or response.get("status") != "succeeded":
        raise TransactionError("Backend bekræftede ikke den rapporterede rollback")
    return {"permit_id": permit_id, "target": target, "backend": "succeeded", "replayed": response.get("replayed")}
