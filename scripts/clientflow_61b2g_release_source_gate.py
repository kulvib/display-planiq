#!/usr/bin/env python3
"""Offline, read-only 61B-2 source/candidate identity gate (NEVER approval).

The currently approved 1.3.44/1245 remains immutable. A successful result
proves only source integrity and eligibility for an *unsigned* independent
candidate build, not a working client, deployment authorization, or pilot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from clientflow_63d6_active_catalog_contract import projected_stable_1245, verified_mode

BASELINE_VERSION = (1, 3, 44)
BASELINE_SEQUENCE = 1245
EXPECTED_CANDIDATE_VERSION = (1, 4, 1)
EXPECTED_CANDIDATE_SEQUENCE = 1251
SHA_RE = re.compile(r'[0-9a-f]{64}\Z')
VERSION_RE = re.compile(r'\d+\.\d+\.\d+\Z')
REQUIRED_SOURCES = (
    'client/VERSION',
    'client/release/release-input.json',
    'client/release/lib/clientflow_release/install_coordinator.py',
    'client/runtime/clientflow_runtime/install_coordinator.py',
    'client/release/lib/clientflow_release/update_controller.py',
    'client/release/lib/clientflow_release/transaction.py',
    'client/release/lib/clientflow_release/cli.py',
    'client/release/lib/clientflow_release/release_public_status.py',
    'client/runtime/clientflow_runtime/release_public_status.py',
    'client/runtime/clientflow_runtime/system_broker.py',
    'client/runtime/clientflow_runtime/display_runtime.py',
    'client/libexec/update-maintenance-screen',
    'client/stable-systemd/planiq-display-maintenance.service',
    'scripts/clientflow_61b2f_pilot_preflight_readonly.py',
    'client/release/lib/clientflow_release/builder.py',
    'backend/service1/clientflow_release_catalog.json',
    'backend/service1/clientflow_pilot_1245_approval.json',
    'backend/service1/clientflow_pilot_1250_approval.json',
    'backend/service1/clientflow_1245_fleet_acceptance.json',
)


def _relative_filename(filename: str) -> bool:
    try:
        path = PurePosixPath(filename)
    except (TypeError, ValueError):
        return False
    return (filename == path.as_posix() and not path.is_absolute()
            and len(path.parts) > 0 and all(part not in ('', '.', '..') for part in path.parts)
            and '\\' not in filename)


def _read(root: Path, name: str) -> bytes:
    if not _relative_filename(name):
        raise ValueError('invalid_relative_filename')
    path = root / name
    if path.is_symlink() or not path.is_file():
        raise ValueError('missing_or_symlinked_source')
    return path.read_bytes()


def _verify_manifest(root: Path) -> dict:
    manifest = _read(root, 'SHA256SUMS.txt').decode('utf-8')
    hashes: dict[str, str] = {}
    for line in manifest.splitlines():
        if not line:
            continue
        match = re.fullmatch(r'([0-9a-f]{64})  ([^\r\n]+)', line)
        if match is None:
            raise ValueError('invalid_sha256_manifest_record')
        digest, filename = match.groups()
        if not _relative_filename(filename) or filename in hashes or filename == 'SHA256SUMS.txt':
            raise ValueError('unsafe_or_duplicate_manifest_path')
        hashes[filename] = digest
    if not hashes or not set(REQUIRED_SOURCES).issubset(hashes):
        raise ValueError('missing_required_manifest_sources')
    for filename, expected in hashes.items():
        if hashlib.sha256(_read(root, filename)).hexdigest() != expected:
            raise ValueError('sha256_mismatch')
    return hashes


def _identity(root: Path) -> tuple[str, int]:
    raw_version = _read(root, 'client/VERSION').decode('ascii').strip()
    if not VERSION_RE.fullmatch(raw_version):
        raise ValueError('invalid_source_version')
    value = json.loads(_read(root, 'client/release/release-input.json'))
    if (not isinstance(value, dict) or value.get('schema_version') != 1
            or type(value.get('release_sequence')) is not int
            or value['release_sequence'] <= 0):
        raise ValueError('invalid_release_input')
    return raw_version, value['release_sequence']


def inspect(root: Path) -> dict:
    """Observe only tracked bytes; never access network, systemd, secrets or locks."""
    if not root.is_absolute() or root.is_symlink():
        raise ValueError('source_root_must_be_absolute_real_directory')
    checks: dict[str, dict] = {}

    def check(key: str, fn):
        try:
            detail = fn()
            checks[key] = {'pass': True, 'detail': detail}
            return detail
        except (OSError, ValueError, UnicodeError, TypeError, KeyError, json.JSONDecodeError) as exc:
            checks[key] = {'pass': False, 'detail': type(exc).__name__}
            return None

    hashes = check('complete_sha256_manifest', lambda: _verify_manifest(root))
    if isinstance(hashes, dict):
        checks['complete_sha256_manifest']['detail'] = f'{len(hashes)}_entries_verified'

    def source_contract():
        a = _read(root, 'client/release/lib/clientflow_release/install_coordinator.py')
        b = _read(root, 'client/runtime/clientflow_runtime/install_coordinator.py')
        if a != b:
            raise ValueError('coordinator_implementations_diverged')
        controller = _read(root, 'client/release/lib/clientflow_release/update_controller.py')
        broker = _read(root, 'client/runtime/clientflow_runtime/system_broker.py')
        rollback = _read(root, 'client/release/lib/clientflow_release/transaction.py')
        for code in (controller, broker, rollback):
            if b'install_coordinator.claim(' not in code or b'install_coordinator.release(' not in code:
                raise ValueError('missing_install_lock_contract')
        unit = _read(root, 'client/stable-systemd/planiq-display-maintenance.service')
        for required in (b'NoNewPrivileges=yes', b'RestrictAddressFamilies=AF_UNIX',
                         b'ProtectSystem=strict', b'/usr/lib/clientflow/maintenance/host-screen'):
            if required not in unit:
                raise ValueError('host_service_hardening_missing')
        builder = _read(root, 'client/release/lib/clientflow_release/builder.py')
        for required in (b'client/libexec', b'client/stable-systemd',
                         b'client/release/lib/clientflow_release'):
            if required not in builder:
                raise ValueError('release_payload_mapping_missing')
        if b'update-maintenance-screen' not in builder:
            raise ValueError('host_screen_not_mapped')
        # Candidate source must include the durable first-claim to healthy
        # first-activation bridge; it must never silently fall back to the
        # older independent first-install transaction.
        cli_source = _read(root, 'client/release/lib/clientflow_release/cli.py')
        coordinator = _read(root, 'client/release/lib/clientflow_release/install_coordinator.py')
        runtime_coordinator = _read(root, 'client/runtime/clientflow_runtime/install_coordinator.py')
        if coordinator != runtime_coordinator:
            raise ValueError('global_install_coordinators_diverged')
        for required in (b"'fresh_install'", b'def _fresh_coordination_root',
                         b'def _only_idle_coordinator_remains',
                         b'install_coordinator.claim(', b'install_coordinator.release('):
            if required not in cli_source and required not in coordinator:
                raise ValueError('fresh_install_coordination_contract_missing')
        # A new candidate must serialize the *preclaim apt upgrade*, which
        # runs before enrollment authority consumption, against the global
        # ClientFlow/Ubuntu/firmware coordinator. Source-only check: not a
        # physical host proof or a deployment authorization.
        if (b'with install_coordinator.preclaim_host_guard(' not in cli_source
                or b'existing_install_id=' not in cli_source
                or b'def preclaim_host_guard(' not in coordinator
                or b"claim(owner='preclaim_host'" not in coordinator
                or b"claim(owner='fresh_install'" not in coordinator
                or b'LOCK_EX | fcntl.LOCK_NB' not in coordinator):
            raise ValueError('missing_preclaim_shared_install_lock_contract')
        for required in (b"coordinator_state.get('owner') != 'fresh_install'",
                         b"owner='fresh_install', operation_id=fresh_install_id"):
            if required not in rollback:
                raise ValueError('fresh_first_activation_proof_missing')
        build_entrypoint = _read(root, 'scripts/build_clientflow_release.py')
        if b'str(repo / "client" / "runtime")' not in build_entrypoint:
            raise ValueError('client_runtime_wheel_build_missing')
        return '61b2_source_and_promotion_contracts_present'

    check('installation_and_maintenance_source_contracts', source_contract)

    def approval_contract():
        build = _read(root, '.github/workflows/release-build.yml')
        approval = _read(root, '.github/workflows/release-approve.yml')
        if (b'run: python scripts/clientflow_61b2g_release_source_gate.py --repo-root ' not in build
                or b'clientflow_61b2g_release_source_gate.py --repo-root "$GITHUB_WORKSPACE" --source-only' in build):
            raise ValueError('release_build_must_refuse_old_identity')
        for required in (b'expected_source_sha', b'candidate-runtime:',
                         b'reproducibility:', b'REPRODUCIBILITY.json'):
            if required not in build:
                raise ValueError('release_build_provenance_gate_missing')
        for required in (b'approve_release', b'test "$APPROVE_RELEASE" = "true"',
                         b'expected_candidate_sha256', b'expected_installer_sha256'):
            if required not in approval:
                raise ValueError('manual_approval_gate_missing')
        return 'separate_reproducible_build_and_explicit_approval_required'

    check('release_provenance_and_manual_approval_contracts', approval_contract)

    def stable_1245_still_immutable():
        # Candidate source is not a new catalog entry. This check intentionally
        # uses the original APPROVED artifact and rollout evidence; a new
        # version can only be published after separate, explicit acceptance.
        # The 1246 catalog is a separately pinned, update-only operator
        # selector; this audit never confers installer/deployment permission.
        verified_mode(root)
        catalog = projected_stable_1245(root)
        approval = json.loads(_read(root, 'backend/service1/clientflow_pilot_1245_approval.json'))
        fleet = json.loads(_read(root, 'backend/service1/clientflow_1245_fleet_acceptance.json'))
        rows = catalog.get('releases')
        if not (catalog.get('catalog_sequence') == BASELINE_SEQUENCE
                and catalog.get('latest_stable') == catalog.get('default_install_version') == '1.3.44'
                and isinstance(rows, list) and len(rows) == 1
                and isinstance(rows[0], dict)
                and rows[0].get('release_id') == 'clientflow-1.3.44-seq-1245'
                and rows[0].get('release_sequence') == BASELINE_SEQUENCE
                and rows[0].get('status') == 'stable'
                and rows[0].get('install_modes') == ['fresh_install', 'in_place_update']
                and rows[0].get('rollback_allowed') is False
                and approval.get('approved') is True
                and approval.get('release_id') == 'clientflow-1.3.44-seq-1245'
                and rows[0].get('version') == rows[0].get('client_version') == '1.3.44'
                and approval.get('approved_bundle_sha256') ==
                    '28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5'
                and approval.get('approved_bundle_size') == 223610880
                and approval.get('source_commit') == '06857104952ebb40bf1394c423c01332d28f8d5e'
                and approval.get('candidate_sha256') ==
                    'ffe58332c8e3b263e00f299e363dc95ecb9ac7e0176fd51888be98fecad9bd97'
                and approval.get('installer_sha256') ==
                    'fc843b6b37772996ecbfa67ff08a0e6f372443bf7d6104ca28d616855bc5737a'
                and approval.get('approval_reference') ==
                    'CF-1.3.44-1245-20261114-0685710-ffe58332-R2'
                and fleet.get('release_id') == 'clientflow-1.3.44-seq-1245'
                and fleet.get('approved_bundle_sha256') == approval.get('approved_bundle_sha256')
                and fleet.get('physical_pilot_accepted') is False):
            raise ValueError('candidate_must_not_modify_approved_stable_or_approval')
        return '1245_stays_sole_stable_target_1246_update_only_separately_gated'

    check('unchanged_approved_stable_catalog_and_disarmed_pilot', stable_1245_still_immutable)
    def immutable_1250():
        raw = _read(root, 'backend/service1/clientflow_pilot_1250_approval.json')
        if hashlib.sha256(raw).hexdigest() != 'fc851982c39de0b7f92b9274f822b70bf61ca014bcbd88e62d7570a08d58f334':
            raise ValueError('approved_1250_lock_changed')
        return 'approved_1250_lock_preserved'

    check('unchanged_approved_1250_lock', immutable_1250)
    identity = check('release_source_identity', lambda: _identity(root))
    version = identity[0] if identity is not None else None
    sequence = identity[1] if identity is not None else None
    # Only the explicitly staged NEXT candidate is eligible for build; do not
    # infer approval for arbitrary future versions from mere monotonicity.
    candidate_identity = bool(identity is not None and
        tuple(int(x) for x in version.split('.')) == EXPECTED_CANDIDATE_VERSION and
        sequence == EXPECTED_CANDIDATE_SEQUENCE)
    source_ok = all(row['pass'] for row in checks.values())
    return {
        'schema_version': 1,
        'kind': 'offline_readonly_release_source_gate',
        'source_verified': source_ok,
        'version': version,
        'release_sequence': sequence,
        'stable_baseline': 'clientflow-1.3.44-seq-1245',
        'candidate_identity_advanced': candidate_identity,
        'result': ('SOURCE_INVALID' if not source_ok else
                   'READY_FOR_UNSIGNED_CANDIDATE_BUILD' if candidate_identity else
                   'STOP_STABLE_SOURCE_NOT_A_NEW_CANDIDATE'),
        'deployment_authorized': False,
        'release_approved': False,
        'signature_verified': False,
        'pilot_accepted': False,
        'fresh_install_concurrency_proven': False,
        'checks': checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--source-only', action='store_true', help='PASS for unchanged stable source; does not authorize build')
    args = parser.parse_args(argv)
    report = inspect(args.repo_root)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if not report['source_verified']:
        return 2
    return 0 if args.source_only or report['candidate_identity_advanced'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
