#!/usr/bin/env python3
"""Fail-closed, operator-authorized cleanup of ONE oldest approved bundle.

Default mode is read-only. The operator must independently verify that no
client (including offline clients), deployment, pinned recovery or install
process needs the target. This script cannot prove that fleet-wide fact.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "client" / "release" / "lib"))

from clientflow_release.crypto import sha256_fd  # noqa: E402
from scripts.audit_clientflow_release_retention import (  # noqa: E402
    KEEP_LATEST_APPROVED,
    StoreAuditError,
    inspect_store,
)
from scripts.publish_clientflow_release import (  # noqa: E402
    _open_published_file,
    _open_secure_directory,
)


class PruneDenied(RuntimeError):
    pass


CATALOG_PATH = ROOT / "backend/service1/clientflow_release_catalog.json"


def _catalog_pinned_release_ids() -> set[str]:
    """Read the current runtime selector, never infer pins from source release identity.

    The still-active fresh-install/default release must never be pruned merely
    because it has become older than the latest approved bundles. This check
    is independent of the operator's offline-client dependency attestation.
    """
    try:
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise PruneDenied("Unable to verify active release catalog pins") from exc
    releases = catalog.get("releases")
    if not isinstance(releases, list):
        raise PruneDenied("Active release catalog has no valid release list")
    pins = set()
    stable = catalog.get("latest_stable")
    default = catalog.get("default_install_version")
    if not isinstance(stable, str) or not isinstance(default, str):
        raise PruneDenied("Stable/default release selectors are missing")
    for row in releases:
        if not isinstance(row, dict):
            raise PruneDenied("Malformed release catalog entry")
        version = row.get("version")
        release_id = row.get("release_id")
        if not isinstance(version, str) or not isinstance(release_id, str):
            raise PruneDenied("Invalid catalog release identity")
        if version in {stable, default} or row.get("installable") is True:
            if not re.fullmatch(r"clientflow-\d+\.\d+\.\d+-seq-[1-9]\d*", release_id):
                raise PruneDenied("Invalid pinned release identity")
            if not release_id.startswith(f"clientflow-{version}-seq-"):
                raise PruneDenied("Pinned catalog release ID and version disagree")
            pins.add(release_id)
    if not pins or stable not in {row["version"] for row in releases} or default not in {row["version"] for row in releases}:
        raise PruneDenied("Stable/default release selectors are not resolvable")
    return pins


def plan_cleanup(directory: Path) -> dict:
    """Read-only: report ONLY the oldest verified bundle, including catalog pins.

    A store with four or five approved bundles can be gradually reconciled to
    the new three-release limit. No automatic deletion or arbitrary skipping
    over older, pinned baseline releases is possible.
    """
    snapshot = inspect_store(directory)
    approved_count = snapshot["approved_count"]
    if approved_count not in {KEEP_LATEST_APPROVED, KEEP_LATEST_APPROVED + 1, KEEP_LATEST_APPROVED + 2}:
        raise PruneDenied("Cleanup requires three, four or five verified approved bundles")
    candidate = (snapshot["protected_latest"] + snapshot["older_review_only"])[-1]
    protected = (snapshot["protected_latest"] + snapshot["older_review_only"])[:-1]
    pins = _catalog_pinned_release_ids()
    blocked = candidate["release_id"] in pins
    return {
        "mode": "read_only",
        "approved_count_before": approved_count,
        "approved_count_after": approved_count - 1,
        "remaining_excess_after": max(0, approved_count - 1 - KEEP_LATEST_APPROVED),
        "protected": [x["release_id"] for x in protected],
        "prune_candidate": candidate,
        "dependency_review_required": True,
        "catalog_pinned_release_ids": sorted(pins),
        "catalog_pin_blocks_cleanup": blocked,
        "deleted": False,
    }


def prune_one_oldest(
    directory: Path,
    *,
    expected_release_id: str,
    expected_sha256: str,
    confirm_prune: bool = False,
    confirm_no_dependencies: bool = False,
) -> dict:
    if not re.fullmatch(r"clientflow-\d+\.\d+\.\d+-seq-[1-9]\d*", expected_release_id):
        raise PruneDenied("Expected canonical release ID is required")
    if re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise PruneDenied("Exact approved SHA-256 required")
    if confirm_prune != confirm_no_dependencies:
        raise PruneDenied("Both explicit prune and independent dependency attestation are required")
    if not confirm_prune:
        plan = plan_cleanup(directory)
        if (plan["prune_candidate"]["release_id"] != expected_release_id
                or plan["prune_candidate"]["sha256"] != expected_sha256):
            raise PruneDenied("Expected release identity does not match verified oldest")
        return plan

    fd = _open_secure_directory(directory)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        st = os.fstat(fd)
        current = directory.stat(follow_symlinks=False)
        if not stat.S_ISDIR(current.st_mode) or (st.st_dev, st.st_ino) != (current.st_dev, current.st_ino):
            raise PruneDenied("Release-store directory changed")
        plan = plan_cleanup(directory)
        if plan["catalog_pin_blocks_cleanup"]:
            raise PruneDenied("Cannot delete active stable/default or installable catalog release")
        candidate = plan["prune_candidate"]
        if candidate["release_id"] != expected_release_id or candidate["sha256"] != expected_sha256:
            raise PruneDenied("Refusing cleanup: oldest approved release identity changed")
        name = expected_release_id + ".tar"
        file_fd = _open_published_file(fd, name)
        try:
            descriptor_meta = os.fstat(file_fd)
            path_meta = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if (descriptor_meta.st_dev, descriptor_meta.st_ino) != (path_meta.st_dev, path_meta.st_ino):
                raise PruneDenied("Bundle changed between inventory and deletion")
            size, sha = sha256_fd(file_fd)
            if (size, sha) != (candidate["size_bytes"], expected_sha256):
                raise PruneDenied("Approved bundle bytes changed before cleanup")
            # No unverified path or glob is ever passed to unlink.
            os.unlink(name, dir_fd=fd)
            os.fsync(fd)
        finally:
            os.close(file_fd)
        after = inspect_store(directory)
        if after["approved_count"] != plan["approved_count_after"]:
            raise PruneDenied("Post-cleanup inventory count changed unexpectedly")
        # Reconciliation from five to three proceeds one independently approved
        # deletion at a time. A four-bundle intermediate state is not PASS for
        # the strict three-release policy, but is safe to resume or stop.
        if after["approved_count"] <= KEEP_LATEST_APPROVED and not after["within_approved_limit"]:
            raise PruneDenied("Post-cleanup inventory violates the three-release limit")
        if any(x["release_id"] not in plan["protected"] for x in after["protected_latest"]):
            raise PruneDenied("Post-cleanup inventory changed unexpectedly")
        return {
            "mode": "explicit_authorized_cleanup",
            "deleted": True,
            "removed_release_id": expected_release_id,
            "removed_sha256": expected_sha256,
            "approved_count_after": after["approved_count"],
            "remaining_excess": max(0, after["approved_count"] - KEEP_LATEST_APPROVED),
            "protected": [x["release_id"] for x in after["protected_latest"]],
            "automatic_deletion_enabled": False,
        }
    finally:
        os.close(fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--expected-release-id")
    parser.add_argument("--expected-sha256")
    parser.add_argument("--confirm-prune", action="store_true")
    parser.add_argument("--confirm-no-dependencies", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.confirm_prune or args.confirm_no_dependencies:
            if args.expected_release_id is None or args.expected_sha256 is None:
                raise PruneDenied("Destructive cleanup requires exact release ID and SHA-256")
            result = prune_one_oldest(
                args.artifact_dir,
                expected_release_id=args.expected_release_id,
                expected_sha256=args.expected_sha256,
                confirm_prune=args.confirm_prune,
                confirm_no_dependencies=args.confirm_no_dependencies,
            )
        else:
            result = plan_cleanup(args.artifact_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        print("RELEASE_RETENTION_CLEANUP=" + ("COMPLETED" if result["deleted"] else "DRY_RUN_ONLY"))
        return 0
    except (PruneDenied, StoreAuditError, OSError, RuntimeError, ValueError) as exc:
        print(f"RELEASE_RETENTION_CLEANUP=STOP: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
