"""Safety regression for stable default + explicitly bounded rollout waves.

All authorizations here are simulated; no live catalog, env or database changes.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from service1 import clientflow_releases as releases
from service1 import clientflow_stable_rollout as rollout

ROOT = Path(__file__).resolve().parents[2]


R2_LOCK = json.loads((ROOT / "backend/service1/clientflow_pilot_1245_approval.json").read_text())


def _stable() -> dict:
    # Same real, read-only stable promotion template that will be reviewed
    # after the pilot; it is NOT the active production catalog.
    return json.loads(
        (ROOT / "backend/service1/clientflow_release_catalog_1245_stable.stage.json").read_text()
    )


def _artifact() -> dict:
    return {
        "target_release_id": "clientflow-1.3.44-seq-1245",
        "bundle_sha256": R2_LOCK["approved_bundle_sha256"],
        "bundle_size": R2_LOCK["approved_bundle_size"],
        "release_approval_reference": R2_LOCK["approval_reference"],
        "release_candidate_sha256": R2_LOCK["candidate_sha256"],
        "source_commit": R2_LOCK["source_commit"],
    }


def _args(**overrides) -> dict:
    cat = _stable()
    return {**{
        "client_id": 3, "current_version": "1.3.43", "release": cat["releases"][0],
        "catalog": cat, "reason": "Godkendt kontrolleret udrulning til Viborg1",
        "pre_first_activation_repair": False, "confirm_downgrade": False,
    }, **overrides}


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv(rollout.ENABLED_FLAG, "1")
    monkeypatch.setenv(rollout.RELEASE_FLAG, "clientflow-1.3.44-seq-1245")
    monkeypatch.setenv(rollout.CLIENTS_FLAG, "3,7")
    monkeypatch.setenv(rollout.BUNDLE_FLAG, R2_LOCK["approved_bundle_sha256"])


def test_real_current_catalog_retains_1244_standard():
    current = releases.load_catalog()
    assert current["latest_stable"] == "1.3.43"
    assert current["default_install_version"] == "1.3.43"
    assert len(current["releases"]) == 2
    assert current["releases"][1]["status"] == "supported"


def test_unpromoted_source_never_changes_existing_default(tmp_path, monkeypatch):
    catalog = _stable()
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog))
    monkeypatch.setattr(releases, "CATALOG_PATH", path)
    releases.load_catalog.cache_clear()
    try:
        assert releases.load_catalog()["latest_stable"] == "1.3.44"
        assert releases.resolve_fresh_install_release()["version"] == "1.3.44"
    finally:
        releases.load_catalog.cache_clear()
    # Read-only synthetic test never changed the live catalog.
    assert json.loads((ROOT / "backend/service1/clientflow_release_catalog.json").read_text())["latest_stable"] == "1.3.43"


def test_stable_requires_explicit_operator_flag(monkeypatch):
    monkeypatch.delenv(rollout.ENABLED_FLAG, raising=False)
    with pytest.raises(rollout.ClientFlowStableRolloutDenied):
        rollout.require_stable_rollout(**_args())


def test_stable_accepts_only_explicit_bounded_client_and_approved_bytes(configured):
    rollout.require_stable_rollout(**_args())
    rollout.require_stable_rollout(**_args(artifact=_artifact()))
    rollout.require_stable_rollout(**_args(client_id=7, artifact=_artifact()))


@pytest.mark.parametrize("flag,value", [
    (rollout.ENABLED_FLAG, "true"), (rollout.ENABLED_FLAG, "0"),
    (rollout.RELEASE_FLAG, "clientflow-1.3.43-seq-1244"),
    (rollout.BUNDLE_FLAG, "B" * 64), (rollout.BUNDLE_FLAG, ""),
    (rollout.CLIENTS_FLAG, ""), (rollout.CLIENTS_FLAG, "*"),
    (rollout.CLIENTS_FLAG, "03"), (rollout.CLIENTS_FLAG, "3,03"),
    (rollout.CLIENTS_FLAG, "3,3"), (rollout.CLIENTS_FLAG, "3, 7"),
    (rollout.CLIENTS_FLAG, ",3"), (rollout.CLIENTS_FLAG, "0,3"),
    (rollout.CLIENTS_FLAG, "-3"),
    (rollout.CLIENTS_FLAG, ",".join(str(i) for i in range(1, 27))),
])
def test_invalid_rollout_env_fails(configured, monkeypatch, flag, value):
    monkeypatch.setenv(flag, value)
    with pytest.raises(rollout.ClientFlowStableRolloutDenied):
        rollout.require_stable_rollout(**_args())


@pytest.mark.parametrize("id", [0, 1, 2, None, True, "3", 28])
def test_only_allowlisted_integer_client(configured, id):
    with pytest.raises(rollout.ClientFlowStableRolloutDenied):
        rollout.require_stable_rollout(**_args(client_id=id))


@pytest.mark.parametrize("field,value", [
    ("status", "supported"), ("installable", False),
    ("update_allowed", False), ("rollback_allowed", True),
    ("requires_explicit_downgrade", True), ("requires_reboot", False),
    ("install_modes", ["fresh_install"]), ("install_modes", ["in_place_update"]),
    ("min_current_version", None),
])
def test_stable_release_cannot_be_a_pilot_or_rollback(configured, field, value):
    args = _args()
    args["release"][field] = value
    with pytest.raises(rollout.ClientFlowStableRolloutDenied):
        rollout.require_stable_rollout(**args)


@pytest.mark.parametrize("field,value", [
    ("latest_stable", "1.3.43"), ("default_install_version", "1.3.43"),
])
def test_catalog_default_must_match_promoted_stable(configured, field, value):
    args = _args()
    args["catalog"][field] = value
    with pytest.raises(rollout.ClientFlowStableRolloutDenied):
        rollout.require_stable_rollout(**args)


@pytest.mark.parametrize("changes", [
    {"current_version": None}, {"current_version": ""},
    {"current_version": "not-a-version"},
    {"current_version": "1.3.44"}, {"current_version": "1.3.45"},
    {"reason": "kort"}, {"reason": None},
    {"pre_first_activation_repair": True}, {"confirm_downgrade": True},
])
def test_no_blank_version_downgrade_repair_or_unexplained_rollout(configured, changes):
    with pytest.raises(rollout.ClientFlowStableRolloutDenied):
        rollout.require_stable_rollout(**_args(**changes))


@pytest.mark.parametrize("field,value", [
    ("target_release_id", "clientflow-1.3.43-seq-1244"),
    ("bundle_sha256", "b" * 64), ("bundle_size", 0),
    ("release_approval_reference", ""),
    ("release_candidate_sha256", "0" * 64 + "x"),
    ("source_commit", "0" * 39),
])
def test_artifact_identity_is_reverified_after_db_lock(configured, field, value):
    artifact = _artifact()
    artifact[field] = value
    with pytest.raises(rollout.ClientFlowStableRolloutDenied):
        rollout.require_stable_rollout(**_args(artifact=artifact))


def test_stable_rollout_does_not_allow_raw_authority_from_catalog(configured):
    args = _args()
    args["catalog"]["releases"][0]["status"] = "supported"
    with pytest.raises(rollout.ClientFlowStableRolloutDenied):
        rollout.require_stable_rollout(**args)


@pytest.mark.parametrize("field,value", [
    ("bundle_size", 223610879),
    ("release_approval_reference", "CF-FAKE-1245-SAME-BYTES"),
    ("release_candidate_sha256", "0" * 64),
    ("source_commit", "0" * 40),
])
def test_stable_r2_provenance_rejects_well_formed_wrong_values(configured, field, value):
    artifact = _artifact()
    artifact[field] = value
    with pytest.raises(rollout.ClientFlowStableRolloutDenied):
        rollout.require_stable_rollout(**_args(artifact=artifact))


def test_stable_1245_rejects_unapproved_bundle_env_even_if_well_formed(configured, monkeypatch):
    monkeypatch.setenv(rollout.BUNDLE_FLAG, "f" * 64)
    with pytest.raises(rollout.ClientFlowStableRolloutDenied):
        rollout.require_stable_rollout(**_args())
