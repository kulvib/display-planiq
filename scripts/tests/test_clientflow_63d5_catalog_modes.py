"""Proof that read-only 1246 pilot catalog cannot silently promote stable."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from service1.clientflow_release_pilot_stage_1246 import (  # noqa: E402
    PilotStageDenied, load_staged_catalog, staged_pilot_summary,
    validated_catalog_mode,
)
from service1.clientflow_release_readiness import planning_readiness  # noqa: E402


def _stable():
    return json.loads((ROOT / "backend/service1/clientflow_release_catalog.json").read_text())


def test_stable_catalog_remains_fresh_install_default():
    active = _stable()
    assert validated_catalog_mode(active_catalog=active) == "stable_1245_only"
    summary = staged_pilot_summary(active_catalog=active)
    assert summary["active_catalog_promoted"] is False
    assert summary["deployment_authorized"] is False


def test_entire_pinned_stage_catalog_is_recognized_without_authorization():
    active = load_staged_catalog()
    assert validated_catalog_mode(active_catalog=active) == "update_only_1246_pilot_catalog"
    assert active["latest_stable"] == active["default_install_version"] == "1.3.44"
    assert active["releases"][1]["installable"] is False
    assert active["releases"][1]["install_modes"] == ["in_place_update"]
    info = staged_pilot_summary(active_catalog=active)
    assert info["active_catalog_promoted"] is True
    for k in ("render_store_publication_verified", "physical_pilot_accepted",
              "deployment_authorized", "fleet_authorized", "fresh_install_authorized",
              "database_cutover_authorized"):
        assert info[k] is False


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(latest_stable="1.3.45"),
    lambda d: d.update(default_install_version="1.3.45"),
    lambda d: d["releases"][1].update(installable=True),
    lambda d: d["releases"][1].update(status="stable"),
    lambda d: d["releases"][1].update(bundle_sha256="0"*64),
    lambda d: d["releases"][0].update(notes=["unreviewed change"]),
    lambda d: d["releases"].append(deepcopy(d["releases"][1])),
])
def test_changed_catalog_is_never_treated_as_pilot(mutation):
    active = deepcopy(load_staged_catalog())
    mutation(active)
    with pytest.raises(PilotStageDenied):
        validated_catalog_mode(active_catalog=active)


def test_readiness_stable_binding_for_exact_two_release_stage_never_authorizes():
    stable = load_staged_catalog()
    record = stable["releases"][0]
    approved = "28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5"
    kwargs = {
        "release_id": record["release_id"], "bundle_sha256": approved,
        "approval_bundle_sha256": approved, "control_revision": 1,
        "cutover_enabled": False, "fleet_open": False, "fresh_install_open": False,
        "physical_acceptance": False, "catalog": stable,
    }
    report = planning_readiness(**kwargs, exact_update_only_pilot_catalog=True)
    assert report["checks"][0] == {"id": "stable_catalog_binding", "ready": True, "reason": None}
    assert report["deployment_authorized"] is False
    assert report["ready_for_fleet"] is False
    assert report["ready_for_fresh_install"] is False
    assert all(not c["ready"] for c in report["checks"][1:])
    report_without_validation = planning_readiness(**kwargs)
    assert report_without_validation["checks"][0]["ready"] is False
