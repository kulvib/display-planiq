"""63D-19: exact 1248 active selector, no installer, fleet or deployment grant."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil

import pytest

from service1 import clientflow_releases as releases
from service1.clientflow_release_pilot_stage_1247 import load_staged_catalog_1247
from service1.clientflow_release_pilot_stage_1248 import (
    load_staged_catalog_1248, validated_catalog_mode_1248,
)
from service1.clientflow_release_readiness import planning_readiness
from scripts.clientflow_63d6_active_catalog_contract import (
    ActiveCatalogDenied, verified_mode,
)

ROOT = Path(__file__).resolve().parents[2]
SVC = ROOT / "backend/service1"
FILES = [
    "backend/service1/clientflow_release_catalog.json",
    "backend/service1/clientflow_release_catalog_1246_pilot.stage.json",
    "backend/service1/clientflow_release_catalog_1247_pilot.stage.json",
    "backend/service1/clientflow_release_catalog_1248_pilot.stage.json",
    "backend/service1/clientflow_pilot_1246_approval.json",
    "backend/service1/clientflow_pilot_1247_approval.json",
    "backend/service1/clientflow_pilot_1248_approval.json",
]


def _isolated(tmp_path: Path) -> Path:
    target = tmp_path / "repo"
    for file in FILES:
        dest = target / file
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / file, dest)
    return target


def test_promoted_catalog_has_exact_pinned_bytes_and_three_selectors():
    stage_path = SVC / "clientflow_release_catalog_1248_pilot.stage.json"
    live_path = SVC / "clientflow_release_catalog.json"
    assert live_path.read_bytes() == stage_path.read_bytes()
    stage = load_staged_catalog_1248()
    assert releases.load_catalog() == stage
    assert validated_catalog_mode_1248(active_catalog=stage) == "update_only_1248_pilot_catalog"
    assert verified_mode(ROOT) == "update_only_1248_pilot_catalog"
    assert [r["release_sequence"] for r in stage["releases"]] == [1245, 1247, 1248]
    assert stage["retention_policy"] == {
        "max_selectable_versions": 3,
        "max_installable_versions": 1,
        "keep_blocked_metadata": False,
    }
    assert stage["latest_stable"] == stage["default_install_version"] == "1.3.44"
    assert [r["installable"] for r in stage["releases"]] == [True, False, False]
    assert [r["rollback_allowed"] for r in stage["releases"]] == [False, False, False]
    assert stage["releases"][2]["min_current_version"] == "1.3.46"
    assert stage["releases"][2]["max_current_version"] == "1.3.46"
    assert stage["releases"][:2] == [
        load_staged_catalog_1247()["releases"][0],
        load_staged_catalog_1247()["releases"][2],
    ]


def test_removed_selector_does_not_remove_signed_artifact_or_stable_default():
    assert releases.resolve_fresh_install_release()["release_id"] == "clientflow-1.3.44-seq-1245"
    assert releases.resolve_release("1.3.46")["release_id"] == "clientflow-1.3.46-seq-1247"
    assert releases.resolve_release("1.3.47")["release_id"] == "clientflow-1.3.47-seq-1248"
    with pytest.raises(releases.ClientFlowCatalogError):
        releases.resolve_release("1.3.45")
    # The historical 1246 immutable source is retained, not rewritten.
    prior = json.loads((SVC / "clientflow_release_catalog_1247_pilot.stage.json").read_text())
    assert prior["releases"][1]["release_id"] == "clientflow-1.3.45-seq-1246"


@pytest.mark.parametrize("field,value", [
    ("catalog_sequence", 1249),
    ("latest_stable", "1.3.47"),
    ("default_install_version", "1.3.47"),
])
def test_catalog_promotion_cannot_be_widened(tmp_path, field, value):
    root = _isolated(tmp_path)
    path = root / FILES[0]
    doc = json.loads(path.read_text())
    doc[field] = value
    path.write_text(json.dumps(doc))
    with pytest.raises(ActiveCatalogDenied):
        verified_mode(root)


@pytest.mark.parametrize("attack", [
    lambda d: d["releases"][0].update(installable=False),
    lambda d: d["releases"][1].update(notes=["replaced source"]),
    lambda d: d["releases"][2].update(installable=True),
    lambda d: d["releases"][2].update(status="stable"),
    lambda d: d["releases"][2].update(rollback_allowed=True),
    lambda d: d["releases"][2].update(install_modes=["fresh_install"]),
    lambda d: d["releases"][2].update(min_current_version="1.3.45"),
    lambda d: d["releases"][2].update(max_current_version="1.3.47"),
    lambda d: d["releases"].append(deepcopy(d["releases"][2])),
])
def test_catalog_mutations_fail_even_with_valid_json(tmp_path, attack):
    root = _isolated(tmp_path)
    path = root / FILES[0]
    doc = json.loads(path.read_text())
    attack(doc)
    path.write_text(json.dumps(doc))
    with pytest.raises(ActiveCatalogDenied):
        verified_mode(root)


@pytest.mark.parametrize("name", [FILES[2], FILES[3], FILES[5], FILES[6]])
def test_historical_or_current_signed_source_tampering_fails(tmp_path, name):
    root = _isolated(tmp_path)
    path = root / name
    value = path.read_bytes().replace(b"1248", b"1249", 1)
    if value == path.read_bytes():
        value = path.read_bytes() + b" "
    path.write_bytes(value)
    with pytest.raises(ActiveCatalogDenied):
        verified_mode(root)


def test_readiness_cannot_authorize_deployment():
    active = releases.load_catalog()
    approved = "28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5"
    report = planning_readiness(
        release_id="clientflow-1.3.44-seq-1245",
        bundle_sha256=approved,
        catalog=active,
        approval_bundle_sha256=approved,
        control_revision=1,
        cutover_enabled=False,
        fleet_open=False,
        fresh_install_open=False,
        physical_acceptance=False,
        exact_update_only_pilot_catalog=True,
    )
    assert report["checks"][0]["ready"] is True
    assert report["deployment_authorized"] is False
    assert report["automatic_rollout_authorized"] is False
    assert report["ready_for_fleet"] is False
    assert report["ready_for_fresh_install"] is False
