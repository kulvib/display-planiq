"""Source-level, exact migration head and secure-by-default rollback gate."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _contract():
    import importlib.util
    import sys

    scripts = ROOT / 'backend/scripts'
    sys.path.insert(0, str(scripts))
    try:
        import display_schema_contract
        return display_schema_contract
    finally:
        sys.path.remove(str(scripts))


def test_signed_rollback_schema_contract_is_exact_and_frozen():
    contract = _contract()
    assert contract.EXPECTED_HEAD_REVISION == '20261023_59a_rollback'
    new = {'clientflow_rollback_permit', 'clientflow_rollback_event'}
    assert new <= contract.EXPECTED_TABLES
    assert set(contract.EXPECTED_COLUMNS['clientflow_rollback_permit']) == {
        'id', 'client_id', 'credential_id', 'admin_id', 'from_release_id',
        'from_sequence', 'to_release_id', 'to_sequence', 'release_approval_reference',
        'bundle_sha256', 'reason_sha256', 'reason', 'policy_revision', 'signing_key_id',
        'signed_envelope', 'issued_at', 'expires_at', 'state', 'reported_at', 'revoked_at',
    }
    assert set(contract.EXPECTED_COLUMNS['clientflow_rollback_event']) == {
        'id', 'permit_id', 'client_id', 'event_type', 'actor_user_id',
        'credential_id', 'occurred_at', 'received_at', 'details',
    }
    assert contract.EXPECTED_COLUMNS['clientflow_rollback_event']['details']['udt_name'] == 'jsonb'
    assert contract.EXPECTED_CONSTRAINTS['clientflow_rollback_event_permit_id_fkey'].endswith('ON DELETE RESTRICT')
    assert contract.EXPECTED_CONSTRAINTS['ck_clientflow_rollback_permit_expiry'] == 'CHECK (expires_at > issued_at)'
    assert 'ix_clientflow_rollback_permit_client_state' in contract.EXPECTED_INDEXES
    assert 'ix_clientflow_rollback_event_permit' in contract.EXPECTED_INDEXES
    payload = {
        'tables': sorted(contract.EXPECTED_TABLES),
        'columns': contract.EXPECTED_COLUMNS,
        'constraints': contract.EXPECTED_CONSTRAINTS,
        'indexes': contract.EXPECTED_INDEXES,
        'extensions': sorted(contract.EXPECTED_EXTENSION_NAMES),
        'sequences': sorted(contract.EXPECTED_SEQUENCES),
        'triggers': sorted(contract.EXPECTED_TRIGGERS),
    }
    computed = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert computed == contract.EXPECTED_FINGERPRINT


def test_signed_rollback_migration_appends_without_rewriting_history():
    migration = (ROOT / 'backend/migrations/versions/20261023_59a_clientflow_rollback_permit.py').read_text()
    assert 'revision = "20261023_59a_rollback"' in migration
    assert 'down_revision = "20260929_58a_maintenance"' in migration
    assert 'op.create_table(\n        "clientflow_rollback_permit"' in migration
    assert 'op.create_table(\n        "clientflow_rollback_event"' in migration
    assert 'def downgrade():' in migration and 'raise RuntimeError' in migration
    runner = (ROOT / 'backend/scripts/run_migrations.py').read_text()
    assert '_verify_schema' in runner
    assert 'if head != EXPECTED_HEAD_REVISION:' in runner
    assert 'REVIEWED_BASELINE_ADOPTION_HEAD = "20260929_58a_maintenance"' in runner


def test_signed_rollback_is_not_enabled_by_source_default():
    trust = json.loads((ROOT / 'client/release/rollback-trust.json').read_text())
    assert trust == {'schema_version': 1, 'enabled': False, 'keys': []}
    signer = (ROOT / 'backend/service1/clientflow_rollback_signing.py').read_text()
    assert 'CLIENTFLOW_SIGNED_ROLLBACK_ENABLED' in signer
    assert '"false"' in signer
    assert 'CLIENTFLOW_ROLLBACK_SIGNING_KEY_PEM_B64' in signer
