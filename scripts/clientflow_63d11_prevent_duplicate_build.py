#!/usr/bin/env python3
"""Refuse rebuilding approved 1247, 1248, 1250 or 1251 identity from newer source bytes.

The previously approved 1247, 1248, 1250 and 1251 TARs are immutable; later backend policy changes
must not create a second bundle with the same release ID and different source.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verify(expected_source_sha: str, root: Path = ROOT) -> None:
    if not re.fullmatch(r'[0-9a-f]{40}', expected_source_sha):
        raise ValueError('Full source commit SHA is required')
    version = (root / 'client/VERSION').read_text().strip()
    release = json.loads((root / 'client/release/release-input.json').read_text())
    if (version, release.get('release_sequence')) == ('1.3.46', 1247):
        locked = json.loads((root / 'backend/service1/clientflow_pilot_1247_approval.json').read_text())
        if (locked.get('release_id') != 'clientflow-1.3.46-seq-1247'
                or locked.get('approved') is not True
                or locked.get('source_commit') != expected_source_sha):
            raise ValueError('1247 is already approved: refuse changed-source duplicate build')


    if (version, release.get("release_sequence")) == ("1.3.47", 1248):
        locked = json.loads(
            (root / "backend/service1/clientflow_pilot_1248_approval.json").read_text()
        )
        if (
            locked.get("release_id") != "clientflow-1.3.47-seq-1248"
            or locked.get("approved") is not True
            or locked.get("source_commit") != expected_source_sha
        ):
            raise ValueError("1248 is already approved: refuse changed-source duplicate build")


    if release.get("release_sequence") == 1250 or version == "1.4.0":
        locked = json.loads(
            (root / "backend/service1/clientflow_pilot_1250_approval.json").read_text()
        )
        if (
            version != "1.4.0"
            or type(release.get("release_sequence")) is not int
            or release["release_sequence"] != 1250
            or locked.get("release_id") != "clientflow-1.4.0-seq-1250"
            or locked.get("approved") is not True
            or locked.get("source_commit") != expected_source_sha
        ):
            raise ValueError("1250 is already approved: refuse changed-source duplicate build")


    if release.get("release_sequence") == 1251 or version == "1.4.1":
        raw = (root / "backend/service1/clientflow_pilot_1251_approval.json").read_bytes()
        locked = json.loads(raw)
        if (
            version != "1.4.1"
            or type(release.get("release_sequence")) is not int
            or release["release_sequence"] != 1251
            or hashlib.sha256(raw).hexdigest() != "2926a9d1bdb1d364616f11c44ef1aba43664e6107379eaa97562b31002cb6038"
            or locked.get("release_id") != "clientflow-1.4.1-seq-1251"
            or locked.get("approved") is not True
            or locked.get("source_commit") != expected_source_sha
        ):
            raise ValueError("1251 is already approved: refuse changed-source duplicate build")


def require_unpublished_inventory(tags, releases, *, version: str, sequence: int) -> None:
    """Fail closed on visible published/draft release, tag or asset collisions."""
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) or type(sequence) is not int:
        raise ValueError("Invalid candidate identity")
    pattern = re.compile(r"(?<![0-9])(?:" + re.escape(version) + "|" + str(sequence) + r")(?![0-9])")
    def check(name):
        if not isinstance(name, str) or not name:
            raise ValueError("Invalid GitHub inventory name")
        if pattern.search(name):
            raise ValueError("Candidate identity already appears in GitHub inventory")
    for pages, is_release in ((tags, False), (releases, True)):
        if not isinstance(pages, list) or not pages or not all(isinstance(page, list) for page in pages):
            raise ValueError("Invalid paginated GitHub inventory")
        for page in pages:
            for row in page:
                if not isinstance(row, dict):
                    raise ValueError("Invalid GitHub inventory entry")
                if not is_release:
                    check(row.get("name"))
                    continue
                check(row.get("tag_name"))
                if row.get("name"):
                    check(row["name"])
                assets = row.get("assets")
                if not isinstance(assets, list):
                    raise ValueError("Invalid GitHub release assets")
                for asset in assets:
                    if not isinstance(asset, dict):
                        raise ValueError("Invalid GitHub release asset")
                    check(asset.get("name"))


def verify_remote_inventory(repository: str, root: Path = ROOT) -> None:
    # CI/build token has contents:read; no network write, no credentials logged.
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid GitHub repository")
    if not os.environ.get("GH_TOKEN"):
        raise ValueError("Missing read-only GitHub token")
    version = (root / "client/VERSION").read_text().strip()
    sequence = json.loads((root / "client/release/release-input.json").read_text())["release_sequence"]
    def pages(endpoint):
        result = subprocess.run(
            ["gh", "api", "--paginate", "--slurp", f"repos/{repository}/{endpoint}?per_page=100"],
            capture_output=True, timeout=90, check=False,
        )
        if result.returncode:
            raise ValueError("GitHub inventory unavailable")
        return json.loads(result.stdout)
    require_unpublished_inventory(pages("tags"), pages("releases"), version=version, sequence=sequence)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-source-sha', required=True)
    parser.add_argument('--verify-unpublished-repository')
    args = parser.parse_args()
    try:
        verify(args.expected_source_sha)
        if args.verify_unpublished_repository:
            verify_remote_inventory(args.verify_unpublished_repository)
        print('IMMUTABLE_APPROVED_RELEASE_REBUILD_GATE=PASS')
        return 0
    except (ValueError, OSError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        print('IMMUTABLE_APPROVED_RELEASE_REBUILD_GATE=STOP: ' + str(exc))
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
