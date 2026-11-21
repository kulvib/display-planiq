"""63D-17: immutable 1248 provenance, staged three-selector catalog and denials."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from service1.clientflow_pilot_1248 import (
    PILOT_RELEASE_ID, APPROVED_BUNDLE_SHA256, APPROVED_BUNDLE_SIZE,
    APPROVAL_REFERENCE, SOURCE_COMMIT, CANDIDATE_SHA256,
    ClientFlowPilot1248Denied, approval_lock_1248,
)
from service1.clientflow_release_pilot_stage_1248 import (
    PilotStage1248Denied, load_staged_catalog_1248, validated_catalog_mode_1248,
)
from service1.clientflow_pilot_1248_db_authorization import (
    DatabasePilot1248Denied, CONFLICTING_FLAGS, require_database_pilot_1248,
)

ROOT = Path(__file__).resolve().parents[2]
SVC = ROOT / "backend" / "service1"


def payload():
    stage = load_staged_catalog_1248()
    return {
        "client_id": 3, "client_name": "Viborg1",
        "current_version": "1.3.46", "expected_current_version": "1.3.46",
        "ubuntu_version": "26.04", "release": copy.deepcopy(stage["releases"][2]),
        "artifact": {
            "target_release_id": PILOT_RELEASE_ID,
            "bundle_sha256": APPROVED_BUNDLE_SHA256,
            "bundle_size": APPROVED_BUNDLE_SIZE,
            "release_approval_reference": APPROVAL_REFERENCE,
            "release_candidate_sha256": CANDIDATE_SHA256,
            "source_commit": SOURCE_COMMIT,
        },
        "catalog": stage, "reason": "Physical Viborg1 HLS and remote desktop acceptance",
        "policy": {
            "revision": 5, "stable_release_id": "clientflow-1.3.44-seq-1245",
            "stable_bundle_sha256": "28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5",
            "cutover_enabled": False, "fleet_open": False, "fresh_install_open": False,
        },
        "expected_revision": 5,
    }


@pytest.fixture()
def closed_pilot(monkeypatch):
    monkeypatch.setenv("CLIENTFLOW_FRESH_INSTALL_SUSPENDED", "1")
    for key in CONFLICTING_FLAGS:
        monkeypatch.delenv(key, raising=False)


def test_exact_1248_release_approved_but_only_source_staged():
    approval = approval_lock_1248()
    assert approval["approval_run_id"] == 44898553899
    assert approval["approved_bundle_size"] == 223692800
    assert approval["approved_bundle_sha256"] == APPROVED_BUNDLE_SHA256
    stage = load_staged_catalog_1248()
    assert [r["release_sequence"] for r in stage["releases"]] == [1245, 1247, 1248]
    assert stage["latest_stable"] == stage["default_install_version"] == "1.3.44"
    assert [r["installable"] for r in stage["releases"]] == [True, False, False]
    assert all(r["rollback_allowed"] is False for r in stage["releases"])
    assert stage["releases"][2]["min_current_version"] == "1.3.46"
    live = json.loads((SVC / "clientflow_release_catalog.json").read_text())
    assert live["catalog_sequence"] == 1248
    assert live == stage
    assert validated_catalog_mode_1248(active_catalog=live) == "update_only_1248_pilot_catalog"


def test_stage_1248_passes_canonical_validator_without_activating_live(monkeypatch):
    from service1 import clientflow_releases as releases
    stage_path = SVC / "clientflow_release_catalog_1248_pilot.stage.json"
    monkeypatch.setattr(releases, "CATALOG_PATH", stage_path)
    releases.load_catalog.cache_clear()
    try:
        catalog = releases.load_catalog()
        assert catalog == load_staged_catalog_1248()
        assert releases.resolve_release("1.3.47")["release_sequence"] == 1248
        with pytest.raises(releases.ClientFlowCatalogError):
            releases.resolve_release("1.3.45")  # 1246 physically retained, no selector
    finally:
        releases.load_catalog.cache_clear()


def test_tampered_approval_lock_denied(monkeypatch, tmp_path):
    from service1 import clientflow_pilot_1248 as pilot
    data = approval_lock_1248()
    data["approved_bundle_sha256"] = "f" * 64
    path = tmp_path / "lock.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr(pilot, "APPROVAL_LOCK_PATH", path)
    with pytest.raises(ClientFlowPilot1248Denied):
        pilot.approval_lock_1248()


def test_tampered_catalog_bytes_denied(monkeypatch, tmp_path):
    from service1 import clientflow_release_pilot_stage_1248 as stage
    data = load_staged_catalog_1248()
    data["releases"][2]["installable"] = True
    path = tmp_path / "stage.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr(stage, "STAGED_CATALOG_PATH", path)
    with pytest.raises(PilotStage1248Denied):
        stage.load_staged_catalog_1248()


def test_exact_pilot_eligibility_is_read_only(closed_pilot):
    require_database_pilot_1248(**payload())


@pytest.mark.parametrize("field,value", [
    ("client_id", 4), ("client_id", True), ("client_name", "Viborg2"),
    ("current_version", "1.3.45"),
    ("expected_current_version", "1.3.45"),
    ("ubuntu_version", "24.04"), ("reason", "short"),
    ("expected_revision", 6),
])
def test_bad_host_status_revision_or_reason_denied(closed_pilot, field, value):
    args = payload()
    args[field] = value
    with pytest.raises(DatabasePilot1248Denied):
        require_database_pilot_1248(**args)


@pytest.mark.parametrize("field,value", [
    ("bundle_sha256", "f" * 64),
    ("bundle_size", 1),
    ("source_commit", "f" * 40),
    ("release_candidate_sha256", "f" * 64),
    ("release_approval_reference", "wrong"),
])
def test_bad_signed_artifact_denied(closed_pilot, field, value):
    args = payload()
    args["artifact"][field] = value
    with pytest.raises(DatabasePilot1248Denied):
        require_database_pilot_1248(**args)


@pytest.mark.parametrize("field,value", [
    ("installable", True), ("rollback_allowed", True),
    ("update_allowed", False), ("release_sequence", 1247),
    ("install_modes", ["fresh_install"]),
    ("min_current_version", "1.3.45"),
    ("max_current_version", "1.3.47"),
])
def test_target_widening_denied(closed_pilot, field, value):
    args = payload()
    args["release"][field] = value
    with pytest.raises(DatabasePilot1248Denied):
        require_database_pilot_1248(**args)


def test_inactive_catalog_denied(closed_pilot):
    args = payload()
    args["catalog"] = json.loads((SVC / "clientflow_release_catalog_1247_pilot.stage.json").read_text())
    with pytest.raises(PilotStage1248Denied):
        require_database_pilot_1248(**args)


@pytest.mark.parametrize("field", ["cutover_enabled", "fleet_open", "fresh_install_open"])
def test_global_release_gates_must_remain_closed(closed_pilot, field):
    args = payload()
    args["policy"][field] = True
    with pytest.raises(DatabasePilot1248Denied):
        require_database_pilot_1248(**args)


def test_legacy_flags_and_fresh_install_gate_denied(closed_pilot, monkeypatch):
    for key in CONFLICTING_FLAGS:
        monkeypatch.setenv(key, "1")
        with pytest.raises(DatabasePilot1248Denied):
            require_database_pilot_1248(**payload())
        monkeypatch.delenv(key)
    monkeypatch.delenv("CLIENTFLOW_FRESH_INSTALL_SUSPENDED")
    with pytest.raises(DatabasePilot1248Denied):
        require_database_pilot_1248(**payload())


def test_admin_pilot_route_wiring_is_sequenced_before_database_write():
    route = (SVC / "routers/clientflow_release_pilot_63d17.py").read_text()
    assert "_reauth(request, session, user, body.password)" in route
    assert "lock_system_client(session, 3)" in route
    assert "control = _bound_control(session, lock=True)" in route
    assert route.index("deployment_release_snapshot(release)") < route.index("require_database_pilot_1248(")
    assert route.index("require_database_pilot_1248(") < route.index("create_authorized_deployment(")
    assert "confirmed_single_pilot is not True" in route
    assert "prior is not None" in route
    assert 'version != "1.3.46"' in route
    assert "clientflow_release_pilot_63d17.router" in (SVC / "main.py").read_text()
    assert "systemctl" not in route
    assert "activate_release(" not in route


def test_approved_1248_identity_cannot_be_rebuilt_from_new_source():
    from scripts.clientflow_63d11_prevent_duplicate_build import verify
    with pytest.raises(ValueError, match="1248 is already approved"):
        verify("f" * 40)
    verify(SOURCE_COMMIT)
