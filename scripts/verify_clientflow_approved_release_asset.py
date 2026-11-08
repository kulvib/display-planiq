#!/usr/bin/env python3
"""Verify approved GitHub Actions handoff before no-replace GitHub Release archival.

Read only. This script grants no Render publication, catalog, or pilot authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tarfile

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
APPROVAL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:/@+-]{0,199}$")
EXPECTED_HANDOFF_FILES = {"APPROVAL.json", "APPROVAL.txt", "clientflow-approved.tar"}


class ApprovedArchiveDenied(ValueError):
    """A read-only verification invariant failed."""


def _regular_file(path: Path) -> None:
    meta = path.lstat()
    if not stat.S_ISREG(meta.st_mode) or stat.S_ISLNK(meta.st_mode):
        raise ApprovedArchiveDenied(f"Not a regular, non-symlink file: {path.name}")


def _sha_file(path: Path) -> tuple[int, str]:
    _regular_file(path)
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    fd = os.open(path, flags)
    try:
        h = hashlib.sha256()
        size = 0
        with os.fdopen(fd, "rb", closefd=False) as f:
            while chunk := f.read(1024 * 1024):
                h.update(chunk)
                size += len(chunk)
        return size, h.hexdigest()
    finally:
        os.close(fd)


def _sha_member(handle, member: tarfile.TarInfo) -> tuple[int, str]:
    data = handle.extractfile(member)
    if data is None:
        raise ApprovedArchiveDenied("Cannot read TAR member")
    h = hashlib.sha256()
    size = 0
    with data:
        while chunk := data.read(1024 * 1024):
            h.update(chunk)
            size += len(chunk)
    return size, h.hexdigest()


def verify_handoff(
    handoff: Path,
    *,
    expected_source_sha: str,
    expected_approved_sha256: str,
    expected_approval_reference: str,
) -> dict:
    if not COMMIT_RE.fullmatch(expected_source_sha):
        raise ApprovedArchiveDenied("Full lowercase approved source SHA required")
    if not SHA256_RE.fullmatch(expected_approved_sha256):
        raise ApprovedArchiveDenied("Approved bundle SHA-256 must be exactly 64 lowercase hex")
    if not APPROVAL_RE.fullmatch(expected_approval_reference):
        raise ApprovedArchiveDenied("Invalid explicit approval reference")
    if not handoff.is_dir() or handoff.is_symlink():
        raise ApprovedArchiveDenied("Handoff must be an ordinary directory")
    actual_files = {item.name for item in handoff.iterdir()}
    if actual_files != EXPECTED_HANDOFF_FILES:
        raise ApprovedArchiveDenied(f"Unexpected handoff files: {sorted(actual_files)}")
    for name in actual_files:
        _regular_file(handoff / name)

    record = json.loads((handoff / "APPROVAL.json").read_text(encoding="utf-8"))
    if record.get("schema_version") != 1:
        raise ApprovedArchiveDenied("Invalid approval record schema")
    if record.get("source_commit") != expected_source_sha:
        raise ApprovedArchiveDenied("Approval record source commit differs")
    if record.get("approved_bundle_sha256") != expected_approved_sha256:
        raise ApprovedArchiveDenied("Approval record approved SHA-256 differs")
    if record.get("approval_reference") != expected_approval_reference:
        raise ApprovedArchiveDenied("Approval record reference differs")
    if not isinstance(record.get("release_build_run_id"), int) or record["release_build_run_id"] <= 0:
        raise ApprovedArchiveDenied("Missing original reproducible-build provenance")
    for field in ("candidate_sha256", "installer_sha256"):
        if not SHA256_RE.fullmatch(str(record.get(field) or "")):
            raise ApprovedArchiveDenied(f"Invalid {field} in approval record")

    bundle = handoff / "clientflow-approved.tar"
    size, digest = _sha_file(bundle)
    if size != record.get("approved_bundle_size") or digest != expected_approved_sha256:
        raise ApprovedArchiveDenied("Approved bundle content size/hash differs from approval record")
    approval_text = (handoff / "APPROVAL.txt").read_text(encoding="utf-8")
    for proof in (
        f"APPROVED_BUNDLE_SHA256={digest}",
        f"APPROVED_BUNDLE_SIZE={size}",
        f"INSTALLER_SHA256={record['installer_sha256']}",
    ):
        if proof not in approval_text.splitlines():
            raise ApprovedArchiveDenied("Approval log text differs from exact approved bytes")

    with tarfile.open(bundle, mode="r:") as archive:
        members = archive.getmembers()
        filenames = [m.name for m in members]
        if len(filenames) != 3 or len(set(filenames)) != 3:
            raise ApprovedArchiveDenied("Approved bundle must contain exactly three unique TAR members")
        if any(not member.isfile() for member in members):
            raise ApprovedArchiveDenied("Approved bundle cannot contain non-regular members")
        by_name = {m.name: m for m in members}
        if "manifest.json" not in by_name or by_name["manifest.json"].size > 65536:
            raise ApprovedArchiveDenied("No canonical bounded bundle manifest")
        manifest_file = archive.extractfile(by_name["manifest.json"])
        if manifest_file is None:
            raise ApprovedArchiveDenied("Cannot open bundle manifest")
        manifest = json.loads(manifest_file.read().decode("utf-8"))
        version = manifest.get("version")
        seq = manifest.get("release_sequence")
        if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
            raise ApprovedArchiveDenied("Malformed approved version")
        if type(seq) is not int or seq <= 0:
            raise ApprovedArchiveDenied("Malformed approved release sequence")
        release_id = f"clientflow-{version}-seq-{seq}"
        if manifest.get("release_id") != release_id:
            raise ApprovedArchiveDenied("Approved release-ID does not match version/sequence")
        if manifest.get("deployable") is not True:
            raise ApprovedArchiveDenied("Unapproved candidate must never be archived as approved")
        if manifest.get("source") != {"commit": expected_source_sha, "dirty": False}:
            raise ApprovedArchiveDenied("Approved manifest source is not exact clean source")
        approval = manifest.get("release_approval") or {}
        if approval.get("reference") != expected_approval_reference:
            raise ApprovedArchiveDenied("Bundle approval reference differs")
        if approval.get("candidate_sha256") != record["candidate_sha256"]:
            raise ApprovedArchiveDenied("Bundle candidate SHA-256 differs")
        expected_members = {"manifest.json", "clientflow-payload.tar", f"clientflow-installer-{version}.pyz"}
        if set(filenames) != expected_members:
            raise ApprovedArchiveDenied("Approved bundle contains unexpected members")
        for descriptor_name in ("payload", "fresh_installer"):
            descriptor = manifest.get(descriptor_name) or {}
            member_name = descriptor.get("file")
            if member_name not in expected_members - {"manifest.json"}:
                raise ApprovedArchiveDenied("Invalid embedded member filename")
            member = by_name[member_name]
            if (member.size, descriptor.get("sha256")) != (descriptor.get("size"), _sha_member(archive, member)[1]):
                raise ApprovedArchiveDenied("Embedded member descriptor hash/size mismatch")
            if member_name.endswith(".pyz") and descriptor["sha256"] != record["installer_sha256"]:
                raise ApprovedArchiveDenied("Embedded fresh installer differs from approved installer")
    tag = f"clientflow-{version}-{seq}-approved-transport"
    asset_name = f"clientflow-approved-{version}-{seq}.tar"
    return {
        "release_id": release_id,
        "tag": tag,
        "asset_name": asset_name,
        "bundle_path": str(bundle.resolve()),
        "approved_bundle_size": size,
        "approved_bundle_sha256": digest,
        "source_commit": expected_source_sha,
        "approval_reference": expected_approval_reference,
        "candidate_sha256": record["candidate_sha256"],
        "installer_sha256": record["installer_sha256"],
        "release_build_run_id": record["release_build_run_id"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--expected-approved-sha256", required=True)
    parser.add_argument("--expected-approval-reference", required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    result = verify_handoff(
        args.handoff,
        expected_source_sha=args.expected_source_sha,
        expected_approved_sha256=args.expected_approved_sha256,
        expected_approval_reference=args.expected_approval_reference,
    )
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as f:
            for field in ("tag", "asset_name", "bundle_path", "approved_bundle_size"):
                f.write(f"{field}={result[field]}\n")
    print(json.dumps(result, sort_keys=True, indent=2))
    print("APPROVED_GITHUB_TRANSPORT_PREFLIGHT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
