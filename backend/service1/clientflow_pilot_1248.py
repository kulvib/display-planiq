"""Immutable, GitHub-approved ClientFlow 1248 identity. No deployment rights."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PILOT_CLIENT_ID = 3
PILOT_RELEASE_ID = "clientflow-1.3.47-seq-1248"
PILOT_TO_VERSION = "1.3.47"
PILOT_FROM_VERSIONS = frozenset({"1.3.46"})
SOURCE_COMMIT = "c0d5a092efe0c4e8638866ad98621481d6f5d0e8"
CANDIDATE_SHA256 = "f82400140eb49efecf697b099cb86c94cecfb3f29dfe069b4d96ecb3b611173b"
INSTALLER_SHA256 = "750bb2e09501fb1a1750b8f3eff65975bf383a43a8a0fcc0eb3469389112f7b0"
APPROVED_BUNDLE_SHA256 = "9ca8852ba29153f2ec40b58d18007c738a03f9569f14762486fc1953c59eb6ff"
APPROVED_BUNDLE_SIZE = 223692800
APPROVAL_REFERENCE = "CF-1.3.47-1248-20261121-c0d5a092-f8240014"
APPROVAL_RUN_ID = 44898553899
GITHUB_RELEASE_TAG = "clientflow-1.3.47-1248-approved-transport"
APPROVAL_LOCK_PATH = Path(__file__).with_name("clientflow_pilot_1248_approval.json")


class ClientFlowPilot1248Denied(ValueError):
    pass


def approval_lock_1248() -> dict[str, Any]:
    expected = {
        "schema_version": 1, "approved": True, "release_id": PILOT_RELEASE_ID,
        "source_commit": SOURCE_COMMIT, "candidate_sha256": CANDIDATE_SHA256,
        "installer_sha256": INSTALLER_SHA256,
        "approved_bundle_sha256": APPROVED_BUNDLE_SHA256,
        "approved_bundle_size": APPROVED_BUNDLE_SIZE,
        "approval_reference": APPROVAL_REFERENCE,
        "approval_run_id": APPROVAL_RUN_ID, "github_release_tag": GITHUB_RELEASE_TAG,
    }
    try:
        if APPROVAL_LOCK_PATH.is_symlink() or not APPROVAL_LOCK_PATH.is_file():
            raise ValueError("unsafe_approval_source")
        if APPROVAL_LOCK_PATH.stat().st_size > 4096:
            raise ValueError("oversized_approval_source")
        actual = json.loads(APPROVAL_LOCK_PATH.read_text(encoding="utf-8"))
        if actual != expected:
            raise ValueError("approval_changed")
    except (OSError, ValueError, TypeError, UnicodeError) as exc:
        raise ClientFlowPilot1248Denied("1248 approval provenance cannot be verified") from exc
    return actual
