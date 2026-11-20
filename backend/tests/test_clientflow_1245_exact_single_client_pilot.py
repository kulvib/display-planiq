"""1245 stage: fail-closed exact identity/approval and future catalog shape.

Tests must not authorize a real deployment, mutate live catalog or change the
existing 1244 release. Future-approved state is simulated in temporary files.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from service1 import clientflow_pilot_1245 as pilot
from service1 import clientflow_releases as releases


ROOT = Path(__file__).resolve().parents[2]


def _future_release() -> dict:
    return {
        "version": "1.3.44", "client_version": "1.3.44",
        "release_id": pilot.PILOT_RELEASE_ID, "revision": pilot.PILOT_RELEASE_ID,
        "release_sequence": 1245, "artifact_type": "runtime_release",
        "status": "stable", "installable": True, "update_allowed": True,
        "rollback_allowed": False, "requires_explicit_downgrade": False,
        "requires_reboot": True, "install_modes": ["fresh_install", "in_place_update"],
        "min_current_version": "1.3.43", "max_current_version": "1.3.43",
        "ubuntu_compatibility": {
            "policy": "ubuntu-desktop-lts-minimum", "minimum_lts_version": "26.04",
            "maximum_certified_version": "26.04", "certified_versions": ["26.04"],
            "architecture": "amd64", "desktop": "gnome", "display_stack": "wayland",
            "requires_platform_preflight": True,
        },
    }


def _future_approval() -> dict:
    locked = json.loads(pilot.APPROVAL_LOCK_PATH.read_text(encoding="utf-8"))
    return {**locked, "approved": True}


def _future_artifact(approval: dict) -> dict:
    return {
        "target_release_id": pilot.PILOT_RELEASE_ID,
        "bundle_sha256": approval["approved_bundle_sha256"],
        "bundle_size": approval["approved_bundle_size"],
        "release_approval_reference": approval["approval_reference"],
        "release_candidate_sha256": pilot.CANDIDATE_SHA256,
        "source_commit": pilot.SOURCE_COMMIT,
    }


def _args(**overrides) -> dict:
    return dict({
        "client_id": 3, "current_version": "1.3.43",
        "release": _future_release(), "reason": "Kontrolleret pilot på Viborg1",
        "pre_first_activation_repair": False, "confirm_downgrade": False,
    }, **overrides)


@pytest.fixture
def fake_approval(monkeypatch, tmp_path):
    record = _future_approval()
    path = tmp_path / "1245-approval.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(pilot, "APPROVAL_LOCK_PATH", path)
    monkeypatch.setenv(pilot.PILOT_FLAG, "3")
    monkeypatch.setenv(pilot.PILOT_ARM_FLAG, pilot.PILOT_ARM_REFERENCE)
    for key in pilot.CONFLICTING_PILOT_FLAGS:
        monkeypatch.delenv(key, raising=False)
    return record, path


def test_real_pilot_approval_file_exact_but_no_environment_autodeploy():
    record = json.loads((ROOT / "backend/service1/clientflow_pilot_1245_approval.json").read_text())
    assert record["approved"] is True
    assert record["approved_bundle_sha256"] == "28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5"
    assert record["approved_bundle_size"] == 223610880
    assert record["approval_reference"] == "CF-1.3.44-1245-20261114-0685710-ffe58332-R2"
    assert record["source_commit"] == pilot.SOURCE_COMMIT
    assert record["candidate_sha256"] == pilot.CANDIDATE_SHA256
    assert record["installer_sha256"] == pilot.INSTALLER_SHA256


def test_pilot_rejects_without_environment_activation(fake_approval, monkeypatch):
    monkeypatch.delenv(pilot.PILOT_FLAG)
    with pytest.raises(pilot.ClientFlowPilot1245Denied):
        pilot.require_pilot_1245(**_args())


def test_pilot_rejects_without_distinct_operator_arm(fake_approval, monkeypatch):
    monkeypatch.delenv(pilot.PILOT_ARM_FLAG)
    with pytest.raises(pilot.ClientFlowPilot1245Denied, match="operatøraktivering"):
        pilot.require_pilot_1245(**_args())


@pytest.mark.parametrize("value", ["", "wrong", "true", "*"])
def test_pilot_rejects_invalid_operator_arm(fake_approval, monkeypatch, value):
    monkeypatch.setenv(pilot.PILOT_ARM_FLAG, value)
    with pytest.raises(pilot.ClientFlowPilot1245Denied, match="operatøraktivering"):
        pilot.require_pilot_1245(**_args())


@pytest.mark.parametrize("value", ["", "03", "3 ", " 3", "1", "2", "4", "3,4", "true", "*"])
def test_pilot_flag_requires_exact_three(fake_approval, monkeypatch, value):
    monkeypatch.setenv(pilot.PILOT_FLAG, value)
    with pytest.raises(pilot.ClientFlowPilot1245Denied):
        pilot.require_pilot_1245(**_args())


@pytest.mark.parametrize("client_id", [1, 2, 4, None, True, "3"])
def test_only_real_integer_client_three(fake_approval, client_id):
    with pytest.raises(pilot.ClientFlowPilot1245Denied):
        pilot.require_pilot_1245(**_args(client_id=client_id))


@pytest.mark.parametrize("flag", pilot.CONFLICTING_PILOT_FLAGS)
def test_old_pilot_flag_blocks_new_pilot(fake_approval, monkeypatch, flag):
    monkeypatch.setenv(flag, "3")
    with pytest.raises(pilot.ClientFlowPilot1245Denied):
        pilot.require_pilot_1245(**_args())


@pytest.mark.parametrize("current", ["1.3.42", "1.3.44", "v1.3.43", "", None])
def test_wrong_or_missing_current_release_fails(fake_approval, current):
    with pytest.raises(pilot.ClientFlowPilot1245Denied):
        pilot.require_pilot_1245(**_args(current_version=current))


@pytest.mark.parametrize("field,value", [
    ("version", "1.3.43"), ("release_id", "clientflow-1.3.43-seq-1244"),
    ("release_sequence", 1244), ("release_sequence", "1245"),
    ("install_modes", ["in_place_update"]),
    ("status", "supported"), ("installable", False), ("update_allowed", False),
    ("rollback_allowed", True), ("requires_explicit_downgrade", True),
    ("requires_reboot", False), ("min_current_version", "1.3.42"),
    ("max_current_version", "1.3.44"),
])
def test_wrong_catalog_authority_fails(fake_approval, field, value):
    release = _future_release()
    release[field] = value
    with pytest.raises(pilot.ClientFlowPilot1245Denied):
        pilot.require_pilot_1245(**_args(release=release))


@pytest.mark.parametrize("overrides", [
    {"reason": ""}, {"reason": None}, {"reason": "kort"}, {"pre_first_activation_repair": True},
    {"confirm_downgrade": True},
])
def test_no_empty_reason_repair_or_downgrade(fake_approval, overrides):
    with pytest.raises(pilot.ClientFlowPilot1245Denied):
        pilot.require_pilot_1245(**_args(**overrides))


@pytest.mark.parametrize("field,value", [
    ("approved", False), ("approved", "true"),
    ("source_commit", "0" * 40), ("candidate_sha256", "0" * 64),
    ("installer_sha256", "0" * 64), ("release_id", "other"),
    ("approved_bundle_sha256", "x" * 64), ("approved_bundle_size", 0),
    ("approved_bundle_size", True), ("approval_reference", ""),
])
def test_missing_or_tampered_approval_lock_fails(fake_approval, field, value):
    record, path = fake_approval
    record[field] = value
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(pilot.ClientFlowPilot1245Denied):
        pilot.require_pilot_1245(**_args())


def test_missing_lock_fails(fake_approval):
    _, path = fake_approval
    path.unlink()
    with pytest.raises(pilot.ClientFlowPilot1245Denied):
        pilot.require_pilot_1245(**_args())


def test_unapproved_staged_lock_fails_even_when_flag_is_three(fake_approval):
    _, path = fake_approval
    inactive = json.loads((ROOT / "backend/service1/clientflow_pilot_1245_approval.json").read_text())
    inactive["approved"] = False
    path.write_text(json.dumps(inactive), encoding="utf-8")
    with pytest.raises(pilot.ClientFlowPilot1245Denied):
        pilot.require_pilot_1245(**_args())


def test_simulated_approved_lock_accepts_only_exact_artifact(fake_approval):
    record, _ = fake_approval
    pilot.require_pilot_1245(**_args())  # Pre-lock, simulated approval only.
    pilot.require_pilot_1245(**_args(artifact=_future_artifact(record)))  # Post-lock.
    for field, value in (
        ("bundle_sha256", "0" * 64), ("bundle_size", 1),
        ("target_release_id", "clientflow-1.3.43-seq-1244"),
        ("release_approval_reference", "wrong"),
        ("source_commit", "0" * 40), ("release_candidate_sha256", "0" * 64),
    ):
        artifact = _future_artifact(record)
        artifact[field] = value
        with pytest.raises(pilot.ClientFlowPilot1245Denied):
            pilot.require_pilot_1245(**_args(artifact=artifact))


@pytest.fixture
def staged_catalog(monkeypatch, tmp_path):
    # Historical pilot selector continues to be tested, without using it as
    # the active standard after promotion.
    live = json.loads((ROOT / "backend/service1/clientflow_release_catalog_1245_pilot.stage.json").read_text(encoding="utf-8"))
    assert live["catalog_sequence"] == 1245 and len(live["releases"]) == 2
    catalog = deepcopy(live)
    assert catalog["releases"][1]["release_id"] == pilot.PILOT_RELEASE_ID
    path = tmp_path / "catalog.json"
    monkeypatch.setattr(releases, "CATALOG_PATH", path)
    releases.load_catalog.cache_clear()
    yield catalog, path
    releases.load_catalog.cache_clear()


def test_current_catalog_is_one_stable_1245_with_two_install_modes():
    catalog = json.loads((ROOT / "backend/service1/clientflow_release_catalog.json").read_text())
    assert catalog["catalog_sequence"] == 1247
    assert catalog["latest_stable"] == catalog["default_install_version"] == "1.3.44"
    assert [r["release_sequence"] for r in catalog["releases"]] == [1245, 1246, 1247]
    assert catalog["releases"][1]["install_modes"] == ["in_place_update"]
    assert catalog["releases"][1]["installable"] is False
    assert catalog["releases"][2]["installable"] is False
    assert catalog["releases"][2]["install_modes"] == ["in_place_update"]
    assert catalog["releases"][0]["status"] == "stable"
    assert catalog["releases"][0]["install_modes"] == ["fresh_install", "in_place_update"]


def test_future_exact_update_only_catalog_is_allowed_without_changing_default(staged_catalog):
    catalog, path = staged_catalog
    path.write_text(json.dumps(catalog), encoding="utf-8")
    validated = releases.load_catalog()
    assert validated["default_install_version"] == "1.3.43"
    assert validated["latest_stable"] == "1.3.43"
    assert releases.resolve_fresh_install_release()["version"] == "1.3.43"
    assert releases.resolve_release("1.3.44")["version"] == "1.3.44"
    releases.validate_release_compatibility(
        releases.resolve_release("1.3.44"), current_version="1.3.43", ubuntu_version="26.04.1 LTS")


@pytest.mark.parametrize("mutation", [
    lambda x: x.update(latest_stable="1.3.44"),
    lambda x: x.update(default_install_version="1.3.44"),
    lambda x: x["releases"][0].update(update_allowed=True),
    lambda x: x["releases"][0].update(install_modes=["fresh_install", "in_place_update"]),
    lambda x: x["releases"][1].update(installable=True),
    lambda x: x["releases"][1].update(install_modes=["fresh_install", "in_place_update"]),
    lambda x: x["releases"][1].update(min_current_version="1.3.42"),
    lambda x: x["releases"][1].update(max_current_version="1.3.44"),
    lambda x: x["releases"][1].update(rollback_allowed=True),
    lambda x: x["releases"][1].update(status="stable"),
    lambda x: x["releases"].append(deepcopy(x["releases"][1])),
    lambda x: x.update(catalog_sequence=1246),
])
def test_future_catalog_refuses_broadened_authority(staged_catalog, mutation):
    catalog, path = staged_catalog
    mutation(catalog)
    path.write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(releases.ClientFlowCatalogError):
        releases.load_catalog()


def test_same_stable_1245_route_selects_supervised_pilot_before_fleet_policy():
    source = (ROOT / "backend/service1/routers/clientflow_deployments.py").read_text()
    scoped = source.split("def _require_exact_scoped_pilot(", 1)[1].split("class ClientFlowDeploymentCreate", 1)[0]
    assert 'os.environ.get(PILOT_1245_FLAG) is not None' in scoped
    assert 'os.environ.get("CLIENTFLOW_1245_PILOT_ARM_REFERENCE") is not None' in scoped
    assert scoped.index("require_pilot_1245(release=release, **kwargs)") < scoped.index("require_stable_rollout(release=release")
    # No catalog-only automatic installation; both guards still wrap the same release.
