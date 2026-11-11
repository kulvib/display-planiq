"""One-time, fail-closed 1244 reset of TWO obsolete ClientFlow identities.

Only the old backend client IDs 1/2 may be retired. No hard-delete,
no re-enrollment of those identities, no credential plaintext, and no
change to release artifacts. Caller owns the DB transaction.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import uuid

from sqlalchemy import Column, DateTime, Integer, JSON, MetaData, String, Table, Boolean, insert, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection

TARGETS = {1: "Heidi1", 2: "Viborg2"}
TOMBSTONE_REASON = "clientflow_1244_identity_decommissioned"
APPROVAL_REFERENCE = "CF-1244-OLD-IDENTITY-DECOMMISSION-20261111"
RELEASE_ID = "clientflow-1.3.43-seq-1244"
RELEASE_SHA256 = "d3fdae8fb2a93f74431780f4aadde21625d10917e99cfbe6095ff2394e1e856b"
RELEASE_SIZE = 223610880
CATALOG_PATH = Path(__file__).with_name("clientflow_release_catalog.json")

metadata = MetaData()
json_type = JSON().with_variant(JSONB(), "postgresql")


def _event_table(name: str, session_column: str) -> Table:
    return Table(
        name, metadata,
        Column("id", String(36)), Column(session_column, String(36)),
        Column("event_type", String(80)), Column("actor_user_id", Integer),
        Column("credential_id", String(36)), Column("created_at", DateTime),
        Column("details", json_type),
    )


TERMINAL_EVENTS = _event_table("terminal_session_event", "terminal_session_id")
REMOTE_EVENTS = _event_table("remote_desktop_session_event", "remote_desktop_session_id")
AUDIT_LOG = Table(
    "audit_logs", metadata,
    Column("created_at", DateTime), Column("action", String(100)),
    Column("status", String(40)), Column("actor_username", String),
    Column("actor_role", String), Column("entity_type", String),
    Column("entity_id", Integer), Column("entity_label", String),
    Column("target_organization_id", Integer), Column("severity", String(20)),
    Column("is_critical", Boolean), Column("details", JSON),
)


class IdentityResetDenied(RuntimeError):
    """A precondition failed; transaction must roll back without partial revocation."""


def require_1244_paused(catalog_path: Path = CATALOG_PATH) -> None:
    if os.environ.get("CLIENTFLOW_FRESH_INSTALL_SUSPENDED") != "1":
        raise IdentityResetDenied("Fresh-install suspension must remain enabled")
    if any(os.environ.get(flag) for flag in (
        "CLIENTFLOW_1241_PILOT_CLIENT_ID", "CLIENTFLOW_1242_PILOT_CLIENT_ID",
        "CLIENTFLOW_1243_PILOT_CLIENT_ID",
    )):
        raise IdentityResetDenied("Historical pilot flags must all be unset")
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise IdentityResetDenied("Cannot verify deployed release catalog") from exc
    releases = catalog.get("releases")
    if (
        catalog.get("catalog_sequence") != 1244
        or catalog.get("latest_stable") != "1.3.43"
        or catalog.get("default_install_version") != "1.3.43"
        or not isinstance(releases, list) or len(releases) != 1
        or releases[0].get("release_id") != RELEASE_ID
        or releases[0].get("installable") is not True
        or releases[0].get("install_modes") != ["fresh_install"]
        or releases[0].get("update_allowed") is not False
        or releases[0].get("rollback_allowed") is not False
    ):
        raise IdentityResetDenied("The deployed 1244-only fresh-install catalog is required")
    if RELEASE_SHA256 not in " ".join(releases[0].get("notes") or []):
        raise IdentityResetDenied("Expected approved 1244 bundle SHA is missing from catalog")


def _rows(conn: Connection, sql: str, **params) -> list:
    return conn.execute(text(sql), params).mappings().all()


def _count(conn: Connection, table: str, condition: str = "1=1") -> int:
    # Only constant internal SQL fragments are used at call sites.
    return int(conn.execute(text(
        f"SELECT COUNT(*) FROM {table} WHERE {condition}"
    )).scalar_one())


# Pin table names/columns. Do not enumerate arbitrary tables from caller input.
ACTIVE_CREDENTIALS = {
    "client_domain_credential": "revoked_at IS NULL",
    "livestream_v2_credential": "revoked_at IS NULL",
    "terminal_credential": "revoked_at IS NULL",
    "remote_desktop_credential": "revoked_at IS NULL",
    "clientflow_update_credential": "revoked_at IS NULL",
    "client_system_encryption_key": "revoked_at IS NULL",
    "clientflow_update_provisioning_token": "revoked_at IS NULL AND used_at IS NULL",
}
OTHER_ACTIVE = {
    "terminal_session": "status IN ('requested','authorized','connected')",
    "remote_desktop_session": "status IN ('requested','authorized','connected')",
    "root_terminal_grant": "revoked_at IS NULL",
    "clientflow_rollback_permit": "state = 'issued'",
    "client_command": "status IN ('queued','claimed')",
    "livestream_v2_command": "state IN ('queued','leased')",
    "livestream_v2_generation": "state IN ('starting','running','stopping')",
    "livestream_v2_viewer": "ended_at IS NULL",
    "client_enrollment_receipt": "expires_at > CURRENT_TIMESTAMP",
}


def snapshot(conn: Connection, *, lock: bool = False) -> dict:
    suffix = " FOR UPDATE" if lock and conn.dialect.name == "postgresql" else ""
    clients = _rows(conn, (
        "SELECT id,name,status,deleted_at,deleted_reason,organization_id,client_token_version, "
        "client_secret_hash,client_secret_revoked_at "
        f"FROM client WHERE id IN (1,2) ORDER BY id{suffix}"
    ))
    if len(clients) != 2 or {row["id"]: row["name"] for row in clients} != TARGETS:
        raise IdentityResetDenied("Exact old client IDs/names are not present: aborting")
    tombstones = [
        row["status"] == "deleted" and row["deleted_at"] is not None
        and row["deleted_reason"] == TOMBSTONE_REASON for row in clients
    ]
    if not (all(tombstones) or not any(tombstones)):
        raise IdentityResetDenied("Partial or unexpected prior reset: operator review required")
    if not all(tombstones) and any(
        row["status"] != "approved" or row["deleted_at"] is not None for row in clients
    ):
        raise IdentityResetDenied("One or both clients are not approved/active as expected")
    global_open_deployments = _count(conn, "clientflow_deployment", "completed_at IS NULL")
    global_open_enrollments = _count(
        conn, "enrollmenttoken",
        "used_at IS NULL AND revoked_at IS NULL AND expires_at > CURRENT_TIMESTAMP",
    )
    if global_open_deployments or global_open_enrollments:
        raise IdentityResetDenied("Open deployments or enrollment tokens exist: aborting")

    active = {
        table: _count(conn, table, "client_id IN (1,2) AND " + condition)
        for table, condition in {**ACTIVE_CREDENTIALS, **OTHER_ACTIVE}.items()
    }
    active["client_legacy_secret"] = sum(
        row["client_secret_hash"] is not None and row["client_secret_revoked_at"] is None
        for row in clients
    )
    isolated_statuses = {}
    for table in ("terminal_client", "remote_desktop_client"):
        rows = _rows(conn, f"SELECT id,status FROM {table} WHERE id IN (1,2) ORDER BY id")
        if [row["id"] for row in rows] != [1, 2]:
            raise IdentityResetDenied("Missing isolated domain identity")
        isolated_statuses[table] = [row["status"] for row in rows]
    if all(tombstones) and any(statuses != ["disabled", "disabled"] for statuses in isolated_statuses.values()):
        raise IdentityResetDenied("Isolated domain identity was not disabled")
    if not any(tombstones) and any(statuses != ["approved", "approved"] for statuses in isolated_statuses.values()):
        raise IdentityResetDenied("Unexpected isolated domain identity status")
    # Do not infer a live client from stale DB last_seen; physical wipe is an
    # independently asserted operator precondition at the command boundary.
    if all(tombstones) and any(active.values()):
        raise IdentityResetDenied("Tombstoned client still has active authority")
    return {
        "client_ids": [row["id"] for row in clients],
        "client_names": [row["name"] for row in clients],
        "already_decommissioned": all(tombstones),
        "global_open_enrollments": global_open_enrollments,
        "global_open_deployments": global_open_deployments,
        "active_before_or_remaining": active,
        "isolated_domain_statuses": isolated_statuses,
        "phase": "read_only" if not lock else "locked_preflight",
    }


def _run(conn: Connection, statement: str, now: datetime) -> int:
    return conn.execute(text(statement), {"now": now}).rowcount


def _append_session_events(conn: Connection, table: Table, session_field: str, session_ids: list[str], now: datetime) -> None:
    for session_id in session_ids:
        conn.execute(insert(table).values(
            id=str(uuid.uuid4()), **{session_field: session_id},
            event_type="revoked", actor_user_id=None, credential_id=None,
            created_at=now, details={"reason": TOMBSTONE_REASON},
        ))


def decommission(conn: Connection) -> dict:
    """MUST be called within one caller-owned DB transaction; no commit here."""
    before = snapshot(conn, lock=True)
    if before["already_decommissioned"]:
        return {"already_decommissioned": True, "modified": False, "before": before}
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # Status and hash revocation are in the SAME transaction. This makes all
    # previously issued short-lived access tokens unusable after commit.
    _run(conn, """
        UPDATE client SET status='deleted', deleted_at=:now,
          deleted_reason='clientflow_1244_identity_decommissioned',
          deleted_previous_status=NULL, restored_at=NULL, restored_by_user_id=NULL,
          client_secret_hash=NULL, client_secret_revoked_at=:now,
          client_token_version=client_token_version+1,
          pending_chrome_action='NONE', pending_chrome_action_source=NULL
        WHERE id IN (1,2)
    """, now)
    # These two isolated identities have their own approval boundary.
    _run(conn, "UPDATE terminal_client SET status='disabled' WHERE id IN (1,2)", now)
    _run(conn, "UPDATE remote_desktop_client SET status='disabled' WHERE id IN (1,2)", now)

    for table in ("client_domain_credential", "terminal_credential", "remote_desktop_credential", "livestream_v2_credential"):
        _run(conn, f"UPDATE {table} SET revoked_at=:now, token_version=token_version+1 "
             "WHERE client_id IN (1,2) AND revoked_at IS NULL", now)
    for table in ("clientflow_update_credential", "client_system_encryption_key"):
        _run(conn, f"UPDATE {table} SET revoked_at=:now "
             "WHERE client_id IN (1,2) AND revoked_at IS NULL", now)
    _run(conn, "UPDATE clientflow_update_provisioning_token SET revoked_at=:now "
         "WHERE client_id IN (1,2) AND used_at IS NULL AND revoked_at IS NULL", now)
    # Revocation of old enrollment resume receipts, preserving their rows.
    _run(conn, "UPDATE client_enrollment_receipt SET expires_at=CURRENT_TIMESTAMP "
         "WHERE client_id IN (1,2) AND expires_at>CURRENT_TIMESTAMP", now)
    _run(conn, "UPDATE root_terminal_grant SET revoked_at=:now "
         "WHERE client_id IN (1,2) AND revoked_at IS NULL", now)
    _run(conn, "UPDATE clientflow_rollback_permit SET state='revoked', revoked_at=:now "
         "WHERE client_id IN (1,2) AND state='issued'", now)

    terminal_ids = [row["id"] for row in _rows(conn, """
        UPDATE terminal_session SET status='revoked',
          disconnected_at=COALESCE(disconnected_at,:now),last_activity_at=:now
        WHERE client_id IN (1,2) AND status IN ('requested','authorized','connected')
        RETURNING id
    """, now=now)]
    rd_ids = [row["id"] for row in _rows(conn, """
        UPDATE remote_desktop_session SET status='revoked',
          disconnected_at=COALESCE(disconnected_at,:now),last_activity_at=:now,
          close_reason='clientflow_1244_identity_decommissioned'
        WHERE client_id IN (1,2) AND status IN ('requested','authorized','connected')
        RETURNING id
    """, now=now)]
    _append_session_events(conn, TERMINAL_EVENTS, "terminal_session_id", terminal_ids, now)
    _append_session_events(conn, REMOTE_EVENTS, "remote_desktop_session_id", rd_ids, now)

    _run(conn, "UPDATE client_command SET status='cancelled',completed_at=:now, "
         "end_reason='client_decommissioned' WHERE client_id IN (1,2) AND status IN ('queued','claimed')", now)
    _run(conn, "UPDATE livestream_v2_command SET state='cancelled',completed_at=:now,updated_at=:now "
         "WHERE client_id IN (1,2) AND state IN ('queued','leased')", now)
    _run(conn, "UPDATE livestream_v2_generation SET state='stopped',stopped_at=:now "
         "WHERE client_id IN (1,2) AND state IN ('starting','running','stopping')", now)
    _run(conn, "UPDATE livestream_v2_viewer SET ended_at=:now,end_reason='decommissioned' "
         "WHERE client_id IN (1,2) AND ended_at IS NULL", now)

    # Audit rows intentionally preserve old Client IDs, names and organization
    # but never record any secret, password, token hash or encryption key.
    for old_id, name in TARGETS.items():
        organization_id = conn.execute(text("SELECT organization_id FROM client WHERE id=:id"), {"id":old_id}).scalar_one()
        conn.execute(insert(AUDIT_LOG).values(
            created_at=now, action="clientflow_1244_old_identity_decommissioned",
            status="success", actor_username="render_shell_operator",
            actor_role="system", entity_type="client", entity_id=old_id,
            entity_label=name, target_organization_id=organization_id,
            severity="critical", is_critical=True,
            details={"reason":TOMBSTONE_REASON, "approval_reference":APPROVAL_REFERENCE,
                     "fresh_install_version":"1.3.43", "new_identity_required":True},
        ))
    after = snapshot(conn, lock=False)
    if not after["already_decommissioned"] or any(after["active_before_or_remaining"].values()):
        raise IdentityResetDenied("Postflight authority remains; rolling back entire transaction")
    return {"already_decommissioned": False, "modified": True,
            "before": before, "after": after,
            "revoked_terminal_sessions": len(terminal_ids),
            "revoked_remote_desktop_sessions": len(rd_ids)}
