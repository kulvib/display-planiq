"""1247 signed-source pilot stage. No catalog promotion, deployment or database mutation."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any
from . import clientflow_pilot_1247 as pilot
from .clientflow_release_pilot_stage_1246 import load_staged_catalog as load_1246

STAGED_CATALOG_PATH = Path(__file__).with_name('clientflow_release_catalog_1247_pilot.stage.json')
EXPECTED_STAGED_CATALOG_SHA256 = 'd54fa0438b020461a668fad241bf08c5e64dcae9befd0b4a7bdc6dac97fc9cd9'

class PilotStage1247Denied(ValueError):
    pass


def load_staged_catalog_1247() -> dict[str, Any]:
    """Require hash of the entire source and exact preservation of prior approvals."""
    pilot.approval_lock_1247()
    try:
        if STAGED_CATALOG_PATH.is_symlink() or STAGED_CATALOG_PATH.stat().st_size > 16000:
            raise ValueError('unsafe_source')
        raw = STAGED_CATALOG_PATH.read_bytes()
        if hashlib.sha256(raw).hexdigest() != EXPECTED_STAGED_CATALOG_SHA256:
            raise ValueError('catalog_digest_changed')
        stage = json.loads(raw)
        prior = load_1246()
        if not isinstance(stage, dict) or set(stage) != set(prior):
            raise ValueError('catalog_schema_changed')
        if stage.get('catalog_sequence') != 1247 or stage.get('releases', [])[:2] != prior['releases']:
            raise ValueError('historical_approvals_changed')
        if any(stage[k] != prior[k] for k in ('manifest_schema', 'channel', 'latest_stable',
                                             'default_install_version', 'retention_policy')):
            raise ValueError('stable_policy_changed')
        rows = stage['releases']
        if not isinstance(rows, list) or len(rows) != 3:
            raise ValueError('wrong_release_count')
        row = rows[2]
        identity = {
            'release_id': pilot.PILOT_RELEASE_ID, 'revision': pilot.PILOT_RELEASE_ID,
            'version': '1.3.46', 'client_version': '1.3.46',
            'release_sequence': 1247, 'status': 'supported',
            'installable': False, 'update_allowed': True,
            'rollback_allowed': False, 'requires_explicit_downgrade': False,
            'requires_reboot': True, 'artifact_type': 'runtime_release',
            'install_modes': ['in_place_update'], 'min_current_version': '1.3.45',
            'max_current_version': '1.3.45',
        }
        if not isinstance(row, dict) or any(type(row.get(k)) is not type(v) or row.get(k) != v for k,v in identity.items()):
            raise ValueError('unsigned_or_wrong_pilot_identity')
        if row.get('ubuntu_compatibility') != rows[1].get('ubuntu_compatibility'):
            raise ValueError('platform_contract_changed')
        return stage
    except (OSError, ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise PilotStage1247Denied('Det eksakte, godkendte 1247-pilotkatalog kan ikke verificeres') from exc


def validated_catalog_mode_1247(*, active_catalog: dict[str, Any]) -> str:
    """Classification is not permission; the active catalog must match byte-pinned stage."""
    stage = load_staged_catalog_1247()
    if active_catalog != stage:
        raise PilotStage1247Denied('Aktivt katalog er ikke eksakt reviewet 1247 update-only stage')
    return 'update_only_1247_pilot_catalog'


def staged_pilot_summary_1247(*, active_catalog: dict[str, Any]) -> dict[str, Any]:
    validated_catalog_mode_1247(active_catalog=active_catalog)
    return {
        'schema_version': 1, 'phase': 'approved_github_archive_source_staged_only',
        'release_id': pilot.PILOT_RELEASE_ID, 'version': '1.3.46', 'sequence': 1247,
        'source_commit': pilot.SOURCE_COMMIT,
        'approved_bundle_sha256': pilot.APPROVED_BUNDLE_SHA256,
        'approved_bundle_size': pilot.APPROVED_BUNDLE_SIZE,
        'approval_reference': pilot.APPROVAL_REFERENCE,
        'active_release_id': 'clientflow-1.3.44-seq-1245',
        'pilot_client_id': pilot.PILOT_CLIENT_ID,
        'github_artifact_approval_pinned': True,
        'render_store_publication_verified': False,
        'active_catalog_promoted': True,
        'physical_pilot_accepted': False,
        'deployment_authorized': False, 'fleet_authorized': False,
        'fresh_install_authorized': False, 'database_cutover_authorized': False,
    }
