#!/usr/bin/env python3
"""Fail-closed GitHub Release metadata verifier; only legacy asset NAME may be repaired.

The SHA-256 identity is not inferred from release labels. Does not authorize
Render publication, client deployment, rollback or catalog promotion.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
TAG_RE = re.compile(r"clientflow-([0-9]+\.[0-9]+\.[0-9]+)-([1-9][0-9]*)-approved-transport\Z")


class GithubArchiveMismatch(ValueError):
    """Do not act on a release which cannot be proven identical to approval."""


def verify_release(
    release: dict,
    *,
    expected_tag: str,
    expected_asset_name: str,
    expected_source_sha: str,
    expected_sha256: str,
    expected_size: int,
    allow_legacy_handoff_name: bool = False,
) -> dict:
    match = TAG_RE.fullmatch(expected_tag)
    if match is None:
        raise GithubArchiveMismatch("Invalid canonical approved archive tag")
    canonical_name = f"clientflow-approved-{match[1]}-{match[2]}.tar"
    if expected_asset_name != canonical_name:
        raise GithubArchiveMismatch("Approved asset name does not match tag")
    if not SHA_RE.fullmatch(expected_source_sha) or not SHA256_RE.fullmatch(expected_sha256):
        raise GithubArchiveMismatch("Invalid expected commit or digest")
    if type(expected_size) is not int or expected_size <= 0:
        raise GithubArchiveMismatch("Invalid expected bundle size")
    if not isinstance(release, dict):
        raise GithubArchiveMismatch("Malformed release API response")
    if release.get("tag_name") != expected_tag or release.get("prerelease") is not True:
        raise GithubArchiveMismatch("Wrong release tag or not a prerelease")
    if release.get("draft") is True:
        raise GithubArchiveMismatch("Approved release must not be a draft")
    if release.get("target_commitish") != expected_source_sha:
        raise GithubArchiveMismatch("Archived release target commit differs")
    assets = release.get("assets")
    if not isinstance(assets, list) or len(assets) != 1 or not isinstance(assets[0], dict):
        raise GithubArchiveMismatch("Release must have exactly one TAR asset")
    asset = assets[0]
    asset_name = asset.get("name")
    is_legacy = asset_name == "clientflow-approved.tar" and asset_name != expected_asset_name
    if asset_name != expected_asset_name and not (allow_legacy_handoff_name and is_legacy):
        raise GithubArchiveMismatch("Archived asset filename differs")
    if type(asset.get("size")) is not int or asset["size"] != expected_size:
        raise GithubArchiveMismatch("Archived asset size differs")
    if asset.get("digest") != "sha256:" + expected_sha256:
        raise GithubArchiveMismatch("Archived asset digest differs")
    if asset.get("state") != "uploaded":
        raise GithubArchiveMismatch("Archive asset has not completed upload")
    asset_id = asset.get("id")
    if type(asset_id) is not int or asset_id <= 0:
        raise GithubArchiveMismatch("Missing exact GitHub asset ID")
    return {"asset_id": asset_id, "needs_rename": is_legacy, "verified": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-json", type=Path, required=True)
    parser.add_argument("--expected-tag", required=True)
    parser.add_argument("--expected-asset-name", required=True)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-size", type=int, required=True)
    parser.add_argument("--allow-legacy-handoff-name", action="store_true")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    release = json.loads(args.release_json.read_text(encoding="utf-8"))
    result = verify_release(
        release,
        expected_tag=args.expected_tag,
        expected_asset_name=args.expected_asset_name,
        expected_source_sha=args.expected_source_sha,
        expected_sha256=args.expected_sha256,
        expected_size=args.expected_size,
        allow_legacy_handoff_name=args.allow_legacy_handoff_name,
    )
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as stream:
            stream.write(f"asset_id={result['asset_id']}\n")
            stream.write(f"needs_rename={str(result['needs_rename']).lower()}\n")
    print("APPROVED_GITHUB_RELEASE_METADATA=VERIFIED")
    print("asset_id=" + str(result["asset_id"]))
    print("metadata_only_rename_needed=" + str(result["needs_rename"]).lower())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
