#!/usr/bin/env python3
"""Read-only post-deploy check of the 1244-only catalog and exact six-bundle store.

The verified sixth bundle was published in an earlier authorized operation.
This command CANNOT publish, delete, resume enrollment, or authorize physical installation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "client/release/lib"))

from service1.clientflow_releases import (  # noqa: E402
    ClientFlowCatalogError,
    load_catalog,
    resolve_fresh_install_release,
    resolve_release,
)
from scripts.audit_clientflow_release_retention import inspect_store  # noqa: E402
from scripts.clientflow_1244_transition_policy import (  # noqa: E402
    APPROVAL_REFERENCE,
    APPROVED_SHA256,
    APPROVED_SIZE,
    RELEASE_ID,
    SOURCE_COMMIT,
    require_exact_store,
    require_quiesced,
)

DEFAULT_STORE = Path("/var/data/clientflow-release-artifacts/store")


class PromotionPreflightDenied(RuntimeError):
    pass


def inspect_catalog_and_store(artifact_dir: Path) -> dict:
    """No writes; require pinned published state and 1244 as sole catalog selector."""
    require_quiesced()
    catalog = load_catalog()
    releases = catalog.get("releases")
    expected_policy = {
        "max_selectable_versions": 3,
        "max_installable_versions": 1,
        "keep_blocked_metadata": False,
    }
    if (
        catalog.get("catalog_sequence") != 1244
        or catalog.get("latest_stable") != "1.3.43"
        or catalog.get("default_install_version") != "1.3.43"
        or catalog.get("retention_policy") != expected_policy
        or not isinstance(releases, list)
        or len(releases) != 1
    ):
        raise PromotionPreflightDenied("Exact 1244-only catalog is not deployed")
    release = releases[0]
    if any((
        release.get("release_id") != RELEASE_ID,
        release.get("version") != "1.3.43",
        release.get("release_sequence") != 1244,
        release.get("status") != "stable",
        release.get("installable") is not True,
        release.get("install_modes") != ["fresh_install"],
        release.get("update_allowed") is not False,
        release.get("rollback_allowed") is not False,
        release.get("requires_explicit_downgrade") is not False,
    )):
        raise PromotionPreflightDenied("1244 release selector is not fresh-only and rollback-disabled")
    if any(pin not in " ".join(release.get("notes") or []) for pin in (
        APPROVED_SHA256, str(APPROVED_SIZE), SOURCE_COMMIT, APPROVAL_REFERENCE,
    )):
        raise PromotionPreflightDenied("1244 approval provenance is missing from catalog notes")
    if resolve_fresh_install_release().get("release_id") != RELEASE_ID:
        raise PromotionPreflightDenied("Fresh-install selector differs from approved 1244")
    for historical_version in ("1.3.38", "1.3.39", "1.3.40", "1.3.41", "1.3.42"):
        try:
            resolve_release(historical_version)
        except ClientFlowCatalogError:
            continue
        raise PromotionPreflightDenied("Retired historical release is selectable")
    try:
        resolve_release("1.3.43")
    except ClientFlowCatalogError:
        pass
    else:
        raise PromotionPreflightDenied("1244 must not become an unapproved in-place update")
    snapshot = inspect_store(artifact_dir)
    require_exact_store(snapshot, after=True)
    return {
        "mode": "read_only_post_catalog_promotion",
        "catalog_sequence": 1244,
        "latest_stable": catalog["latest_stable"],
        "default_install_version": catalog["default_install_version"],
        "selectable_releases": [RELEASE_ID],
        "verified_store_count": snapshot["approved_count"],
        "expected_store_count_before_cleanup": 6,
        "oldest_first_cleanup_requires_separate_approval": True,
        "fresh_install_suspended": True,
        "automatic_deletion_enabled": snapshot["automatic_deletion_enabled"],
        "rollback_enabled": snapshot["rollback_enabled"],
        "approved_sha256": APPROVED_SHA256,
        "artifact_dir": str(artifact_dir),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_STORE)
    args = parser.parse_args(argv)
    try:
        result = inspect_catalog_and_store(args.artifact_dir)
    except (OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
        print(f"CLIENTFLOW_1244_CATALOG_PREFLIGHT=STOP: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    print("CLIENTFLOW_1244_CATALOG_PREFLIGHT=READ_ONLY_PASS")
    print("CLIENTFLOW_1244_STORE_CLEANUP=SEPARATE_APPROVAL_REQUIRED")
    print("CLIENTFLOW_1244_INSTALL=NOT_AUTHORIZED_HERE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
