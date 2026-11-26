#!/usr/bin/env python3
"""Read-only 1.4 baseline retirement inventory for Display's Render PostgreSQL.

Run only after publishing and physically accepting 1250. This program never
authorizes deletion: the snapshot cannot prove offline host or local rollback
dependencies, and a later mutation requires a fresh, locked revalidation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from scripts.audit_clientflow_release_retention import inspect_store  # noqa: E402

BASELINE = "clientflow-1.4.0-seq-1250"
MAX_CLIENTS = 1000
DEPENDENCY_QUERIES = {
    "active_deployments": "SELECT count(*) FROM clientflow_deployment WHERE completed_at IS NULL",
    "unacknowledged_recovery_failures": """
        SELECT count(*) FROM clientflow_deployment d
        WHERE d.state = 'recovery_failed' AND NOT EXISTS (
            SELECT 1 FROM clientflow_deployment_event e
            WHERE e.deployment_id = d.id AND e.event_type = 'operator_recovery_acknowledged'
        )""",
    "open_enrollment_tokens": """
        SELECT count(*) FROM enrollmenttoken
        WHERE used_at IS NULL AND revoked_at IS NULL
          AND expires_at > CURRENT_TIMESTAMP AT TIME ZONE 'UTC'""",
    "unfinished_enrollment_receipts": """
        SELECT count(*) FROM client_enrollment_receipt WHERE completed_at IS NULL""",
    "issued_rollback_permits": """
        SELECT count(*) FROM clientflow_rollback_permit WHERE state = 'issued'""",
    "approved_or_running_waves": """
        SELECT count(*) FROM clientflow_rollout_wave WHERE state IN ('approved','running')""",
    "approved_targets": """
        SELECT count(*) FROM clientflow_rollout_target WHERE state = 'approved'""",
}
CLIENT_QUERY = """
    SELECT c.id, c.status, s.agent_version, s.observed_state, s.reported_at,
           cred.id AS active_status_credential_id
    FROM client c
    LEFT JOIN client_domain_status s ON s.client_id = c.id AND s.domain = 'status'
    LEFT JOIN client_domain_credential cred
      ON cred.id = s.credential_id AND cred.client_id = c.id
      AND cred.domain = 'status' AND cred.revoked_at IS NULL
    WHERE c.deleted_at IS NULL
    ORDER BY c.id LIMIT :limit
