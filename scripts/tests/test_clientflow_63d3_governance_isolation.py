"""Independently runnable guard: no DB governance route or release gate bypass."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / 'backend/service1/clientflow_release_governance.py'
POLICY = ROOT / 'backend/service1/clientflow_release_governance_policy.py'


def test_governance_code_has_no_production_entry_point_or_policy_writes():
    for path in (ROOT / 'backend/service1/routers').glob('*.py'):
        source = path.read_text(encoding='utf-8')
        assert 'clientflow_release_governance' not in source, path
        assert 'stage_approve_controlled_wave' not in source, path
        assert 'stage_physical_acceptance' not in source, path
    code = MODULE.read_text(encoding='utf-8')
    tree = ast.parse(code)
    definitions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert {'stage_physical_acceptance', 'stage_approve_controlled_wave',
            'stage_control_wave', 'stage_reconcile_wave'} <= definitions
    assert 'session.commit(' not in code
    assert 'create_authorized_deployment' not in code
    assert 'cutover_enabled = True' not in code
    assert 'fleet_open = True' not in code
    assert 'deployment_release_snapshot' in code
    assert 'add_audit_log(' in code


def test_governance_policy_has_no_mutation_or_network_calls():
    source = POLICY.read_text(encoding='utf-8')
    ast.parse(source)
    assert 'Session' not in source
    assert 'requests.' not in source
    assert 'session.commit' not in source
    assert 'httpx' not in source


def test_production_deployment_still_uses_legacy_pilot_gates():
    source = (ROOT / 'backend/service1/routers/clientflow_deployments.py').read_text(encoding='utf-8')
    for gate in ('require_pilot_1245', 'require_stable_rollout', 'lock_system_client'):
        assert gate in source
    assert 'create_staged_wave_deployment' not in source
