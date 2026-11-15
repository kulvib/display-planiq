"""61B-1 security contract: planning is not deployment authorization.

The integration tests cover state changes; these source checks pin the
critical non-integration boundaries until an independently approved cutover.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def source(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_61b_review_cannot_create_a_deployment_or_physical_acceptance():
    handler = source("backend/service1/routers/clientflow_release_administration.py")
    assert '"authorization_active": False' in handler
    assert '"physical_pilot_accepted": False' in handler
    assert '"cutover_enabled": False' in handler
    assert '"fleet_open": False' in handler
    assert '"fresh_install_open": False' in handler
    assert '"deployment_authorized": False' in handler
    assert 'wave.state = "draft"' in handler
    assert 'wave.state = "paused"' in handler
    assert 'target.state = "revoked"' in handler
    assert 'target.state = "approved"' not in handler
    assert 'wave.state = "approved"' not in handler
    assert 'ClientFlowDeployment(' not in handler
    assert 'ClientFlowPhysicalAcceptance(' not in handler
    assert 'session.add(wave)' in handler and 'session.add(ClientFlowRolloutTarget(' in handler
    assert '"clientflow_rollout_plan_reviewed"' in handler
    assert '"clientflow_rollout_plan_paused"' in handler
    assert '"clientflow_rollout_plan_resumed"' in handler
    assert 'verify_password' in handler and 'assert_key_not_limited' in handler
    assert 'with_for_update()' in handler and 'expected_revision' in handler


def test_61b_existing_runtime_authorities_and_61a_frozen_schema_untouched():
    deployments = source("backend/service1/routers/clientflow_deployments.py")
    assert 'require_pilot_1245' in deployments
    assert 'require_stable_rollout' in deployments
    maintenance = source("backend/service1/clientflow_fresh_install_maintenance.py")
    assert 'CLIENTFLOW_FRESH_INSTALL_SUSPENDED' in maintenance
    runner = source("backend/scripts/run_migrations.py")
    assert 'REVIEWED_RELEASE_ADMIN_61A_SOURCE_SHA256' in runner
    assert 'REVIEWED_RELEASE_ADMIN_61A_REVISION = "20261115_61a_cf_release_admin"' in runner
    assert 'head_revision.down_revision != REVIEWED_INCIDENT_60A_REVISION' in runner


def test_61b_admin_display_never_confuses_plan_review_with_release_approval():
    ui = source("frontend/src/pages/adminpages/ClientFlowReleaseAdministration.jsx")
    assert 'data.authorization_active !== false' in ui
    assert 'data.fresh_install_open !== false' in ui
    assert 'data.fleet_open !== false' in ui
    assert 'data.cutover_enabled !== false' in ui
    assert 'planning_review_available !== true' in ui
    assert 'setClientIds("3")' not in ui
    assert 'React.useState("3")' not in ui
    assert 'Forventet kildeversion' in ui
    assert 'Udrulning ikke autoriseret' in ui
    for operation in ("review", "pause", "resume", "cancel"):
        assert f'decidePlan(wave, "{operation}")' in ui
