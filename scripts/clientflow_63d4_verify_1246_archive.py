#!/usr/bin/env python3
"""Offline read-only verification of the exact GitHub-approved 1246 TAR.

The CLI does NOT fetch, publish, sign, select or install a release.  Operators
must first download approved GitHub Release bytes to a trusted local path.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'client/release/lib'))

from clientflow_release.bundle import open_verified_bundle  # noqa: E402
from clientflow_release.constants import INSTALL_MODE_UPDATE  # noqa: E402
from service1.clientflow_pilot_1246 import (  # noqa: E402
    APPROVAL_REFERENCE, APPROVED_BUNDLE_SHA256, APPROVED_BUNDLE_SIZE,
    CANDIDATE_SHA256, INSTALLER_SHA256, PILOT_RELEASE_ID, SOURCE_COMMIT,
    approval_lock,
)
from service1.clientflow_release_pilot_stage_1246 import load_staged_catalog  # noqa: E402


class ArchivePreflightDenied(ValueError):
    pass


def verify_1246_archive(path: Path) -> dict:
    approval_lock()
    load_staged_catalog()
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ArchivePreflightDenied('Path must be an absolute regular non-symlink TAR')
    if path.stat().st_size != APPROVED_BUNDLE_SIZE:
        raise ArchivePreflightDenied('Approved TAR size mismatch')
    handle = None
    try:
        manifest, _payload, size, digest, handle = open_verified_bundle(
            path, require_deployable=True, required_install_mode=INSTALL_MODE_UPDATE,
        )
        approval = manifest.get('release_approval') or {}
        source = manifest.get('source') or {}
        installer = manifest.get('fresh_installer') or {}
        if (
            size != APPROVED_BUNDLE_SIZE or digest != APPROVED_BUNDLE_SHA256
            or manifest.get('version') != '1.3.45'
            or manifest.get('release_id') != PILOT_RELEASE_ID
            or type(manifest.get('release_sequence')) is not int
            or manifest['release_sequence'] != 1246
            or manifest.get('deployable') is not True
            or source != {'commit': SOURCE_COMMIT, 'dirty': False}
            or approval.get('reference') != APPROVAL_REFERENCE
            or approval.get('candidate_sha256') != CANDIDATE_SHA256
            or installer.get('sha256') != INSTALLER_SHA256
        ):
            raise ArchivePreflightDenied('Approved 1246 TAR provenance differs from locked GitHub approval')
        return {
            'status': 'VERIFIED_OFFLINE_ARCHIVE_ONLY',
            'release_id': PILOT_RELEASE_ID,
            'approved_bundle_sha256': APPROVED_BUNDLE_SHA256,
            'approved_bundle_size': APPROVED_BUNDLE_SIZE,
            'approval_reference': APPROVAL_REFERENCE,
            'source_commit': SOURCE_COMMIT,
            'published_to_render': False,
            'catalog_promoted': False,
            'deployment_authorized': False,
        }
    except ArchivePreflightDenied:
        raise
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        raise ArchivePreflightDenied('Approved 1246 TAR signature/structure could not be verified') from exc
    finally:
        if handle is not None:
            handle.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approved-tar', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify_1246_archive(args.approved_tar)
    except ArchivePreflightDenied as exc:
        print(f'CLIENTFLOW_1246_ARCHIVE_PREFLIGHT=STOP: {exc}', file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, indent=2))
    print('CLIENTFLOW_1246_ARCHIVE_PREFLIGHT=PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
