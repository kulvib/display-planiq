"""Read-only 1246 GitHub-approved pilot source staging, never a deployment grant.

Source-lock / staged catalog are immutable evidence to help human operators
prepare an offline verified 1246 publication. Neither is active catalog state.
No network, database writes, environment toggles, signing or release promotion.
"""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any

from . import clientflow_pilot_1246 as pilot

STAGED_CATALOG_PATH = Path(__file__).with_name('clientflow_release_catalog_1246_pilot.stage.json')
# Full-file pin of the immutable reviewed stage, not only selected JSON fields.
EXPECTED_STAGED_CATALOG_SHA256 = 'c416efdf9f5794e7bd7b48c355fbf91c77cfe691a6fbd46b6a489ef3f3052c8a'


class PilotStageDenied(ValueError):
    pass


def load_staged_catalog() -> dict[str, Any]:
    """Require one stable 1245 and an exact update-only 1246 candidate."""
    try:
        if STAGED_CATALOG_PATH.is_symlink() or STAGED_CATALOG_PATH.stat().st_size > 12000:
            raise ValueError('invalid_catalog_file')
        content = STAGED_CATALOG_PATH.read_bytes()
        if hashlib.sha256(content).hexdigest() != EXPECTED_STAGED_CATALOG_SHA256:
            raise ValueError('changed_pilot_source_bytes')
        stage = json.loads(content.decode('utf-8'))
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise PilotStageDenied('1246-pilotkataloget er ikke verificerbart') from exc
    if not isinstance(stage, dict) or set(stage) != {
        'manifest_schema', 'channel', 'catalog_sequence', 'latest_stable',
        'default_install_version', 'retention_policy', 'releases',
    } or stage['manifest_schema'] != 4 or stage['channel'] != 'canonical-release-catalog' or type(stage['catalog_sequence']) is not int or stage['catalog_sequence'] != 1246:
        raise PilotStageDenied('1246-pilotkatalogets schema eller sekvens er ugyldig')
    if stage['latest_stable'] != '1.3.44' or stage['default_install_version'] != '1.3.44':
        raise PilotStageDenied('1246-piloten må ikke have en uafhængig fresh-install-standard')
    retention = stage['retention_policy']
    if not isinstance(retention, dict) or retention != {
        'max_selectable_versions': 3, 'max_installable_versions': 1,
        'keep_blocked_metadata': False,
    }:
        raise PilotStageDenied('1246-piloten mangler tre-release recovery-politikken')
    releases = stage['releases']
    if not isinstance(releases, list) or len(releases) != 2 or any(not isinstance(row, dict) for row in releases):
        raise PilotStageDenied('1246-piloten kræver stabil 1245 + særskilt update-only 1246')
    stable, release = releases
    if any(stable.get(k) != value for k, value in {
        'version': '1.3.44', 'client_version': '1.3.44',
        'release_id': 'clientflow-1.3.44-seq-1245',
        'release_sequence': 1245, 'status': 'stable',
        'installable': True, 'update_allowed': True,
        'install_modes': ['fresh_install', 'in_place_update'],
        'rollback_allowed': False,
    }.items()):
        raise PilotStageDenied('1245 skal fortsat være uændret stabil/fresh-install standard')
    required = {
        'version': '1.3.45', 'client_version': '1.3.45',
        'release_sequence': 1246, 'revision': pilot.PILOT_RELEASE_ID,
        'release_id': pilot.PILOT_RELEASE_ID, 'status': 'supported',
        'installable': False, 'update_allowed': True,
        'rollback_allowed': False, 'requires_explicit_downgrade': False,
        'requires_reboot': True, 'artifact_type': 'runtime_release',
        'install_modes': ['in_place_update'],
        'min_current_version': '1.3.43', 'max_current_version': '1.3.44',
    }
    if any(type(release.get(k)) is not type(v) or release.get(k) != v for k, v in required.items()):
        raise PilotStageDenied('1246-pilotkatalogets godkendte releaseidentitet er ændret')
    os_info = release.get('ubuntu_compatibility')
    if not isinstance(os_info, dict) or any(os_info.get(k) != v for k, v in {
        'policy':'ubuntu-desktop-lts-minimum', 'minimum_lts_version':'26.04',
        'maximum_certified_version':'26.04', 'certified_versions':['26.04'],
        'architecture':'amd64', 'desktop':'gnome', 'display_stack':'wayland',
        'requires_platform_preflight':True,
    }.items()):
        raise PilotStageDenied('1246-pilotens Ubuntu 26.04-kontrakt er ændret')
    return stage



def validated_catalog_mode(*, active_catalog: dict[str, Any]) -> str:
    """Recognize ONLY pinned stable-1245 or the entire exact 1246 pilot stage.

    Exact full-record comparison (including notes, policy and compatibility)
    prevents an accidental two-entry catalog from silently widening pilot
    eligibility. This is a read-only classifier, NEVER a deployment grant.
    """
    pilot.approval_lock()
    staged = load_staged_catalog()
    if not isinstance(active_catalog, dict):
        raise PilotStageDenied('Aktivt releasekatalog er ugyldigt')
    # The published 1245 baseline must match the locked staged copy byte-for-
    # byte at the structured-data level, independently of catalog sequence.
    stable = staged['releases'][0]
    base = {**staged,
            'catalog_sequence': 1245,
            'releases': [stable]}
    if active_catalog == base:
        return 'stable_1245_only'
    if active_catalog == staged:
        return 'update_only_1246_pilot_catalog'
    raise PilotStageDenied('Releasekataloget er ikke eksakt stabil 1245 eller godkendt 1246 pilotkatalog')


def staged_pilot_summary(*, active_catalog: dict[str, Any]) -> dict[str, Any]:
    """Operator-facing, strict / no publication inference, no installation permission."""
    mode = validated_catalog_mode(active_catalog=active_catalog)
    pilot_catalog_active = mode == 'update_only_1246_pilot_catalog'
    return {
        'schema_version': 1,
        'phase': 'approved_github_archive_source_staged_only',
        'release_id': pilot.PILOT_RELEASE_ID,
        'version': pilot.PILOT_TO_VERSION,
        'sequence': 1246,
        'source_commit': pilot.SOURCE_COMMIT,
        'approved_bundle_sha256': pilot.APPROVED_BUNDLE_SHA256,
        'approved_bundle_size': pilot.APPROVED_BUNDLE_SIZE,
        'approval_reference': pilot.APPROVAL_REFERENCE,
        'active_release_id': 'clientflow-1.3.44-seq-1245',
        'pilot_client_id': pilot.PILOT_CLIENT_ID,
        'github_artifact_approval_pinned': True,
        'render_store_publication_verified': False,
        'active_catalog_promoted': pilot_catalog_active,
        'physical_pilot_accepted': False,
        'deployment_authorized': False,
        'fleet_authorized': False,
        'fresh_install_authorized': False,
        'database_cutover_authorized': False,
    }
