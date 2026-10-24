"""Security, recovery and retention gates for the reviewed 60A incident history."""
from __future__ import annotations

import ast
import hashlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "scripts"))

from service1.incident_policy import signals_for_report
from service1.incident_models import OperationalIncident, OperationalIncidentEvent
from service1.incident_service import reconcile_observation

BOOT1 = "11111111-1111-4111-8111-111111111111"
BOOT2 = "22222222-2222-4222-8222-222222222222"
T1 = datetime(2026, 10, 24, 12, 0, 0)


class FakeSession:
    def __init__(self):
        self.objects = []

    def add(self, obj):
        self.objects.append(obj)


def data(*, status="failed"):
    return {"services": {"clientflow-status-agent.service": status}, "wifi_ssid": "SECRET-NAME"}


def run(session, active, *, when=T1, payload=None, boot=BOOT1, domain="status", observed="online"):
    return reconcile_observation(
        session, client_id=7, domain=domain, observed_state=observed,
        payload=data() if payload is None else payload, boot_id=boot,
        reported_at=when, active=active,
    )


def test_healthy_report_clears_only_same_domain_and_never_on_missing_evidence():
    db, active = FakeSession(), []
    assert run(db, active) == (1, 0)
    assert run(db, active, when=T1 + timedelta(minutes=1), payload={}) == (0, 0)
    assert active[0].resolved_at is None
    assert run(db, active, when=T1 + timedelta(minutes=2), payload=data(status="active")) == (0, 1)
    assert active[0].resolution_evidence == "healthy_report"
    assert len([x for x in db.objects if isinstance(x, OperationalIncidentEvent) and x.kind == "recovered"]) == 1


def test_partial_status_report_cannot_clear_other_service_or_missing_ntp():
    db, active = FakeSession(), []
    run(db, active, payload={"services": {"clientflow-status-agent.service": "failed"}, "ntp_synchronized": False, "ntp_enabled": True})
    assert len(active) == 2
    # Other service state is not evidence for status-agent recovery.
    assert run(db, active, when=T1 + timedelta(minutes=1), payload={"services": {"clientflow-browser-guard.service": "active"}}) == (0, 0)
    assert all(row.resolved_at is None for row in active)
    # NTP proof is missing; only the explicit status-agent recovery is accepted.
    assert run(db, active, when=T1 + timedelta(minutes=2), payload={"services": {"clientflow-status-agent.service": "active"}}) == (0, 1)
    assert len([row for row in active if row.resolved_at is None]) == 1
    assert active[1].code == "ntp_not_synchronized" and active[1].resolved_at is None


def test_reboot_does_not_clear_error_but_is_recorded_as_independent_event():
    db, active = FakeSession(), []
    assert run(db, active) == (1, 0)
    assert run(db, active, when=T1 + timedelta(minutes=1), boot=BOOT2) == (0, 0)
    assert active[0].resolved_at is None
    assert [e.kind for e in db.objects if isinstance(e, OperationalIncidentEvent)] == ["opened", "reboot_observed"]
    assert run(db, active, when=T1 + timedelta(minutes=2), boot=BOOT2, payload=data(status="active")) == (0, 1)
    assert active[0].resolution_evidence == "healthy_report"


def test_healthy_after_new_boot_records_both_transition_and_causality_disclaimer():
    db, active = FakeSession(), []
    run(db, active)
    run(db, active, when=T1 + timedelta(minutes=1), boot=BOOT2, payload=data(status="active"))
    assert active[0].resolution_evidence == "healthy_after_reboot"
    assert [e.kind for e in db.objects if isinstance(e, OperationalIncidentEvent)] == ["opened", "reboot_observed", "recovered"]


def test_recurrence_creates_a_new_episode_not_rewriting_history():
    db, active = FakeSession(), []
    run(db, active)
    run(db, active, when=T1 + timedelta(minutes=1), payload=data(status="active"))
    assert run(db, active, when=T1 + timedelta(minutes=2)) == (1, 0)
    assert len({r.id for r in active}) == 2
    assert active[0].resolved_at is not None
    assert active[1].resolved_at is None


def test_redaction_allowlist_never_copies_client_error_or_network_secrets():
    secret = "s3cr3t-ssid/password/test"
    payload = {"runtime": {"state": "failed", "error": secret}, "kiosk_lockdown": {"status": "failed", "message": secret}}
    assert set(signals_for_report("display", "online", payload)) == {"browser_runtime_failed", "kiosk_lockdown_failed"}
    db, active = FakeSession(), []
    run(db, active, domain="display", payload=payload)
    assert secret not in repr(db.objects)
    # A healthy, explicitly observed browser state is valid recovery evidence,
    # not a missing/untrustworthy observation. Other unobserved incidents stay open.
    assert signals_for_report("display", "online", {"runtime": {"state": "running"}}) == {}
    assert run(db, active, when=T1 + timedelta(minutes=1), domain="display", payload={"runtime": {"state": "running"}}) == (0, 1)
    assert {row.code for row in active if row.resolved_at is None} == {"kiosk_lockdown_failed"}
    assert signals_for_report("display", "online", {"runtime": {"state": "waiting_internet"}, "kiosk_lockdown": {"status": "applied"}}) == {}


