"""Isolated 1243 exact-byte guard tests; no production state or source refreeze."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from service1.clientflow_pilot_1243 import (
    ClientFlowPilot1243Denied, PILOT_FLAG, PILOT_APPROVED_BUNDLE_SHA256,
    PILOT_APPROVED_BUNDLE_SIZE, PILOT_APPROVAL_REFERENCE, PILOT_CANDIDATE_SHA256,
    PILOT_SOURCE_COMMIT, PILOT_RELEASE_ID, require_pilot_1243,
)

ROOT = Path(__file__).resolve().parents[2]


def _release():
    # The 1243 catalog entry must NOT be published before the release store.
    # Model its strictly update-only shape without writing live catalog data.
    return {
        "version": "1.3.42", "release_id": PILOT_RELEASE_ID,
        "release_sequence": 1243, "status": "supported", "installable": False,
        "update_allowed": True, "rollback_allowed": False,
        "requires_explicit_downgrade": False, "requires_reboot": True,
        "install_modes": ["in_place_update"], "min_current_version": "1.3.38",
        "max_current_version": "1.3.38",
    }


def _artifact():
    return {
        "target_release_id": PILOT_RELEASE_ID,
        "bundle_sha256": PILOT_APPROVED_BUNDLE_SHA256,
        "bundle_size": PILOT_APPROVED_BUNDLE_SIZE,
        "release_approval_reference": PILOT_APPROVAL_REFERENCE,
        "release_candidate_sha256": PILOT_CANDIDATE_SHA256,
        "source_commit": PILOT_SOURCE_COMMIT,
    }


def _require(**changes):
    args = {
        "client_id": 2, "current_version": "1.3.38", "release": _release(),
        "reason": "Observed local recovery and physical Viborg2 pilot",
        "pre_first_activation_repair": False, "confirm_downgrade": False,
        "artifact": _artifact(),
    }
    args.update(changes)
    return require_pilot_1243(**args)


@pytest.mark.parametrize("flag", [None, "", "0", "1", "02", "2 ", " 2", "2,3", "*", "all", "True", "２", "3", "-2", "2.0"])
def test_pilot_disabled_or_malformed(monkeypatch, flag):
    monkeypatch.delenv("CLIENTFLOW_1241_PILOT_CLIENT_ID", raising=False)
    monkeypatch.delenv("CLIENTFLOW_1242_PILOT_CLIENT_ID", raising=False)
    if flag is None:
        monkeypatch.delenv(PILOT_FLAG, raising=False)
    else:
        monkeypatch.setenv(PILOT_FLAG, flag)
    with pytest.raises(ClientFlowPilot1243Denied):
        _require()


def test_exact_viborg2_only(monkeypatch):
    monkeypatch.setenv(PILOT_FLAG, "2")
    monkeypatch.delenv("CLIENTFLOW_1241_PILOT_CLIENT_ID", raising=False)
    monkeypatch.delenv("CLIENTFLOW_1242_PILOT_CLIENT_ID", raising=False)
    assert _require() is None
    for other in [1, 0, 3, -1, "2", 2.0, True, None]:
        with pytest.raises(ClientFlowPilot1243Denied):
            _require(client_id=other)


@pytest.mark.parametrize("other", ["CLIENTFLOW_1241_PILOT_CLIENT_ID", "CLIENTFLOW_1242_PILOT_CLIENT_ID"])
def test_conflicting_pilots_fail_closed(monkeypatch, other):
    monkeypatch.setenv(PILOT_FLAG, "2")
    monkeypatch.setenv(other, "1")
    with pytest.raises(ClientFlowPilot1243Denied, match="1241/1242"):
        _require()


@pytest.mark.parametrize("version", [None, "", "1.3.37", "1.3.39", "1.3.40", "1.3.41", "v1.3.38"])
def test_requires_exact_installed_version(monkeypatch, version):
    monkeypatch.setenv(PILOT_FLAG, "2")
    monkeypatch.delenv("CLIENTFLOW_1241_PILOT_CLIENT_ID", raising=False)
    monkeypatch.delenv("CLIENTFLOW_1242_PILOT_CLIENT_ID", raising=False)
    with pytest.raises(ClientFlowPilot1243Denied):
        _require(current_version=version)


@pytest.mark.parametrize("key,value", [
    ("version", "1.3.41"), ("release_id", "clientflow-1.3.41-seq-1242"),
    ("release_sequence", 1242), ("release_sequence", "1243"),
    ("release_sequence", True), ("status", "stable"),
    ("installable", True), ("update_allowed", False),
    ("rollback_allowed", True), ("requires_explicit_downgrade", True),
    ("requires_reboot", False), ("install_modes", ["fresh_install", "in_place_update"]),
    ("min_current_version", "1.3.37"), ("max_current_version", "1.3.41"),
])
def test_broadened_release_rejected(monkeypatch, key, value):
    monkeypatch.setenv(PILOT_FLAG, "2")
    monkeypatch.delenv("CLIENTFLOW_1241_PILOT_CLIENT_ID", raising=False)
    monkeypatch.delenv("CLIENTFLOW_1242_PILOT_CLIENT_ID", raising=False)
    release = _release()
    release[key] = value
    with pytest.raises(ClientFlowPilot1243Denied):
        _require(release=release)


@pytest.mark.parametrize("key,value", [
    ("target_release_id", "other"), ("bundle_sha256", "0" * 64),
    ("bundle_size", 223610881), ("release_approval_reference", "other"),
    ("release_candidate_sha256", "0" * 64), ("source_commit", "f" * 40),
])
def test_mutated_artifact_rejected(monkeypatch, key, value):
    monkeypatch.setenv(PILOT_FLAG, "2")
    monkeypatch.delenv("CLIENTFLOW_1241_PILOT_CLIENT_ID", raising=False)
    monkeypatch.delenv("CLIENTFLOW_1242_PILOT_CLIENT_ID", raising=False)
    artifact = _artifact()
    artifact[key] = value
    with pytest.raises(ClientFlowPilot1243Denied, match="artifact matcher ikke"):
        _require(artifact=artifact)


@pytest.mark.parametrize("changes", [
    {"reason": " "}, {"reason": None},
    {"pre_first_activation_repair": True}, {"confirm_downgrade": True},
])
def test_repair_downgrade_and_missing_reason_blocked(monkeypatch, changes):
    monkeypatch.setenv(PILOT_FLAG, "2")
    monkeypatch.delenv("CLIENTFLOW_1241_PILOT_CLIENT_ID", raising=False)
    monkeypatch.delenv("CLIENTFLOW_1242_PILOT_CLIENT_ID", raising=False)
    with pytest.raises(ClientFlowPilot1243Denied):
        _require(**changes)


def test_source_and_catalog_do_not_enable_pilot_by_merging():
    source = json.loads((ROOT / "backend/service1/clientflow_release_catalog.json").read_text())
    assert source["catalog_sequence"] == 1242
    assert all(row["release_sequence"] != 1243 for row in source["releases"])
    assert source["latest_stable"] == source["default_install_version"] == "1.3.38"
    assert "clientflow-1.3.42-seq-1243" not in (ROOT / "backend/service1/clientflow_release_catalog.json").read_text()
    router = (ROOT / "backend/service1/routers/clientflow_deployments.py").read_text()
    create = router[router.index("def create_clientflow_deployment("):router.index("@router.get(", router.index("def create_clientflow_deployment("))]
    assert create.count("_require_exact_scoped_pilot(") == 2
    assert create.index("_require_exact_scoped_pilot(") < create.index("deployment_release_snapshot(release)")
    assert create.index("lock_system_client(") < create.rindex("_require_exact_scoped_pilot(")
    assert create.rindex("_require_exact_scoped_pilot(") < create.index("create_authorized_deployment(")
