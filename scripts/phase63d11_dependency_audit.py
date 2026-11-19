#!/usr/bin/env python3
"""Bounded, read-only Neon inventory for the 1244 release retirement review.

No deletion/deployment grants. Offline legacy clients and offsite backups MUST
be independently verified outside Neon, whatever this audit returns.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from sqlalchemy import text  # noqa: E402
from service1.db import engine, IS_PRODUCTION  # noqa: E402

RETIRED = 'clientflow-1.3.43-seq-1244'
MAX_ROWS = 1000


def read_inventory() -> dict:
    if not IS_PRODUCTION or not engine.url.drivername.startswith('postgresql'):
        raise RuntimeError('Only explicit production Postgres audit is supported')
    with engine.connect() as conn:
        # Transaction-scoped, never persists to the pool on rollback.
        conn.execute(text('SET TRANSACTION READ ONLY'))
        clients = conn.execute(text('''
            SELECT c.id, c.name, c.status, c.deleted_at,
                   s.agent_version, s.observed_state, s.reported_at
              FROM client c
              LEFT JOIN client_domain_status s
                ON s.client_id = c.id AND s.domain = 'status'
             ORDER BY c.id LIMIT :limit
        '''), {'limit': MAX_ROWS + 1}).mappings().all()
        deployments = conn.execute(text('''
            SELECT id, client_id, target_release_id, target_version,
                   state, completed_at, observed_previous_release_id
              FROM clientflow_deployment
             WHERE completed_at IS NULL
                OR target_release_id = :old_release
                OR observed_previous_release_id = :old_release
             ORDER BY requested_at DESC LIMIT :limit
        '''), {'old_release': RETIRED, 'limit': MAX_ROWS + 1}).mappings().all()
        controls = conn.execute(text('''
            SELECT revision, stable_release_id, cutover_enabled,
                   fleet_open, fresh_install_open
              FROM clientflow_release_control WHERE id = 1
        ''')).mappings().all()
        # Closing the connection rolls back SET TRANSACTION READ ONLY.
    if len(clients) > MAX_ROWS or len(deployments) > MAX_ROWS or len(controls) != 1:
        raise RuntimeError('Inventory bound exceeded or release control missing')
    control = controls[0]
    live = [row for row in clients if row['deleted_at'] is None and row['status'] == 'approved']
    old = [row for row in live if str(row['agent_version'] or '') in ('1.3.43', 'v1.3.43')]
    def fresh_status(row) -> bool:
        reported = row['reported_at']
        if reported is None or row['observed_state'] != 'online' or not row['agent_version']:
            return False
        if reported.tzinfo is None:
            reported = reported.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - reported.astimezone(timezone.utc)
        return timedelta(seconds=-5) <= age <= timedelta(seconds=90)

    unknown = [row for row in live if not fresh_status(row)]
    in_flight = [row for row in deployments if row['completed_at'] is None]
    historical = [row for row in deployments if row['target_release_id'] == RETIRED]
    flags_closed = all(control[k] is False for k in ('cutover_enabled', 'fleet_open', 'fresh_install_open'))
    return {
        'mode': 'read_only_neon_dependency_inventory',
        'retiring_release_id': RETIRED,
        'approved_live_client_count': len(live),
        'status_at_1244_client_ids': [int(row['id']) for row in old],
        'offline_or_unknown_status_client_ids': [int(row['id']) for row in unknown],
        'active_deployment_ids': [str(row['id']) for row in in_flight],
        'historical_1244_deployment_count': len(historical),
        'historical_1244_client_ids': sorted({int(row['client_id']) for row in historical}),
        'control_revision': int(control['revision']),
        'stable_release_id': control['stable_release_id'],
        'global_flags_closed': flags_closed,
        'unresolved_database_dependencies': bool(old or unknown or in_flight or not flags_closed),
        'offline_legacy_hosts_review_required': True,
        'offsite_1244_backup_independently_verified': False,
        'operator_no_dependencies_attestation_required': True,
        'deletion_authorized': False,
        'pilot_authorized': False,
    }


def main() -> int:
    try:
        result = read_inventory()
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        print('PHASE_63D11_DB_READ_ONLY=PASS')
        return 0
    except Exception as exc:
        print('PHASE_63D11_DB_READ_ONLY=STOP: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
