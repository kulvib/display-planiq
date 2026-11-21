"""63D-17 read-only local pilot preflight: all default-deny and no side effects."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import phase63d17_viborg1_readonly_preflight as pilot


def fixture(root: Path):
    (root / "etc/clientflow").mkdir(parents=True)
    (root / "opt/clientflow/releases" / pilot.CURRENT_RELEASE).mkdir(parents=True)
    (root / "var/lib/clientflow/release").mkdir(parents=True)
    (root / "etc/clientflow/identity.json").write_text(json.dumps({"schema_version": 1, "client_id": 3}))
    (root / "var/lib/clientflow/release/state.json").write_text(json.dumps({
        "active_release_id": pilot.CURRENT_RELEASE,
        "installed": {pilot.CURRENT_RELEASE: {"bundle_sha256": pilot.EXPECTED_SHA}},
    }))
    (root / "opt/clientflow/active").symlink_to(root / "opt/clientflow/releases" / pilot.CURRENT_RELEASE)


SERVICES = {
    "updater_active": "inactive", "updater_enabled": "disabled",
    "controller_active": "inactive", "status_active": "active",
}


def test_local_read_only_evidence_cannot_issue_deployment(tmp_path):
    fixture(tmp_path)
    result = pilot.inspect(root=tmp_path, services=SERVICES, hostname=pilot.HOST)
    assert result["local_preflight_pass"] is True
    assert result["deployment_performed"] is False
    assert result["one_shot_controller_authorized"] is False
    assert result["backend_deployment_independently_verified"] is False
    assert result["physical_acceptance"] is False


@pytest.mark.parametrize("key,value", [
    ("updater_enabled", "enabled"), ("updater_active", "active"),
    ("controller_active", "active"), ("status_active", "inactive"),
])
def test_service_drift_denied(tmp_path, key, value):
    fixture(tmp_path)
    services = {**SERVICES, key: value}
    result = pilot.inspect(root=tmp_path, services=services, hostname=pilot.HOST)
    assert result["local_preflight_pass"] is False
    assert result["checks"][{"updater_enabled": "updater_disabled",
                             "updater_active": "updater_inactive",
                             "controller_active": "controller_inactive",
                             "status_active": "status_agent_active"}[key]] is False


def test_wrong_host_and_identity_denied(tmp_path):
    fixture(tmp_path)
    assert pilot.inspect(root=tmp_path, services=SERVICES, hostname="another-host")["local_preflight_pass"] is False
    (tmp_path / "etc/clientflow/identity.json").write_text(json.dumps({"client_id": 4}))
    assert pilot.inspect(root=tmp_path, services=SERVICES, hostname=pilot.HOST)["local_preflight_pass"] is False


def test_unknown_signed_release_denied(tmp_path):
    fixture(tmp_path)
    path = tmp_path / "var/lib/clientflow/release/state.json"
    state = json.loads(path.read_text())
    state["installed"][pilot.CURRENT_RELEASE]["bundle_sha256"] = "f" * 64
    path.write_text(json.dumps(state))
    assert pilot.inspect(root=tmp_path, services=SERVICES, hostname=pilot.HOST)["local_preflight_pass"] is False


def test_symlink_identity_evidence_denied(tmp_path):
    fixture(tmp_path)
    path = tmp_path / "etc/clientflow/identity.json"
    target = tmp_path / "identity-copy"
    target.write_text(path.read_text())
    path.unlink()
    path.symlink_to(target)
    with pytest.raises(ValueError):
        pilot.inspect(root=tmp_path, services=SERVICES, hostname=pilot.HOST)
