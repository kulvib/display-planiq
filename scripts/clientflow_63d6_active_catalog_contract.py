"""Strict, read-only source audit for pinned 1245/1246/1247/1248 catalogs.

Legacy 1245 source gates use this common contract to review a promoted
1246 update-only catalog without weakening their historical 1245 invariants.
No network, database, environment mutation, publication or deployment grant.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

STAGE_PATH = "backend/service1/clientflow_release_catalog_1246_pilot.stage.json"
ACTIVE_PATH = "backend/service1/clientflow_release_catalog.json"
APPROVAL_PATH = "backend/service1/clientflow_pilot_1246_approval.json"
STAGED_SHA256 = "c416efdf9f5794e7bd7b48c355fbf91c77cfe691a6fbd46b6a489ef3f3052c8a"
APPROVAL_SHA256 = "71b6154de4d52a9f51c1eaebf5d33e280997a20c3e7cd092822b56cbb50f38e0"
STAGE_1247_PATH = "backend/service1/clientflow_release_catalog_1247_pilot.stage.json"
APPROVAL_1247_PATH = "backend/service1/clientflow_pilot_1247_approval.json"
STAGED_1247_SHA256 = "d54fa0438b020461a668fad241bf08c5e64dcae9befd0b4a7bdc6dac97fc9cd9"
APPROVAL_1247_SHA256 = "f2e84210e39850b87d382ec4dd186ad39f5b7e768fa8cef42bf76a8d5b81bf04"
STAGE_1248_PATH = "backend/service1/clientflow_release_catalog_1248_pilot.stage.json"
APPROVAL_1248_PATH = "backend/service1/clientflow_pilot_1248_approval.json"
STAGED_1248_SHA256 = "79b33f2431d6321a6f9b98b45d22dc327217f74b327452ce2a2632a3e11d3dac"
APPROVAL_1248_SHA256 = "0d493cf0782c4616a632334ce258b2363d81a3429e95d5663189221051704a25"


class ActiveCatalogDenied(ValueError):
    """No implicit acceptance of a modified or otherwise broadened catalog."""


def _strict_json(repo: Path, name: str, *, max_size: int = 16_384) -> tuple[dict[str, Any], str]:
    path = repo / name
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > max_size:
            raise ValueError("missing_or_unsafe_file")
        data = path.read_bytes()
        def unique(pairs):
            out = {}
            for key, value in pairs:
                if key in out:
                    raise ValueError("duplicate_json_key")
                out[key] = value
            return out
        parsed = json.loads(data, object_pairs_hook=unique,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid_number")))
        if not isinstance(parsed, dict):
            raise ValueError("non_object")
        return parsed, hashlib.sha256(data).hexdigest()
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise ActiveCatalogDenied(f"1246 source authority invalid: {name}") from exc


def verified_mode(repo: Path) -> str:
    """Recognize only the full pinned baseline, 1246, 1247 or 1248 stage."""
    stage, stage_sha = _strict_json(repo, STAGE_PATH)
    lock, lock_sha = _strict_json(repo, APPROVAL_PATH, max_size=4096)
    active, active_sha = _strict_json(repo, ACTIVE_PATH)
    if stage_sha != STAGED_SHA256 or lock_sha != APPROVAL_SHA256:
        raise ActiveCatalogDenied("Pinned stage or artifact approval changed")
    if (stage.get("catalog_sequence") != 1246 or
        stage.get("latest_stable") != stage.get("default_install_version") or
        stage.get("latest_stable") != "1.3.44" or
        type(stage.get("releases")) is not list or len(stage["releases"]) != 2 or
        stage["releases"][0].get("release_id") != "clientflow-1.3.44-seq-1245" or
        stage["releases"][1].get("release_id") != lock.get("release_id") or
        stage["releases"][1].get("status") != "supported" or
        stage["releases"][1].get("installable") is not False or
        stage["releases"][1].get("update_allowed") is not True or
        stage["releases"][1].get("rollback_allowed") is not False or
        stage["releases"][1].get("install_modes") != ["in_place_update"] or
        lock.get("approved") is not True):
        raise ActiveCatalogDenied("1246 source identity is not update-only and approved")
    baseline = {**stage, "catalog_sequence": 1245, "releases": [stage["releases"][0]]}
    if active == baseline:
        return "stable_1245_only"
    if active == stage:
        return "update_only_1246_pilot_catalog"
    # 1247 is a *distinct*, already GitHub-approved, update-only stage.
    # Only read these additional files for the actual 1247 catalog; historic
    # baseline/1246 fixtures remain independently verifiable without them.
    if active.get("catalog_sequence") == 1247:
        new_stage, new_stage_sha = _strict_json(repo, STAGE_1247_PATH)
        new_approval, approval_sha = _strict_json(repo, APPROVAL_1247_PATH, max_size=4096)
        if new_stage_sha != STAGED_1247_SHA256 or approval_sha != APPROVAL_1247_SHA256:
            raise ActiveCatalogDenied("1247 pinned stage or approval changed")
        if (new_stage.get("catalog_sequence") != 1247
                or type(new_stage.get("releases")) is not list
                or len(new_stage["releases"]) != 3
                or new_stage["releases"][:2] != stage["releases"]
                or any(new_stage.get(k) != stage.get(k) for k in (
                    "manifest_schema", "channel", "latest_stable",
                    "default_install_version", "retention_policy"
                ))
                or new_stage["releases"][2].get("release_id") != "clientflow-1.3.46-seq-1247"
                or new_stage["releases"][2].get("status") != "supported"
                or new_stage["releases"][2].get("installable") is not False
                or new_stage["releases"][2].get("update_allowed") is not True
                or new_stage["releases"][2].get("rollback_allowed") is not False
                or new_stage["releases"][2].get("install_modes") != ["in_place_update"]
                or new_stage["releases"][2].get("min_current_version") != "1.3.45"
                or new_stage["releases"][2].get("max_current_version") != "1.3.45"
                or new_approval.get("approved") is not True
                or new_approval.get("release_id") != "clientflow-1.3.46-seq-1247"
                or new_approval.get("approved_bundle_sha256") != "3d6df5ec096a5713866943a67d9f88bba3fc6287458d0ea2f616bd41e42db150"
                or active != new_stage):
            raise ActiveCatalogDenied("Active 1247 catalog differs from exact approved stage")
        return "update_only_1247_pilot_catalog"
    # 1248 replaces only the 1246 *selector*, not its immutable TAR.
    # Compare the full source-locked 1245 and 1247 rows and the 1248 stage
    # bytes. A new field, changed note or widened install mode must fail shut.
    if active.get("catalog_sequence") == 1248:
        prior, prior_sha = _strict_json(repo, STAGE_1247_PATH)
        prior_approval, prior_approval_sha = _strict_json(
            repo, APPROVAL_1247_PATH, max_size=4096,
        )
        current, current_sha = _strict_json(repo, STAGE_1248_PATH)
        approval, approval_sha = _strict_json(repo, APPROVAL_1248_PATH, max_size=4096)
        if (
            prior_sha != STAGED_1247_SHA256
            or prior_approval_sha != APPROVAL_1247_SHA256
            or prior_approval.get("approved") is not True
            or current_sha != STAGED_1248_SHA256
            or approval_sha != APPROVAL_1248_SHA256
        ):
            raise ActiveCatalogDenied("Pinned 1247/1248 source or approval changed")
        if (
            current.get("catalog_sequence") != 1248
            or type(current.get("releases")) is not list
            or len(current["releases"]) != 3
            or current["releases"][:2] != [prior["releases"][0], prior["releases"][2]]
            or any(current.get(k) != prior.get(k) for k in (
                "manifest_schema", "channel", "latest_stable",
                "default_install_version", "retention_policy",
            ))
            or current["releases"][2].get("release_id") != "clientflow-1.3.47-seq-1248"
            or current["releases"][2].get("status") != "supported"
            or current["releases"][2].get("installable") is not False
            or current["releases"][2].get("update_allowed") is not True
            or current["releases"][2].get("rollback_allowed") is not False
            or current["releases"][2].get("install_modes") != ["in_place_update"]
            or current["releases"][2].get("min_current_version") != "1.3.46"
            or current["releases"][2].get("max_current_version") != "1.3.46"
            or approval.get("approved") is not True
            or approval.get("release_id") != "clientflow-1.3.47-seq-1248"
            or approval.get("approved_bundle_sha256")
                != "9ca8852ba29153f2ec40b58d18007c738a03f9569f14762486fc1953c59eb6ff"
            or active != current
        ):
            raise ActiveCatalogDenied("Active 1248 differs from exact pinned update-only stage")
        return "update_only_1248_pilot_catalog"
    if active.get("catalog_sequence") in {1250, 1251}:
        closed, closed_sha = _strict_json(repo, "backend/service1/clientflow_release_catalog_1250_closed.stage.json")
        historical, historical_sha = _strict_json(repo, STAGE_1248_PATH)
        _, historical_approval_sha = _strict_json(repo, APPROVAL_1248_PATH, max_size=4096)
        _, prior_sha = _strict_json(repo, STAGE_1247_PATH)
        _, prior_approval_sha = _strict_json(repo, APPROVAL_1247_PATH, max_size=4096)
        _, baseline_approval_sha = _strict_json(repo, "backend/service1/clientflow_pilot_1250_approval.json", max_size=4096)
        _, successor_approval_sha = _strict_json(repo, "backend/service1/clientflow_pilot_1251_approval.json", max_size=4096)
        if (closed_sha != "27b14ddd7f692ec37d2e5e372cfb3470d5af84bacd9662d7a7e4aabbc21848f4"
                or (active.get("catalog_sequence") == 1250 and active != closed)
                or historical_sha != STAGED_1248_SHA256 or historical_approval_sha != APPROVAL_1248_SHA256
                or prior_sha != STAGED_1247_SHA256 or prior_approval_sha != APPROVAL_1247_SHA256
                or baseline_approval_sha != "fc851982c39de0b7f92b9274f822b70bf61ca014bcbd88e62d7570a08d58f334"
                or successor_approval_sha != "2926a9d1bdb1d364616f11c44ef1aba43664e6107379eaa97562b31002cb6038"):
            raise ActiveCatalogDenied("Closed 1250 catalog or immutable approval history changed")
        if historical["releases"][0] != stage["releases"][0]:
            raise ActiveCatalogDenied("Historical 1245 stable record changed")
        if active.get("catalog_sequence") == 1251:
            successor, successor_sha = _strict_json(repo, "backend/service1/clientflow_release_catalog_1251_closed.stage.json")
            if (successor_sha != "c3c98d8e30791483d1f5e5ade7a70dc96a732b8b69f7dc7440740c025c2d10a5"
                    or active_sha != successor_sha or active != successor):
                raise ActiveCatalogDenied("Closed 1251 differs from exact stage")
            return "closed_1251_standard"
        return "closed_1250_baseline"
    raise ActiveCatalogDenied("Active catalog differs from pinned baseline/pilot")


def projected_stable_1245(repo: Path) -> dict[str, Any]:
    """A historical baseline projection, never an active deployment catalog."""
    mode = verified_mode(repo)
    active, _ = _strict_json(repo, STAGE_1248_PATH if mode in {"closed_1250_baseline", "closed_1251_standard"} else ACTIVE_PATH)
    return {**active, "catalog_sequence": 1245, "releases": [active["releases"][0]]}
