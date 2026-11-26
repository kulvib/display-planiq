#!/usr/bin/env python3
"""Refuse rebuilding approved 1247, 1248 or 1250 identity from newer source bytes.

The previously approved 1247, 1248 and 1250 TARs are immutable; later backend policy changes
must not create a second bundle with the same release ID and different source.
"""
from __future__ import annotations
import argparse
import json
import re
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-source-sha', required=True)
    args = parser.parse_args()
    try:
        verify(args.expected_source_sha)
        print('IMMUTABLE_APPROVED_RELEASE_REBUILD_GATE=PASS')
        return 0
    except (ValueError, OSError, TypeError, KeyError) as exc:
        print('IMMUTABLE_APPROVED_RELEASE_REBUILD_GATE=STOP: ' + str(exc))
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
