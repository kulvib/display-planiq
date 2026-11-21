"""Fail-closed exact 1248 pilot stage; never promote or authorize deployment."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import clientflow_pilot_1248 as pilot
from .clientflow_release_pilot_stage_1247 import load_staged_catalog_1247

STAGED_CATALOG_PATH = Path(__file__).with_name("clientflow_release_catalog_1248_pilot.stage.json")
EXPECTED_STAGED_CATALOG_SHA256 = "79b33f2431d6321a6f9b98b45d22dc327217f74b327452ce2a2632a3e11d3dac"


class PilotStage1248Denied(ValueError):
    pass


def load_staged_catalog_1248() -> dict[str, Any]:
    """Validate full file hash and immutable historical 1245/1247 source records."""
    pilot.approval_lock_1248()
    try:
        if STAGED_CATALOG_PATH.is_symlink() or not STAGED_CATALOG_PATH.is_file():
            raise ValueError("unsafe_stage_file")
        if STAGED_CATALOG_PATH.stat().st_size > 16000:
            raise ValueError("oversized_stage_file")
        raw = STAGED_CATALOG_PATH.read_bytes()
        if hashlib.sha256(raw).hexdigest() != EXPECTED_STAGED_CATALOG_SHA256:
            raise ValueError("source_stage_hash_changed")
        catalog = json.loads(raw)
        prior = load_staged_catalog_1247()
        if not isinstance(catalog, dict) or set(catalog) != set(prior):
            raise ValueError("stage_schema_changed")
        if type(catalog.get("catalog_sequence")) is not int or catalog["catalog_sequence"] != 1248:
            raise ValueError("stage_sequence_changed")
        for key in ("manifest_schema", "channel", "latest_stable",
                    "default_install_version", "retention_policy"):
            if catalog[key] != prior[key]:
                raise ValueError("stable_or_retention_policy_changed")
        rows = catalog["releases"]
        if not isinstance(rows, list) or len(rows) != 3:
            raise ValueError("stage_must_have_exactly_three_selectable_rows")
        # Historical 1246 is still an immutable Render TAR, but is deliberately
        # no longer selectable; 1245 and 1247 retain their entire exact records.
        if rows[:2] != [prior["releases"][0], prior["releases"][2]]:
            raise ValueError("historical_stable_or_source_release_mutated")
        row = rows[2]
        identity = {
            "release_id": pilot.PILOT_RELEASE_ID,
            "revision": pilot.PILOT_RELEASE_ID,
            "version": "1.3.47", "client_version": "1.3.47",
            "release_sequence": 1248, "status": "supported",
            "installable": False, "update_allowed": True,
            "rollback_allowed": False, "requires_explicit_downgrade": False,
            "requires_reboot": True, "artifact_type": "runtime_release",
            "install_modes": ["in_place_update"],
            "min_current_version": "1.3.46", "max_current_version": "1.3.46",
        }
        if not isinstance(row, dict) or any(
            type(row.get(key)) is not type(value) or row[key] != value
            for key, value in identity.items()
        ):
            raise ValueError("1248_is_not_exact_update_only_target")
        if row.get("ubuntu_compatibility") != rows[1].get("ubuntu_compatibility"):
            raise ValueError("ubuntu_2604_compatibility_changed")
        if catalog["latest_stable"] != "1.3.44" or catalog["default_install_version"] != "1.3.44":
            raise ValueError("stable_default_changed")
        return catalog
    except (OSError, KeyError, TypeError, ValueError, UnicodeError) as exc:
        raise PilotStage1248Denied("1248 pilot stage is not exact and verified") from exc


def validated_catalog_mode_1248(*, active_catalog: dict[str, Any]) -> str:
    """Source staging is not sufficient; live catalog must match exactly."""
    stage = load_staged_catalog_1248()
    if active_catalog != stage:
        raise PilotStage1248Denied("1248 pilot stage is not the active exact catalog")
    return "update_only_1248_pilot_catalog"
