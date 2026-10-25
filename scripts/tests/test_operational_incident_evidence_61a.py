"""61A: independent evidence-gate tests (no PostgreSQL or SQLModel required)."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from service1.incident_policy import (  # noqa: E402
    EXPECTED_ACTIVE_UNITS, SERVICE_UNITS,
    observed_codes_for_report, signals_for_report,
)
from service1.incident_coverage import coverage_summary  # noqa: E402


def code(unit):
    return "service_" + unit.replace(".", "_").replace("-", "_")


@pytest.mark.parametrize("unit", sorted(EXPECTED_ACTIVE_UNITS))
def test_inactive_expected_units_are_faults_and_only_active_proves_recovery(unit):
    assert unit in SERVICE_UNITS
    signal = signals_for_report("status", "online", {"services": {unit: "inactive"}})
    assert code(unit) in signal
    assert code(unit) not in observed_codes_for_report("status", {"services": {unit: "inactive"}})
    assert code(unit) in observed_codes_for_report("status", {"services": {unit: "active"}})


def test_optional_and_oneshot_inactive_is_not_failure_or_recovery():
    unit = "clientflow-livestream-producer.service"
    assert unit not in EXPECTED_ACTIVE_UNITS
    assert signals_for_report("status", "online", {"services": {unit: "inactive"}}) == {}
    assert code(unit) not in observed_codes_for_report("status", {"services": {unit: "inactive"}})
    assert code(unit) in signals_for_report("status", "online", {"services": {unit: "failed"}})
    assert code(unit) not in observed_codes_for_report("status", {"services": {unit: "failed"}})
    assert code(unit) in observed_codes_for_report("status", {"services": {unit: "active"}})


@pytest.mark.parametrize("state", ["activating", "deactivating", "unknown", "not-found", "inactive", "failed"])
def test_negative_or_indeterminate_service_state_cannot_clear_existing_failure(state):
    assert code("clientflow-status-agent.service") not in observed_codes_for_report(
        "status", {"services": {"clientflow-status-agent.service": state}}
    )


@pytest.mark.parametrize("state", ["waiting_internet", "stopped", "countdown", "unknown", "failed", "starting"])
def test_browser_nonrunning_is_never_recovery_evidence(state):
    assert "browser_runtime_failed" not in observed_codes_for_report("display", {"runtime": {"state": state}})
    if state == "waiting_internet":
        assert signals_for_report("display", "online", {"runtime": {"state": state}}) == {}


def test_browser_running_is_positive_and_no_new_fault():
    assert signals_for_report("display", "online", {"runtime": {"state": "running"}}) == {}
    assert "browser_runtime_failed" in observed_codes_for_report("display", {"runtime": {"state": "running"}})


@pytest.mark.parametrize("state", ["applied", "disabled"])
def test_kiosk_lockdown_expected_healthy_states_prove_recovery(state):
    assert "kiosk_lockdown_failed" in observed_codes_for_report("display", {"kiosk_lockdown": {"status": state}})


@pytest.mark.parametrize("state", ["rollback", "drifted", "applying", "rolling_back", "failed", "unknown"])
def test_kiosk_lockdown_never_false_recovery(state):
    assert "kiosk_lockdown_failed" not in observed_codes_for_report("display", {"kiosk_lockdown": {"status": state}})
    if state == "drifted":
        assert signals_for_report("display", "online", {"kiosk_lockdown": {"status": state}})["kiosk_lockdown_failed"].severity == "critical"


def test_system_broker_and_firmware_recovery_require_explicit_positive_evidence():
    assert "system_broker_unavailable" in observed_codes_for_report("system", {"broker_socket": True})
    assert "system_broker_unavailable" not in observed_codes_for_report("system", {"firmware": {"status": "ok"}})
    assert "firmware_update_failed" not in observed_codes_for_report("system", {"firmware": {"status": "pending"}})
    assert "firmware_update_failed" in observed_codes_for_report("system", {"firmware": {"status": "success"}})


def test_report_coverage_100_clients_and_future_skew_guard():
    now = datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc)
    report_rows = (
        [("status", now - timedelta(seconds=10))] * 100
        + [("display", now - timedelta(seconds=180))] * 98
        + [("system", now - timedelta(seconds=181))] * 95
    )
    result = coverage_summary(100, report_rows, now=now)
    assert result["approved_clients"] == 100
    assert result["freshness_seconds"] == 180
    assert result["domains"] == [
        {"domain": "status", "fresh": 100, "stale": 0, "missing": 0},
        {"domain": "display", "fresh": 98, "stale": 0, "missing": 2},
        {"domain": "system", "fresh": 0, "stale": 95, "missing": 5},
    ]
    future = coverage_summary(1, [("status", now + timedelta(minutes=1))], now=now)
    assert future["domains"][0]["stale"] == 1


def test_missing_client_report_is_never_presented_as_healthy():
    now = datetime.now(timezone.utc)
    result = coverage_summary(5, [], now=now)
    assert all(x == {"domain": d, "fresh": 0, "stale": 0, "missing": 5} for x, d in zip(result["domains"], ("status", "display", "system")))
    with pytest.raises(ValueError, match="exceed"):
        coverage_summary(1, [("status", now), ("status", now)], now=now)


def test_superadmin_api_uses_no_raw_payload_or_new_client_request():
    path = ROOT / "backend/service1/routers/operational_incidents.py"
    src = path.read_text(encoding="utf-8")
    api = src.split('@router.get("/report-coverage")', 1)[1].split('@router.get("")', 1)[0]
    assert "Depends(get_current_superadmin_user)" in api
    assert "ClientDomainStatus.reported_at" in api
    assert "ClientDomainStatus.domain" in api
    assert "status_payload" not in api
    assert "Cache-Control" in api and '"no-store"' in api
    assert "session.exec" in api
    assert "commit(" not in api


def test_release_trust_remains_fail_closed_until_operator_provisioning():
    import json
    trust = json.loads((ROOT / "client/release/rollback-trust.json").read_text(encoding="utf-8"))
    release = json.loads((ROOT / "client/release/release-input.json").read_text(encoding="utf-8"))
    assert trust == {"schema_version": 1, "enabled": False, "keys": []}
    assert release["release_sequence"] == 1241
