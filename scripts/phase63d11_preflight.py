#!/usr/bin/env python3
"""Read-only 1247 source/retention release gate. No network, DB, mutation or deployment."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'backend')]
from scripts.audit_clientflow_release_retention import inspect_store
from scripts.prune_clientflow_release_retention import plan_cleanup
from service1.clientflow_pilot_1247 import (approval_lock_1247, PILOT_RELEASE_ID,
                                             APPROVED_BUNDLE_SHA256, APPROVED_BUNDLE_SIZE)
from service1.clientflow_release_pilot_stage_1247 import load_staged_catalog_1247


def inspect(directory: Path) -> dict:
    approval_lock_1247()
    staged = load_staged_catalog_1247()
    snapshot = inspect_store(directory)
    cleanup = plan_cleanup(directory)
    expected = [('clientflow-1.3.45-seq-1246', 1246),
                ('clientflow-1.3.44-seq-1245', 1245),
                ('clientflow-1.3.43-seq-1244', 1244)]
    rows = snapshot['protected_latest'] + snapshot['older_review_only']
    if [(row['release_id'], row['release_sequence']) for row in rows] != expected:
        raise ValueError('Expected exact 1244/1245/1246 approved store before rotation')
    if cleanup['prune_candidate']['release_id'] != 'clientflow-1.3.43-seq-1244':
        raise ValueError('Unanticipated oldest cleanup candidate')
    if cleanup['catalog_pin_blocks_cleanup']:
        raise ValueError('Oldest release is still catalog-pinned')
    if snapshot['invalid_artifacts'] or snapshot['approved_count'] != 3:
        raise ValueError('Release store is not fully verified')
    if staged['catalog_sequence'] != 1247:
        raise ValueError('Wrong staged catalog')
    return {
       'release_id': PILOT_RELEASE_ID, 'approved_sha256': APPROVED_BUNDLE_SHA256,
       'approved_size': APPROVED_BUNDLE_SIZE,
       'store': snapshot, 'cleanup': cleanup,
       'deployment_authorized': False,
       'pilot_authorized': False,
       'render_publication_authorized': False,
       'external_backup_verified': False,
       'offline_client_dependencies_verified': False,
       'next': 'External offsite 1244 backup + dependency review, then separate approved one-bundle cleanup; rerun audit before publication',
    }


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-dir', type=Path, required=True)
    args=parser.parse_args()
    try:
        result=inspect(args.artifact_dir)
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        print('PHASE_63D11_READ_ONLY_PREFLIGHT=PASS')
        return 0
    except (Exception,) as exc:
        print('PHASE_63D11_READ_ONLY_PREFLIGHT=STOP: '+str(exc), file=sys.stderr)
        return 1
if __name__=='__main__':
    raise SystemExit(main())
