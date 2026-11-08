#!/usr/bin/env python3
"""Read-only, operator-facing preflight for the one-off 1243 five-release handoff.

This script does not download/publish/delete files, change clients, verify any
live database deployment state or attest offsite backups. Operators must check
those independent dependencies separately before the publication command.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "client" / "release" / "lib"))

from scripts.audit_clientflow_release_retention import plan_publication  # noqa: E402
from scripts.clientflow_1243_transition_policy import (  # noqa: E402
    TRANSITION_RELEASE_ID, TRANSITION_APPROVED_SIZE, TRANSITION_APPROVED_SHA256,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = plan_publication(
            args.artifact_dir,
            release_id=TRANSITION_RELEASE_ID,
            size_bytes=TRANSITION_APPROVED_SIZE,
            sha256=TRANSITION_APPROVED_SHA256,
            authorized_1243_transition=True,
        )
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"CLIENTFLOW_1243_TRANSITION_PREFLIGHT=BLOCKED: {exc}", file=sys.stderr)
        return 1
    result["warning"] = (
        "READ-ONLY only: active deployments, fresh-install token bindings, "
        "GitHub offsite release and physical Viborg2 rescue are NOT verified here"
    )
    print(json.dumps(result, sort_keys=True, indent=2))
    print("CLIENTFLOW_1243_TRANSITION_PREFLIGHT=READ_ONLY_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