"""


def _utc(value):
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def assess(*, catalog, store, control, clients, dependencies, physical_acceptance_verified, now):
    """Pure report; all uncertain inputs block retirement readiness."""
    from service1.clientflow_standard_release import StandardReleaseDenied, validate_baseline_catalog

    blockers = []
    try:
        validate_baseline_catalog(catalog)
    except StandardReleaseDenied:
        blockers.append("active_catalog_not_1250_only")
    rows = store["protected_latest"] + store["older_review_only"]
    baseline = [row for row in rows if row["release_id"] == BASELINE]
    sha = baseline[0]["sha256"] if len(baseline) == 1 else None
    if not sha or not re.fullmatch(r"[a-f0-9]{64}", sha) or store.get("invalid_artifacts"):
        blockers.append("verified_1250_artifact_missing")
    if any(row["release_sequence"] > 1250 or
           (row["release_sequence"] == 1250 and row["release_id"] != BASELINE) for row in rows):
        blockers.append("unexpected_newer_artifact")
    if (not control or control.get("stable_release_id") != BASELINE
            or control.get("stable_bundle_sha256") != sha
            or control.get("fleet_open") is not False
            or control.get("fresh_install_open") is not False
            or control.get("cutover_enabled") is not True):
        blockers.append("baseline_control_not_bound_and_quiesced")
    if physical_acceptance_verified is not True:
        blockers.append("physical_acceptance_not_verified")
    ids = [row["id"] for row in clients]
    if not ids or len(ids) > MAX_CLIENTS or len(set(ids)) != len(ids):
        blockers.append("client_inventory_incomplete")
    unknown = []
    clock = _utc(now)
    for row in clients[:MAX_CLIENTS]:
        stamp = _utc(row.get("reported_at"))
        if (row.get("status") != "approved" or not row.get("active_status_credential_id")
                or row.get("agent_version") != "1.4.0" or row.get("observed_state") != "online"
                or stamp is None or clock is None or not 0 <= (clock - stamp).total_seconds() <= 30):
            unknown.append(row["id"])
    if unknown:
        blockers.append("clients_not_confirmed_online_on_1250")
    for name in DEPENDENCY_QUERIES:
        count = dependencies.get(name)
        if type(count) is not int or count != 0:
            blockers.append(name)
    older = [row for row in rows if row["release_sequence"] < 1250]
    return {
        "mode": "read_only_render_postgresql_retirement_inventory",
        "target_release_id": BASELINE,
        "baseline_sha256": sha,
        "approved_store_count": len(rows),
        "old_artifacts_review_only": [
            {"release_id": row["release_id"], "sha256": row["sha256"], "size_bytes": row["size_bytes"]}
            for row in older
        ],
        "potential_store_reclaim_bytes": sum(row["size_bytes"] for row in older),
        "clients_not_confirmed": unknown,
        "dependency_counts": dependencies,
        "database_and_store_snapshot_clear": not blockers,
        "blockers": blockers,
        "local_recovery_inventory_required": True,
        "offline_and_backup_review_required": True,
        "deletion_authorized": False,
        "rollback_authorized": False,
    }


def read_database(catalog, store):
    from sqlalchemy import text
    from service1.db import engine, IS_PRODUCTION
    from service1.clientflow_release_governance_policy import GovernanceDenied, require_approved_physical_evidence

    if not IS_PRODUCTION or not engine.url.drivername.startswith("postgresql"):
        raise RuntimeError("Only explicit production PostgreSQL audit is supported")
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        conn.execute(text("SET LOCAL statement_timeout = '10s'"))
        now = conn.execute(text("SELECT CURRENT_TIMESTAMP")).scalar_one()
        controls = conn.execute(text("""
            SELECT stable_release_id, stable_bundle_sha256, fleet_open,
                   fresh_install_open, cutover_enabled
            FROM clientflow_release_control WHERE id = 1
        """)).mappings().all()
        control = dict(controls[0]) if len(controls) == 1 else None
        clients = conn.execute(text(CLIENT_QUERY), {"limit": MAX_CLIENTS + 1}).mappings().all()
        counts = {name: conn.execute(text(query)).scalar_one() for name, query in DEPENDENCY_QUERIES.items()}
        physical = False
        baseline = next((row for row in store["protected_latest"] + store["older_review_only"]
                         if row["release_id"] == BASELINE), None)
        if baseline:
            evidence = conn.execute(text("""
                SELECT release_id, bundle_sha256, client_id, actor_user_id, decision, evidence, created_at
                FROM clientflow_physical_acceptance
                WHERE release_id = :release AND bundle_sha256 = :sha LIMIT 2
            """), {"release": BASELINE, "sha": baseline["sha256"]}).mappings().all()
            if len(evidence) == 1:
                record = dict(evidence[0])
                try:
                    require_approved_physical_evidence(
                        acceptance=record, release_id=BASELINE, bundle_sha256=baseline["sha256"], now=now)
                    physical = (
                        record["evidence"].get("observed_version") == "1.4.0"
                        and conn.execute(text("""
                            SELECT count(*) FROM clientflow_deployment
                            WHERE client_id = :client AND target_release_id = :release
                              AND bundle_sha256 = :sha AND bundle_size = :size
                              AND release_approval_reference = :approval AND source_commit = :source
                              AND state = 'succeeded'
                        """), {"client": record["client_id"], "release": BASELINE, "sha": baseline["sha256"],
                               "size": baseline["size_bytes"], "approval": baseline["approval_reference"],
                               "source": baseline["source_commit"]}).scalar_one() > 0
                    )
                except GovernanceDenied:
                    physical = False
        # The context rolls back its read-only transaction; no DB row is changed.
    return assess(catalog=catalog, store=store, control=control, clients=clients,
                  dependencies=counts, physical_acceptance_verified=physical, now=now)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        from service1.clientflow_releases import load_catalog
        configured = args.artifact_dir or os.environ.get("CLIENTFLOW_RELEASE_ARTIFACT_DIR")
        if not configured:
            raise RuntimeError("Artifact directory is required")
        report = read_database(load_catalog(), inspect_store(Path(configured)))
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["database_and_store_snapshot_clear"] else 2
    except Exception as exc:
        # Do not echo SQL parameters, DB URLs, or arbitrary exception content.
        print("CLIENTFLOW_140_RETIREMENT_AUDIT=STOP: " + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
