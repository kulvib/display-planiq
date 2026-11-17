"""A small source-level guard on phase 62A's permission and deployment boundaries."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROUTE = (ROOT / "backend/service1/routers/clientflow_release_administration.py").read_text(encoding="utf-8")
UI = (ROOT / "frontend/src/pages/adminpages/ClientFlowReleaseAdministration.jsx").read_text(encoding="utf-8")
PREFLIGHT = (ROOT / "scripts/display_62_storage_preflight.py").read_text(encoding="utf-8")


def test_62a_preview_is_superadmin_only_and_repeated_on_draft_write():
    assert '@router.post("/preview")' in ROUTE
    assert '_require_actor(request, user)' in ROUTE
    assert '_bound_control(session)' in ROUTE
    assert '_verify_live_planning_sources(session, payload.client_ids, payload.source_version)' in ROUTE
    assert ROUTE.count('_verify_live_planning_sources(session, payload.client_ids, payload.source_version)') == 2
    assert '"deployment_authorized": False' in ROUTE
    assert '"release_approved_for_deployment": False' in ROUTE
    assert 'state="draft"' in ROUTE
    assert 'state="approved"' not in ROUTE


def test_62a_frontend_does_not_offer_approval_or_rollback_action():
    assert 'client.post(`${RELEASE_PATH}/preview`' in UI
    assert 'validatePlanningPreview(data,' in UI
    assert 'AdminRefreshButton' in UI
    assert 'ml: "auto", flexShrink: 0' in UI
    assert 'startReleaseDeployment' not in UI
    assert 'clientflow-deployments' not in UI


def test_62a_preflight_never_runs_shell_or_database_commands():
    assert 'subprocess' not in PREFLIGHT
    assert 'psycopg' not in PREFLIGHT
    assert 'sqlalchemy' not in PREFLIGHT
    assert 'database_cutover_authorized": False' in PREFLIGHT
    assert 'backup_verified": False' in PREFLIGHT
    assert '_sha256_verified_file' in PREFLIGHT