def test_incomplete_status_never_proves_recovery_and_ntp_false_is_critical():
    assert signals_for_report("status", "online", {"ntp_synchronized": False})["ntp_not_synchronized"].severity == "critical"
    issue = signals_for_report("status", "online", {"services": {}, "ntp_synchronized": False})
    assert issue["ntp_not_synchronized"].severity == "critical"
    assert "firmware_update_failed" in signals_for_report("system", "online", {"firmware": {"status": "failed"}})
    assert signals_for_report("status", "online", {"services": {}, "ntp_synchronized": None}) == {}


def test_60a_schema_fingerprint_and_frozen_59a_predecessor():
    import display_schema_contract as contract
    import run_migrations as runner
    migration = ROOT / "backend/migrations/versions/20261024_60a_operational_incidents.py"
    assert hashlib.sha256(migration.read_bytes()).hexdigest() == runner.REVIEWED_INCIDENT_60A_SOURCE_SHA256
    assert contract.EXPECTED_HEAD_REVISION == runner.REVIEWED_INCIDENT_60A_REVISION
    assert runner.REVIEWED_ROLLBACK_59A_REVISION == "20261023_59a_rollback"
    assert contract.EXPECTED_TABLES >= runner.INCIDENT_60A_TABLES
    assert contract.EXPECTED_TABLES >= runner.ROLLBACK_59A_TABLES
    columns, constraints, indexes = runner._without_incident_60a_schema(
        contract.EXPECTED_COLUMNS, contract.EXPECTED_CONSTRAINTS, contract.EXPECTED_INDEXES,
    )
    assert runner.INCIDENT_60A_TABLES.isdisjoint(columns)
    assert runner.ROLLBACK_59A_TABLES <= columns.keys()
    assert runner.INCIDENT_60A_CONSTRAINTS.isdisjoint(constraints)
    assert runner.INCIDENT_60A_INDEXES.isdisjoint(indexes)
    baseline_columns, _, _ = runner._baseline_schema_contract()
    assert runner.INCIDENT_60A_TABLES.isdisjoint(baseline_columns)
    payload = {
        "tables": sorted(contract.EXPECTED_TABLES),
        "columns": contract.EXPECTED_COLUMNS,
        "constraints": contract.EXPECTED_CONSTRAINTS,
        "indexes": contract.EXPECTED_INDEXES,
        "extensions": sorted(contract.EXPECTED_EXTENSION_NAMES),
        "sequences": sorted(contract.EXPECTED_SEQUENCES),
        "triggers": sorted(contract.EXPECTED_TRIGGERS),
    }
    computed = hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",", ":")).encode()).hexdigest()
    assert computed == contract.EXPECTED_FINGERPRINT


def test_superadmin_read_boundary_and_no_raw_status_payload():
    source = (ROOT / "backend/service1/routers/operational_incidents.py").read_text()
    assert "get_current_superadmin_user" in source
    assert "operational-incidents" in source
    assert "status_payload" not in source
    assert "Cache-Control" in source
    assert "Query(default=50, ge=1, le=100)" in source


def test_60a_migration_matches_model_security_and_ondelete():
    migration = (ROOT / "backend/migrations/versions/20261024_60a_operational_incidents.py").read_text()
    assert 'down_revision = "20261023_59a_rollback"' in migration
    assert 'ondelete="CASCADE"' in migration
    assert "resolved_at IS NULL" in migration
    assert "raise RuntimeError" in migration
    assert "ck_operational_incident_domain" in migration
    assert "ck_operational_incident_event_kind" in migration


def test_60a_model_registration_is_shared_by_platform_validator_and_alembic():
    """Both entry points must explicitly register 60A tables before metadata binding."""
    for relative in ("scripts/validate_display_baseline.py", "migrations/env.py"):
        source = ROOT / "backend" / relative
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        imports = [
            index for index, node in enumerate(tree.body)
            if isinstance(node, ast.Import)
            and any(alias.name == "service1.incident_models" for alias in node.names)
        ]
        metadata = [
            index for index, node in enumerate(tree.body)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id in {"METADATA", "target_metadata"}
                    for target in node.targets)
        ]
        assert len(imports) == 1, f"Explicit incident-model registration missing: {relative}"
        assert len(metadata) == 1 and imports[0] < metadata[0], (
            f"Incident models must be registered before SQLModel.metadata is used: {relative}"
        )
