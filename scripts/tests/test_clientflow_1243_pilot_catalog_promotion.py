"""Exact 1243 pilot catalog: published bytes are NOT runtime authorization."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from service1.clientflow_pilot_1243 import (  # noqa: E402
    ClientFlowPilot1243Denied,
    PILOT_APPROVAL_REFERENCE,
    PILOT_APPROVED_BUNDLE_SHA256,
    PILOT_APPROVED_BUNDLE_SIZE,
    PILOT_CANDIDATE_SHA256,
    PILOT_CLIENT_ID,
    PILOT_FLAG,
    PILOT_RELEASE_ID,
    PILOT_SOURCE_COMMIT,
    require_pilot_1243,
)


def _catalog() -> dict:
    return json.loads((ROOT / "backend/service1/clientflow_release_catalog.json").read_text(encoding="utf-8"))


def _approved_artifact() -> dict:
    return {
        "target_release_id": PILOT_RELEASE_ID,
        "bundle_sha256": PILOT_APPROVED_BUNDLE_SHA256,
        "bundle_size": PILOT_APPROVED_BUNDLE_SIZE,
        "release_approval_reference": PILOT_APPROVAL_REFERENCE,
        "release_candidate_sha256": PILOT_CANDIDATE_SHA256,
        "source_commit": PILOT_SOURCE_COMMIT,
    }


def test_only_1243_is_new_and_stable_default_remains_1239() -> None:
    catalog = _catalog()
    assert catalog["catalog_sequence"] == 1243
    assert [r["release_id"] for r in catalog["releases"]] == [
        "clientflow-1.3.38-seq-1239",
        "clientflow-1.3.40-seq-1241",
        "clientflow-1.3.41-seq-1242",
        "clientflow-1.3.42-seq-1243",
    ]
    assert catalog["latest_stable"] == catalog["default_install_version"] == "1.3.38"
    assert catalog["retention_policy"] == {
        "max_installable_versions": 1, "keep_blocked_metadata": False,
    }
    assert [r["version"] for r in catalog["releases"] if r["installable"]] == ["1.3.38"]
    assert all(r["rollback_allowed"] is False for r in catalog["releases"])
    assert [r["release_id"] for r in catalog["releases"] if r["update_allowed"]] == [
        "clientflow-1.3.40-seq-1241",
        "clientflow-1.3.41-seq-1242",
        "clientflow-1.3.42-seq-1243",
    ]
    release = catalog["releases"][-1]
    assert release["version"] == release["client_version"] == "1.3.42"
    assert release["release_sequence"] == 1243
    assert release["status"] == "supported"
    assert release["installable"] is False and release["update_allowed"] is True
    assert release["rollback_allowed"] is False
    assert release["requires_explicit_downgrade"] is False
    assert release["requires_reboot"] is True
    assert release["install_modes"] == ["in_place_update"]
    assert release["min_current_version"] == release["max_current_version"] == "1.3.38"
    assert release["ubuntu_compatibility"]["architecture"] == "amd64"
    assert release["ubuntu_compatibility"]["minimum_lts_version"] == "26.04"
    assert PILOT_APPROVED_BUNDLE_SHA256 in " ".join(release["notes"])
    assert PILOT_SOURCE_COMMIT in " ".join(release["notes"])
    assert PILOT_APPROVAL_REFERENCE in " ".join(release["notes"])
    assert str(PILOT_APPROVED_BUNDLE_SIZE) in " ".join(release["notes"])
    assert "PENDING" in " ".join(release["notes"])


def test_no_pilot_flag_grants_no_deployment_authority(monkeypatch) -> None:
    release = _catalog()["releases"][-1]
    monkeypatch.delenv(PILOT_FLAG, raising=False)
    monkeypatch.delenv("CLIENTFLOW_1241_PILOT_CLIENT_ID", raising=False)
    monkeypatch.delenv("CLIENTFLOW_1242_PILOT_CLIENT_ID", raising=False)
    with pytest.raises(ClientFlowPilot1243Denied):
        require_pilot_1243(
            client_id=PILOT_CLIENT_ID, current_version="1.3.38", release=release,
            reason="Viborg2 attended physical pilot", pre_first_activation_repair=False,
            confirm_downgrade=False, artifact=_approved_artifact(),
        )


def test_enabled_flag_never_authorizes_another_client_or_release(monkeypatch) -> None:
    release = _catalog()["releases"][-1]
    monkeypatch.setenv(PILOT_FLAG, "2")
    monkeypatch.delenv("CLIENTFLOW_1241_PILOT_CLIENT_ID", raising=False)
    monkeypatch.delenv("CLIENTFLOW_1242_PILOT_CLIENT_ID", raising=False)
    with pytest.raises(ClientFlowPilot1243Denied):
        require_pilot_1243(
            client_id=1, current_version="1.3.38", release=release,
            reason="Test", pre_first_activation_repair=False,
            confirm_downgrade=False, artifact=_approved_artifact(),
        )
    with pytest.raises(ClientFlowPilot1243Denied):
        require_pilot_1243(
            client_id=2, current_version="1.3.40", release=release,
            reason="Test", pre_first_activation_repair=False,
            confirm_downgrade=False, artifact=_approved_artifact(),
        )
    assert require_pilot_1243(
        client_id=2, current_version="1.3.38", release=release,
        reason="Attended Viborg2 pilot after approval", pre_first_activation_repair=False,
        confirm_downgrade=False, artifact=_approved_artifact(),
    ) is None


def test_runtime_source_and_manual_rollback_are_unchanged() -> None:
    assert (ROOT / "client/VERSION").read_text().strip() == "1.3.43"
    inp = json.loads((ROOT / "client/release/release-input.json").read_text())
    assert inp["release_sequence"] == 1244
    assert json.loads((ROOT / "client/release/rollback-trust.json").read_text()) == {
        "schema_version": 1, "enabled": False, "keys": [],
    }
