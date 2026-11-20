"""No-production-mutation regression for the first DB administration phase.

These checks run without Neon credentials, Render access or a physical client.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "backend/migrations/versions/20261115_61a_clientflow_release_admin.py"


def _source(path):
    return (ROOT / path).read_text(encoding="utf-8")


def _migration_module():
    spec = importlib.util.spec_from_file_location("clientflow_release_admin_61a", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_new_migration_is_additive_and_runner_pins_reviewed_bytes():
    import sys

    sys.path.insert(0, str(ROOT / "backend/scripts"))
    try:
        import display_schema_contract as contract
        import run_migrations as runner

        assert contract.EXPECTED_HEAD_REVISION == runner.REVIEWED_RELEASE_ADMIN_61A_REVISION
        assert runner.REVIEWED_RELEASE_ADMIN_61A_SOURCE_SHA256 == hashlib.sha256(MIGRATION.read_bytes()).hexdigest()
        assert runner.RELEASE_ADMIN_61A_TABLES <= contract.EXPECTED_TABLES
        assert runner.RELEASE_ADMIN_61A_CONSTRAINTS <= contract.EXPECTED_CONSTRAINTS.keys()
        assert runner.RELEASE_ADMIN_61A_INDEXES <= contract.EXPECTED_INDEXES.keys()
        runner._require_reviewed_61a_extension()
        runner._require_reviewed_60a_extension()
        runner._require_reviewed_59a_extension()
        columns, constraints, indexes = runner._without_release_admin_61a_schema(
            contract.EXPECTED_COLUMNS, contract.EXPECTED_CONSTRAINTS, contract.EXPECTED_INDEXES,
        )
        assert runner.RELEASE_ADMIN_61A_TABLES.isdisjoint(columns)
        assert runner.INCIDENT_60A_TABLES <= columns.keys()
        assert runner.RELEASE_ADMIN_61A_CONSTRAINTS.isdisjoint(constraints)
        assert runner.RELEASE_ADMIN_61A_INDEXES.isdisjoint(indexes)
        baseline_columns, _, _ = runner._baseline_schema_contract()
        assert runner.RELEASE_ADMIN_61A_TABLES.isdisjoint(baseline_columns)
        payload = {
            "tables": sorted(contract.EXPECTED_TABLES),
            "columns": contract.EXPECTED_COLUMNS,
            "constraints": contract.EXPECTED_CONSTRAINTS,
            "indexes": contract.EXPECTED_INDEXES,
            "extensions": sorted(contract.EXPECTED_EXTENSION_NAMES),
            "sequences": sorted(contract.EXPECTED_SEQUENCES),
            "triggers": sorted(contract.EXPECTED_TRIGGERS),
        }
        assert contract.EXPECTED_FINGERPRINT == hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    finally:
        sys.path.remove(str(ROOT / "backend/scripts"))


def test_sqlite_additive_migration_bootstrap_is_closed_and_fks_are_explicit():
    module = _migration_module()
    assert module.down_revision == "20261024_60a_incidents"
    engine = create_engine("sqlite://", poolclass=StaticPool)
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE "user" (id INTEGER PRIMARY KEY)'))
        connection.execute(text('CREATE TABLE "client" (id INTEGER PRIMARY KEY)'))
        connection.execute(text('CREATE TABLE "clientflow_deployment" (id VARCHAR(36) PRIMARY KEY)'))
        ctx = MigrationContext.configure(connection)
        module.op = Operations(ctx)
        module.upgrade()
        control = connection.execute(text("SELECT * FROM clientflow_release_control WHERE id = 1")).mappings().one()
        assert control["stable_release_id"] == "clientflow-1.3.44-seq-1245"
        assert control["stable_bundle_sha256"] == "28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5"
        assert control["fresh_install_open"] is False or control["fresh_install_open"] == 0
        assert control["fleet_open"] is False or control["fleet_open"] == 0
        assert control["cutover_enabled"] is False or control["cutover_enabled"] == 0
        assert control["revision"] == 1
        assert connection.execute(text("SELECT count(*) FROM clientflow_rollout_target")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM clientflow_rollout_wave")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM clientflow_physical_acceptance")).scalar_one() == 0
        with pytest.raises(IntegrityError):
            connection.execute(text("INSERT INTO clientflow_release_control (id,stable_release_id,stable_bundle_sha256,updated_at) VALUES (2,'x','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',CURRENT_TIMESTAMP)"))
    assert {"clientflow_release_control", "clientflow_rollout_wave", "clientflow_rollout_target", "clientflow_physical_acceptance"} <= set(inspect(engine).get_table_names())
    with pytest.raises(RuntimeError, match="ikke automatisk"):
        module.downgrade()


def test_rollout_admin_is_inert_and_legacy_gates_remain_untouched():
    endpoint = _source("backend/service1/routers/clientflow_release_administration.py")
    deploy = _source("backend/service1/routers/clientflow_deployments.py")
    maintenance = _source("backend/service1/clientflow_fresh_install_maintenance.py")
    active_catalog = json.loads(_source("backend/service1/clientflow_release_catalog.json"))
    assert len(active_catalog["releases"]) == 3
    assert active_catalog["catalog_sequence"] == 1247
    assert active_catalog["releases"][1]["install_modes"] == ["in_place_update"]
    assert active_catalog["releases"][1]["installable"] is False
    assert active_catalog["releases"][2]["installable"] is False
    assert active_catalog["releases"][2]["install_modes"] == ["in_place_update"]
    assert active_catalog["releases"][0]["install_modes"] == ["fresh_install", "in_place_update"]
    assert "additive_draft_only" in endpoint and '"authorization_active": False' in endpoint
    assert '"cutover_enabled": False' in endpoint
    assert '"fresh_install_open": False' in endpoint
    assert '"fleet_open": False' in endpoint
    assert "get_current_superadmin_user" in endpoint and "verify_password" in endpoint
    assert "assert_key_not_limited" in endpoint and "commit_audit_log" in endpoint
    assert "session.commit()" in endpoint and "add_audit_log" in endpoint
    assert "require_pilot_1245" in deploy and "require_stable_rollout" in deploy
    assert "CLIENTFLOW_FRESH_INSTALL_SUSPENDED" in maintenance
    assert '"physical_pilot_accepted": false' in _source("backend/service1/clientflow_1245_fleet_acceptance.json")
    assert "clientflow_release_administration.router" in _source("backend/service1/main.py")
    ui = _source("frontend/src/pages/adminpages/ClientFlowReleaseAdministration.jsx")
    assert "Gennemgå og gem inaktiv plan" in ui and "Ingen installation" in ui
    assert "ClientFlowReleaseAdministration" in _source("frontend/src/pages/adminpages/AdminPage.jsx")
