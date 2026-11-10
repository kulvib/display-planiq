#!/usr/bin/env python3
"""Read-only check for the exact approved 1244 five-to-six publication bridge."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from scripts.audit_clientflow_release_retention import (  # noqa: E402
    StoreAuditError, plan_publication,
)
from scripts.clientflow_1244_transition_policy import (  # noqa: E402
    APPROVED_SHA256, APPROVED_SIZE, RELEASE_ID, ClientFlow1244ResetDenied,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        plan = plan_publication(
            args.artifact_dir,
            release_id=RELEASE_ID,
            size_bytes=APPROVED_SIZE,
            sha256=APPROVED_SHA256,
            authorized_1244_reset=True,
        )
    except (StoreAuditError, ClientFlow1244ResetDenied, OSError, ValueError) as exc:
        print(f"CLIENTFLOW_1244_PUBLICATION_PREFLIGHT=BLOCKED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
    print("CLIENTFLOW_1244_PUBLICATION_PREFLIGHT=READ_ONLY_PASS")
    print("CLIENTFLOW_1244_STORE_CLEANUP=NOT_AUTHORIZED_HERE")
    print("CLIENTFLOW_1244_CATALOG_PROMOTION=NOT_AUTHORIZED_HERE")
    print("CLIENTFLOW_1244_PHYSICAL_INSTALL=NOT_AUTHORIZED_HERE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
