"""Source-level no-cutover guard is dependency-free and runs on host + CI."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / 'backend/service1/clientflow_release_wave_transactions.py'
DEPLOY = ROOT / 'backend/service1/routers/clientflow_deployments.py'
ADMIN = ROOT / 'backend/service1/routers/clientflow_release_administration.py'


def test_staged_engine_cannot_be_called_by_any_production_router():
    for path in (DEPLOY, ADMIN):
        source = path.read_text(encoding='utf-8')
        assert 'clientflow_release_wave_transactions' not in source
        assert 'create_staged_wave_deployment' not in source
    engine = ENGINE.read_text(encoding='utf-8')
    tree = ast.parse(engine)
    exported = {item.name for item in tree.body if isinstance(item, (ast.FunctionDef, ast.ClassDef))}
    assert {'locked_wave_preconditions', 'consume_locked_wave', 'create_staged_wave_deployment'} <= exported
    assert 'session.commit(' not in engine
    assert 'deployment_release_snapshot' in engine
    assert 'legacy_guard()' in engine
    assert 'lock_system_client(session, client_id)' in engine
    assert 'ClientFlowPhysicalAcceptance' in engine


def test_stable_policy_and_inert_ui_are_never_implicitly_reopened():
    admin = ADMIN.read_text(encoding='utf-8')
    assert 'row.cutover_enabled is not False' in admin
    assert 'row.fresh_install_open is not False' in admin
    assert 'row.fleet_open is not False' in admin
    assert '"authorization_active": False' in admin
    assert '"deployment_authorized": False' in admin
    catalog = (ROOT / 'backend/service1/clientflow_release_catalog.json').read_text(encoding='utf-8')
    assert '"latest_stable": "1.4.0"' in catalog
    assert '"default_install_version": "1.4.0"' in catalog
    assert '"max_selectable_versions": 1' in catalog
    assert '"max_installable_versions": 1' in catalog
